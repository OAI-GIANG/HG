import json, signal, sys, threading, secrets
from pathlib import Path

base = Path(sys.argv[1])
worktree = Path(sys.argv[2])
sys.path.insert(0, str(worktree))
base.mkdir(parents=True, exist_ok=True)
home = base / "assistant-home"
home.mkdir(mode=0o700, exist_ok=True)
token = "ui-dom-e2e-token-" + secrets.token_urlsafe(48)
(base / "token.txt").write_text(token, encoding="utf-8")
(base / "token.txt").chmod(0o600)

from maep.authority.canonical_source import CanonicalManifest
from maep.tests.test_canonical_source import FakeGitHub
from hg.assistant.notes import Notebook
from hg.chat import ChatService
from hg.http_api import HGHTTPServer
from hg.runtime import build_runtime
from hg.tests.support import Clock
from hg.tests.test_chat_service import DIGEST, MODEL, FakeOllama

ollama = FakeOllama("Không được gọi inference trong smoke test.")
config = {"ollama_url": ollama.url, "model": MODEL, "model_digest": DIGEST, "timeout_s": 10}
(home / "config.json").write_text(json.dumps(config), encoding="utf-8")
(home / "config.json").chmod(0o600)
Notebook(home).add(
    "Ghi chú XSS sentinel: xe cần thay dầu sau 3.000 km. <img src=x onerror=alert(1)>",
    origin="test",
)
clock = Clock()
authority = CanonicalManifest.from_github(http_get=FakeGitHub().get, max_age_s=0, clock=clock)
state = base / "state"
runtime = build_runtime(state, [], authority=authority, issue_task_grants=True, clock=clock)
server = HGHTTPServer(
    runtime=runtime, token=token.encode(), port=0,
    release_report=lambda: {"result": "VERIFIED", "release_id": "e" * 64},
    trust_report=lambda: {"result": "LOADED", "provenance": {"commit": "c" * 40}},
    idempotency_path=state / "idem.sqlite3",
    chat=ChatService(home, release_id="e" * 64), notes_home=home,
    ui_dir=worktree / "hg" / "ui",
)
thread = threading.Thread(target=server.serve_forever, daemon=True)
thread.start()
(base / "server.json").write_text(json.dumps({"port": server.server_port}), encoding="utf-8")
stop = threading.Event()
signal.signal(signal.SIGTERM, lambda *_: stop.set())
signal.signal(signal.SIGINT, lambda *_: stop.set())
stop.wait()
server.shutdown()
server.server_close()
ollama.close()
(base / "server-metrics.json").write_text(
    json.dumps({"tag_requests": ollama.tag_requests, "chat_requests": len(ollama.chat_requests)}),
    encoding="utf-8",
)
