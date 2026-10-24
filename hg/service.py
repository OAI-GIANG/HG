"""Fail-closed service entrypoint for python -B -m hg serve --config FILE."""
from __future__ import annotations

import argparse
import fcntl
import importlib
import json
import os
from pathlib import Path
import signal
import stat
import sys
import threading

from hg.http_api import HGHTTPServer, planned_write_readback_verifier
from hg.release import ReleaseError, verify_root

CONFIG_KEYS = {
    "schema", "host", "port", "state_dir", "token_file",
    "release_root", "release_manifest", "release_id", "max_body_bytes",
}
CONFIG_SCHEMA = "hg-runtime-service-config-v1"
BLOCKED_EXIT = 78


class ServiceConfigError(RuntimeError):
    pass


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _reject_constant(_value):
    raise ValueError("non-finite JSON constant is not permitted")


def _regular_owned_file(path: Path, *, mode: int | None = None, private: bool = False):
    if not path.is_absolute() or path.resolve() != path:
        raise ServiceConfigError(f"required path must be absolute and contain no symlinked parents: {path.name}")
    try:
        st = path.lstat()
    except OSError as exc:
        raise ServiceConfigError(f"required file is unavailable: {path.name}") from exc
    if not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid():
        raise ServiceConfigError(f"required path must be a regular file owned by this user: {path.name}")
    if mode is not None and stat.S_IMODE(st.st_mode) != mode:
        raise ServiceConfigError(f"{path.name} must have mode {mode:03o}")
    if private and stat.S_IMODE(st.st_mode) & 0o077:
        raise ServiceConfigError(f"{path.name} must not grant group/other access")
    return st


def load_config(path: str | Path):
    path = Path(path)
    _regular_owned_file(path, private=True)
    try:
        raw = path.read_bytes()
        if len(raw) > 65536:
            raise ServiceConfigError("service config exceeds 64 KiB")
        doc = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object,
                         parse_constant=_reject_constant)
    except ServiceConfigError:
        raise
    except (OSError, UnicodeError, ValueError) as exc:
        raise ServiceConfigError("service config is not strict UTF-8 JSON") from exc
    if not isinstance(doc, dict) or set(doc) != CONFIG_KEYS:
        raise ServiceConfigError("service config keys must match the documented schema exactly")
    if doc.get("schema") != CONFIG_SCHEMA:
        raise ServiceConfigError("unsupported service config schema")
    if doc.get("host") != "127.0.0.1":
        raise ServiceConfigError("host must be 127.0.0.1")
    if isinstance(doc.get("port"), bool) or not isinstance(doc.get("port"), int) or not 1 <= doc["port"] <= 65535:
        raise ServiceConfigError("port must be an integer in 1..65535")
    if (isinstance(doc.get("max_body_bytes"), bool) or not isinstance(doc.get("max_body_bytes"), int)
            or not 1 <= doc["max_body_bytes"] <= 1048576):
        raise ServiceConfigError("max_body_bytes must be in 1..1048576")
    for field in ("state_dir", "token_file", "release_root", "release_manifest"):
        value = doc.get(field)
        if not isinstance(value, str) or not value or not Path(value).is_absolute():
            raise ServiceConfigError(f"{field} must be an absolute path")
    release_id = doc.get("release_id")
    if not isinstance(release_id, str) or len(release_id) != 64 or any(c not in "0123456789abcdef" for c in release_id):
        raise ServiceConfigError("release_id must be a lowercase SHA-256 digest")
    return doc


def read_token(path: str | Path) -> bytes:
    path = Path(path)
    _regular_owned_file(path, mode=0o600)
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ServiceConfigError("service token could not be read") from exc
    if raw.endswith(b"\n"):
        raw = raw[:-1]
    if len(raw) < 32 or any(b < 33 or b > 126 for b in raw):
        raise ServiceConfigError("service token must be at least 32 printable ASCII bytes")
    return raw


def _ensure_state_dir(path: Path, *, create: bool):
    if not path.is_absolute() or path.resolve() != path:
        raise ServiceConfigError("state_dir must be absolute and contain no symlinked parents")
    if not path.exists() and create:
        path.mkdir(parents=True, mode=0o700)
    try:
        st = path.lstat()
    except OSError as exc:
        raise ServiceConfigError("state_dir does not exist; create it with mode 700 before preflight") from exc
    if not stat.S_ISDIR(st.st_mode) or stat.S_ISLNK(st.st_mode) or st.st_uid != os.getuid():
        raise ServiceConfigError("state_dir must be a real directory owned by this user")
    if stat.S_IMODE(st.st_mode) & 0o077:
        raise ServiceConfigError("state_dir must not grant group/other access")


def _open_writer_lock(state_dir: Path):
    path = state_dir / ".writer.lock"
    flags = os.O_CREAT | os.O_RDWR
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(path, flags, 0o600)
    except OSError as exc:
        raise ServiceConfigError("cannot safely open the single-writer lock") from exc
    st = os.fstat(fd)
    if not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid() or stat.S_IMODE(st.st_mode) != 0o600:
        os.close(fd)
        raise ServiceConfigError("writer lock must be a private regular file owned by this user")
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        os.close(fd)
        raise ServiceConfigError("another HG service already owns this state directory") from exc
    return fd


def verify_config(config, *, create_state=False):
    token = read_token(config["token_file"])
    state = Path(config["state_dir"])
    _ensure_state_dir(state, create=create_state)
    release_root = Path(config["release_root"])
    _regular_owned_file(Path(config["release_manifest"]))
    try:
        root_stat = release_root.lstat()
    except OSError as exc:
        raise ServiceConfigError("release_root is unavailable") from exc
    if (not stat.S_ISDIR(root_stat.st_mode) or stat.S_ISLNK(root_stat.st_mode)
            or root_stat.st_uid != os.getuid() or release_root.resolve() != release_root):
        raise ServiceConfigError("release_root must be a real owner-owned immutable-version directory")
    release = verify_root(config["release_root"], config["release_manifest"], config["release_id"])
    importlib.import_module("hg.runtime")
    importlib.import_module("maep.authority.canonical_source")
    return {"token_bytes": len(token), "release": release}


def trust_report(authority):
    doc, provenance = authority.current()
    return {"result": "LOADED", "provenance": provenance, "policy_version": doc["policy_version"]}


def create_service(config, *, token, authority, release_report):
    from hg.runtime import build_runtime
    state = Path(config["state_dir"])
    runtime = build_runtime(state, [], authority=authority, issue_task_grants=True, memory=True,
                            verifiers={"AC-READBACK": planned_write_readback_verifier(state / "root")})
    return HGHTTPServer(runtime=runtime, token=token, host=config["host"], port=config["port"],
                        max_body_bytes=config["max_body_bytes"], release_report=release_report,
                        trust_report=lambda: trust_report(authority),
                        idempotency_path=state / "http-idempotency.sqlite3")


def run(config_path: str | Path, *, check=False) -> int:
    lock_fd = None
    server = None
    try:
        config = load_config(config_path)
        report = verify_config(config, create_state=False)
        token = read_token(config["token_file"])
        from maep.authority.canonical_source import CanonicalManifest
        # Use the canonical source's bounded 300-second cache to avoid exhausting
        # the unauthenticated GitHub REST quota. Stale reload failures still block.
        authority = CanonicalManifest.from_github()
        trust = trust_report(authority)
        if check:
            print(json.dumps({"result": "PREFLIGHT_PASS", "release": report["release"],
                              "trust": trust}, sort_keys=True))
            return 0
        lock_fd = _open_writer_lock(Path(config["state_dir"]))
        # All state, SQLite journals and newly-created files are private to this UID.
        os.umask(0o077)
        release_report = lambda: verify_root(
            config["release_root"], config["release_manifest"], config["release_id"])
        report["release"] = release_report()
        trust_report(authority)
        server = create_service(config, token=token, authority=authority, release_report=release_report)
    except Exception as exc:
        print(f"HG_BLOCKED: startup validation failed ({type(exc).__name__})", file=sys.stderr)
        if lock_fd is not None:
            os.close(lock_fd)
        return BLOCKED_EXIT

    stop_once = threading.Event()
    def stop(_sig, _frame):
        if stop_once.is_set():
            return
        stop_once.set()
        threading.Thread(target=server.shutdown, name="hg-service-shutdown", daemon=True).start()

    previous = {}
    for sig in (signal.SIGINT, signal.SIGTERM):
        previous[sig] = signal.signal(sig, stop)
    print(f"HG_RUNTIME_READY host=127.0.0.1 port={server.address[1]} release_id={config['release_id']}", flush=True)
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        stop(signal.SIGINT, None)
    finally:
        server.server_close()
        if lock_fd is not None:
            os.close(lock_fd)
        for sig, handler in previous.items():
            signal.signal(sig, handler)
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m hg serve")
    parser.add_argument("--config", required=True, help="absolute path to a private service JSON config")
    parser.add_argument("--check", action="store_true", help="read-only preflight; do not start the server")
    args = parser.parse_args(argv)
    return run(args.config, check=args.check)


if __name__ == "__main__":
    raise SystemExit(main())
