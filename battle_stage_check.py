#!/usr/bin/env python3
"""Deterministic acceptance check for one stage of a battle-request chain (stdlib only, no network, no model).

    python3 tools/build_manager/battle_stage_check.py <stage> <battle_key> [--root DIR]

The chain tasks (see systems/battle_request_templates.toml) list this as their acceptance command. It only checks that
the files a stage must produce exist under game/episodes/<battle_key>/ and have the contracted shape; it does not judge
historical truth. Exit 0 = pass, 1 = failed (every problem is printed), 2 = bad usage.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

KEY_RE = re.compile(r"[a-z0-9][a-z0-9_-]*\Z")
PROVENANCE = {"SOURCED", "MAP_DERIVED", "INFERRED"}
STAGES = ("evidence", "map_research", "web_research", "reconstruct", "package")
INPUTS = ("evidence/dossier.json", "maps/map_evidence.json", "research/research.json",
          "reconstruction/reconstruction.json")


def _load(path: Path, problems: list[str]):
    if not path.is_file() or path.stat().st_size == 0:
        problems.append(f"missing or empty: {path.as_posix()}")
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        problems.append(f"not valid JSON: {path.as_posix()} ({exc})")
        return None


def _lists(data, keys, name: str, problems: list[str]) -> None:
    if not isinstance(data, dict):
        problems.append(f"{name}: top level must be a JSON object")
        return
    for key in keys:
        if not isinstance(data.get(key), list):
            problems.append(f"{name}: '{key}' must be a list")


def _walk_provenance(value, found: list, problems: list[str], where: str = "$") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "provenance":
                found.append(item)
                if item not in PROVENANCE:
                    problems.append(f"{where}.provenance = {item!r}; allowed: {sorted(PROVENANCE)}")
            else:
                _walk_provenance(item, found, problems, f"{where}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _walk_provenance(item, found, problems, f"{where}[{index}]")


def check_evidence(episode: Path, key: str, problems: list[str]) -> None:
    data = _load(episode / "evidence/dossier.json", problems)
    if data is not None:
        _lists(data, ("facts", "unknowns", "sources"), "dossier.json", problems)
        if isinstance(data, dict) and data.get("battle_key") != key:
            problems.append(f"dossier.json: battle_key is {data.get('battle_key')!r}, expected {key!r}")
    md = episode / "evidence/EVIDENCE.md"
    if not md.is_file() or md.stat().st_size == 0:
        problems.append(f"missing or empty: {md.as_posix()}")


def check_map_research(episode: Path, key: str, problems: list[str]) -> None:
    data = _load(episode / "maps/map_evidence.json", problems)
    if data is None:
        return
    _lists(data, ("maps", "observations", "gaps", "acquisition"), "map_evidence.json", problems)
    if isinstance(data, dict) and isinstance(data.get("maps"), list) and not data["maps"] and not data.get("gaps"):
        problems.append("map_evidence.json: no maps and no gaps; a missing map must be recorded as a gap "
                        "(MAP_COVERAGE_GAP / MAP_BBOX_UNKNOWN)")


def check_web_research(episode: Path, key: str, problems: list[str]) -> None:
    data = _load(episode / "research/research.json", problems)
    if data is None:
        return
    _lists(data, ("units", "events", "citations", "gap_searches", "inferred"), "research.json", problems)
    if not isinstance(data, dict):
        return
    if data.get("battle_key") != key:
        problems.append(f"research.json: battle_key is {data.get('battle_key')!r}, expected {key!r}")
    cited = set()
    for index, cit in enumerate(data.get("citations") or []):
        if not isinstance(cit, dict):
            problems.append(f"citations[{index}] must be an object")
            continue
        cited.add(cit.get("id"))
        if not str(cit.get("url") or "").startswith(("http://", "https://")):
            problems.append(f"citations[{index}]: url must be http(s)")
        if not str(cit.get("quote") or "").strip():
            problems.append(f"citations[{index}]: a short quote is required")
    for index, item in enumerate(data.get("inferred") or []):
        if not isinstance(item, dict):
            problems.append(f"inferred[{index}] must be an object")
            continue
        if item.get("provenance") != "INFERRED":
            problems.append(f"inferred[{index}]: provenance must be 'INFERRED'")
        if not str(item.get("rationale") or "").strip():
            problems.append(f"inferred[{index}]: a rationale is required")
        conf = item.get("confidence")
        if isinstance(conf, bool) or not isinstance(conf, (int, float)) or not 0 <= conf <= 1:
            problems.append(f"inferred[{index}]: confidence must be a number in 0..1")
    for section in ("units", "events"):
        for index, item in enumerate(data.get(section) or []):
            if isinstance(item, dict) and item.get("provenance") == "SOURCED":
                ids = item.get("citation_ids")
                if not isinstance(ids, list) or not ids or any(i not in cited for i in ids):
                    problems.append(f"{section}[{index}]: a SOURCED claim must cite existing citation ids")
            elif isinstance(item, dict) and item.get("provenance") not in PROVENANCE:
                problems.append(f"{section}[{index}]: provenance must be one of {sorted(PROVENANCE)}")
    # Gap-driven: every unknown of the dossier must have a recorded search.
    dossier = _load(episode / "evidence/dossier.json", problems)
    if isinstance(dossier, dict):
        searched = {g.get("gap_id") for g in data.get("gap_searches") or [] if isinstance(g, dict)}
        for gap in dossier.get("unknowns") or []:
            gap_id = gap.get("id") if isinstance(gap, dict) else None
            if gap_id and gap_id not in searched:
                problems.append(f"gap_searches: no search recorded for dossier unknown {gap_id}")
    for index, search in enumerate(data.get("gap_searches") or []):
        if not isinstance(search, dict) or not search.get("gap_id") or not search.get("query"):
            problems.append(f"gap_searches[{index}]: gap_id and query are required")


def check_reconstruct(episode: Path, key: str, problems: list[str]) -> None:
    data = _load(episode / "reconstruction/reconstruction.json", problems)
    if data is None:
        return
    if not isinstance(data, dict) or not data:
        problems.append("reconstruction.json: top level must be a non-empty JSON object")
        return
    found: list = []
    _walk_provenance(data, found, problems)
    if not found:
        problems.append("reconstruction.json: no item carries a provenance label (SOURCED/MAP_DERIVED/INFERRED)")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check_package(episode: Path, key: str, problems: list[str]) -> None:
    package = episode / "package"
    manifest = _load(package / "package_manifest.json", problems)
    if manifest is None:
        return
    if not isinstance(manifest, dict):
        problems.append("package_manifest.json: top level must be a JSON object")
        return
    if manifest.get("battle_key") != key:
        problems.append(f"package_manifest.json: battle_key is {manifest.get('battle_key')!r}, expected {key!r}")
    inputs = manifest.get("inputs")
    if not isinstance(inputs, dict):
        problems.append("package_manifest.json: 'inputs' must map input paths to sha256")
        inputs = {}
    for rel in INPUTS:
        path = episode / rel
        if rel not in inputs:
            problems.append(f"package_manifest.json: inputs lacks {rel}")
        elif not path.is_file():
            problems.append(f"missing input file: {path.as_posix()}")
        elif inputs[rel] != _sha256(path):
            problems.append(f"package_manifest.json: hash of {rel} does not match the file (stale package)")
    files = manifest.get("files")
    if not isinstance(files, list) or not files:
        problems.append("package_manifest.json: 'files' must be a non-empty list")
        return
    root = package.resolve()
    for rel in files:
        target = (package / str(rel)).resolve()
        if not target.is_relative_to(root) or not target.is_file():
            problems.append(f"package file missing or outside package/: {rel}")


CHECKS = {"evidence": check_evidence, "map_research": check_map_research, "web_research": check_web_research,
          "reconstruct": check_reconstruct, "package": check_package}


def check_stage(stage: str, battle_key: str, root: Path) -> list[str]:
    """Problems found for one stage ([] = pass)."""
    if stage not in CHECKS:
        return [f"unknown stage {stage!r}; expected one of {list(STAGES)}"]
    if not KEY_RE.fullmatch(battle_key or ""):
        return ["battle_key must contain lowercase letters, digits, '_' or '-' only"]
    problems: list[str] = []
    CHECKS[stage](Path(root) / "game" / "episodes" / battle_key, battle_key, problems)
    return problems


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("stage", choices=STAGES)
    ap.add_argument("battle_key")
    ap.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2], help="repository root")
    args = ap.parse_args(argv)
    problems = check_stage(args.stage, args.battle_key, args.root)
    for problem in problems:
        print(f"FAIL {args.stage}: {problem}", file=sys.stderr)
    if not problems:
        print(f"ok {args.stage} {args.battle_key}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
