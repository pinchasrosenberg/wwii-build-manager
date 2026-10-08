"""Parse the worker's TaskResult handoff. Raw output is always kept on disk by the
runner; this only extracts structure when it exists."""
from __future__ import annotations

import json
import re
from typing import Any

from .prompts import OPTIONAL_RESULT_KEYS, RESULT_SCHEMA

VALID, MALFORMED, MISSING = "VALID", "MALFORMED", "MISSING"
_FENCE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.S)


def _candidates(text: str) -> list[str]:
    out = [m.group(1) for m in _FENCE.finditer(text)]
    # last top-level {...} block
    depth, start = 0, None
    blocks = []
    in_str = esc = False
    for i, ch in enumerate(text):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}" and depth:
            depth -= 1
            if depth == 0 and start is not None:
                blocks.append(text[start:i + 1])
    out.extend(reversed(blocks))
    return out


def normalize(obj: dict, task_id: str) -> tuple[dict, list[str]]:
    """Fill missing keys with empty values; report what was missing/wrong."""
    problems = []
    out: dict[str, Any] = {}
    for key, spec in RESULT_SCHEMA["properties"].items():
        if key not in obj:
            if key not in OPTIONAL_RESULT_KEYS:
                problems.append(f"missing {key}")
            t = spec.get("type")
            out[key] = [] if t == "array" else (False if t == "boolean" else (None if isinstance(t, list) else ""))
            continue
        v = obj[key]
        t = spec.get("type")
        if t == "array" and not isinstance(v, list):
            problems.append(f"{key} not a list")
            v = [v] if v else []
        out[key] = v
    if out.get("task_id") and out["task_id"] != task_id:
        problems.append(f"task_id mismatch ({out['task_id']})")
    out["task_id"] = task_id
    return out, problems


def parse_result(task_id: str, structured: Any = None, text: str | None = None) -> tuple[dict | None, str, list[str]]:
    """Returns (handoff | None, VALID|MALFORMED|MISSING, problems)."""
    obj = None
    if isinstance(structured, dict):
        obj = structured
    elif isinstance(structured, str):
        try:
            obj = json.loads(structured)
        except ValueError:
            obj = None
    if obj is None and text:
        for cand in _candidates(text):
            try:
                c = json.loads(cand)
            except ValueError:
                continue
            if isinstance(c, dict) and ("summary" in c or "status" in c or "changed_files" in c):
                obj = c
                break
    if obj is None:
        return None, (MALFORMED if text and text.strip() else MISSING), ["no parseable JSON handoff"]
    norm, problems = normalize(obj, task_id)
    return norm, (VALID if not problems else MALFORMED), problems
