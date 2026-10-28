"""HG v1 deploy smoke against the live loopback service (AC-D3, AC-D4). Never prints the token.

usage: python3 -I -B deploy_smoke.py ready             -> readiness JSON
       python3 -I -B deploy_smoke.py submit TAG        -> new task, independent read-back, replay, conflict
       python3 -I -B deploy_smoke.py get TASK_ID       -> HTTP status and state of an existing task
Config: $HG_SERVICE_CONFIG or ~/.config/hg/runtime-service.json (port, state_dir, token_file).
"""
import http.client
import json
import os
import sys
from pathlib import Path

HOME = Path(os.environ["HOME"])
CONF = json.loads(Path(os.environ.get("HG_SERVICE_CONFIG", HOME / ".config/hg/runtime-service.json")).read_text())
TOKEN = Path(CONF["token_file"]).read_text().strip()


def call(method, path, body=None, key=None):
    conn = http.client.HTTPConnection("127.0.0.1", CONF["port"], timeout=60)
    headers = {"Authorization": f"Bearer {TOKEN}"}
    raw = None
    if body is not None:
        raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers.update({"Content-Type": "application/json", "Content-Length": str(len(raw)), "Idempotency-Key": key})
    conn.request(method, path, body=raw, headers=headers)
    resp = conn.getresponse()
    data = resp.read().decode("utf-8")
    conn.close()
    try:
        return resp.status, json.loads(data)
    except ValueError:
        return resp.status, data


def payload(tag, content):
    task_id = f"DEPLOY-SMOKE-{tag}"
    path = f"out/deploy-smoke-{tag}.txt"
    task = {"task_id": task_id, "objective": f"Write {path} and read it back", "scope": {"include": ["out/"], "exclude": []},
            "inputs": [], "outputs": [{"name": "file", "description": path}],
            "acceptance_criteria": [{"criterion_id": "AC-READBACK", "description": "write content can be read back exactly",
                                     "mandatory": True, "evidence_types": ["TEST_RESULT"]}],
            "evidence_requirements": ["independent read-back"], "risks": [], "stop_conditions": ["authorization denied"],
            "next_action": "execute plan", "state": "DRAFT", "policy_version": "MAEP-1.1.0"}
    step = {"step_id": "S-1", "tool": "fs.write", "action": "WRITE", "resource": f"file:{path}", "scope": ["out/"],
            "authorization_id": f"AUTH-{task_id}", "params": {"path": path, "content": content}}
    return task_id, path, {"task": task, "steps": [step]}


def main():
    cmd = sys.argv[1]
    if cmd == "ready":
        print(json.dumps(call("GET", "/v1/health/ready"), ensure_ascii=False))
        return 0
    if cmd == "get":
        status, body = call("GET", f"/v1/tasks/{sys.argv[2]}")
        state = (body.get("task") or {}).get("state") if isinstance(body, dict) else None
        print(json.dumps({"http": status, "state": state}, ensure_ascii=False))
        return 0 if status == 200 else 1
    tag = sys.argv[2]
    content = f"HG v1 deploy smoke {tag}"
    task_id, path, body = payload(tag, content)
    key = f"deploy-smoke-{tag}"
    s1, r1 = call("POST", "/v1/tasks", body, key)
    result = r1.get("result") if isinstance(r1, dict) else None
    final = ((result or {}).get("task") or {}).get("state")
    on_disk = Path(CONF["state_dir"]) / "root" / path
    readback = on_disk.read_text(encoding="utf-8") if on_disk.is_file() else None
    s2, r2 = call("POST", "/v1/tasks", body, key)
    replay_ok = isinstance(r2, dict) and r2.get("replayed") is True and r2.get("result") == result
    _tid, _path, other = payload(tag, content + " CHANGED")
    s3, r3 = call("POST", "/v1/tasks", other, key)
    report = {"task_id": task_id, "first": {"http": s1, "state": final}, "readback_matches": readback == content,
              "replay": {"http": s2, "same_result": replay_ok},
              "changed_body": {"http": s3, "error": r3.get("error") if isinstance(r3, dict) else r3}}
    print(json.dumps(report, ensure_ascii=False))
    ok = s1 == 200 and final == "CLOSED_VERIFIED" and readback == content and replay_ok and s3 == 409
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
