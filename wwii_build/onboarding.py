"""System onboarding: bring an existing body of work into the manager in one deterministic pass.

A *system manifest* (TOML, see ``tools/build_manager/systems/``) lists the components of a system. For each
component this module:

1. writes a RAG context file ``<context_dir>/<component>.md`` extracted from the component's own files
   (README heads, Python docstrings/signatures, JS/shell header comments, run commands, ports, interfaces).
   No LLM is used, the output is byte-stable for the same inputs, and it is size-bounded.
2. upserts a Deliver (``deliver_catalog``, ``source_kind='system_manifest'``), its context source
   (``context_sources``, ``origin_kind='system_context'``), its graph-RAG access and its prerequisite edges.
3. optionally ingests the context file into the graph RAG service (``POST /ingest``), only when its content
   hash changed since the last successful ingest.

Re-running is idempotent. Adding another system later = writing one more manifest and running
``wwii-build onboard <manifest>``.
"""
from __future__ import annotations

import ast
import fnmatch
import hashlib
import json
import os
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from .config import MANAGER_DIR, Config
from .db import DB
from .models import iso, utcnow

SYSTEMS_DIR = MANAGER_DIR / "systems"
EXECUTION_KINDS = {"worker", "deterministic", "llm_research", "asset_pipeline"}
AVAILABILITY = {"available", "prototype", "planned"}
GRAPH_ACCESS = {"none", "limited", "full"}
EXCLUDED_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", ".pytest_cache", "dist", "build",
                 "_to_delete", "tmp", "logs", "wiki_cache", "backups", ".worktrees", ".wwii-build"}
MAX_DOC_CHARS = 3500
MAX_FILES = 40
MAX_SYMBOLS = 18
MAX_CONTEXT_CHARS = 20000


class OnboardingError(ValueError):
    pass


@dataclass
class Component:
    deliver_id: str
    title: str
    description: str
    owner: str
    domain: str
    execution_kind: str = "worker"
    availability: str = "available"
    root: str = ""
    docs: list[str] = field(default_factory=list)
    code: list[str] = field(default_factory=list)
    run: list[str] = field(default_factory=list)
    ports: list[int] = field(default_factory=list)
    interfaces: list[str] = field(default_factory=list)
    depends_on: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    graph_access: str = "limited"
    graph_scope: str = ""
    entry: str = ""
    discover: list[dict] = field(default_factory=list)       # capability discovery rules (see DISCOVERERS)
    capabilities: list[dict] = field(default_factory=list)   # explicit capabilities: {group, name, description}


@dataclass
class SystemManifest:
    system_id: str
    title: str
    description: str
    context_dir: str
    components: list[Component]
    path: Path
    tags: list[str] = field(default_factory=list)
    graph_ingest: bool = True
    graph_text: bool = False          # also send the context text through the service's LLM extraction (slow)
    notes: list[str] = field(default_factory=list)


# ------------------------------------------------------------------ manifest
def load_manifest(path: Path) -> SystemManifest:
    path = Path(path).expanduser()
    if not path.is_file():
        cand = SYSTEMS_DIR / (str(path) if str(path).endswith(".toml") else f"{path}.toml")
        if not cand.is_file():
            raise OnboardingError(f"manifest not found: {path}")
        path = cand
    with open(path, "rb") as f:
        data = tomllib.load(f)
    sysd = data.get("system") or {}
    for key in ("id", "title", "context_dir"):
        if not str(sysd.get(key) or "").strip():
            raise OnboardingError(f"[system].{key} is required")
    if not re.fullmatch(r"[a-z0-9_]+", sysd["id"]):
        raise OnboardingError("[system].id must be lowercase letters, digits and _")
    if Path(sysd["context_dir"]).is_absolute() or ".." in Path(sysd["context_dir"]).parts:
        raise OnboardingError("[system].context_dir must be a relative path inside the repo")
    comps, seen = [], set()
    for raw in data.get("components") or []:
        known = set(Component.__dataclass_fields__)
        unknown = set(raw) - known
        if unknown:
            raise OnboardingError(f"component {raw.get('deliver_id')}: unknown keys {sorted(unknown)}")
        c = Component(**raw)
        if not re.fullmatch(r"[a-z0-9_.\-/]+", c.deliver_id or ""):
            raise OnboardingError(f"invalid deliver_id {c.deliver_id!r}")
        if c.deliver_id in seen:
            raise OnboardingError(f"duplicate deliver_id {c.deliver_id}")
        seen.add(c.deliver_id)
        if c.execution_kind not in EXECUTION_KINDS:
            raise OnboardingError(f"{c.deliver_id}: execution_kind must be one of {sorted(EXECUTION_KINDS)}")
        if c.availability not in AVAILABILITY:
            raise OnboardingError(f"{c.deliver_id}: availability must be one of {sorted(AVAILABILITY)}")
        if c.graph_access not in GRAPH_ACCESS:
            raise OnboardingError(f"{c.deliver_id}: graph_access must be one of {sorted(GRAPH_ACCESS)}")
        for rule in c.discover:
            if rule.get("kind") not in DISCOVERERS or not rule.get("glob") or not rule.get("group"):
                raise OnboardingError(f"{c.deliver_id}: discover rules need kind ({sorted(DISCOVERERS)}), glob, group")
        comps.append(c)
    if not comps:
        raise OnboardingError("the manifest has no [[components]]")
    return SystemManifest(system_id=sysd["id"], title=sysd["title"], description=sysd.get("description", ""),
                          context_dir=sysd["context_dir"], components=comps, path=path,
                          tags=list(sysd.get("tags") or []), graph_ingest=bool(sysd.get("graph_ingest", True)),
                          graph_text=bool(sysd.get("graph_text", False)),
                          notes=list(sysd.get("notes") or []))


def _root(cfg: Config, c: Component) -> Path | None:
    if not c.root:
        return None
    p = Path(os.path.expanduser(c.root))
    return p if p.is_absolute() else cfg.repo / p


def _glob(root: Path, patterns: list[str], limit: int = MAX_FILES) -> list[Path]:
    out: list[Path] = []
    for pat in patterns:
        for p in sorted(root.glob(pat)):
            if p.is_file() and not (set(p.relative_to(root).parts[:-1]) & EXCLUDED_DIRS) \
                    and not any(part.startswith("_bak") for part in p.relative_to(root).parts):
                out.append(p)
    return list(dict.fromkeys(out))[:limit]


# ------------------------------------------------------------------ extraction (deterministic, no LLM)
def _doc_head(path: Path) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    lines = [ln.rstrip() for ln in text.splitlines()]
    out, size = [], 0
    for ln in lines:
        if not ln.strip() and (not out or not out[-1].strip()):
            continue
        out.append(ln)
        size += len(ln) + 1
        if size >= MAX_DOC_CHARS:
            out.append("…")
            break
    return "\n".join(out).strip()


def _first_line(doc: str | None) -> str:
    return (doc or "").strip().splitlines()[0][:160] if (doc or "").strip() else ""


def _py_symbols(path: Path) -> list[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except (SyntaxError, ValueError, OSError):
        return []
    out = []
    mod = _first_line(ast.get_docstring(tree))
    if mod:
        out.append(f"> {mod}")
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and not node.name.startswith("_"):
            kind = "class" if isinstance(node, ast.ClassDef) else "def"
            args = ""
            if kind == "def":
                names = [a.arg for a in node.args.args][:6]
                args = "(" + ", ".join(names) + ")"
            doc = _first_line(ast.get_docstring(node))
            out.append(f"- `{kind} {node.name}{args}`" + (f" — {doc}" if doc else ""))
        if len(out) >= MAX_SYMBOLS:
            break
    return out


_JS_FN = re.compile(r"^\s*(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_$][\w$]*)\s*\(|"
                    r"^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?(?:\([^)]*\)|[\w$]+)\s*=>|"
                    r"^\s*(?:export\s+)?class\s+([A-Za-z_$][\w$]*)", re.M)


def _js_symbols(path: Path) -> list[str]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")[:400_000]
    except OSError:
        return []
    out = []
    head = re.match(r"\s*/\*\*?(.*?)\*/", text, re.S)
    if head:
        first = " ".join(x.strip(" *") for x in head.group(1).splitlines() if x.strip(" *"))[:200]
        if first:
            out.append(f"> {first}")
    else:
        comments = []
        for ln in text.splitlines()[:8]:
            if ln.strip().startswith("//"):
                comments.append(ln.strip()[2:].strip())
            elif ln.strip():
                break
        if comments:
            out.append("> " + " ".join(comments)[:200])
    names = []
    for m in _JS_FN.finditer(text):
        name = next(g for g in m.groups() if g)
        if name not in names and not name.startswith("_"):
            names.append(name)
    if names:
        out.append("- " + ", ".join(f"`{n}`" for n in names[:MAX_SYMBOLS]) + (" …" if len(names) > MAX_SYMBOLS else ""))
    return out


def _sh_symbols(path: Path) -> list[str]:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[:15]
    except OSError:
        return []
    comments = [ln.lstrip("# ").strip() for ln in lines[1:] if ln.startswith("#") and ln.lstrip("# ").strip()]
    return [f"> {' '.join(comments)[:240]}"] if comments else []


def _symbols(path: Path) -> list[str]:
    ext = path.suffix.lower()
    if ext == ".py":
        return _py_symbols(path)
    if ext in {".js", ".mjs", ".ts", ".tsx", ".jsx"}:
        return _js_symbols(path)
    if ext in {".sh", ".command"}:
        return _sh_symbols(path)
    return []


# ------------------------------------------------------------------ capability discovery (deterministic)
MAX_CAPS_PER_RULE = 150
MAX_CAPS_PER_COMPONENT = 300
_ROUTE_DECORATOR = re.compile(r"@\w+\.(get|post|put|delete|patch)\(\s*[\"'](/[^\"']*)[\"']")
_ROUTE_COMPARE = re.compile(r"(?:path|route|endpoint)\s*(?:==|in)\s*\(?\s*[\"'](/[\w\-/{}.]+)[\"']")
_ROUTE_PREFIX = re.compile(r"path\.startswith\(\s*[\"'](/[\w\-/{}.]+)[\"']")
_ARGPARSE = re.compile(r"add_parser\(\s*[\"']([\w\-]+)[\"'](?:[^)]*?help\s*=\s*[\"']([^\"']+)[\"'])?", re.S)


def _summary(path: Path) -> str:
    """One-line description of a file: module docstring, JS header comment, or shell header comment."""
    for line in _symbols(path):
        if line.startswith("> "):
            return line[2:].strip()[:200]
    return ""


def _disc_files(root: Path, rule: dict) -> list[dict]:
    return [{"name": p.stem, "source": str(p.relative_to(root)), "description": _summary(p)}
            for p in _glob(root, [rule["glob"]], MAX_CAPS_PER_RULE)]


def _disc_py_functions(root: Path, rule: dict, only_tools: bool = False) -> list[dict]:
    out = []
    for p in _glob(root, [rule["glob"]], MAX_CAPS_PER_RULE):
        try:
            tree = ast.parse(p.read_text(encoding="utf-8", errors="replace"))
        except (SyntaxError, ValueError, OSError):
            continue
        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) or node.name.startswith("_"):
                continue
            if only_tools and not any("tool" in ast.unparse(d) for d in node.decorator_list):
                continue
            out.append({"name": node.name, "source": str(p.relative_to(root)),
                        "description": _first_line(ast.get_docstring(node))})
    return out


def _disc_mcp_tools(root: Path, rule: dict) -> list[dict]:
    return _disc_py_functions(root, rule, only_tools=True)


def _disc_http_routes(root: Path, rule: dict) -> list[dict]:
    out, seen = [], set()
    for p in _glob(root, [rule["glob"]], MAX_CAPS_PER_RULE):
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        found = [f"{m.group(1).upper()} {m.group(2)}" for m in _ROUTE_DECORATOR.finditer(text)]
        found += [m.group(1) for m in _ROUTE_COMPARE.finditer(text)]
        found += [m.group(1) + "*" for m in _ROUTE_PREFIX.finditer(text)]
        for route in found:
            if route not in seen:
                seen.add(route)
                out.append({"name": route, "source": str(p.relative_to(root)), "description": ""})
    return out


def _disc_argparse(root: Path, rule: dict) -> list[dict]:
    out, seen = [], set()
    for p in _glob(root, [rule["glob"]], MAX_CAPS_PER_RULE):
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for m in _ARGPARSE.finditer(text):
            if m.group(1) not in seen:
                seen.add(m.group(1))
                out.append({"name": m.group(1), "source": str(p.relative_to(root)),
                            "description": (m.group(2) or "").strip()[:200]})
    return out


def _disc_js_functions(root: Path, rule: dict) -> list[dict]:
    out = []
    for p in _glob(root, [rule["glob"]], MAX_CAPS_PER_RULE):
        try:
            text = p.read_text(encoding="utf-8", errors="replace")[:400_000]
        except OSError:
            continue
        for m in _JS_FN.finditer(text):
            name = next(g for g in m.groups() if g)
            if not name.startswith("_"):
                out.append({"name": name, "source": str(p.relative_to(root)), "description": ""})
    return out


DISCOVERERS = {"files": _disc_files, "py_functions": _disc_py_functions, "mcp_tools": _disc_mcp_tools,
               "http_routes": _disc_http_routes, "argparse": _disc_argparse, "js_functions": _disc_js_functions}


def _slug(text: str) -> str:
    """ASCII id part; text with no ASCII letters (e.g. a Hebrew group name) gets a stable short hash."""
    ascii_part = re.sub(r"[^a-z0-9_.\-]+", "_", text.lower()).strip("_.-")[:60]
    return ascii_part if len(ascii_part) >= 2 else "h" + hashlib.sha1(text.encode()).hexdigest()[:8]


def discover_capabilities(cfg: Config, c: Component) -> list[dict]:
    """Capabilities (groups) and sub-capabilities (items) of a component, from its own source. No LLM."""
    root = _root(cfg, c)
    items: list[dict] = []
    for cap in c.capabilities:
        items.append({"group": cap.get("group") or "יכולות", "name": cap["name"], "kind": "declared",
                      "source": cap.get("source", ""), "description": cap.get("description", "")})
    if root is not None and root.exists():
        for rule in c.discover:
            excluded = [rule["exclude"]] if isinstance(rule.get("exclude"), str) else list(rule.get("exclude") or [])
            found = [f for f in DISCOVERERS[rule["kind"]](root, rule)
                     if not any(fnmatch.fnmatch(Path(f["source"]).name, pat) for pat in excluded)][:MAX_CAPS_PER_RULE]
            items += [dict(f, group=rule["group"], kind=rule["kind"]) for f in found]
    out, seen = [], set()
    for it in items:
        cid = f"{c.deliver_id}/{_slug(it['group'])}/{_slug(it['name'])}"
        if cid in seen:
            continue
        seen.add(cid)
        out.append(dict(it, capability_id=cid))
    return out[:MAX_CAPS_PER_COMPONENT]


def render_component(cfg: Config, m: SystemManifest, c: Component) -> str:
    root = _root(cfg, c)
    L = [f"# {c.title}", "",
         f"`{c.deliver_id}` · מערכת: {m.title} · בעלים: `{c.owner}` · תחום: `{c.domain}` · "
         f"ביצוע: `{c.execution_kind}` · זמינות: `{c.availability}`", "", "## מטרה", c.description.strip(), ""]
    if root is not None:
        L += ["## מיקום", f"- שורש: `{root}`" + ("" if root.exists() else " (לא נמצא בזמן ההכנסה)")]
        if c.entry:
            L.append(f"- נקודת כניסה: `{c.entry}`")
        L.append("")
    if c.run or c.ports:
        L.append("## הפעלה")
        L += [f"- `{r}`" for r in c.run]
        if c.ports:
            L.append("- פורטים (127.0.0.1): " + ", ".join(str(p) for p in c.ports))
        L.append("")
    if c.interfaces:
        L += ["## ממשקים", *[f"- {i}" for i in c.interfaces], ""]
    if c.depends_on:
        L += ["## תלויות", *[f"- `{d}`" for d in c.depends_on], ""]
    if c.notes:
        L += ["## הערות וסייגים", *[f"- {n}" for n in c.notes], ""]
    caps = discover_capabilities(cfg, c)
    if caps:
        L += [f"## יכולות ותתי־יכולות ({len(caps)})", ""]
        for group in dict.fromkeys(cap["group"] for cap in caps):
            L.append(f"### {group}")
            for cap in (x for x in caps if x["group"] == group):
                tail = " — ".join(x for x in (cap["description"], f"`{cap['source']}`" if cap["source"] else "") if x)
                L.append(f"- `{cap['name']}`" + (f" — {tail}" if tail else ""))
            L.append("")
    body_docs, body_code = [], []
    if root is not None and root.exists():
        for doc in _glob(root, c.docs):
            head = _doc_head(doc)
            if head:
                body_docs += [f"### {doc.relative_to(root)}", head, ""]
        for f in _glob(root, c.code):
            syms = _symbols(f)
            body_code += [f"### `{f.relative_to(root)}`", *(syms or ["- (אין סמלים ציבוריים)"]), ""]
    if body_docs:
        L += ["## מסמכים (תקציר מהמקור)", "", *body_docs]
    if body_code:
        L += ["## מבנה הקוד", "", *body_code]
    text = "\n".join(L).rstrip() + "\n"
    if len(text) > MAX_CONTEXT_CHARS:
        text = text[:MAX_CONTEXT_CHARS - 80].rsplit("\n", 1)[0] + "\n\n… (נחתך לגבול הקונטקסט)\n"
    return text


def render_index(m: SystemManifest) -> str:
    L = [f"# {m.title} — מפת המערכת", "", f"`{m.system_id}`", "", m.description.strip(), ""]
    if m.notes:
        L += ["## עקרונות", *[f"- {n}" for n in m.notes], ""]
    L += ["## רכיבים (Delivers)", "", "| Deliver | כותרת | תחום | ביצוע | זמינות | תלוי ב־ |", "|---|---|---|---|---|---|"]
    for c in m.components:
        L.append(f"| `{c.deliver_id}` | {c.title} | {c.domain} | {c.execution_kind} | {c.availability} | "
                 f"{', '.join(f'`{d}`' for d in c.depends_on) or '—'} |")
    L += ["", "לכל רכיב יש קובץ קונטקסט מפורט באותה תיקייה (`<deliver_id>.md`)."]
    return "\n".join(L).rstrip() + "\n"


def _file_name(deliver_id: str) -> str:
    return re.sub(r"[^a-z0-9_.\-]", "_", deliver_id) + ".md"


# ------------------------------------------------------------------ apply
def onboard(cfg: Config, db: DB, manifest_path: Path, *, graph: bool | None = None, dry_run: bool = False,
            graph_service=None, progress=None) -> dict:
    m = load_manifest(manifest_path)
    try:
        manifest_ref = str(m.path.resolve().relative_to(cfg.repo.resolve()))
    except ValueError:
        manifest_ref = str(m.path)
    known = {c.deliver_id for c in m.components} | {r["deliver_id"] for r in db.q("SELECT deliver_id FROM deliver_catalog")}
    missing = sorted({d for c in m.components for d in c.depends_on} - known)
    if missing:
        raise OnboardingError(f"depends_on names unknown Delivers: {missing}")
    out_dir = cfg.repo / m.context_dir
    docs = [("__index__", f"{m.system_id}.index.md", render_index(m), None)]
    docs += [(c.deliver_id, _file_name(c.deliver_id), render_component(cfg, m, c), c) for c in m.components]
    report = {"system": m.system_id, "manifest": manifest_ref, "context_dir": m.context_dir, "components": [],
              "graph": {"enabled": False}}
    if dry_run:
        report["components"] = [{"deliver_id": d, "file": f"{m.context_dir}/{n}", "chars": len(t)} for d, n, t, _ in docs]
        return report
    out_dir.mkdir(parents=True, exist_ok=True)
    now = iso(utcnow())
    caps_by = {c.deliver_id: discover_capabilities(cfg, c) for c in m.components}
    with db.tx():
        db.conn.execute("UPDATE deliver_capabilities SET active=0 WHERE system_id=?", (m.system_id,))
        for deliver_id, name, text, c in docs:
            rel = f"{m.context_dir}/{name}"
            path = out_dir / name
            if not path.exists() or path.read_text(encoding="utf-8") != text:
                path.write_text(text, encoding="utf-8")
            sha = hashlib.sha256(text.encode()).hexdigest()
            if c is not None:
                root = _root(cfg, c)
                impl = c.entry or (str(root) if root else rel)
                definition = hashlib.sha256(json.dumps(c.__dict__, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
                db.conn.execute(
                    "INSERT INTO deliver_catalog(deliver_id,packet,owner,domain,description,source_kind,source_ref,"
                    "execution_kind,implementation_ref,definition_hash,enabled,availability,updated_at) "
                    "VALUES(?,?,?,?,?,'system_manifest',?,?,?,?,1,?,?) ON CONFLICT(deliver_id) DO UPDATE SET "
                    "packet=excluded.packet,owner=excluded.owner,domain=excluded.domain,description=excluded.description,"
                    "source_kind=excluded.source_kind,source_ref=excluded.source_ref,execution_kind=excluded.execution_kind,"
                    "implementation_ref=excluded.implementation_ref,definition_hash=excluded.definition_hash,enabled=1,"
                    "availability=excluded.availability,updated_at=excluded.updated_at",
                    (deliver_id, m.system_id, c.owner, c.domain, f"{c.title} — {c.description.strip()}"[:2000],
                     f"{manifest_ref}#{deliver_id}", c.execution_kind, impl, definition, c.availability, now))
                db.conn.execute(
                    "INSERT INTO deliver_graph_access(deliver_id,access_mode,scope_text,max_chunks,max_chars,updated_at) "
                    "VALUES(?,?,?,6,6000,?) ON CONFLICT(deliver_id) DO UPDATE SET access_mode=excluded.access_mode,"
                    "scope_text=excluded.scope_text,updated_at=excluded.updated_at",
                    (deliver_id, c.graph_access, c.graph_scope or c.title, now))
            tags = [m.system_id, *(m.tags if c is None else [*m.tags, *c.tags, c.domain])]
            source_key = f"system:{m.system_id}:{deliver_id}"
            db.conn.execute(
                "INSERT INTO context_sources(source_key,task_id,deliver_id,origin_kind,origin_ref,graph_entity_id,"
                "graph_revision,title,excerpt,content_sha256,tags_json,active,created_at,updated_at) "
                "VALUES(?,NULL,?,'system_context',?,NULL,?,?,?,?,?,1,?,?) ON CONFLICT(source_key) DO UPDATE SET "
                "deliver_id=excluded.deliver_id,origin_ref=excluded.origin_ref,graph_revision=excluded.graph_revision,"
                "title=excluded.title,excerpt=excluded.excerpt,content_sha256=excluded.content_sha256,"
                "tags_json=excluded.tags_json,active=1,updated_at=CASE WHEN context_sources.content_sha256="
                "excluded.content_sha256 THEN context_sources.updated_at ELSE excluded.updated_at END",
                (source_key, c.deliver_id if c else None, rel, sha[:16],
                 (f"{m.title}: {c.title}" if c else f"{m.title} — מפת המערכת"), text, sha,
                 json.dumps(list(dict.fromkeys(tags)), ensure_ascii=False), now, now))
            db.conn.execute(
                "INSERT INTO system_onboarding(system_id,deliver_id,manifest_ref,context_path,content_sha256,updated_at) "
                "VALUES(?,?,?,?,?,?) ON CONFLICT(system_id,deliver_id) DO UPDATE SET manifest_ref=excluded.manifest_ref,"
                "context_path=excluded.context_path,content_sha256=excluded.content_sha256,updated_at=excluded.updated_at",
                (m.system_id, deliver_id, manifest_ref, rel, sha, now))
            report["components"].append({"deliver_id": deliver_id, "file": rel, "chars": len(text), "sha": sha[:12]})
        for c in m.components:
            for cap in caps_by[c.deliver_id]:
                db.conn.execute(
                    "INSERT INTO deliver_capabilities(capability_id,deliver_id,system_id,group_name,name,kind,source_ref,"
                    "description,active,updated_at) VALUES(?,?,?,?,?,?,?,?,1,?) ON CONFLICT(capability_id) DO UPDATE SET "
                    "deliver_id=excluded.deliver_id,system_id=excluded.system_id,group_name=excluded.group_name,"
                    "name=excluded.name,kind=excluded.kind,source_ref=excluded.source_ref,description=excluded.description,"
                    "active=1,updated_at=excluded.updated_at",
                    (cap["capability_id"], c.deliver_id, m.system_id, cap["group"], cap["name"], cap["kind"],
                     cap["source"], cap["description"], now))
        report["capabilities"] = {d: len(v) for d, v in caps_by.items()}
        # Edges last: a component may depend on one listed after it in the manifest.
        for c in m.components:
            for dep in c.depends_on:
                lid = "system-prerequisite:" + hashlib.sha256(f"{dep}->{c.deliver_id}".encode()).hexdigest()[:24]
                db.conn.execute(
                    "INSERT INTO deliver_listener_edges(listener_id,source_deliver_id,target_deliver_id,event_type,"
                    "context_selector,source_kind,edge_type,jev_gate,enabled,proposal_reason,updated_at) "
                    "VALUES(?,?,?,'PREREQUISITE_PASSED',NULL,'system_manifest','prerequisite',0,1,?,?) "
                    "ON CONFLICT(listener_id) DO UPDATE SET enabled=1,updated_at=excluded.updated_at",
                    (lid, dep, c.deliver_id, f"{c.deliver_id} builds on {dep} ({m.system_id})", now))
    db.set_flag(f"onboarding_title:{m.system_id}", m.title)
    db.event("SYSTEM_ONBOARDED", system=m.system_id, manifest=manifest_ref, components=len(m.components),
             context_dir=m.context_dir)
    do_graph = m.graph_ingest if graph is None else graph
    if do_graph:
        report["graph"] = push_structured_graph(cfg, db, m, graph_service=graph_service, progress=progress)
        if m.graph_text:
            report["graph"]["text"] = ingest_to_graph(cfg, db, m.system_id, graph_service=graph_service,
                                                      progress=progress)
    return report


def structured_graph(cfg: Config, db: DB, m: SystemManifest) -> tuple[list[dict], list[dict]]:
    """System -> component Deliver -> capability (group) -> sub-capability, plus Deliver dependencies.
    Entity names are the stable ids, so re-running updates the same nodes."""
    ents: list[dict] = [{"name": f"system:{m.system_id}", "type": "SYSTEM",
                         "description": f"{m.title}. {m.description.strip()}", "snippet": m.context_dir}]
    rels: list[dict] = []
    known = {c.deliver_id for c in m.components}
    for c in m.components:
        ents.append({"name": c.deliver_id, "type": "DELIVER",
                     "description": f"{c.title}. {c.description.strip()} (תחום {c.domain}, בעלים {c.owner}, "
                                    f"ביצוע {c.execution_kind}, זמינות {c.availability})",
                     "snippet": f"{m.context_dir}/{_file_name(c.deliver_id)}"})
        rels.append({"from_name": f"system:{m.system_id}", "to_name": c.deliver_id, "rel_type": "HAS_COMPONENT"})
        for dep in c.depends_on:
            if dep not in known:
                ents.append({"name": dep, "type": "DELIVER", "description": f"Deliver {dep} (existing catalog)",
                             "snippet": ""})
            rels.append({"from_name": c.deliver_id, "to_name": dep, "rel_type": "DEPENDS_ON"})
        groups: dict[str, str] = {}
        for cap in db.q("SELECT * FROM deliver_capabilities WHERE deliver_id=? AND active=1 ORDER BY capability_id",
                        (c.deliver_id,)):
            gid = cap["capability_id"].rsplit("/", 1)[0]
            if gid not in groups:
                groups[gid] = cap["group_name"]
                ents.append({"name": gid, "type": "CAPABILITY", "description": f"{cap['group_name']} — {c.title}",
                             "snippet": c.deliver_id})
                rels.append({"from_name": c.deliver_id, "to_name": gid, "rel_type": "HAS_CAPABILITY"})
            ents.append({"name": cap["capability_id"], "type": "SUBCAPABILITY",
                         "description": " — ".join(x for x in (cap["name"], cap["description"], cap["group_name"],
                                                               c.title) if x),
                         "snippet": cap["source_ref"] or ""})
            rels.append({"from_name": gid, "to_name": cap["capability_id"], "rel_type": "HAS_SUBCAPABILITY"})
    unique = list({e["name"]: e for e in ents}.values())
    return unique, rels


def push_structured_graph(cfg: Config, db: DB, m: SystemManifest, *, graph_service=None, force: bool = False,
                          progress=None, batch: int = 40) -> dict:
    """Write the capability tree to the graph RAG service (``POST /ingest/structured``); skipped when unchanged."""
    if graph_service is None and not cfg.section("graph_rag").get("allow_ingest", False):
        return {"enabled": False, "reason": "the public graph API is read-only"}
    from .graph_rag import GraphRagError, GraphRagService
    svc = graph_service or GraphRagService(cfg, db)
    ents, rels = structured_graph(cfg, db, m)
    digest = hashlib.sha256(json.dumps([ents, rels], sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    flag = f"onboarding_graph:{m.system_id}"
    if not force and db.get_flag(flag) == digest:
        return {"enabled": True, "mode": "structured", "skipped_unchanged": True, "entities": len(ents),
                "relationships": len(rels)}
    sent_e = sent_r = 0
    try:
        for i in range(0, len(ents), batch):
            r = svc.transport("POST", "/ingest/structured", {"source": f"onboarding:{m.system_id}",
                                                              "entities": ents[i:i + batch], "relationships": []}, 120.0)
            if not r.get("ok"):
                raise GraphRagError(str(r.get("error") or "structured ingest failed"))
            sent_e += int(r.get("entities") or 0)
            if progress:
                progress(f"graph entities {sent_e}/{len(ents)}")
        for i in range(0, len(rels), batch * 3):
            r = svc.transport("POST", "/ingest/structured", {"source": f"onboarding:{m.system_id}", "entities": [],
                                                              "relationships": rels[i:i + batch * 3]}, 120.0)
            if not r.get("ok"):
                raise GraphRagError(str(r.get("error") or "structured ingest failed"))
            sent_r += int(r.get("relationships") or 0)
        if progress:
            progress(f"graph relationships {sent_r}/{len(rels)}")
    except GraphRagError as exc:
        db.event("SYSTEM_GRAPH_FAILED", system=m.system_id, error=str(exc)[:300], entities=sent_e)
        return {"enabled": True, "mode": "structured", "ok": False, "error": str(exc)[:300], "entities": sent_e,
                "relationships": sent_r}
    db.set_flag(flag, digest)
    db.x("UPDATE system_onboarding SET graph_status='INGESTED', graph_detail='structured', "
         "graph_ingested_sha=content_sha256, graph_ingested_at=? WHERE system_id=?", (iso(utcnow()), m.system_id))
    db.event("SYSTEM_GRAPH_INGESTED", system=m.system_id, mode="structured", entities=sent_e, relationships=sent_r)
    return {"enabled": True, "mode": "structured", "ok": True, "entities": sent_e, "relationships": sent_r}


GRAPH_CHUNK_CHARS = 3800   # the RAG service analyses at most ~4000 characters per /ingest call


def graph_chunks(text: str, limit: int = GRAPH_CHUNK_CHARS) -> list[str]:
    """Split a context file on its ``##``/``###`` headings into parts the RAG service reads completely.
    Every part repeats the file's title line so the extracted entities stay attached to the component."""
    lines = text.splitlines()
    title = lines[0] if lines and lines[0].startswith("# ") else ""
    sections, cur = [], []
    for ln in lines[1:] if title else lines:
        if ln.startswith(("## ", "### ")) and cur:
            sections.append("\n".join(cur))
            cur = []
        cur.append(ln)
    if cur:
        sections.append("\n".join(cur))
    budget = limit - len(title) - 2
    parts, buf = [], ""
    for sec in sections:
        while len(sec) > budget:                       # one oversized section: hard-split on lines
            cut = sec.rfind("\n", 0, budget)
            cut = cut if cut > 0 else budget
            if buf.strip():
                parts.append(buf)
                buf = ""
            parts.append(sec[:cut])
            sec = sec[cut:].lstrip("\n")
        if len(buf) + len(sec) + 1 > budget and buf.strip():
            parts.append(buf)
            buf = ""
        buf = f"{buf}\n{sec}" if buf else sec
    if buf.strip():
        parts.append(buf)
    return [f"{title}\n\n{p.strip()}" if title else p.strip() for p in parts if p.strip()]


def ingest_to_graph(cfg: Config, db: DB, system_id: str, *, graph_service=None, force: bool = False,
                    progress=None) -> dict:
    """Send changed context files to the graph RAG service (``POST /ingest``). Never re-sends unchanged text."""
    if graph_service is None and not cfg.section("graph_rag").get("allow_ingest", False):
        return {"enabled": False, "reason": "the public graph API is read-only"}
    from .graph_rag import GraphRagError, GraphRagService
    svc = graph_service or GraphRagService(cfg, db)
    done = skipped = failed = 0
    for r in db.q("SELECT * FROM system_onboarding WHERE system_id=? ORDER BY deliver_id", (system_id,)):
        if not force and r["graph_status"] == "INGESTED" and r["graph_ingested_sha"] == r["content_sha256"]:
            skipped += 1
            continue
        path = cfg.repo / r["context_path"]
        try:
            parts = graph_chunks(path.read_text(encoding="utf-8"))
            results = []
            for i, part in enumerate(parts, 1):
                result = svc.transport("POST", "/ingest", {"file_name": f"{system_id}/{path.name}#part{i}",
                                                           "content": part, "force_type": "doc"}, 600.0)
                results.append(result)
                if not result.get("ok"):
                    break
            ok = len(results) == len(parts) and all(r.get("ok") for r in results)
            status = "INGESTED" if ok else "FAILED"
            detail = json.dumps({"parts": len(parts), "sent": len(results),
                                 "entities": sum(int(r.get("entities") or 0) for r in results),
                                 "relationships": sum(int(r.get("relationships") or 0) for r in results),
                                 "mode": results[-1].get("mode") if results else None,
                                 "error": next((r.get("error") for r in results if not r.get("ok")), None)})
        except (GraphRagError, OSError) as exc:
            ok, status, detail = False, "FAILED", str(exc)[:300]
        db.x("UPDATE system_onboarding SET graph_status=?, graph_detail=?, graph_ingested_sha=CASE WHEN ?=1 THEN "
             "content_sha256 ELSE graph_ingested_sha END, graph_ingested_at=CASE WHEN ?=1 THEN ? ELSE graph_ingested_at END "
             "WHERE system_id=? AND deliver_id=?", (status, detail, int(ok), int(ok), iso(utcnow()), system_id, r["deliver_id"]))
        done, failed = done + ok, failed + (not ok)
        if progress:
            progress(f"{r['deliver_id']}: {status} {detail}")
    db.event("SYSTEM_GRAPH_INGESTED", system=system_id, ingested=done, skipped=skipped, failed=failed)
    return {"enabled": True, "ingested": done, "skipped_unchanged": skipped, "failed": failed}


def systems(db: DB) -> list[dict]:
    return [dict(r) for r in db.q(
        "SELECT system_id, manifest_ref, COUNT(*) - SUM(deliver_id='__index__') components, "
        "SUM(graph_status='INGESTED' AND graph_ingested_sha=content_sha256) graph_current, MAX(updated_at) updated_at, "
        "(SELECT COUNT(*) FROM deliver_capabilities c WHERE c.system_id=o.system_id AND c.active=1) capabilities "
        "FROM system_onboarding o GROUP BY system_id, manifest_ref ORDER BY system_id")]
