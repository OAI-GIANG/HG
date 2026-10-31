"""deploy/termux/ollama_bench.py against a local fake Ollama that streams NDJSON with known timing."""
import importlib.util
import json
import shutil
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

BENCH = Path(__file__).resolve().parents[2] / "deploy" / "termux" / "ollama_bench.py"
spec = importlib.util.spec_from_file_location("ollama_bench", BENCH)
bench = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bench)

DIGEST = "8f68893c685c3ddff2aa3fffce2aa60a30bb2da65ca488b61fff134a4d1730e7"


class FakeOllama(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _json(self, doc):
        body = json.dumps(doc).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/api/version":
            self._json({"version": "0.40.13"})
        elif self.path == "/api/tags":
            self._json({"models": [{"name": "qwen3:1.7b", "digest": DIGEST, "size": 1}]})
        elif self.path == "/api/ps":
            self._json({"models": [{"name": "qwen3:1.7b"}] if self.server.loaded else []})

    def do_POST(self):
        request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.server.requests.append(request)
        chat = self.path == "/api/chat"
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.end_headers()

        def emit(doc, delay):
            time.sleep(delay)
            self.wfile.write((json.dumps(doc) + "\n").encode())
            self.wfile.flush()

        part = (lambda c, t="": {"message": {"role": "assistant", "content": c, "thinking": t}, "done": False}) \
            if chat else (lambda c, t="": {"response": c, "thinking": t, "done": False})
        emit(part("", "đang nghĩ"), 0.05)            # thinking only: not TTFT
        emit(part(""), 0.05)                         # empty chunk
        emit(part("Bầu"), 0.20)                      # first generated text at ~0.30 s
        emit(part(" trời"), 0.05)
        emit({**part(""), "done": True, "done_reason": "stop", "eval_count": 50, "eval_duration": 2_500_000_000,
              "prompt_eval_count": 20, "prompt_eval_duration": 400_000_000, "load_duration": 3_000_000_000,
              "total_duration": 9_000_000_000}, 0.05)
        self.server.loaded = True


class BenchTests(unittest.TestCase):
    def setUp(self):
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), FakeOllama)
        self.server.requests, self.server.loaded = [], False
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.tmp = Path(tempfile.mkdtemp(prefix="hg-bench-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_raw_capture_ttft_and_tps_formula(self):
        out = self.tmp / "run"
        code = bench.main(["--out", str(out), "--url", f"http://127.0.0.1:{self.server.server_port}", "--runs", "1"])
        self.assertEqual(code, 0)
        report = json.loads((out / "report.json").read_text(encoding="utf-8"))
        self.assertEqual((report["version"], report["model_digest"]), ({"version": "0.40.13"}, DIGEST))
        chat, gen = report["runs"]
        for run in (chat, gen):
            self.assertEqual(run["generation_tps"], 20.0)        # 50 / 2.5 s, not 50 / total_duration
            self.assertEqual(run["prompt_tps"], 50.0)
            self.assertNotEqual(run["generation_tps"], 50 / 9.0)
            self.assertGreaterEqual(run["ttft_s"], 0.28)        # thinking and empty chunks do not count
            self.assertLess(run["first_thinking_s"], run["ttft_s"])
            self.assertLess(run["ttfb_s"], run["ttft_s"])
            self.assertEqual((run["chunks"], run["empty_chunks"]), (5, 1))
            raw = (out / run["raw_file"]).read_bytes()
            self.assertEqual(len(raw.splitlines()), 5)
            self.assertEqual(bench.hashlib.sha256(raw).hexdigest(), run["raw_sha256"])
        self.assertEqual((chat["start"], gen["start"]), ("cold", "warm"))
        self.assertEqual(self.server.requests[0]["options"], {"num_thread": 4, "num_ctx": 4096})
        self.assertIs(self.server.requests[0]["think"], False)

    def test_non_loopback_or_named_host_refused(self):
        for url in ("http://localhost:11434", "http://10.0.0.2:11434", "https://127.0.0.1:11434",
                    "http://u:p@127.0.0.1:11434"):
            with self.assertRaises(SystemExit):
                bench.loopback(url)

    def test_missing_final_chunk_gives_null_tps(self):
        class Truncated(FakeOllama):
            def do_POST(self):
                self.rfile.read(int(self.headers["Content-Length"]))
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'{"message":{"content":"x"},"done":false}\n')

        server = ThreadingHTTPServer(("127.0.0.1", 0), Truncated)
        server.requests, server.loaded = [], True
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        code = bench.main(["--out", str(self.tmp / "t"), "--url", f"http://127.0.0.1:{server.server_port}",
                           "--runs", "1", "--endpoint", "chat"])
        report = json.loads((self.tmp / "t" / "report.json").read_text(encoding="utf-8"))
        self.assertEqual(code, 1)
        self.assertIsNone(report["runs"][0]["generation_tps"])


if __name__ == "__main__":
    unittest.main()
