"""HG command-line entry point.

    python -m hg selfcheck [--workdir DIR]   run the runtime self-check scenarios
    python -m hg status --workdir DIR        read-only task and pending-action report
    python -m hg authority-check             read the canonical owner manifest (RT-06), live
    python -m hg bench [--json P] [--baseline P]   fixed benchmark suite; exit 1 on invariant/regression
    python -m hg learn --workdir DIR [--threshold N] [--cases-out P]   failures -> lessons
    python -m hg health --workdir DIR [--trust]    health report from a runtime's ledgers

Assistant (runs as the owner in their own shell, outside the governed runtime path; see
hg/assistant/cli.py for exit codes):
    python -m hg                              interactive prompt (when stdin is a terminal)
    python -m hg note add|search|list|show|forget ...
    python -m hg ask "câu hỏi" [--notes-only] [--provider local|anthropic] [--json]
    python -m hg check "văn bản"             compare text with the notes, no model
    python -m hg summarize FILE|- [--model] [--strict]
    python -m hg model status | use NAME      local model status / select and pin
    python -m hg eval [--set FILE]            fixed Vietnamese evaluation in a temporary home
    python -m hg repair                       recover a ledger with a cut-off last line

selfcheck exercises the real runtime path (BrainOrchestrator -> TaskStore -> ActionGateway
-> local filesystem -> AcceptanceGate) in a scratch directory. Its grants are self-check
fixtures created in-process; they are not anchored to the owner trust root (RT-06 BLOCKED).
Exit code 0 only if every scenario's observed outcome equals its expected outcome.
"""
import argparse
import json
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from maep.core import POLICY_VERSION
from maep.ledger import read_events
from maep.authority.canonical_source import load_canonical_manifest
from maep.authority.trust_anchor import TrustAnchorError
from maep.task_store import TaskStore
from hg.runtime import DEFAULT_PRINCIPAL, build_runtime
from hg.tools.gateway import pending_from_events
from hg.verification.evidence import EventLog


def _task(task_id, path):
    return {
        "task_id": task_id, "objective": f"Write {path} and verify its content",
        "scope": {"include": ["out/"], "exclude": []}, "inputs": [],
        "outputs": [{"name": "file", "description": path}],
        "acceptance_criteria": [{"criterion_id": "AC-1", "description": "file content matches",
                                 "mandatory": True, "evidence_types": ["TEST_RESULT"]}],
        "evidence_requirements": ["independent read-back of the file"], "risks": [],
        "stop_conditions": ["authorization denied", "scope exceeded"],
        "next_action": "execute plan", "state": "DRAFT", "policy_version": POLICY_VERSION,
    }


def _step(task_id, path, content):
    return {"step_id": "S-1", "tool": "fs.write", "action": "WRITE", "resource": f"file:{path}",
            "scope": ["out/"], "authorization_id": f"AUTH-{task_id}", "params": {"path": path, "content": content}}


def _grant(task_id, path, now):
    return {"authorization_id": f"AUTH-{task_id}", "principal": DEFAULT_PRINCIPAL, "action": "WRITE",
            "resource": f"file:{path}", "scope": ["out/"], "conditions": [], "task_id": task_id,
            "policy_version": POLICY_VERSION, "decision": "ALLOW",
            "issued_at": (now - timedelta(minutes=1)).isoformat(),
            "expires_at": (now + timedelta(minutes=30)).isoformat()}


def selfcheck(workdir):
    now = datetime.now(timezone.utc)
    content = {"out/allowed.txt": "HG self-check", "out/ungranted.txt": "must not exist",
               "out/readonly.txt": "must not exist"}
    results = []

    def readback(root, path):
        def file_content_matches(_snapshot):
            target = root / path
            actual = target.read_text(encoding="utf-8") if target.is_file() else None
            return actual == content[path], f"read back {actual!r}"
        return file_content_matches

    def scenario(name, subdir, grants, mode, task_id, path, expected_state, expect_file):
        rt_dir = workdir / subdir
        root = rt_dir / "root"
        rt = build_runtime(rt_dir, grants, mode=mode, verifiers={"AC-1": readback(root, path)},
                           allow_fixture_grants=True)    # self-check fixtures; reported in "limitations"
        final = rt.orch.execute_task(_task(task_id, path), [_step(task_id, path, content[path])])
        observed_file = (root / path).is_file()
        ok = final["task"]["state"] == expected_state and observed_file == expect_file
        results.append({"scenario": name, "workdir": str(rt_dir), "task_id": task_id,
                        "expected_state": expected_state, "observed_state": final["task"]["state"],
                        "expected_file": expect_file, "observed_file": observed_file,
                        "result": "PASS" if ok else "FAIL"})

    scenario("authorized write closes with evidence", "authorized", [_grant("SC-1", "out/allowed.txt", now)],
             "AUTHORIZED_EXECUTION", "SC-1", "out/allowed.txt", "CLOSED_VERIFIED", True)
    scenario("write without a grant never executes", "ungranted", [],
             "AUTHORIZED_EXECUTION", "SC-2", "out/ungranted.txt", "PLANNED", False)
    scenario("READ_ONLY mode blocks a granted write", "readonly", [_grant("SC-3", "out/readonly.txt", now)],
             "READ_ONLY", "SC-3", "out/readonly.txt", "BLOCKED", False)
    return {
        "policy_version": POLICY_VERSION, "workdir": str(workdir),
        "limitations": ["grants are in-process self-check fixtures, not anchored to the trust root (RT-06 BLOCKED)",
                        "verifiers are internal checks, not independent review"],
        "scenarios": results,
        "result": "PASS" if all(r["result"] == "PASS" for r in results) else "FAIL",
    }


def status(workdir):
    """Read-only: replays both ledgers without writing to either."""
    tasks_path, actions_path = workdir / "tasks.jsonl", workdir / "actions.jsonl"
    store = TaskStore.restore(tasks_path)
    pending = pending_from_events(EventLog(actions_path).events())
    report = []
    task_ids = sorted({e["task_id"] for e in read_events(tasks_path) if e.get("type") == "TASK_CREATED"})
    for task_id in task_ids:
        snap = store.snapshot(task_id)
        report.append({"task_id": task_id, "state": snap["task"]["state"], "version": snap["version"],
                       "open_blockers": snap["open_blockers"],
                       "pending_actions": [p["action_id"] for p in pending.values() if p["task_id"] == task_id]})
    return {"workdir": str(workdir), "tasks": report}


def authority_check(loader=load_canonical_manifest):
    """Report whether the trust root on main can be loaded. Exit 0 loaded, 3 unavailable/invalid."""
    try:
        doc, provenance = loader()
    except TrustAnchorError as exc:
        return 3, {"result": "BLOCKED", "reason": str(exc),
                   "meaning": "anchored runtime denies every action until a valid manifest exists on main"}
    grants = [{"principal": g["principal"], "actions": g["actions"], "scope": g["scope"],
               "issued_at": g["issued_at"], "expires_at": g["expires_at"]} for g in doc["grants"]]
    return 0, {"result": "LOADED", "provenance": provenance, "policy_version": doc["policy_version"],
               "grants": grants}


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m hg")
    sub = parser.add_subparsers(dest="command")
    sc = sub.add_parser("selfcheck", help="run runtime self-check scenarios")
    sc.add_argument("--workdir", help="directory for ledgers and files (default: a new temp directory)")
    st = sub.add_parser("status", help="read-only report from a runtime work directory")
    st.add_argument("--workdir", required=True)
    sub.add_parser("authority-check", help="read the canonical owner manifest from main (network)")
    bench = sub.add_parser("bench", help="run the fixed benchmark suite (offline)")
    bench.add_argument("--json", help="write the full report to this file")
    bench.add_argument("--baseline", help="compare against a previous report; regressions fail the run")
    learn = sub.add_parser("learn", help="classify failures in a runtime's ledgers into lessons")
    learn.add_argument("--workdir", required=True, action="append")
    learn.add_argument("--threshold", type=int, default=2)
    learn.add_argument("--cases-out", help="write proposed regression cases (for review) to this file")
    hl = sub.add_parser("health", help="health report from a runtime's ledgers")
    hl.add_argument("--workdir", required=True)
    hl.add_argument("--trust", action="store_true", help="also read the trust root on main (network)")
    serve = sub.add_parser("serve", help="run authenticated loopback HTTP service")
    serve.add_argument("--config", required=True)
    serve.add_argument("--check", action="store_true", help="run read-only preflight without binding a port")
    from hg.assistant import cli as assistant_cli
    assistant_cli.add_parsers(sub)
    args = parser.parse_args(argv)

    if args.command is None:
        if sys.stdin.isatty():
            return assistant_cli.interactive()
        parser.print_help()
        return 2
    if args.command in {"note", "ask", "check", "summarize", "model", "eval", "repair"}:
        return assistant_cli.run(args)

    if args.command == "serve":
        from hg.service import run as run_service
        return run_service(args.config, check=args.check)

    if args.command == "bench":
        from hg.verification.benchmark import run_benchmark, verdict
        report = run_benchmark()
        baseline = json.loads(Path(args.baseline).read_text(encoding="utf-8")) if args.baseline else None
        problems = verdict(report, baseline)
        report["verdict"] = problems or ["PASS"]
        if args.json:
            Path(args.json).write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        print(json.dumps({"metrics": report["metrics"], "verdict": report["verdict"]}, indent=2, ensure_ascii=False))
        return 1 if problems else 0
    if args.command == "learn":
        from hg.verification.learning import analyze, proposed_cases_json
        report = analyze(args.workdir, threshold=args.threshold)
        if args.cases_out:
            Path(args.cases_out).write_text(proposed_cases_json(report), encoding="utf-8")
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 0
    if args.command == "health":
        from hg.ops import health
        report = health(Path(args.workdir), trust_loader=load_canonical_manifest if args.trust else None)
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return {"OK": 0, "DEGRADED": 1}.get(report["status"], 2)

    if args.command == "authority-check":
        code, report = authority_check()
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return code

    if args.command == "selfcheck":
        workdir = Path(args.workdir) if args.workdir else Path(tempfile.mkdtemp(prefix="hg-selfcheck-"))
        workdir.mkdir(parents=True, exist_ok=True)
        if any(workdir.iterdir()):
            print(json.dumps({"result": "BLOCKED", "reason": f"workdir {workdir} is not empty"}))
            return 2
        report = selfcheck(workdir)
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 0 if report["result"] == "PASS" else 1
    print(json.dumps(status(Path(args.workdir)), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
