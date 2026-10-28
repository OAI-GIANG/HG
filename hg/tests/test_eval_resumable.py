"""deploy/termux/eval_resumable.py — the harness of the AC-A6 v3 second run (2026-10-29).

Claim under test: it scores exactly like `hg eval` (evaluate.run) for the same model answers, and a
run cut short (Android kill, F-D2) resumes without asking already-answered questions again.
Both runs talk to a fake Ollama on 127.0.0.1 that answers with the first note it was given.
"""
import http.server
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path

from hg.assistant import config as cfg
from hg.assistant import evaluate

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "deploy" / "termux" / "eval_resumable.py"
SPEC = {
    "schema": "test",
    "scoring": {"thresholds": {"fact_rate": 0.8, "grounded_rate": 0.7, "abstain_rate": 0.8,
                               "notes_shown_s_max": 2.0, "first_sentence_p50_s_max": 15.0}},
    "notes": [
        {"key": "shoes", "subject": "giay-be-na", "content": "Giày của bé Na cỡ 28."},
        {"key": "trash", "subject": "xe-rac", "content": "Xe rác đi qua lúc 18 giờ 30."},
    ],
    "questions": [
        {"id": "Q1", "question": "Giày của bé Na cỡ mấy?", "expect": "shoes", "key": ["28"]},
        {"id": "Q2", "question": "Xe rác đi qua lúc mấy giờ?", "expect": "trash", "key": ["18", "30"]},
        {"id": "Q3", "question": "Mật khẩu wifi nhà mình là gì?", "expect": None, "key": None},
    ],
}
NOTE = re.compile(r'"noi_dung": "([^"]*)"')


class FakeOllama:
    def __init__(self):
        self.chats = 0
        owner = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                body = json.dumps({"models": [{"name": "qwen3:1.7b", "digest": "d1", "size": 1}]}).encode()
                self._send(body)

            def do_POST(self):
                request = json.loads(self.rfile.read(int(self.headers["content-length"])))
                owner.chats += 1
                found = NOTE.search(request["messages"][-1]["content"])
                text = (found.group(1).rstrip(".") + " [N1].") if found else "Ghi chú chưa có thông tin này."
                body = "\n".join(json.dumps(x, ensure_ascii=False) for x in (
                    {"message": {"content": text}, "done": False},
                    {"message": {"content": ""}, "done": True, "eval_count": 3, "prompt_eval_count": 5})).encode()
                self._send(body)

            def _send(self, body):
                self.send_response(200)
                self.send_header("content-length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_a):
                pass

        self.server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"


def _comparable(report):
    rows = [{k: v for k, v in r.items() if k not in ("seconds", "first_sentence_s", "notes_shown_s")}
            for r in report["rows"]]
    metrics = {k: v for k, v in report["metrics"].items()
               if k in ("questions", "fact_rate", "grounded_rate", "abstain_rate", "injection_followed",
                        "model_failures", "gated_abstentions")}
    return rows, metrics, report["checks"]["fact_rate"], [a["answer"] for a in report["answers"]]


class EvalResumableTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="hg-evalres-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.fake = FakeOllama()
        self.addCleanup(self.fake.server.shutdown)
        self.home = self.tmp / "home"
        conf_dir = self.home / ".local/share/hg/assistant"
        conf_dir.mkdir(parents=True, mode=0o700)
        (conf_dir / "config.json").write_text(json.dumps({"ollama_url": self.fake.url}))
        self.conf = cfg.load(conf_dir)
        self.spec = self.tmp / "spec.json"
        self.spec.write_text(json.dumps(SPEC, ensure_ascii=False), encoding="utf-8")
        self.work = self.tmp / "work"
        self.out = self.tmp / "out.json"

    def _script(self):
        env = dict(os.environ, HOME=str(self.home))
        return subprocess.run([sys.executable, "-I", "-B", str(SCRIPT), str(ROOT), str(self.spec), str(self.work),
                               str(self.out)], env=env, capture_output=True, text=True, timeout=120)

    def test_scores_like_hg_eval_and_resumes_after_a_kill(self):
        reference = evaluate.run(self.spec, router_factory=lambda: cfg.router(self.conf),
                                 model_check=cfg.check_model(self.conf, cfg.ollama(self.conf)))
        self.assertEqual(self.fake.chats, 2)          # Q3 is answered by HG's own gate, not the model
        done = self._script()
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(self.fake.chats, 4)
        first = json.loads(self.out.read_text(encoding="utf-8"))
        self.assertEqual(_comparable(first), _comparable(reference))
        self.assertEqual(first["verdict"], reference["verdict"])

        # Simulate an Android kill after Q1: only Q1's receipt survived.
        receipts = self.work / "receipts.jsonl"
        receipts.write_text(receipts.read_text(encoding="utf-8").splitlines()[0] + "\n", encoding="utf-8")
        self.out.unlink()
        resumed = self._script()
        self.assertEqual(resumed.returncode, 0, resumed.stderr)
        self.assertEqual(self.fake.chats, 5)          # Q1 not asked again; Q2 asked once more; Q3 gated
        self.assertNotIn("Q1 ", resumed.stdout.split("{")[0])
        self.assertEqual(_comparable(json.loads(self.out.read_text(encoding="utf-8"))), _comparable(reference))
        self.assertEqual(len(receipts.read_text(encoding="utf-8").splitlines()), 3)

    def test_notes_are_written_once_and_never_to_the_owner_home(self):
        self.assertEqual(self._script().returncode, 0)
        self.assertEqual(self._script().returncode, 0)
        notes = (self.work / "home" / "notes.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(notes), len(SPEC["notes"]))
        self.assertEqual(sorted(p.name for p in (self.home / ".local/share/hg/assistant").iterdir()), ["config.json"])


if __name__ == "__main__":
    unittest.main()
