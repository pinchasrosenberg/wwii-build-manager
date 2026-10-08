#!/usr/bin/env python3
"""FakeCodexCLI / FakeClaudeCLI: stand-ins that speak the same wire formats as the
installed CLIs (codex-cli 0.148 `exec --json` JSONL + app-server JSON-RPC; Claude Code
2.1.280 `-p --output-format stream-json`), so the manager can be tested for free.

Usage (as a provider `command`):
    [python, fake_cli.py, "codex"|"claude", "--scenario", "<scenario.json>", <real CLI args...>]

Scenario JSON:
{
  "log": "<calls.jsonl>",                 # every invocation + app-server method is logged here
  "state": "<state.json>",                # per-task invocation counters
  "codex":  {"auth": "chatgpt"|"api"|"none",
             "quota": {"used": 10, "reset_in_s": 3600, "window_mins": 10080, "reached": false},
             "tasks": {"B07/inventory": ["rate_limit:600", "success"]}, "default": "success"},
  "claude": {"auth": "claude.ai"|"api_key"|"none", "tasks": {...}, "default": "success"}
}
Behaviors: success | malformed | rate_limit[:reset_s] | weekly_limit[:reset_s] | model_unavailable |
           auth_error | crash | long_running[:seconds] | overage | test_fail | no_change |
           out_of_scope | out_of_scope_py | edit_shared | pycache | trailing_blank | rate_limit_iso[:reset_s]
Repair tasks (TASK_ID REPAIR/...): success|fix = repair the failure, noop = no change, arch = needs architecture
Environment variables are NOT used: the manager scrubs worker environments.
"""
import datetime as dt
import fcntl
import json
import os
import re
import signal
import sys
import time


def load(path):
    with open(path) as f:
        return json.load(f)


def log(scn, entry):
    p = scn.get("log")
    if not p:
        return
    entry["t"] = time.time()
    entry["pid"] = os.getpid()
    with open(p, "a") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        f.write(json.dumps(entry) + "\n")


def next_behavior(scn, flavor, task_id):
    cfg = scn.get(flavor, {})
    seq = cfg.get("tasks", {}).get(task_id)
    if not seq:
        return cfg.get("default", "success")
    sp = scn.get("state")
    n = 0
    if sp:
        with open(sp, "a+") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            f.seek(0)
            txt = f.read()
            st = json.loads(txt) if txt.strip() else {}
            key = f"{flavor}:{task_id}"
            n = st.get(key, 0)
            st[key] = n + 1
            f.seek(0)
            f.truncate()
            f.write(json.dumps(st))
    return seq[min(n, len(seq) - 1)]


def parse_prompt(prompt):
    tid = re.search(r"^TASK_ID:\s*(\S+)", prompt, re.M)
    scope, in_scope = [], False
    for ln in prompt.splitlines():
        if ln.startswith("## WRITE SCOPE"):
            in_scope = True
            continue
        if in_scope:
            if ln.startswith("## "):
                break
            m = re.match(r"- `([^`]+)`", ln)
            if m:
                scope.append(m.group(1))
    lego_line = re.search(r"^Lego ids:\s*(.+)$", prompt, re.M)
    lego_ids = re.findall(r"`([^`]+)`", lego_line.group(1)) if lego_line else []
    return (tid.group(1) if tid else "unknown"), scope, "READ-ONLY task" in prompt, lego_ids


def handoff(task_id, changed, flavor, report=None, status="completed", lego_ids=None):
    return {
        "task_id": task_id, "status": status, "summary": f"fake {flavor} did {task_id}",
        "changed_files": changed,
        "artifacts": [{"path": p, "kind": "report", "description": "fake output"} for p in changed[:1]],
        "tests_run": [], "tests_passed": [], "tests_failed": [], "context_used": ["INVARIANTS.md"],
        "contracts_used": [], "evidence_used": [], "assumptions": ["synthetic fake run"],
        "uncertainties": [], "untested_limits": [], "capability_gaps": ["fake gap: no real engine"],
        "cross_domain_requests": [], "next_dependency": [], "review_required": False,
        "report_markdown": report,
        "listener_manifest": [{"lego_id": lego_id, "no_listener_reason": "synthetic fixture needs no listener",
                               "proposed_listeners": []} for lego_id in (lego_ids or [])],
    }


def repair_work(behavior, prompt, scope, cwd, arg=""):
    """Repair behaviors: success/fix = repair the recorded failure; noop = change nothing;
    slow_fix:N = sleep N s (SIGINT-aware) then fix; escape = fix but also write outside the scope."""
    changed = []
    if behavior == "slow_fix":
        interrupted = []
        signal.signal(signal.SIGINT, lambda *_: interrupted.append(1))
        end = time.time() + float(arg or 30)
        while time.time() < end and not interrupted:
            time.sleep(0.1)
        if interrupted:
            sys.exit(130)
        behavior = "fix"
    if behavior == "escape":
        f = os.path.join(cwd, "outside_scope/fake.txt")
        os.makedirs(os.path.dirname(f), exist_ok=True)
        open(f, "w").write("repair escaped its scope\n")
        changed.append("outside_scope/fake.txt")
        behavior = "fix"
    if behavior not in ("success", "fix"):
        return changed
    for p in re.findall(r"OUT-OF-SCOPE PATH: `([^`]+)`", prompt):
        f = os.path.join(cwd, p)
        if os.path.exists(f):
            os.remove(f)
            changed.append(p)
    for sc in scope:
        root = os.path.join(cwd, sc)
        for dp, _, files in os.walk(root) if os.path.isdir(root) else []:
            if "__pycache__" in dp:
                continue
            for fn in files:
                f = os.path.join(dp, fn)
                try:
                    txt = open(f).read()
                except (UnicodeDecodeError, OSError):
                    continue
                new = txt.replace("BROKEN", "OK").rstrip("\n") + "\n"
                if new != txt:
                    open(f, "w").write(new)
                    changed.append(os.path.relpath(f, cwd))
    return changed


def repair_result(task_id, prompt, changed, behavior):
    parent = task_id.split("/", 1)[1].rsplit("/", 1)[0]
    return {"repair_task_id": task_id, "parent_task_id": parent, "failure_addressed": "fake repair",
            "summary": f"fake repair ({behavior})", "changed_files": changed, "tests_run": ["fake"],
            "tests_passed": ["fake"] if changed else [], "remaining_failures": [] if changed else ["unchanged"],
            "cross_domain_requests": [], "requires_architecture_change": behavior == "arch"}


def plan_result(prompt, behavior):
    """Fake planner: each line '- key: scope=a/,b/; deps=k1,k2; model=sol; ro; cmd=...' under USER REQUEST."""
    if behavior == "malformed":
        return "here are some ideas, not JSON"
    req = prompt.split("## USER REQUEST", 1)[1].split("\n## ", 1)[0] if "## USER REQUEST" in prompt else ""
    tasks = []
    for ln in req.splitlines():
        m = re.match(r"\s*-\s*([\w-]+):\s*(.*)", ln)
        if not m:
            continue
        opts = dict(kv.split("=", 1) if "=" in kv else (kv.strip(), "1") for kv in m.group(2).split(";") if kv.strip())
        opts = {k.strip(): v.strip() for k, v in opts.items()}
        tasks.append({"key": m.group(1), "title": f"do {m.group(1)}", "instructions": f"implement {m.group(1)}",
                      "task_target": opts.get("target", "project"),
                      "owner": opts.get("owner", ""), "model_key": opts.get("model", "sol"), "fallback": True,
                      "depends_on": [d for d in opts.get("deps", "").split(",") if d],
                      "write_scope": [s for s in opts.get("scope", "").split(",") if s],
                      "read_only": "ro" in opts, "context_files": [c for c in opts.get("ctx", "").split(",") if c],
                      "reference_files": [], "mcp_servers": [x for x in opts.get("mcp", "").split(",") if x],
                      "tool_names": [],
                      "acceptance_commands": [opts["cmd"]] if opts.get("cmd") else []})
    return json.dumps({"summary": f"{len(tasks)} tasks", "questions": [], "tasks": tasks})


def do_work(behavior, task_id, scope, read_only, flavor, cwd):
    changed = []
    if read_only:
        return changed, f"# Fake report for {task_id}\n\nsynthetic inventory by {flavor}\n"
    if behavior == "no_change" or not scope:
        return changed, None
    def write(rel, content):
        path = os.path.join(cwd, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(content)
        changed.append(rel)
    base_dir = scope[0] if scope[0].endswith("/") else os.path.dirname(scope[0]) + "/"
    if behavior == "pycache":
        write(base_dir + f"fake_{flavor}.txt", f"OK {task_id}\n")
        write(base_dir + "__pycache__/mod.cpython-314.pyc", "bytecode")
        write("game/__pycache__/contracts.cpython-314.pyc", "bytecode")
        write(".pytest_cache/v/cache/nodeids", "[]")
        write(base_dir + ".DS_Store", "x")
        return changed, None
    if behavior == "visual":
        import base64
        png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==")
        path = os.path.join(cwd, base_dir + "preview.png")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        open(path, "wb").write(png)
        changed.append(base_dir + "preview.png")
        write(base_dir + "report.html", "<h1>fake report</h1><script>fetch('/')</script>\n")
        write(base_dir + "tank.py", "ARMOR_MM = 80\n")
        return changed, None
    if behavior == "trailing_blank":
        write(base_dir + f"fake_{flavor}.txt", f"OK {task_id}\n\n")
        return changed, None
    if behavior == "edit_shared":
        write(base_dir + f"fake_{flavor}.txt", f"OK {task_id}\n")
        write("game/contracts.py", "# edited by a worker that does not own it\n")
        return changed, None
    if behavior == "out_of_scope_py":
        write(base_dir + f"fake_{flavor}.txt", f"OK {task_id}\n")
        write("outside_scope/mod.py", "X = 1\n")
        return changed, None
    if behavior == "out_of_scope":
        path = os.path.join(cwd, "outside_scope/fake.txt")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write("OK but in someone else's module\n")
        return ["outside_scope/fake.txt"], None
    target = scope[0]
    rel = (target + f"fake_{flavor}.txt") if target.endswith("/") else target
    path = os.path.join(cwd, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(("BROKEN" if behavior == "test_fail" else "OK") + f" {task_id} by {flavor}\n")
    changed.append(rel)
    return changed, None


def reset_phrase(reset_s):
    t = dt.datetime.now() + dt.timedelta(seconds=reset_s)
    return t.strftime("%I:%M %p").lstrip("0")


# ----------------------------------------------------------------------------- codex
CODEX_EXEC_HELP = """Run Codex non-interactively
  -m, --model <MODEL>  -s, --sandbox <SANDBOX_MODE>  -C, --cd <DIR>  --ephemeral  --ignore-user-config
  --output-schema <FILE>  --json  -o, --output-last-message <FILE>  --skip-git-repo-check
  --search  Enable live web search
"""


def codex(scn, args):
    c = scn.get("codex", {})
    if args[:1] == ["--version"]:
        print("codex-cli 0.148.0 (fake)")
        return 0
    if args[:2] == ["exec", "--help"]:
        print(CODEX_EXEC_HELP)
        return 0
    if args[:2] == ["login", "status"]:
        a = c.get("auth", "chatgpt")
        print({"chatgpt": "Logged in using ChatGPT", "api": "Logged in using an API key - sk-***"}.get(a, "Not logged in"))
        return 0 if a != "none" else 1
    if args[:3] == ["mcp", "list", "--json"]:
        print(json.dumps([{"name": n, "enabled": True, "transport": {"type": "stdio", "command": "/bin/echo",
                                                                     "env": {"ALLOW_WRITES": "1"} if n == "writer" else None}}
                          for n in c.get("mcp", [])]))
        return 0
    if args[:2] == ["debug", "models"]:
        print(json.dumps({"models": [{"slug": "gpt-5.6-sol", "visibility": "list"},
                                     {"slug": "gpt-5.6-luna", "visibility": "list"}]}))
        return 0
    if args[:1] == ["app-server"]:
        return codex_app_server(scn)
    if args[:1] == ["exec"]:
        return codex_exec(scn, args[1:])
    print(f"fake codex: unsupported args {args}", file=sys.stderr)
    return 2


def codex_app_server(scn):
    q = scn.get("codex", {}).get("quota", {"used": 10, "reset_in_s": 3600, "window_mins": 10080})
    for line in sys.stdin:
        try:
            m = json.loads(line)
        except ValueError:
            continue
        log(scn, {"flavor": "codex", "app_server_method": m.get("method")})
        mid = m.get("id")
        if m.get("method") == "initialize":
            out = {"id": mid, "result": {"userAgent": "fake"}}
        elif m.get("method") == "account/rateLimits/read":
            snap = {"limitId": "codex", "primary": {"usedPercent": q.get("used", 10),
                                                    "windowDurationMins": q.get("window_mins", 10080),
                                                    "resetsAt": int(time.time() + q.get("reset_in_s", 3600))},
                    "secondary": None, "planType": "plus",
                    "rateLimitReachedType": "rate_limit_reached" if q.get("reached") else None}
            out = {"id": mid, "result": {"rateLimits": snap, "rateLimitsByLimitId": {"codex": snap},
                                         "rateLimitResetCredits": {"availableCount": 2}}}
        elif mid is None:
            continue
        else:
            out = {"id": mid, "error": {"code": -32601, "message": "method not allowed in fake"}}
        sys.stdout.write(json.dumps(out) + "\n")
        sys.stdout.flush()
    return 0


def emit(o):
    sys.stdout.write(json.dumps(o) + "\n")
    sys.stdout.flush()


def codex_exec(scn, args):
    model = args[args.index("-m") + 1] if "-m" in args else None
    cwd = args[args.index("-C") + 1] if "-C" in args else os.getcwd()
    last = args[args.index("-o") + 1] if "-o" in args else None
    prompt = sys.stdin.read()
    tid, scope, ro, lego_ids = parse_prompt(prompt)
    beh = next_behavior(scn, "codex", tid)
    log(scn, {"flavor": "codex", "task_id": tid, "behavior": beh, "model": model, "args": args,
              "prompt_bytes": len(prompt), "env_keys": sorted(os.environ)})
    name, _, arg = beh.partition(":")
    emit({"type": "thread.started", "thread_id": f"fake-{os.getpid()}"})
    emit({"type": "turn.started"})
    if name in ("rate_limit", "weekly_limit", "rate_limit_iso"):
        reset = int(arg or 600)
        when = (dt.datetime.now().astimezone() + dt.timedelta(seconds=reset)).isoformat(timespec="seconds") \
            if name == "rate_limit_iso" else reset_phrase(reset)
        msg = ("You've hit your usage limit for the weekly window. " if name == "weekly_limit"
               else "You've hit your usage limit. ") + f"Try again at {when}."
        emit({"type": "turn.failed", "error": {"message": msg}})
        return 1
    if name == "model_unavailable":
        emit({"type": "error", "message": f"model {model} does not exist or you do not have access"})
        return 1
    if name == "auth_error":
        print("Error: Not logged in. Please run codex login", file=sys.stderr)
        return 1
    if name == "crash":
        print("thread 'main' panicked at fake crash", file=sys.stderr)
        return 101
    if name == "long_running":
        interrupted = []
        signal.signal(signal.SIGINT, lambda *_: interrupted.append(1))
        end = time.time() + float(arg or 3600)
        do_work("success", tid, scope, ro, "codex-partial", cwd)
        while time.time() < end and not interrupted:
            time.sleep(0.1)
        if interrupted:
            log(scn, {"flavor": "codex", "task_id": tid, "event": "SIGINT"})
            return 130
    if tid.startswith("PLAN/"):
        text = plan_result(prompt, name)
    elif tid.startswith("REPAIR/"):
        changed = repair_work(name, prompt, scope, cwd, arg)
        text = json.dumps(handoff(tid.split("/", 1)[1].rsplit("/", 1)[0], [], "codex")) if "READ-ONLY repair" in prompt \
            else json.dumps(repair_result(tid, prompt, changed, name))
    else:
        changed, report = do_work(name, tid, scope, ro, "codex", cwd)
        text = "I did the work, but here is prose instead of JSON." if name == "malformed" else \
            json.dumps(handoff(tid, changed, "codex", report, lego_ids=lego_ids))
    emit({"type": "item.completed", "item": {"id": "i1", "type": "agent_message", "text": text}})
    emit({"type": "turn.completed", "usage": {"input_tokens": 1200, "cached_input_tokens": 100, "output_tokens": 300}})
    if last:
        with open(last, "w") as f:
            f.write(text)
    return 0


# ----------------------------------------------------------------------------- claude
CLAUDE_HELP = """Usage: claude [options]
  -p, --print  --output-format <format>  --json-schema <schema>  --no-session-persistence  --model <model>
  --permission-mode <mode>  --effort <level>  --safe-mode  --permission-prompts <target>  --strict-mcp-config
  --allowedTools <tools...>  --disallowedTools <tools...>  --tools <tools...>  --verbose
"""


def claude(scn, args):
    c = scn.get("claude", {})
    if args[:1] in (["--version"], ["-v"]):
        print("2.1.280 (Claude Code) (fake)")
        return 0
    if args[:1] == ["--help"]:
        print(CLAUDE_HELP)
        return 0
    if args[:2] == ["auth", "status"]:
        a = c.get("auth", "claude.ai")
        print(json.dumps({"loggedIn": a != "none", "authMethod": a if a != "none" else "none",
                          "apiProvider": "firstParty"}))
        return 0
    if "-p" in args or "--print" in args:
        return claude_print(scn, args)
    print(f"fake claude: unsupported args {args}", file=sys.stderr)
    return 2


def claude_print(scn, args):
    model = args[args.index("--model") + 1] if "--model" in args else None
    cwd = os.getcwd()
    prompt = sys.stdin.read()
    tid, scope, ro, lego_ids = parse_prompt(prompt)
    beh = next_behavior(scn, "claude", tid)
    log(scn, {"flavor": "claude", "task_id": tid, "behavior": beh, "model": model, "args": args,
              "prompt_bytes": len(prompt), "env_keys": sorted(os.environ)})
    name, _, arg = beh.partition(":")
    sid = f"fake-{os.getpid()}"
    emit({"type": "system", "subtype": "init", "session_id": sid, "model": model})
    if name in ("rate_limit", "weekly_limit"):
        reset = int(time.time() + int(arg or 600))
        rtype = "seven_day" if name == "weekly_limit" else "five_hour"
        emit({"type": "rate_limit_event", "rate_limit_info": {"status": "rejected", "resetsAt": reset,
                                                              "rateLimitType": rtype, "isUsingOverage": False}})
        emit({"type": "result", "subtype": "error_during_execution", "is_error": True, "session_id": sid,
              "result": "Claude usage limit reached"})
        return 1
    if name == "overage":
        emit({"type": "rate_limit_event", "rate_limit_info": {"status": "allowed", "resetsAt": int(time.time() + 900),
                                                              "rateLimitType": "five_hour", "isUsingOverage": True}})
        interrupted = []
        signal.signal(signal.SIGINT, lambda *_: interrupted.append(1))
        end = time.time() + 60
        while time.time() < end and not interrupted:
            time.sleep(0.1)
        return 130 if interrupted else 0
    if name == "model_unavailable":
        emit({"type": "result", "subtype": "error_during_execution", "is_error": True, "session_id": sid,
              "result": f"There's an issue with the selected model ({model}). It may not exist or you may not have access to it."})
        return 1
    if name == "auth_error":
        emit({"type": "result", "is_error": True, "result": "Not logged in · Please run /login"})
        return 1
    if name == "crash":
        print("fatal: fake claude crash", file=sys.stderr)
        return 1
    if name == "events_then_wait":      # real Claude reports usage while it works
        for rtype, util in (("five_hour", 0.37), ("seven_day", 0.55)):
            emit({"type": "rate_limit_event", "rate_limit_info": {
                "status": "allowed", "resetsAt": int(time.time() + 3600), "rateLimitType": rtype,
                "utilization": util, "isUsingOverage": False}})
        time.sleep(float(arg or 3))
    if name == "long_running":
        interrupted = []
        signal.signal(signal.SIGINT, lambda *_: interrupted.append(1))
        end = time.time() + float(arg or 3600)
        while time.time() < end and not interrupted:
            time.sleep(0.1)
        if interrupted:
            log(scn, {"flavor": "claude", "task_id": tid, "event": "SIGINT"})
            return 130
    if name not in ("rate_limit", "weekly_limit", "overage", "model_unavailable", "auth_error", "crash"):
        for rtype, util in (("five_hour", 0.42), ("seven_day", 0.61)):
            emit({"type": "rate_limit_event", "rate_limit_info": {
                "status": "allowed", "resetsAt": int(time.time() + (3600 if rtype == "five_hour" else 86400 * 3)),
                "rateLimitType": rtype, "utilization": util, "isUsingOverage": False}})
    if tid.startswith("PLAN/"):
        txt = plan_result(prompt, name)
        try:
            h = json.loads(txt)
        except ValueError:
            h = None
        emit({"type": "result", "subtype": "success", "is_error": False, "session_id": sid, "result": txt,
              **({"structured_output": h} if h else {})})
        return 0
    if tid.startswith("REPAIR/"):
        changed = repair_work(name, prompt, scope, cwd, arg)
        h = handoff(tid.split("/", 1)[1].rsplit("/", 1)[0], [], "claude") if "READ-ONLY repair" in prompt \
            else repair_result(tid, prompt, changed, name)
    else:
        changed, report = do_work(name, tid, scope, ro, "claude", cwd)
        h = handoff(tid, changed, "claude", report, lego_ids=lego_ids)
    emit({"type": "assistant", "message": {"content": [{"type": "text", "text": "working..."}]}})
    res = {"type": "result", "subtype": "success", "is_error": False, "session_id": sid,
           "total_cost_usd": 0.0123, "usage": {"input_tokens": 900, "cache_read_input_tokens": 50,
                                               "cache_creation_input_tokens": 10, "output_tokens": 200}}
    if name == "malformed":
        res["result"] = "Done, no JSON today."
    else:
        res["result"] = json.dumps(h)
        res["structured_output"] = h
    emit(res)
    return 0


def main():
    argv = sys.argv[1:]
    flavor = argv.pop(0)
    scn = {}
    if argv[:1] == ["--scenario"]:
        scn = load(argv[1])
        argv = argv[2:]
    return (codex if flavor == "codex" else claude)(scn, argv)


if __name__ == "__main__":
    sys.exit(main())
