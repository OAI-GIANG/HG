"""Helpers for staging_rehearsal.sh. Staging only: every command that talks to a service or writes a
file first proves its target is inside the staging directory. Never prints a token.

usage: python3 -I -B staging_probe.py guard PRODUCTION_CONFIG STAGING_DIR PORT
       python3 -I -B staging_probe.py field JSON_FILE KEY
       python3 -I -B staging_probe.py staging-conf CONFIG                     (needs HG_STAGING_DIR)
       python3 -I -B staging_probe.py token PATH
       python3 -I -B staging_probe.py mkconf CONFIG RELEASE_ID STAGING_HOME PORT TOKEN_FILE
       python3 -I -B staging_probe.py port-free PORT
       python3 -I -B staging_probe.py chat CONFIG MESSAGE OUT_JSON           (needs HG_STAGING_DIR)
       python3 -I -B staging_probe.py j2 CONFIG TASK_ID REL_PATH OUT_DIR       (needs HG_STAGING_DIR)
Exit 2 = refused (the target is not staging, or the input is unusable).
"""
import hashlib
import http.client
import json
import os
import secrets
import socket
import sys
from pathlib import Path

PATH_KEYS = ("state_dir", "token_file", "release_root", "release_manifest")


class Refused(Exception):
    pass


def _inside(path, root):
    path, root = os.path.realpath(path), os.path.realpath(root)
    return path == root or path.startswith(root + os.sep)


def _load(path):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise Refused(f"{path}: not readable JSON ({exc.__class__.__name__})") from exc
    if not isinstance(data, dict):
        raise Refused(f"{path}: not a JSON object")
    return data


def guard(production_config, staging_dir, port):
    """The staging directory and port must not reach anything the production service uses."""
    prod = _load(production_config)
    if not isinstance(port, int) or not 1024 <= port <= 65535:
        raise Refused("port must be 1024..65535")
    if prod.get("port") == port:
        raise Refused(f"port {port} is the production port")
    for key in PATH_KEYS:
        value = prod.get(key)
        if not isinstance(value, str) or not value.startswith("/"):
            raise Refused(f"production config has no absolute {key}")
        if _inside(value, staging_dir) or _inside(staging_dir, value):
            raise Refused(f"staging dir overlaps production {key}")
    for live in (Path(production_config).parent, Path(prod["release_root"]).parent):
        if _inside(staging_dir, live):
            raise Refused(f"staging dir is inside a live HG directory: {live}")
    return prod


def staging_conf(path):
    """A config the rehearsal may talk to: every path inside $HG_STAGING_DIR, loopback host."""
    root = os.environ.get("HG_STAGING_DIR")
    if not root or not root.startswith("/"):
        raise Refused("HG_STAGING_DIR must name the staging directory")
    conf = _load(path)
    if conf.get("host") != "127.0.0.1" or not isinstance(conf.get("port"), int):
        raise Refused(f"{path}: not a loopback service config")
    for key in ("state_dir", "token_file", "release_root"):
        value = conf.get(key)
        if not isinstance(value, str) or not _inside(value, root):
            raise Refused(f"{path}: {key} is outside the staging directory")
    return conf


def call(conf, method, path, body=None, timeout=300):
    token = Path(conf["token_file"]).read_text(encoding="utf-8").strip()
    conn = http.client.HTTPConnection("127.0.0.1", conf["port"], timeout=timeout)
    headers = {"Authorization": f"Bearer {token}"}
    raw = None
    if body is not None:
        raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers.update({"Content-Type": "application/json", "Content-Length": str(len(raw))})
    conn.request(method, path, body=raw, headers=headers)
    resp = conn.getresponse()
    data = resp.read().decode("utf-8")
    conn.close()
    try:
        return resp.status, json.loads(data)
    except ValueError:
        return resp.status, data


def _lines(path):
    return sum(1 for _ in path.open("rb")) if path.is_file() else 0


def counts(conf):
    state = Path(conf["state_dir"])
    root = state / "root"
    files = sorted(str(p.relative_to(root)) for p in root.rglob("*") if p.is_file()) if root.is_dir() else []
    return {"tasks_lines": _lines(state / "tasks.jsonl"), "actions_lines": _lines(state / "actions.jsonl"),
            "memory_lines": _lines(state / "memory.jsonl"), "root_files": files}


def mkconf(config, release_id, staging_home, port, token_file):
    doc = {"schema": "hg-runtime-service-config-v1", "host": "127.0.0.1", "port": port, "max_body_bytes": 262144,
           "state_dir": f"{staging_home}/.local/share/hg/runtime-service-state-staging", "token_file": token_file,
           "release_root": f"{staging_home}/hg-releases/{release_id}",
           "release_manifest": f"{staging_home}/.config/hg/releases/{release_id}.json", "release_id": release_id}
    text = json.dumps(doc, sort_keys=True, indent=2) + "\n"
    path = Path(config)
    if path.exists():
        if path.read_text(encoding="utf-8") != text:
            raise Refused(f"{config} exists with other content")
        return
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        stream.write(text)


def main(argv):
    cmd, args = argv[0], argv[1:]
    if cmd == "guard":
        guard(args[0], args[1], int(args[2]) if args[2].isdigit() else -1)
        print("STAGING_GUARD_PASS")
        return 0
    if cmd == "staging-conf":
        staging_conf(args[0])
        return 0
    if cmd == "field":
        print(_load(args[0])[args[1]])
        return 0
    if cmd == "token":
        path = Path(args[0])
        if not path.exists():
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write(secrets.token_hex(32) + "\n")
        return 0
    if cmd == "mkconf":
        mkconf(args[0], args[1], args[2], int(args[3]), args[4])
        staging_conf(args[0])
        return 0
    if cmd == "port-free":
        with socket.socket() as sock:
            sock.settimeout(2)
            if sock.connect_ex(("127.0.0.1", int(args[0]))) == 0:
                raise Refused(f"something already listens on 127.0.0.1:{args[0]}")
        return 0
    if cmd == "chat":
        conf = staging_conf(args[0])
        before = counts(conf)
        status, body = call(conf, "POST", "/v1/chat", {"message": args[1], "general": True})
        after = counts(conf)
        record = {"http": status, "response": body, "state_before": before, "state_after": after,
                  "no_task_or_action": before == after}
        Path(args[2]).write_text(json.dumps(record, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
        outcome = body.get("outcome") if isinstance(body, dict) else None
        print(json.dumps({"http": status, "outcome": outcome, "no_task_or_action": before == after}))
        return 0 if status == 200 and outcome == "ANSWERED" and before == after else 1
    if cmd == "j2":
        conf = staging_conf(args[0])
        task_id, rel, out = args[1], args[2], Path(args[3])
        state = Path(conf["state_dir"])
        for name in ("tasks.jsonl", "actions.jsonl", "memory.jsonl"):
            src = state / name
            picked = [ln for ln in src.read_text(encoding="utf-8").splitlines() if task_id in ln] if src.is_file() else []
            (out / f"j2-{name}").write_text("".join(ln + "\n" for ln in picked), encoding="utf-8")
        target = state / "root" / rel
        if not _inside(target, state / "root"):
            raise Refused("task file is outside the staging root")
        raw = target.read_bytes() if target.is_file() else None
        status, body = call(conf, "GET", f"/v1/tasks/{task_id}")
        record = {"task_id": task_id, "file_sha256": hashlib.sha256(raw).hexdigest() if raw is not None else None,
                  "file_bytes": None if raw is None else len(raw), "get_http": status,
                  "state": (body.get("task") or {}).get("state") if isinstance(body, dict) else None}
        (out / "j2-file.json").write_text(json.dumps(record, indent=1, sort_keys=True), encoding="utf-8")
        print(json.dumps(record))
        return 0 if record["state"] == "CLOSED_VERIFIED" and raw is not None else 1
    raise Refused(f"unknown command {cmd}")


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except (Refused, IndexError, KeyError, ValueError) as exc:
        print(f"STAGING_REFUSED: {exc}", file=sys.stderr)
        sys.exit(2)
