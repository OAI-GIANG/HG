"""hg.chat.ChatService: the service side of POST /v1/chat, end to end against a real loopback model server.

The model server here is a fake Ollama over real HTTP (GET /api/tags, streamed POST /api/chat), so
the real OllamaProvider, ModelRouter (HG Brain model layer, C-12), grounding and receipt code run.
Plus one test through HGHTTPServer with the real ChatService (request -> Brain -> answer).
"""
import http.client
import http.server
import json
import os
import shutil
import tempfile
import threading
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path

from hg.assistant.home import locked
from hg.assistant.notes import Notebook
from hg.chat import ChatService
from hg.http_api import HGHTTPServer, HTTPBoundaryError
from hg.verification.evidence import EventLog

MODEL = "qwen3:1.7b"
DIGEST = "d" * 64
NOW = datetime(2026, 10, 29, 3, 0, tzinfo=timezone.utc)


class FakeOllama:
    """Loopback HTTP server speaking the two Ollama endpoints HG uses."""

    def __init__(self, text="Paris là thủ đô của Pháp.", *, digest=DIGEST, gate=None):
        self.text, self.digest, self.gate = text, digest, gate
        self.chat_requests, self.tag_requests = [], 0
        outer = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path != "/api/tags":
                    self.send_error(404)
                    return
                outer.tag_requests += 1
                body = json.dumps({"models": [{"name": MODEL, "digest": outer.digest, "size": 1234}]}).encode()
                self.send_response(200)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self):
                if self.path != "/api/chat":
                    self.send_error(404)
                    return
                outer.chat_requests.append(json.loads(self.rfile.read(int(self.headers["content-length"]))))
                if outer.gate is not None:
                    outer.gate.wait(10)
                words = [w + " " for w in outer.text.split(" ")]
                lines = [{"model": MODEL, "message": {"content": w}, "done": False} for w in words]
                lines.append({"model": MODEL, "message": {"content": ""}, "done": True, "done_reason": "stop",
                              "prompt_eval_count": 40, "eval_count": len(words)})
                body = "\n".join(json.dumps(x, ensure_ascii=False) for x in lines).encode()
                self.send_response(200)
                self.send_header("content-type", "application/x-ndjson")
                self.send_header("content-length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_args):
                pass

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"

    def close(self):
        self.server.shutdown()
        self.server.server_close()


class ChatServiceBase(unittest.TestCase):
    text = "Paris là thủ đô của Pháp."
    pin = True

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="hg-chat-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.home = self.tmp / "home"
        self.home.mkdir(mode=0o700)
        self.ollama = FakeOllama(self.text)
        self.addCleanup(self.ollama.close)
        self.write_config(self.ollama.url)
        saved = os.environ.pop("HG_MODEL", None)
        self.addCleanup(lambda: saved is not None and os.environ.__setitem__("HG_MODEL", saved))
        self.service = ChatService(self.home, release_id="r" * 64, clock=lambda: NOW)

    def write_config(self, url, digest=DIGEST):
        config = {"ollama_url": url, "model": MODEL, "timeout_s": 10}
        if self.pin:
            config["model_digest"] = digest
        path = self.home / "config.json"
        path.write_text(json.dumps(config), encoding="utf-8")
        path.chmod(0o600)

    def ledger(self):
        return EventLog(self.home / f"asks-{NOW:%Y-%m}.jsonl").events()


class ChatServiceTests(ChatServiceBase):
    def test_general_question_goes_through_the_local_model_and_is_labelled(self):
        result = self.service("Thủ đô của Pháp là gì?", general=True)
        self.assertEqual(result["outcome"], "ANSWERED")
        self.assertEqual(result["answer"], self.text)
        self.assertEqual([s["label"] for s in result["sentences"]], ["MODEL"])
        self.assertEqual((result["provider"], result["model"]), ("ollama", MODEL))
        self.assertEqual(result["model_check"]["status"], "READY")
        self.assertEqual(result["model_check"]["digest"], DIGEST)
        self.assertEqual(result["channel"], "http:/v1/chat")
        self.assertEqual(len(self.ollama.chat_requests), 1)
        sent = self.ollama.chat_requests[0]
        self.assertEqual((sent["model"], sent["stream"]), (MODEL, True))
        self.assertIn("Thủ đô của Pháp là gì?", sent["messages"][-1]["content"])
        # Brain evidence: one MODEL_CALL event and one ASK receipt in the owner's ledger.
        kinds = [(e["kind"], e["payload"].get("status")) for e in self.ledger()]
        self.assertEqual(kinds, [("MODEL_CALL", "OK"), ("ASK", None)])
        call = self.ledger()[0]
        self.assertEqual((call["payload"]["provider"], call["payload"]["model"]), ("ollama", MODEL))
        self.assertNotIn("Pháp", json.dumps(call["payload"], ensure_ascii=False))     # no prompt text
        self.assertEqual(result["brain"]["router"], "hg.brain.providers.ModelRouter")
        self.assertEqual(result["brain"]["model_calls"][0]["event_id"], call["event_id"])
        self.assertEqual(result["brain"]["model_calls"][0]["status"], "OK")
        self.assertEqual(result["brain"]["ledger"], f"asks-{NOW:%Y-%m}.jsonl")
        receipt = self.ledger()[1]["payload"]
        self.assertEqual((receipt["channel"], receipt["outcome"], receipt["release"]),
                         ("http:/v1/chat", "ANSWERED", "r" * 64))
        self.assertEqual(result["brain"]["receipt_event_id"], self.ledger()[1]["event_id"])

    def test_note_grounded_answer_cites_the_note(self):
        Notebook(self.home).add("Xe máy thay dầu lần cuối ngày 2026-09-15 ở mốc 18.200 km.", origin="test")
        self.ollama.text = "Bạn thay dầu xe lần cuối ngày 2026-09-15 ở mốc 18.200 km [N1]."
        result = self.service("lan cuoi thay dau xe khi nao", general=False)
        self.assertEqual(result["outcome"], "ANSWERED")
        self.assertEqual(result["sentences"][0]["label"], "NOTE")
        self.assertEqual(result["sentences"][0]["note"], "N1")
        self.assertEqual(result["notes"][0]["ref"], "N1")
        self.assertIn("18.200 km", result["notes"][0]["content"])
        self.assertEqual(result["counts"]["NOTE"], 1)

    def test_personal_question_without_notes_never_reaches_the_model(self):
        result = self.service("Lịch khám răng của tôi là khi nào?", general=True)
        self.assertEqual(result["outcome"], "NO_DATA")
        self.assertEqual(result["sentences"][0]["label"], "ABSTAIN")
        self.assertEqual(result["brain"]["model_calls"], [])
        self.assertEqual(self.ollama.chat_requests, [])

    def test_model_unavailable_degrades_honestly(self):
        Notebook(self.home).add("Họp nhóm dự án HG vào thứ Năm lúc 20 giờ qua Google Meet.", origin="test")
        self.ollama.close()
        result = self.service("họp nhóm HG lúc mấy giờ", general=False)
        self.assertEqual(result["outcome"], "MEMORY_ONLY")
        self.assertEqual(result["model_check"]["status"], "UNAVAILABLE")
        self.assertIn("20 giờ", result["notes"][0]["content"])
        self.assertNotIn("answer", {k for k, v in result.items() if v})
        result = self.service("Thủ đô của Pháp là gì?", general=True)
        self.assertEqual(result["outcome"], "NO_DATA")

    def test_paid_provider_is_never_used(self):
        os.environ["ANTHROPIC_API_KEY"] = "sk-test-not-a-real-key"
        self.addCleanup(os.environ.pop, "ANTHROPIC_API_KEY", None)
        result = self.service("Thủ đô của Pháp là gì?", general=True)
        self.assertEqual({c["provider"] for c in result["brain"]["model_calls"]}, {"ollama"})
        self.assertEqual(result["provider"], "ollama")

    def test_changed_model_digest_is_refused(self):
        self.write_config(self.ollama.url, digest="e" * 64)
        with self.assertRaises(HTTPBoundaryError) as ctx:
            self.service("Thủ đô của Pháp là gì?", general=True)
        self.assertEqual((ctx.exception.status, ctx.exception.code), (503, "model_untrusted"))
        self.assertEqual(self.ollama.chat_requests, [])

    def test_missing_home_is_unavailable_and_not_created(self):
        service = ChatService(self.tmp / "absent", release_id="r" * 64)
        with self.assertRaises(HTTPBoundaryError) as ctx:
            service("xin chào", general=True)
        self.assertEqual((ctx.exception.status, ctx.exception.code), (503, "assistant_unavailable"))
        self.assertFalse((self.tmp / "absent").exists())

    def test_shared_home_is_refused(self):
        self.home.chmod(0o755)
        self.addCleanup(self.home.chmod, 0o700)
        with self.assertRaises(HTTPBoundaryError) as ctx:
            self.service("xin chào", general=True)
        self.assertEqual(ctx.exception.code, "assistant_unavailable")

    def test_home_locked_by_another_writer_is_busy(self):
        service = ChatService(self.home, release_id="r" * 64, clock=lambda: NOW, lock_wait_s=0.2)
        with locked(self.home, exclusive=True):
            with self.assertRaises(HTTPBoundaryError) as ctx:
                service("Thủ đô của Pháp là gì?", general=True)
        self.assertEqual((ctx.exception.status, ctx.exception.code), (503, "assistant_busy"))

    def test_one_chat_at_a_time(self):
        gate = threading.Event()
        self.ollama.gate = gate
        first = {}
        worker = threading.Thread(target=lambda: first.update(r=self.service("Thủ đô của Pháp?", general=True)))
        worker.start()
        deadline = time.monotonic() + 5
        while not self.ollama.chat_requests and time.monotonic() < deadline:
            time.sleep(0.01)
        try:
            with self.assertRaises(HTTPBoundaryError) as ctx:
                self.service("Thủ đô của Đức?", general=True)
            self.assertEqual((ctx.exception.status, ctx.exception.code), (503, "chat_busy"))
        finally:
            gate.set()
            worker.join(10)
        self.assertEqual(first["r"]["outcome"], "ANSWERED")

    def test_control_characters_do_not_reach_the_answer(self):
        self.ollama.text = "Xin\x1b]52;c;ZXZpbA==\x07 chào."
        result = self.service("chào", general=True)
        texts = [result["answer"], *(s["sentence"] for s in result["sentences"]), *result["display"]]
        for text in texts:
            self.assertNotIn("\x1b", text)
            self.assertNotIn("\x07", text)


class UnpinnedModelTests(ChatServiceBase):
    pin = False

    def test_unpinned_model_is_reported_not_pinned(self):
        result = self.service("Thủ đô của Pháp là gì?", general=True)
        self.assertEqual(result["model_check"]["pinned"], False)
        self.assertEqual(result["listener"]["status"], "UNVERIFIED")


class ChatOverHTTPTests(ChatServiceBase):
    """Request -> hg serve boundary -> ChatService -> ModelRouter -> local model -> labelled answer."""

    TOKEN = b"chat-token-that-is-long-enough-for-the-boundary"

    def setUp(self):
        super().setUp()
        tasks_dir = self.tmp / "state"
        from maep.authority.canonical_source import CanonicalManifest
        from maep.tests.test_canonical_source import FakeGitHub
        from hg.runtime import build_runtime
        from hg.tests.support import Clock
        clock = Clock()
        authority = CanonicalManifest.from_github(http_get=FakeGitHub().get, max_age_s=0, clock=clock)
        runtime = build_runtime(tasks_dir, [], authority=authority, issue_task_grants=True, clock=clock)
        self.server = HGHTTPServer(runtime=runtime, token=self.TOKEN, port=0,
                                   release_report=lambda: {"result": "VERIFIED", "release_id": "r" * 64},
                                   trust_report=lambda: {"result": "LOADED"},
                                   idempotency_path=tasks_dir / "idem.sqlite3", chat=self.service)
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(lambda: (self.server.shutdown(), thread.join(2), self.server.server_close()))

    def test_chat_end_to_end_over_loopback_http(self):
        host, port = self.server.address
        conn = http.client.HTTPConnection(host, port, timeout=15)
        raw = json.dumps({"message": "Thủ đô của Pháp là gì?", "general": True}, ensure_ascii=False).encode()
        conn.request("POST", "/v1/chat", body=raw, headers={
            "Authorization": "Bearer " + self.TOKEN.decode(), "Content-Type": "application/json",
            "Content-Length": str(len(raw))})
        response = conn.getresponse()
        body = json.loads(response.read().decode("utf-8"))
        conn.close()
        self.assertEqual(response.status, 200)
        self.assertEqual((body["outcome"], body["answer"], body["provider"]), ("ANSWERED", self.text, "ollama"))
        self.assertEqual(body["brain"]["model_calls"][0]["status"], "OK")
        self.assertEqual([e["kind"] for e in self.ledger()], ["MODEL_CALL", "ASK"])


if __name__ == "__main__":
    unittest.main()


class CreateServiceWiringTests(unittest.TestCase):
    """hg serve's production factory attaches the chat route to the owner's assistant home."""

    def test_create_service_attaches_chat_service(self):
        from maep.authority.canonical_source import CanonicalManifest
        from maep.tests.test_canonical_source import FakeGitHub
        from hg.chat import ChatService
        from hg.service import create_service
        from hg.tests.support import Clock
        tmp = Path(tempfile.mkdtemp(prefix="hg-svc-chat-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        state = tmp / "state"
        state.mkdir(mode=0o700)
        config = {"host": "127.0.0.1", "port": 0, "max_body_bytes": 4096, "state_dir": str(state),
                  "release_id": "f" * 64}
        authority = CanonicalManifest.from_github(http_get=FakeGitHub().get, max_age_s=0, clock=Clock())
        server = create_service(config, token=b"t" * 40, authority=authority,
                                release_report=lambda: {"result": "VERIFIED"}, assistant_home=tmp / "assistant")
        self.addCleanup(server.server_close)
        self.assertIsInstance(server.chat, ChatService)
        self.assertEqual((server.chat.home, server.chat.release_id), (tmp / "assistant", "f" * 64))
        self.assertEqual(set(server.ui_assets), {"/ui/", "/ui/index.html", "/ui/app.js", "/ui/styles.css"})
        self.assertFalse((tmp / "assistant").exists())       # never created by the service
