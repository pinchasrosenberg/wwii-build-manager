"""Conversation about the manager's current state, from the dashboard.

Runs immediately (outside the task queue), read-only, on a model the user picks or on the best-fit model for
the CHAT profile. The context is a snapshot the manager builds from SQLite (daemon, tasks, why READY tasks are
not starting, approvals, workers, quotas, recent events) plus the earlier turns of the same conversation. Like
every LLM context it passes through Jev first (fail closed).
"""
from __future__ import annotations

import json
import time

from .models import AttemptStatus, RunSpec, TaskRequest, iso, utcnow
from .quota import QuotaManager
from .routing import RUN, select_route

CHAT_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {"answer": {"type": "string"},
                   "suggested_actions": {"type": "array", "items": {"type": "string"}}},
    "required": ["answer", "suggested_actions"],
}
MAX_TURNS = 12
MAX_MESSAGE = 8000


class ChatError(Exception):
    pass


def _blockers(db) -> dict[str, list[str]]:
    """Why each READY task is not starting (the scheduler's one-writer rule), in plain words."""
    from .scheduler import scopes_overlap
    held = [(r["task_id"], r["owner"], json.loads(r["write_scope"] or "[]"), True)
            for r in db.q("SELECT w.task_id, t.owner, t.write_scope FROM workers w JOIN tasks t USING(task_id)")]
    held += [(r["task_id"], r["owner"], json.loads(r["write_scope"] or "[]"), False)
             for r in db.q("SELECT task_id, owner, write_scope FROM tasks WHERE state IN "
                           "('CODE_READY','REVIEWING','WAITING_REPAIR')")]
    out = {}
    for t in db.q("SELECT * FROM tasks WHERE state='READY'"):
        scope = json.loads(t["write_scope"] or "[]")
        exempt = t["parent_task_id"] if t["kind"] == "repair" else None
        why = []
        for tid, owner, sc, active in held:
            if tid == exempt:
                continue
            if active and owner == t["owner"]:
                why.append(f"owner {owner} busy with running {tid}")
            elif scopes_overlap(scope, sc):
                why.append(f"write scope overlaps {tid}")
        out[t["task_id"]] = why
    return out


def snapshot(db, cfg) -> str:
    from . import control
    L = [f"NOW: {iso(utcnow())}"]
    pid = control.daemon_pid(cfg)
    L.append(f"DAEMON: {'running pid ' + str(pid) if pid else 'NOT RUNNING'} | paused={bool(db.get_flag('paused'))} "
             f"| emergency_stop={bool(db.get_flag('emergency_stop'))} | max_parallel="
             f"{cfg.section('scheduler').get('max_parallel', 3)}")
    counts = {r["state"]: r["n"] for r in db.q("SELECT state, COUNT(*) n FROM tasks GROUP BY state")}
    L.append("TASK COUNTS: " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    L.append("\nRUNNING WORKERS:")
    for w in db.q("SELECT * FROM workers"):
        L.append(f"- {w['task_id']} {w['provider']}/{w['model']} since {w['started_at']}")
    blockers = _blockers(db)
    L.append("\nOPEN TASKS (not passed/cancelled):")
    for t in db.q("SELECT task_id, state, state_reason, owner, model_profile, preferred_model_key, last_model_key, "
                  "failed_attempts FROM tasks WHERE state NOT IN ('PASSED','CANCELLED','SKIPPED') "
                  "ORDER BY state, wave, task_id LIMIT 80"):
        line = (f"- {t['task_id']} [{t['state']}] owner={t['owner']} profile={t['model_profile']} "
                f"model={t['preferred_model_key'] or 'auto'} last={t['last_model_key'] or '-'} "
                f"fails={t['failed_attempts'] or 0} :: {(t['state_reason'] or '')[:220]}")
        if t["task_id"] in blockers:
            line += " :: not starting because: " + ("; ".join(blockers[t["task_id"]]) or "free (capacity)")
        L.append(line)
    L.append("\nPENDING APPROVALS:")
    for a in db.q("SELECT * FROM approvals WHERE status='pending' ORDER BY id"):
        L.append(f"- #{a['id']} {a['task_id']} {a['kind']} {a['subject'] or ''}: {(a['reason'] or '')[:200]}")
    L.append("\nQUOTA (one account per provider):")
    for q in QuotaManager(db, cfg.section("quota")).accounts():
        L.append(f"- {q['provider']}: {q['status']} 5h={q['session_used_percent']} (reset {q['session_reset_at']}) "
                 f"weekly={q['weekly_used_percent']} (reset {q['weekly_reset_at']}) data_at={q['data_at']}"
                 + "".join(f" [{n}]" for n in q["notes"]))
    L.append("\nMODELS: " + ", ".join(f"{k}={m.provider}/{m.model}" for k, m in cfg.models().items()))
    L.append("\nLATEST EVENTS (newest first):")
    for e in db.q("SELECT at, event, task_id, provider, detail FROM event_log ORDER BY id DESC LIMIT 30"):
        L.append(f"- {e['at']} {e['event']} {e['task_id'] or ''} {e['provider'] or ''} {(e['detail'] or '')[:200]}")
    return "\n".join(L)


def history(db, conversation_id: int) -> list[dict]:
    return [dict(r) for r in db.q("SELECT * FROM state_chat_messages WHERE conversation_id=? ORDER BY id",
                                  (conversation_id,))]


def latest_conversation(db) -> int | None:
    r = db.one("SELECT MAX(conversation_id) c FROM state_chat_messages")
    return r["c"] if r and r["c"] is not None else None


def pick_model(cfg, db, model_key: str | None) -> str:
    if model_key:
        if model_key not in cfg.data["models"]:
            raise ChatError("המודל שנבחר אינו קיים")
        return model_key
    req = TaskRequest(task_id="CHAT/route", packet="CHAT", owner="state_chat", domain="manager",
                      mode="read_only_state_chat", model_profile="CHAT", lego_ids=[], write_scope=[], depends_on=[],
                      context_entry=None, brief_path=None, note="", extra={}, kind="plan")
    route = select_route(cfg, QuotaManager(db, cfg.section("quota")), req, approvals={})
    if route.kind != RUN or not route.model_key:
        raise ChatError(f"אין כרגע מודל זמין לשיחה: {route.reason}")
    return route.model_key


def ask(dash, conversation_id: int | None, message: str, model_key: str | None, run_now, progress=None) -> dict:
    """One user turn -> one model answer. ``run_now`` runs a coroutine to completion (dashboard helper).

    ``progress(line)`` (optional) hears the stages; the user's message is committed first, and the live detector is
    poked so every open client shows it while the model is still thinking.
    """
    from .supervisor import Supervisor
    db, cfg = dash.db, dash.cfg
    say = progress or (lambda line: None)
    message = (message or "").strip()[:MAX_MESSAGE]
    if not message:
        raise ChatError("ההודעה ריקה")
    key = pick_model(cfg, db, model_key or None)
    model = cfg.model(key)
    provider = dash.providers.get(model.provider)
    if provider is None:
        raise ChatError(f"הספק {model.provider} אינו זמין")
    say(f"נבחר המודל {key} ({model.provider})")
    if conversation_id is None:
        conversation_id = (latest_conversation(db) or 0) + 1
    now = iso(utcnow())
    mid = db.x("INSERT INTO state_chat_messages(conversation_id, role, content, model_key, created_at) "
               "VALUES(?,?,?,?,?)", (conversation_id, "user", message, model_key or None, now))
    live = getattr(dash, "live", None)
    if live is not None:
        live.poke()                          # the chat topic shows the question to every open client right away
    if cfg.section("jev").get("require_for_all_llm_context", True):
        from .jev import JevError
        try:
            selected = dash.jev.select_context_bundles(f"CHAT/{conversation_id}/{mid}", [{
                "id": "context:manager_state", "execution_kind": "context_bundle", "required_for_execution": True,
                "description": "read-only snapshot of the task manager state (tasks, locks, approvals, quotas, "
                               "events) and the previous turns of this dashboard conversation"}],
                f"answer the user's question about the task manager state: {message[:300]}")
        except JevError as exc:
            raise ChatError(f"Jev אינו זמין ולכן לא נשלח קונטקסט למודל: {exc}") from exc
        if "context:manager_state" not in selected:
            db.event("JEV_CONTEXT_GATE_BLOCKED", task_id=f"CHAT/{conversation_id}", provider="jev",
                     reason="state chat context not selected")
            raise ChatError("Jev לא אישר את קונטקסט המצב לשיחה (בדוק את מצב Jev בעמוד Delivers)")
    say("בונה את תמונת המצב לשיחה")
    turns = history(db, conversation_id)[-MAX_TURNS:]
    convo = "\n\n".join(f"{'USER' if t['role'] == 'user' else 'ASSISTANT'}: {t['content']}" for t in turns)
    prompt = "\n".join([
        f"TASK_ID: CHAT/{conversation_id}/{mid}",
        "You are the assistant inside the user's local WWII Build Manager dashboard. Discuss the CURRENT STATE",
        "below with the user: explain what is running, what is stuck and why, and what they could do next.",
        "Read-only: do not edit files, do not run commands and do not create tasks. Base every claim on the",
        "snapshot; say when something is not in it. Answer in the user's language (usually Hebrew), concisely.",
        "Return one JSON object: {answer, suggested_actions[]} (actions are short dashboard steps for the user).",
        "", "## CURRENT STATE", snapshot(db, cfg), "", "## CONVERSATION", convo,
    ]) + "\n"
    run_dir = cfg.state_dir / "state_chat" / str(conversation_id) / str(mid)
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "prompt.md").write_text(prompt)
    (run_dir / "result.schema.json").write_text(json.dumps(CHAT_SCHEMA, indent=1))
    task = TaskRequest(task_id=f"CHAT/{conversation_id}/{mid}", packet="CHAT", owner="state_chat", domain="manager",
                       mode="read_only_state_chat", model_profile="CHAT", lego_ids=[], write_scope=[], depends_on=[],
                       context_entry=None, brief_path=None, note=message[:500], extra={}, kind="plan")
    spec = RunSpec(task=task, attempt_id=mid, attempt_no=1, model=model, worktree=str(cfg.repo),
                   prompt_path=str(run_dir / "prompt.md"), run_dir=str(run_dir),
                   result_schema_path=str(run_dir / "result.schema.json"), kind="plan", schema=CHAT_SCHEMA)
    started = time.monotonic()
    say(f"ממתין לתשובה מ־{model.provider}/{model.model}")
    run = run_now(provider.run_task(spec, Supervisor(), timeout=300.0))
    for sig in getattr(run, "quota_signals", None) or []:
        QuotaManager(db, cfg.section("quota")).record_signal(sig)
    if run.status != AttemptStatus.SUCCEEDED:
        raise ChatError(f"{model.provider}/{model.model}: {(run.error or run.failure_class or run.status.value)[:400]}")
    payload = run.structured if isinstance(run.structured, dict) else None
    if payload is None and run.final_text:
        from .result_parser import _candidates
        for cand in _candidates(run.final_text):
            try:
                parsed = json.loads(cand)
            except ValueError:
                continue
            if isinstance(parsed, dict):
                payload = parsed
                break
    answer = str((payload or {}).get("answer") or run.final_text or "").strip()
    actions = [str(a) for a in (payload or {}).get("suggested_actions") or []][:8]
    if actions:
        answer += "\n\nצעדים מוצעים:\n" + "\n".join(f"• {a}" for a in actions)
    db.x("INSERT INTO state_chat_messages(conversation_id, role, content, model_key, provider, model, created_at, "
         "input_tokens, output_tokens, reported_cost_usd) VALUES(?,?,?,?,?,?,?,?,?,?)",
         (conversation_id, "assistant", answer, key, model.provider, model.model, iso(utcnow()),
          run.input_tokens, run.output_tokens, run.reported_cost_usd))
    if live is not None:
        live.poke()
    say("התשובה נשמרה בשיחה")
    db.event("STATE_CHAT", task_id=f"CHAT/{conversation_id}", provider=model.provider, model_key=key,
             model_selection="manual" if model_key else "auto", elapsed_ms=int((time.monotonic() - started) * 1000),
             input_tokens=run.input_tokens, output_tokens=run.output_tokens)
    return {"conversation_id": conversation_id, "model_key": key}
