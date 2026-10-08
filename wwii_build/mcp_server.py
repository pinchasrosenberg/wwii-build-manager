"""MCP control surface for the WWII Build Manager.

Mutation tools call the same dashboard action path. Graph reads are fail-closed:
deterministic search creates candidates and Jev must explicitly select every
result returned to the calling model.
"""
from __future__ import annotations

import base64
import binascii
import json
import sys
import uuid
from pathlib import Path

from .config import load_config
from .dashboard import Dashboard
from . import battle_request
from . import manual as mn
from . import planner_uploads
from .models import iso, utcnow
from .model_watch import ModelWatch
from .explanations import task_he


def _schema(properties: dict, required: list[str]) -> dict:
    return {"type": "object", "properties": properties, "required": required,
            "additionalProperties": False}


S = {"type": "string"}
WEB_NOTE = ("Opt-in live web access (web search/fetch) for a research task. Default false; "
            "rejected for task_target='task_manager'.")
TOOLS = [
    {"name": "planner_request", "description": "Ask the Task Manager planner what to do, plan work, or query the graph. Optional files and images are base64 uploads; Jev selects which ones reach the planner.",
     "inputSchema": _schema({"prompt": S, "mode": {"type": "string", "enum": ["plan_build", "advise_next", "graph_query"]},
                              "model_key": S, "mcp_servers": {"type": "array", "items": S},
                              "attachments": {"type": "array", "maxItems": 8, "items": {
                                  "type": "object", "properties": {"name": S, "media_type": S,
                                      "content_base64": S}, "required": ["name", "content_base64"],
                                  "additionalProperties": False}}}, ["prompt"])},
    {"name": "context_planned_task_create", "description": "Create a locked worker task through a context-planning pass. The planner searches Neo4j Graph RAG and Markdown; Jev admits the minimal sources.",
     "inputSchema": _schema({"title": S, "instructions": S, "description_he": S, "context_request": S,
                              "worker_model_key": S, "planner_model_key": S, "owner": S,
                              "task_target": {"type": "string", "enum": ["project", "task_manager"]},
                              "fallback": {"type": "boolean"}, "depends_on": {"type": "array", "items": S},
                              "write_scope": {"type": "array", "items": S}, "read_only": {"type": "boolean"},
                              "context_files": {"type": "array", "items": S},
                              "reference_files": {"type": "array", "items": S},
                              "mcp_servers": {"type": "array", "items": S},
                              "tool_names": {"type": "array", "items": S},
                              "acceptance_commands": {"type": "array", "items": S},
                              "auto_approve": {"type": "boolean"},
                              "allow_web": {"type": "boolean", "description": WEB_NOTE}},
                             ["title", "instructions", "context_request", "worker_model_key", "write_scope", "read_only"])},
    {"name": "system_repair_task_create", "description": "Create a staged self-repair task for this Task Manager. Scope is fixed to tools/build_manager; full manager tests, drift checking, rollback backup and graceful restart are mandatory.",
     "inputSchema": _schema({"title": S, "instructions": S, "description_he": S, "model_key": S,
                              "context_request": S, "planner_model_key": S,
                              "acceptance_commands": {"type": "array", "items": S},
                              "auto_approve": {"type": "boolean"}},
                             ["title", "instructions"])},
    {"name": "battle_request", "description": "Request a battle: one call creates the whole battle-builder task chain (evidence dossier -> map research -> web research -> reconstruction -> episode package) as project tasks with dependencies, best-fit models, write scope under game/episodes/<battle_key>/ and file-checking acceptance commands. Only the research task gets web access. Refused when an unfinished chain for the same battle_key exists. Templates: tools/build_manager/systems/battle_request_templates.toml.",
     "inputSchema": _schema({"title": S, "battle_key": {"type": "string", "description": "Slug (lowercase letters, digits, - and _); generated from the title when missing."},
                              "date": {"type": "string", "description": "YYYY-MM-DD or a range YYYY-MM-DD..YYYY-MM-DD."},
                              "date_end": {"type": "string", "description": "End of the range when date is only the start."},
                              "bbox": {"description": "west,south,east,north in degrees, as text or as 4 numbers.",
                                       "oneOf": [S, {"type": "array", "items": {"type": "number"}, "minItems": 4, "maxItems": 4}]},
                              "place": S, "notes": S,
                              "dry_run": {"type": "boolean", "description": "Describe the chain without creating tasks."}},
                             ["title", "date"])},
    {"name": "deliver_upsert", "description": "Create or update a Deliver definition in the Task Manager. The description must clearly explain its purpose in Hebrew.",
     "inputSchema": _schema({"deliver_id": S, "owner": S, "domain": S, "description": S,
                              "execution_kind": {"type": "string", "enum": ["worker", "deterministic", "llm_research", "context_bundle", "review"]}},
                             ["deliver_id", "description", "execution_kind"])},
    {"name": "listener_upsert", "description": "Add a Jev-gated listener proposal owned by a source Deliver/Lego.",
     "inputSchema": _schema({"listener_id": S, "source_deliver_id": S, "source_lego_id": S,
                              "target_deliver_id": S, "event_type": S, "proposal_reason": S,
                              "context_selector": {"type": "object"}},
                             ["listener_id", "source_deliver_id", "target_deliver_id", "event_type", "proposal_reason", "context_selector"])},
    {"name": "dependency_add", "description": "Add a hard prerequisite between two existing Delivers.",
     "inputSchema": _schema({"depends_on": S, "target_deliver_id": S}, ["depends_on", "target_deliver_id"])},
    {"name": "task_dependency_add", "description": "Add a hard prerequisite between two existing queued tasks.",
     "inputSchema": _schema({"depends_on": S, "task_id": S}, ["depends_on", "task_id"])},
    {"name": "task_model_set", "description": "Select the model profile used for an existing queued task.",
     "inputSchema": _schema({"task_id": S, "model_key": S}, ["task_id", "model_key"])},
    {"name": "task_expedite", "description": "Give one already READY task a one-shot front-of-queue boost. Eligibility, dependencies, quotas, capacity and writer locks are unchanged.",
     "inputSchema": _schema({"task_id": S}, ["task_id"])},
    {"name": "auto_approval_mode", "description": "Enable or disable global automatic review approval. Acceptance failures still block; enabling also approves currently pending review-only gates.",
     "inputSchema": _schema({"enabled": {"type": "boolean"}}, ["enabled"])},
    {"name": "subtask_create", "description": "Decompose an existing queued task into one persisted child with its own model, context, MCP servers and tool contract. This never creates a Deliver.",
     "inputSchema": _schema({"parent_task_id": S, "key": S, "title": S, "instructions": S, "description_he": S,
                              "owner": S, "model_key": S, "fallback": {"type": "boolean"},
                              "write_scope": {"type": "array", "items": S}, "read_only": {"type": "boolean"},
                              "context_files": {"type": "array", "items": S},
                              "context_request": S,
                              "reference_files": {"type": "array", "items": S},
                              "mcp_servers": {"type": "array", "items": S},
                              "tool_names": {"type": "array", "items": S},
                              "acceptance_commands": {"type": "array", "items": S},
                              "auto_approve": {"type": "boolean"},
                              "allow_web": {"type": "boolean", "description": WEB_NOTE}},
                             ["parent_task_id", "title", "instructions", "model_key", "write_scope", "read_only"])},
    {"name": "deliver_template_web_access_set", "description": "Opt a promoted Deliver template in to (or out of) web research access for the tasks created from it. Default is closed.",
     "inputSchema": _schema({"deliver_id": S, "allow_web": {"type": "boolean", "description": WEB_NOTE}},
                             ["deliver_id", "allow_web"])},
    {"name": "subtask_patterns", "description": "List saved subtask reuse patterns, counts, thresholds and promotion status.",
     "inputSchema": _schema({"status": {"type": "string", "enum": ["all", "learning", "eligible", "promoted", "rejected"]}}, [])},
    {"name": "subtask_promote", "description": "Explicitly promote an eligible reused subtask pattern into a governed Deliver template.",
     "inputSchema": _schema({"pattern_hash": S, "deliver_id": S, "owner": S, "domain": S, "description": S},
                             ["pattern_hash", "deliver_id"])},
    {"name": "deliver_model_set", "description": "Select the persistent model profile for an existing Deliver and its linked task, when present.",
     "inputSchema": _schema({"deliver_id": S, "model_key": S}, ["deliver_id", "model_key"])},
    {"name": "deliver_graph_access_set", "description": "Set one Deliver's Graph RAG access to none, limited or full. Retrieved context is still gated by Jev.",
     "inputSchema": _schema({"deliver_id": S, "access_mode": {"type": "string", "enum": ["none", "limited", "full"]},
                              "scope_text": S, "max_chunks": {"type": "integer", "minimum": 1, "maximum": 50},
                              "max_chars": {"type": "integer", "minimum": 500, "maximum": 100000}},
                             ["deliver_id", "access_mode"])},
    {"name": "rag_graph_query", "description": "Query the existing Graph RAG for one Deliver under its saved access policy and return only Jev-selected context.",
     "inputSchema": _schema({"deliver_id": S, "query": S}, ["deliver_id", "query"])},
    {"name": "graph_query_console", "description": "Immediately run a persisted read-only Cypher query, or ask a natural-language graph question through the selected local/Codex/Claude model without creating a queued task. Non-local model context is Jev-gated.",
     "inputSchema": _schema({"mode": {"type": "string", "enum": ["cypher", "natural"]},
                              "query": S, "model_key": S, "parameters": {"type": "object"},
                              "max_rows": {"type": "integer", "minimum": 1, "maximum": 200}},
                             ["mode", "query"])},
    {"name": "run_unstick", "description": "Diagnose why the build run is stuck and continue it: resume, approvals, backoff, provider re-probe, retry/repair of failed or blocked prerequisites (bounded), stale acceptance. Returns findings and actions in Hebrew.",
     "inputSchema": _schema({}, [])},
    {"name": "system_onboard", "description": "Bring a system into the Task Manager from a manifest in tools/build_manager/systems/: deterministic RAG context files, Delivers, context sources, graph-RAG access and (optionally) graph ingest. Idempotent.",
     "inputSchema": _schema({"manifest": S, "dry_run": {"type": "boolean"}, "graph": {"type": "boolean"}}, ["manifest"])},
    {"name": "system_onboarding_status", "description": "List onboarded systems, their components and graph-ingest state.",
     "inputSchema": _schema({}, [])},
    {"name": "rag_graph_status", "description": "Read Graph RAG health, endpoint, statistics and per-Deliver access policies.",
     "inputSchema": _schema({}, [])},
    {"name": "rag_graph_configure", "description": "Set the local Graph RAG HTTP endpoint used by the Task Manager.",
     "inputSchema": _schema({"url": S}, ["url"])},
    {"name": "task_context_access", "description": "Grant or revoke a task's access to an existing graph context candidate. Jev still decides whether it enters an LLM prompt.",
     "inputSchema": _schema({"task_id": S, "source_key": S, "active": {"type": "boolean"}},
                            ["task_id", "source_key", "active"])},
    {"name": "scoped_change_request", "description": "Ask the planner to change one existing Task or Deliver using only its local graph neighborhood and Jev-selected context.",
     "inputSchema": _schema({"scope_kind": {"type": "string", "enum": ["task", "deliver"]},
                              "scope_id": S, "prompt": S,
                              "mode": {"type": "string", "enum": ["plan_build", "advise_next", "graph_query"]},
                              "model_key": S, "mcp_servers": {"type": "array", "items": S}},
                             ["scope_kind", "scope_id", "prompt"])},
    {"name": "context_candidate_add", "description": "Add graph/provenance context as a candidate. It cannot enter an LLM prompt until Jev selects it.",
     "inputSchema": _schema({"source_key": S, "deliver_id": S, "task_id": S, "title": S, "origin_ref": S,
                              "graph_entity_id": S, "excerpt": S}, ["source_key", "title", "excerpt"])},
    {"name": "economics_update", "description": "Update a Deliver fixed price, valuation and allocated budget.",
     "inputSchema": _schema({"deliver_id": S, "currency": S, "fixed_price": {"type": "number"},
                              "valuation_amount": {"type": "number"}, "valuation_as_of": S,
                              "valuation_source_url": S, "valuation_basis": S,
                              "budget_allocated": {"type": "number"}}, ["deliver_id"])},
    {"name": "jev_selected_graph_query", "description": "Search registered graph context and return only evidence explicitly selected by Jev.",
     "inputSchema": _schema({"query": S, "max_results": {"type": "integer", "minimum": 1, "maximum": 12}}, ["query"])},
    {"name": "jev_status", "description": "Read the cached Jev health, usage and routing state without exposing credentials.",
     "inputSchema": _schema({}, [])},
    {"name": "model_watch_status", "description": "Read the last official Codex and Claude model discovery, active profiles, and deferred upgrades.",
     "inputSchema": _schema({}, [])},
    {"name": "model_watch_check", "description": "Check official Codex and Claude releases now and safely update eligible model profiles.",
     "inputSchema": _schema({}, [])},
    {"name": "task_explain", "description": "Read the current Hebrew purpose, status and selected model for one task.",
     "inputSchema": _schema({"task_id": S}, ["task_id"])},
    {"name": "deliver_explain", "description": "Read a Deliver's current Hebrew purpose and implementation explanation.",
     "inputSchema": _schema({"deliver_id": S}, ["deliver_id"])},
    {"name": "event_log_list", "description": "Read persisted Task Manager audit events directly from the SQLite event journal.",
     "inputSchema": _schema({"limit": {"type": "integer", "minimum": 1, "maximum": 400},
                              "before_id": {"type": "integer", "minimum": 1},
                              "task_id": S, "provider": S, "event": S, "search": S}, [])},
    {"name": "event_log_get", "description": "Read one persisted Task Manager audit event by its database id.",
     "inputSchema": _schema({"event_id": {"type": "integer", "minimum": 1}}, ["event_id"])},
    {"name": "deterministic_run_record", "description": "Record or update one lightweight deterministic Deliver invocation. It has zero LLM cost and is persisted separately from model attempts.",
     "inputSchema": _schema({"run_id": S, "deliver_id": S, "episode_id": S,
                              "status": {"type": "string", "enum": ["RUNNING", "COMPLETED", "FAILED", "CANCELLED"]},
                              "input_bytes": {"type": "integer", "minimum": 0},
                              "output_bytes": {"type": "integer", "minimum": 0},
                              "detail": {"type": "object"}}, ["deliver_id", "status"])},
    {"name": "listener_activation_update", "description": "Persist the actual runtime state of a Jev-selected listener activation.",
     "inputSchema": _schema({"activation_id": S,
                              "status": {"type": "string", "enum": ["SELECTED", "RUNNING", "COMPLETED", "FAILED", "CANCELLED"]}},
                             ["activation_id", "status"])},
]


class Server:
    def __init__(self):
        self.dashboard = Dashboard(load_config())

    def call(self, name: str, args: dict) -> dict:
        if name == "planner_request":
            uploads = []
            for item in args.get("attachments") or []:
                try:
                    data = base64.b64decode(str(item["content_base64"]), validate=True)
                except (binascii.Error, ValueError) as exc:
                    raise ValueError(f"invalid base64 attachment {item.get('name') or ''}") from exc
                uploads.append(planner_uploads.IncomingUpload(
                    "planner_files", str(item["name"]), str(item.get("media_type") or "application/octet-stream"), data))
            planner_uploads.validate_uploads(uploads)
            tid = mn.create_plan(self.dashboard.db, self.dashboard.cfg, args["prompt"],
                                 args.get("model_key") or None, args.get("mode") or "plan_build",
                                 args.get("mcp_servers") or [])
            stored = planner_uploads.store(self.dashboard.db, self.dashboard.cfg, tid, uploads) if uploads else []
            return {"task_id": tid, "status": "queued", "attachment_count": len(stored),
                    "attachment_gate": "jev" if stored else None}
        if name == "context_planned_task_create":
            spec = {
                "key": args["title"], "title": args["title"], "instructions": args["instructions"],
                "description_he": args.get("description_he") or "",
                "context_request": args["context_request"], "model_key": args["worker_model_key"],
                "task_target": args.get("task_target") or "project",
                "owner": args.get("owner") or "", "fallback": args.get("fallback", True),
                "depends_on": args.get("depends_on") or [], "write_scope": args.get("write_scope") or [],
                "read_only": bool(args.get("read_only")), "context_files": args.get("context_files") or [],
                "reference_files": args.get("reference_files") or [], "mcp_servers": args.get("mcp_servers") or [],
                "tool_names": args.get("tool_names") or [],
                "acceptance_commands": args.get("acceptance_commands") or [],
                "auto_approve": bool(args.get("auto_approve")),
                "allow_web": bool(args.get("allow_web")),
            }
            tid = mn.create_context_plan(
                self.dashboard.db, self.dashboard.cfg, spec, args["context_request"],
                args.get("planner_model_key") or None, self.dashboard._mcp_cached())
            self.dashboard.wake()
            return {"task_id": tid, "status": "context_planning", "worker_contract_locked": True,
                    "gate": "jev", "sources": ["neo4j_graph_rag", "markdown"]}
        if name == "system_repair_task_create":
            spec = {
                "key": args["title"], "title": args["title"], "instructions": args["instructions"],
                "description_he": args.get("description_he") or "",
                "task_target": "task_manager", "model_key": args.get("model_key") or "",
                "fallback": True, "owner": "task_manager_maintenance", "depends_on": [],
                "write_scope": ["tools/build_manager/"], "read_only": False,
                "context_files": [], "reference_files": [], "mcp_servers": [], "tool_names": [],
                "acceptance_commands": args.get("acceptance_commands") or [],
                "auto_approve": bool(args.get("auto_approve")),
                "context_request": str(args.get("context_request") or "").strip(),
            }
            if spec["context_request"]:
                tid = mn.create_context_plan(self.dashboard.db, self.dashboard.cfg, spec, spec["context_request"],
                                             args.get("planner_model_key") or None,
                                             self.dashboard._mcp_cached())
                status = "context_planning"
            else:
                tid = mn.create_tasks(self.dashboard.db, self.dashboard.cfg, [spec], "manual",
                                      self.dashboard._mcp_cached())[0]
                status = "queued"
            self.dashboard.wake()
            return {"task_id": tid, "status": status, "task_target": "task_manager",
                    "activation": "staged_tested_drift_checked_graceful_restart"}
        if name == "battle_request":
            result = battle_request.request_battle(
                self.dashboard.db, self.dashboard.cfg, title=args["title"], battle_key=args.get("battle_key") or "",
                date=args.get("date") or "", date_end=args.get("date_end") or "", bbox=args.get("bbox"),
                place=args.get("place") or "", notes=args.get("notes") or "", dry_run=bool(args.get("dry_run")))
            if result["created"]:
                self.dashboard.wake()
            return result
        if name == "deliver_upsert":
            return {"result": self.dashboard.action({"action": "save_deliver", **args})}
        if name == "listener_upsert":
            form = {"action": "add_listener", **args,
                    "context_selector": json.dumps(args.get("context_selector") or {}, ensure_ascii=False)}
            return {"result": self.dashboard.action(form)}
        if name == "dependency_add":
            return {"result": self.dashboard.action({"action": "add_dependency", **args})}
        if name == "task_dependency_add":
            return {"result": self.dashboard.action({"action": "add_task_dependency", **args})}
        if name == "task_model_set":
            return {"result": self.dashboard.action({"action": "set_provider", **args})}
        if name == "task_expedite":
            return {"result": self.dashboard.action({"action": "expedite", **args})}
        if name == "auto_approval_mode":
            return {"result": self.dashboard.action({"action": "set_auto_approve_all",
                                                       "enabled": "1" if args["enabled"] else "0"})}
        if name == "subtask_create":
            spec = {key: args.get(key) for key in (
                "key", "title", "instructions", "description_he", "owner", "model_key", "fallback", "write_scope", "read_only",
                "context_files", "context_request", "reference_files", "mcp_servers", "tool_names", "acceptance_commands", "auto_approve",
                "allow_web")}
            ids = mn.create_subtasks(self.dashboard.db, self.dashboard.cfg, args["parent_task_id"], [spec],
                                     self.dashboard._mcp_cached(), "mcp")
            self.dashboard.wake()
            return {"task_id": ids[0], "status": "saved_subtask", "deliver_created": False}
        if name == "deliver_template_web_access_set":
            mn.set_template_allow_web(self.dashboard.db, args["deliver_id"], bool(args["allow_web"]))
            return {"deliver_id": args["deliver_id"], "allow_web": bool(args["allow_web"])}
        if name == "subtask_patterns":
            status = args.get("status") or "all"
            where, params = ("", ()) if status == "all" else (" WHERE promotion_status=?", (status,))
            rows = []
            for row in self.dashboard.db.q("SELECT * FROM subtask_patterns" + where +
                                           " ORDER BY last_seen_at DESC", params):
                item = dict(row)
                item["spec"] = json.loads(item.pop("spec_json"))
                item["occurrences"] = [dict(o) for o in self.dashboard.db.q(
                    "SELECT parent_task_id,child_task_id,source,created_at FROM subtask_occurrences "
                    "WHERE pattern_hash=? ORDER BY created_at DESC", (item["pattern_hash"],))]
                rows.append(item)
            return {"patterns": rows, "automatic_promotion": False}
        if name == "subtask_promote":
            did = self.dashboard._safe_graph_id(args["deliver_id"], "Deliver ID")
            result = mn.promote_subtask_pattern(
                self.dashboard.db, self.dashboard.cfg, args["pattern_hash"], did,
                args.get("owner") or "", args.get("domain") or "", args.get("description") or "")
            return {"deliver_id": result, "status": "promoted"}
        if name == "deliver_model_set":
            return {"result": self.dashboard.action({"action": "set_deliver_model", **args})}
        if name == "deliver_graph_access_set":
            form = {"action": "save_deliver_graph_access", **args,
                    "max_chunks": str(args.get("max_chunks", 6)),
                    "max_chars": str(args.get("max_chars", 6000))}
            return {"result": self.dashboard.action(form)}
        if name == "rag_graph_query":
            return self.dashboard.graph_rag.selected_query(
                self.dashboard.jev, args["deliver_id"], args["query"])
        if name == "graph_query_console":
            outcome = self.dashboard.run_graph_console_query(
                args["mode"], args["query"], args.get("model_key") or "local",
                args.get("parameters") or {}, int(args.get("max_rows", 100)))
            row = dict(self.dashboard.db.one("SELECT * FROM graph_console_queries WHERE id=?", (outcome["id"],)))
            raw = row.pop("result_json", None)
            row["result"] = json.loads(raw) if raw else None
            return row
        if name == "run_unstick":
            from . import unstick as us
            return us.unstick(self.dashboard.cfg, self.dashboard.db, "mcp")
        if name == "system_onboard":
            from . import onboarding as ob
            return ob.onboard(self.dashboard.cfg, self.dashboard.db, Path(args["manifest"]),
                              graph=args.get("graph"), dry_run=bool(args.get("dry_run")),
                              graph_service=self.dashboard.graph_rag)
        if name == "system_onboarding_status":
            from . import onboarding as ob
            return {"systems": ob.systems(self.dashboard.db),
                    "files": [dict(r) for r in self.dashboard.db.q(
                        "SELECT system_id,deliver_id,context_path,graph_status,updated_at FROM system_onboarding "
                        "ORDER BY system_id,deliver_id")]}
        if name == "rag_graph_status":
            return {"health": self.dashboard.graph_rag.health(),
                    "planner_access": self.dashboard.graph_rag.access("planner", planner=True),
                    "deliver_access": [dict(row) for row in self.dashboard.db.q(
                        "SELECT c.deliver_id,COALESCE(a.access_mode,'none') access_mode,"
                        "COALESCE(a.scope_text,'') scope_text,COALESCE(a.max_chunks,6) max_chunks,"
                        "COALESCE(a.max_chars,6000) max_chars FROM deliver_catalog c "
                        "LEFT JOIN deliver_graph_access a ON a.deliver_id=c.deliver_id "
                        "WHERE c.enabled=1 ORDER BY c.deliver_id")]}
        if name == "rag_graph_configure":
            return {"result": self.dashboard.action({"action": "save_graph_rag_config",
                                                       "graph_rag_url": args["url"]})}
        if name == "task_context_access":
            action = "bind_task_context" if args["active"] else "toggle_task_context"
            form = {"action": action, "task_id": args["task_id"], "source_key": args["source_key"]}
            if not args["active"]:
                form["enabled"] = "0"
            return {"result": self.dashboard.action(form)}
        if name == "scoped_change_request":
            form = {"action": "scoped_plan", "scope_kind": args["scope_kind"],
                    "scope_id": args["scope_id"], "prompt": args["prompt"],
                    "prompt_mode": args.get("mode") or "plan_build",
                    "model_key": args.get("model_key") or "",
                    "mcp_servers": ",".join(args.get("mcp_servers") or [])}
            return {"result": self.dashboard.action(form)}
        if name == "context_candidate_add":
            return {"result": self.dashboard.action({"action": "add_context", **args})}
        if name == "economics_update":
            form = {"action": "save_economics", **{k: str(v) for k, v in args.items()}}
            return {"result": self.dashboard.action(form)}
        if name == "jev_status":
            return self.dashboard.jev.status()
        if name == "model_watch_status":
            return {"check": ModelWatch(self.dashboard.cfg, self.dashboard.db).status(),
                    "models": {key: {"provider": value["provider"], "model": value["model"]}
                               for key, value in self.dashboard.cfg.data["models"].items()}}
        if name == "model_watch_check":
            return ModelWatch(self.dashboard.cfg, self.dashboard.db).check(force=True)
        if name == "task_explain":
            task = self.dashboard.db.task(args["task_id"])
            if not task:
                raise ValueError("task not found")
            key = task["preferred_model_key"] or task["last_model_key"]
            return {"task_id": task["task_id"], "description_he": task_he(self.dashboard.cfg, task),
                    "state": task["state"], "model_key": key,
                    "model": self.dashboard.cfg.data["models"].get(key, {}).get("model") if key else None}
        if name == "deliver_explain":
            deliver = next((item for item in self.dashboard.delivers_json()["delivers"]
                            if item["deliver_id"] == args["deliver_id"]), None)
            if not deliver:
                raise ValueError("Deliver not found")
            return {"deliver_id": deliver["deliver_id"], "description_he": deliver["description_he"],
                    "implementation_he": deliver["implementation_he"],
                    "execution_kind": deliver["execution_kind"], "availability": deliver["availability"]}
        if name == "event_log_list":
            query = {key: str(value) for key, value in args.items() if value is not None}
            return self.dashboard.events_json(query)
        if name == "event_log_get":
            row = self.dashboard.db.one("SELECT * FROM event_log WHERE id=?", (int(args["event_id"]),))
            if not row:
                raise ValueError("event not found")
            item = dict(row)
            raw = item.pop("detail", None)
            try:
                item["detail"] = json.loads(raw) if raw else None
            except (TypeError, json.JSONDecodeError):
                item["detail"] = raw
            return {"source": "sqlite:event_log", "event": item}
        if name == "deterministic_run_record":
            deliver_id = args["deliver_id"]
            deliver = self.dashboard.db.one(
                "SELECT execution_kind FROM deliver_catalog WHERE deliver_id=? AND enabled=1", (deliver_id,))
            if not deliver or deliver["execution_kind"] != "deterministic":
                raise ValueError("enabled deterministic Deliver not found")
            run_id = (args.get("run_id") or "deterministic:" + str(uuid.uuid4())).strip()
            status = args["status"]
            existing = self.dashboard.db.one(
                "SELECT deliver_id,started_at FROM deterministic_deliver_runs WHERE run_id=?", (run_id,))
            if existing and existing["deliver_id"] != deliver_id:
                raise ValueError("run_id belongs to another Deliver")
            now = iso(utcnow())
            completed_at = None if status == "RUNNING" else now
            self.dashboard.db.x(
                "INSERT INTO deterministic_deliver_runs(run_id,deliver_id,episode_id,status,input_bytes,output_bytes,cost_usd,detail_json,started_at,completed_at) "
                "VALUES(?,?,?,?,?,?,0,?,?,?) ON CONFLICT(run_id) DO UPDATE SET episode_id=excluded.episode_id,"
                "status=excluded.status,input_bytes=excluded.input_bytes,output_bytes=excluded.output_bytes,"
                "detail_json=excluded.detail_json,completed_at=excluded.completed_at",
                (run_id, deliver_id, args.get("episode_id") or None, status,
                 int(args.get("input_bytes") or 0), int(args.get("output_bytes") or 0),
                 json.dumps(args.get("detail") or {}, ensure_ascii=False, default=str),
                 existing["started_at"] if existing else now, completed_at))
            self.dashboard.db.event("DETERMINISTIC_DELIVER_RUN_RECORDED", task_id=deliver_id,
                                    run_id=run_id, status=status, cost_usd=0)
            return {"run_id": run_id, "deliver_id": deliver_id, "status": status,
                    "cost_usd": 0, "persisted": True}
        if name == "listener_activation_update":
            activation_id, status = args["activation_id"], args["status"]
            activation = self.dashboard.db.one(
                "SELECT * FROM listener_activations WHERE activation_id=?", (activation_id,))
            if not activation:
                raise ValueError("listener activation not found")
            transitions = {"SELECTED": {"SELECTED", "RUNNING", "CANCELLED", "FAILED"},
                           "RUNNING": {"RUNNING", "COMPLETED", "FAILED", "CANCELLED"},
                           "COMPLETED": {"COMPLETED"}, "FAILED": {"FAILED"}, "CANCELLED": {"CANCELLED"}}
            if status not in transitions.get(activation["status"], set()):
                raise ValueError(f"invalid activation transition {activation['status']} -> {status}")
            now = iso(utcnow())
            started_at = activation["started_at"] or (now if status == "RUNNING" else None)
            completed_at = activation["completed_at"] or (now if status in {"COMPLETED", "FAILED", "CANCELLED"} else None)
            self.dashboard.db.x(
                "UPDATE listener_activations SET status=?,started_at=?,completed_at=? WHERE activation_id=?",
                (status, started_at, completed_at, activation_id))
            self.dashboard.db.event("LISTENER_ACTIVATION_UPDATED", task_id=activation["target_deliver_id"],
                                    provider="jev", activation_id=activation_id,
                                    listener_id=activation["listener_id"], previous=activation["status"], status=status)
            return {"activation_id": activation_id, "previous": activation["status"],
                    "status": status, "persisted": True}
        if name == "jev_selected_graph_query":
            limit = min(int(args.get("max_results", 6)), 12)
            candidates = mn.planner_graph_candidates(self.dashboard.db, args["query"], max(2, limit // 2))
            candidates += self.dashboard.graph_rag.retrieve_candidates("mcp:planner", args["query"], planner=True)
            candidates = candidates[:limit]
            selected = self.dashboard.jev.select_context_bundles(
                "MCP/graph-query", candidates,
                "Select only graph evidence needed to answer this MCP query: " + args["query"][:600])
            by_id = {item["id"]: item for item in candidates}
            return {"gate": "jev", "query": args["query"], "candidate_count": len(candidates),
                    "selected": [{k: v for k, v in by_id[item_id].items() if k != "id"}
                                 for item_id in selected if item_id in by_id]}
        raise ValueError("unknown tool")

    def handle(self, request: dict) -> dict | None:
        method = request.get("method")
        if method == "initialize":
            return {"protocolVersion": "2025-06-18", "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": "wwii-task-manager", "version": "0.1.0"}}
        if method == "notifications/initialized":
            return None
        if method == "ping":
            return {}
        if method == "tools/list":
            return {"tools": TOOLS}
        if method == "tools/call":
            params = request.get("params") or {}
            result = self.call(params.get("name", ""), params.get("arguments") or {})
            return {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False, default=str)}],
                    "isError": False}
        raise ValueError("method not found")


def main() -> int:
    server = Server()
    for line in sys.stdin:
        try:
            request = json.loads(line)
            result = server.handle(request)
            if result is not None and "id" in request:
                print(json.dumps({"jsonrpc": "2.0", "id": request["id"], "result": result}, ensure_ascii=False), flush=True)
        except Exception as exc:
            req_id = locals().get("request", {}).get("id")
            if req_id is not None:
                print(json.dumps({"jsonrpc": "2.0", "id": req_id,
                                  "error": {"code": -32603, "message": str(exc)[:500]}}, ensure_ascii=False), flush=True)
    server.dashboard.db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
