"""Bounded, read-only access to the public WWII Atlas graph API (see the wwii-atlas repo, ``api/``).

Only HTTPS endpoints on public hosts are accepted: the manager can never reach a database, a loopback
service or a private network address. Nothing is configured by default.

The service only creates context candidates. Jev must explicitly select a
candidate before it can be returned to an MCP caller or included in an LLM
prompt.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import ipaddress
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable

from .config import Config
from .db import DB


class GraphRagError(ValueError):
    pass


Transport = Callable[[str, str, dict | None, float], dict]
_CYPHER_FORBIDDEN = re.compile(
    r"\b(?:CREATE|MERGE|SET|REMOVE|DELETE|DROP|ALTER|LOAD\s+CSV|CALL|FOREACH|USE|"
    r"GRANT|DENY|REVOKE|TERMINATE|START\s+DATABASE|STOP\s+DATABASE|SHOW|PROFILE|EXPLAIN)\b", re.I)


class GraphRagService:
    def __init__(self, cfg: Config, db: DB, transport: Transport | None = None,
                 cypher_transport: Transport | None = None):
        self.cfg = cfg
        self.db = db
        self.settings = cfg.section("graph_rag")
        self.transport = transport or self._http
        self.cypher_transport = cypher_transport or self._cypher_http

    @staticmethod
    def _public_url(value: str, label: str) -> str:
        value = value.strip().rstrip("/")
        if not value:
            return ""  # not configured: shown as empty, refused by the transport
        parsed = urllib.parse.urlparse(value)
        host = (parsed.hostname or "").lower()
        if parsed.scheme != "https" or not host or host == "localhost" or host.endswith((".local", ".internal")):
            raise GraphRagError(f"כתובת {label} חייבת להיות שירות HTTPS ציבורי")
        try:
            ip = ipaddress.ip_address(host)
        except ValueError:
            ip = None  # a hostname
        if ip is not None and not ip.is_global:
            raise GraphRagError(f"כתובת {label} חייבת להיות שירות HTTPS ציבורי")
        return value

    @property
    def base_url(self) -> str:
        value = (self.db.get_flag("graph_rag_url") or self.settings.get("url") or "").strip().rstrip("/")
        return self._public_url(value, "גרף ה־RAG")

    @property
    def cypher_base_url(self) -> str:
        value = (self.db.get_flag("graph_cypher_url") or self.settings.get("cypher_url") or
                 self.db.get_flag("graph_rag_url") or self.settings.get("url") or "")
        return self._public_url(str(value), "קונסולת ה־Cypher")

    @staticmethod
    def console_key() -> str:
        """Owner key for the API's read-only Cypher console; read from the environment only."""
        return os.environ.get("WW2_GRAPH_CONSOLE_KEY", "").strip()

    @property
    def timeout(self) -> float:
        return max(2.0, min(float(self.settings.get("timeout_seconds", 45)), 120.0))

    def configure(self, url: str) -> None:
        old = self.db.get_flag("graph_rag_url")
        self.db.set_flag("graph_rag_url", url.strip().rstrip("/"))
        try:
            _ = self.base_url
        except Exception:
            self.db.set_flag("graph_rag_url", old)
            raise

    def configure_cypher(self, url: str) -> None:
        old = self.db.get_flag("graph_cypher_url")
        self.db.set_flag("graph_cypher_url", url.strip().rstrip("/"))
        try:
            _ = self.cypher_base_url
        except Exception:
            self.db.set_flag("graph_cypher_url", old)
            raise

    def _http_at(self, base_url: str, method: str, path: str, payload: dict | None, timeout: float,
                 headers: dict | None = None) -> dict:
        data = json.dumps(payload, ensure_ascii=False).encode() if payload is not None else None
        req = urllib.request.Request(base_url + path, data=data, method=method,
                                     headers={"Content-Type": "application/json", **(headers or {})})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                raw = response.read(2_000_001)
        except urllib.error.HTTPError as exc:
            try:
                detail = json.loads(exc.read(16_384).decode("utf-8", errors="replace"))
                message = detail.get("message") or detail.get("error") or str(exc)
            except Exception:
                message = str(exc)
            raise GraphRagError(str(message)[:500]) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise GraphRagError("שירות גרף ה־RAG אינו זמין") from exc
        if len(raw) > 2_000_000:
            raise GraphRagError("תשובת גרף ה־RAG גדולה מהמותר")
        try:
            result = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise GraphRagError("שירות גרף ה־RAG החזיר תשובה לא תקינה") from exc
        if not isinstance(result, dict):
            raise GraphRagError("שירות גרף ה־RAG החזיר מבנה לא תקין")
        return result

    def _http(self, method: str, path: str, payload: dict | None, timeout: float) -> dict:
        if not self.base_url:
            raise GraphRagError("כתובת ה־API של הגרף לא הוגדרה")
        return self._http_at(self.base_url, method, path, payload, timeout)

    def _cypher_http(self, method: str, path: str, payload: dict | None, timeout: float) -> dict:
        key = self.console_key()
        if not self.cypher_base_url:
            raise GraphRagError("כתובת ה־API של הגרף לא הוגדרה")
        if not key:
            raise GraphRagError("קונסולת ה־Cypher דורשת WW2_GRAPH_CONSOLE_KEY בסביבה")
        return self._http_at(self.cypher_base_url, method, path, payload, timeout,
                             headers={"Authorization": f"Bearer {key}"})

    @staticmethod
    def validate_read_cypher(cypher: str) -> str:
        query = str(cypher or "").strip()
        if not query or len(query) > 20_000:
            raise GraphRagError("שאילתת Cypher חייבת להיות באורך 1–20,000 תווים")
        code = re.sub(r"/\*.*?\*/|//[^\n]*", " ", query, flags=re.S)
        code = re.sub(r"'(?:\\.|''|[^'])*'|\"(?:\\.|\"\"|[^\"])*\"", "''", code)
        if ";" in code.rstrip().rstrip(";"):
            raise GraphRagError("מותרת פקודת Cypher אחת בלבד")
        if _CYPHER_FORBIDDEN.search(code):
            raise GraphRagError("קונסולת הגרף מאפשרת שאילתות קריאה בלבד")
        if not re.match(r"^\s*(?:MATCH|OPTIONAL\s+MATCH|WITH|UNWIND|RETURN)\b", code, re.I):
            raise GraphRagError("השאילתה חייבת להתחיל ב־MATCH, OPTIONAL MATCH, WITH, UNWIND או RETURN")
        if not re.search(r"\bRETURN\b", code, re.I):
            raise GraphRagError("שאילתת קריאה חייבת לכלול RETURN")
        return query

    def query_cypher(self, cypher: str, parameters: dict | None = None, max_rows: int = 100) -> dict:
        query = self.validate_read_cypher(cypher)
        if parameters is None:
            parameters = {}
        if not isinstance(parameters, dict):
            raise GraphRagError("פרמטרי Cypher חייבים להיות אובייקט JSON")
        rows = max(1, min(int(max_rows), 200))
        result = self.cypher_transport("POST", "/query", {
            "cypher": query, "parameters": parameters, "max_rows": rows,
            "timeout_seconds": min(self.timeout, 15.0),
        }, min(self.timeout, 20.0))
        if not result.get("ok"):
            raise GraphRagError(str(result.get("message") or result.get("error") or "שאילתת Cypher נכשלה")[:500])
        return result

    def query_natural(self, question: str) -> dict:
        value = str(question or "").strip()
        if not value or len(value) > 12_000:
            raise GraphRagError("השאלה חייבת להיות באורך 1–12,000 תווים")
        result = self.transport("POST", "/pipeline/query", {
            "question": value,
            "session_id": "wwii-task-manager:graph-console",
            "use_cypher": True,
            "use_vector": True,
        }, self.timeout)
        if not result.get("ok"):
            raise GraphRagError(str(result.get("error") or "שאילתת השפה החופשית נכשלה")[:500])
        return result

    def health(self) -> dict:
        started = time.monotonic()
        try:
            health = self.transport("GET", "/health", None, min(self.timeout, 8.0))
            if not health.get("ok"):
                raise GraphRagError("בדיקת התקינות נכשלה")
            stats = self.transport("GET", "/entities/stats", None, min(self.timeout, 12.0))
            if not stats.get("ok"):
                stats = {}
            return {"status": "READY", "url": self.base_url, "reachable": True,
                    "model": health.get("model"), "neo4j": health.get("neo4j"),
                    "nodes": stats.get("nodeCount"), "relationships": stats.get("relCount"),
                    "insights": stats.get("insightCount"),
                    "latency_ms": int((time.monotonic() - started) * 1000)}
        except GraphRagError as exc:
            try:
                url = self.base_url
            except GraphRagError:
                url = ""
            return {"status": "UNREACHABLE" if url else "NOT_CONFIGURED", "url": url, "reachable": False,
                    "model": None, "nodes": None, "relationships": None, "insights": None,
                    "latency_ms": int((time.monotonic() - started) * 1000), "detail": str(exc)}

    def access(self, deliver_id: str, *, planner: bool = False) -> dict:
        if planner:
            return {"deliver_id": deliver_id, "access_mode": "full", "scope_text": "",
                    "max_chunks": int(self.settings.get("planner_max_chunks", 24)),
                    "max_chars": int(self.settings.get("planner_max_chars", 24000))}
        row = self.db.one("SELECT * FROM deliver_graph_access WHERE deliver_id=?", (deliver_id,))
        return dict(row) if row else {"deliver_id": deliver_id, "access_mode": "none", "scope_text": "",
                                      "max_chunks": 6, "max_chars": 6000}

    def save_access(self, deliver_id: str, mode: str, scope_text: str = "",
                    max_chunks: int = 6, max_chars: int = 6000) -> None:
        if mode not in {"none", "limited", "full"}:
            raise GraphRagError("מצב הגישה חייב להיות ללא גישה, מוגבל או מלא")
        if not self.db.one("SELECT 1 FROM deliver_catalog WHERE deliver_id=?", (deliver_id,)):
            raise GraphRagError("ה־Deliver המבוקש אינו קיים")
        max_chunks = max(1, min(int(max_chunks), 50))
        max_chars = max(500, min(int(max_chars), 100_000))
        now = dt.datetime.now(dt.timezone.utc).isoformat()
        self.db.x(
            "INSERT INTO deliver_graph_access(deliver_id,access_mode,scope_text,max_chunks,max_chars,updated_at) "
            "VALUES(?,?,?,?,?,?) ON CONFLICT(deliver_id) DO UPDATE SET access_mode=excluded.access_mode,"
            "scope_text=excluded.scope_text,max_chunks=excluded.max_chunks,max_chars=excluded.max_chars,updated_at=excluded.updated_at",
            (deliver_id, mode, scope_text.strip(), max_chunks, max_chars, now))
        self.db.event("DELIVER_GRAPH_ACCESS_CHANGED", task_id=deliver_id, source="dashboard",
                      access_mode=mode, max_chunks=max_chunks, max_chars=max_chars)

    @staticmethod
    def _chunks(text: str, max_chars: int) -> list[str]:
        pieces = [p.strip() for p in re.split(r"\n\s*\n|(?=--- [A-Z])", text) if p.strip()]
        out: list[str] = []
        for piece in pieces:
            while piece:
                out.append(piece[:2000])
                piece = piece[2000:]
                if sum(len(item) for item in out) >= max_chars:
                    return out
        return out

    def retrieve_candidates(self, scope_id: str, question: str, *, planner: bool = False) -> list[dict]:
        policy = self.access(scope_id, planner=planner)
        mode = policy["access_mode"]
        if mode == "none" or not question.strip():
            self._record(scope_id, mode, question, 0, "NO_ACCESS", 0)
            return []
        scoped_question = question.strip()
        scope_text = (policy.get("scope_text") or "").strip()
        if mode == "limited" and scope_text:
            scoped_question = f"תחום גישה מותר: {scope_text}\n\nהשאלה: {scoped_question}"
        started = time.monotonic()
        try:
            response = self.transport("POST", "/pipeline/query", {
                "question": scoped_question,
                "session_id": "wwii-task-manager:" + hashlib.sha256(scope_id.encode()).hexdigest()[:16],
                "use_cypher": mode == "full",
                "use_vector": True,
            }, self.timeout)
            if not response.get("ok"):
                raise GraphRagError(str(response.get("error") or "שאילתת הגרף נכשלה"))
            context = str(response.get("context") or "")
            chunks = self._chunks(context, int(policy["max_chars"]))
            if mode == "limited" and scope_text:
                terms = {term.casefold() for term in re.findall(r"[\w./-]{3,}", scope_text, re.UNICODE)}
                scoped = [chunk for chunk in chunks if any(term in chunk.casefold() for term in terms)]
                chunks = scoped
            chunks = chunks[:int(policy["max_chunks"])]
            entities = [str(x) for x in (response.get("used_entity_names") or [])[:30]]
            out = []
            for index, chunk in enumerate(chunks):
                digest = hashlib.sha256((scope_id + "\0" + chunk).encode()).hexdigest()
                out.append({
                    "id": "rag-context:" + digest[:20],
                    "source_key": "rag:" + digest[:20],
                    "description": (f"Graph RAG {mode} · entities {', '.join(entities[:6]) or 'unknown'} · "
                                    + re.sub(r"\s+", " ", chunk)[:360]),
                    "execution_kind": "graph_rag_context",
                    "excerpt": chunk,
                    "origin_kind": "graph_rag",
                    "origin_ref": self.base_url,
                    "graph_entity_id": entities[index] if index < len(entities) else None,
                    "access_mode": mode,
                })
            self._record(scope_id, mode, question, len(out), "CANDIDATES", started)
            return out
        except GraphRagError as exc:
            self._record(scope_id, mode, question, 0, "UNREACHABLE", started, str(exc))
            return []

    def _record(self, scope_id: str, mode: str, question: str, count: int,
                status: str, started: float, detail: str | None = None,
                selected_count: int = 0) -> None:
        latency = int((time.monotonic() - started) * 1000) if started else 0
        self.db.x(
            "INSERT INTO graph_rag_queries(created_at,scope_id,access_mode,query_sha256,candidate_count,selected_count,status,latency_ms,detail) "
            "VALUES(?,?,?,?,?,?,?,?,?)",
            (dt.datetime.now(dt.timezone.utc).isoformat(), scope_id, mode,
             hashlib.sha256(question.encode()).hexdigest(), count, selected_count, status, latency, detail))

    def selected_query(self, jev: Any, scope_id: str, question: str, *, planner: bool = False) -> dict:
        candidates = self.retrieve_candidates(scope_id, question, planner=planner)
        selected_ids = jev.select_context_bundles(
            scope_id, candidates, f"{scope_id}: select only Graph RAG evidence needed for this request") if candidates else []
        by_id = {item["id"]: item for item in candidates}
        selected = [by_id[item_id] for item_id in selected_ids if item_id in by_id]
        if candidates:
            self.db.x("UPDATE graph_rag_queries SET selected_count=?,status=? WHERE id=(SELECT MAX(id) FROM graph_rag_queries WHERE scope_id=?)",
                      (len(selected), "JEV_SELECTED" if selected else "JEV_NO_MATCH", scope_id))
        return {"scope_id": scope_id, "access": self.access(scope_id, planner=planner)["access_mode"],
                "gate": "jev", "candidate_count": len(candidates), "selected": selected}
