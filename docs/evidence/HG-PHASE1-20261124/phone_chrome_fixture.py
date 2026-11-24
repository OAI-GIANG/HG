"""One-shot synthetic fixture for a real Chrome Android browser."""
import hashlib
import json
import os
import secrets
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

from hg.assistant.notes import Notebook
from hg.chat import ChatService
from hg.http_api import HGHTTPServer
from hg.runtime import build_runtime
from hg.tests.support import Clock
from hg.tests.test_chat_service import DIGEST, MODEL, FakeOllama
from maep.authority.canonical_source import CanonicalManifest
from maep.tests.test_canonical_source import FakeGitHub

PIN = "40254e60802bc59e40cd739d6ae4081241af4acd"
PORT = 18870
TOKEN = secrets.token_hex(24)
RECEIVED = threading.Event()
RESULT = {}
VISITS = []


class Fixture(HGHTTPServer):
    def _handler_type(self):
        base = super()._handler_type()

        class Handler(base):
            def do_GET(self):
                if self.path in {"/ui/", "/ui/phase1-harness.js"}:
                    VISITS.append((self.path, self.headers.get("User-Agent", "")[:250]))
                return super().do_GET()

            def do_POST(self):
                if self.path != "/ui/phase1-result":
                    return super().do_POST()
                agent = self.headers.get("User-Agent", "")
                if self.client_address[0] != "127.0.0.1" or self.headers.get("Authorization") != "Bearer " + TOKEN:
                    self._send(403, {"error": "fixture_only"})
                    return
                length = int(self.headers.get("Content-Length", 0))
                if not 0 < length <= 8192:
                    self._send(400, {"error": "invalid_report"})
                    return
                RESULT.update(json.loads(self.rfile.read(length)), user_agent=agent)
                self._send(200, {"received": True})
                RECEIVED.set()

        return Handler


def main(js_file, report_file):
    assert subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip() == PIN
    with tempfile.TemporaryDirectory(prefix="hg-android-chrome-fixture-") as tmp:
        root = Path(tmp)
        notes = root / "notes"
        notes.mkdir(mode=0o700)
        model = FakeOllama("Bạn thay dầu xe lần cuối ngày 2026-09-15 ở mốc 18.200 km [N1].")
        cfg = notes / "config.json"
        cfg.write_text(json.dumps({"ollama_url": model.url, "model": MODEL, "model_digest": DIGEST,
                                   "timeout_s": 10}))
        cfg.chmod(0o600)
        Notebook(notes).add("Xe máy thay dầu lần cuối ngày 2026-09-15 ở mốc 18.200 km.", origin="test")
        clock = Clock()
        trust = CanonicalManifest.from_github(http_get=FakeGitHub().get, max_age_s=0, clock=clock)
        runtime = build_runtime(root / "state", [], authority=trust, issue_task_grants=True, clock=clock)
        server = Fixture(runtime=runtime, token=TOKEN.encode(), port=PORT,
                         release_report=lambda: {"result": "VERIFIED", "release_id": "e" * 64},
                         trust_report=lambda: {"result": "LOADED", "provenance": {"commit": "c" * 40}},
                         idempotency_path=root / "state/idem.sqlite3", notes_home=notes,
                         chat=ChatService(notes, release_id="e" * 64))
        assets = server.ui_assets
        hashes = {path: hashlib.sha256(assets[path][0]).hexdigest()
                  for path in ("/ui/", "/ui/app.js", "/ui/styles.css")}
        page, kind = assets["/ui/"]
        assert page.count(b"</body>") == 1
        assets["/ui/"] = (page.replace(b"</body>", b'<script src="phase1-harness.js"></script></body>'), kind)
        harness = Path(js_file).read_text().replace("__FIXTURE_TOKEN__", TOKEN)
        assets["/ui/phase1-harness.js"] = (harness.encode(), "application/javascript; charset=utf-8")
        threading.Thread(target=server.serve_forever, daemon=True).start()
        launch = None
        try:
            manual = os.environ.get("HG_MANUAL_CHROME") == "1"
            if manual:
                print(f"CHROME_FIXTURE_READY http://127.0.0.1:{PORT}/ui/ (180 s)", flush=True)
            else:
                launch = subprocess.run(["am", "start", "-W", "-a", "android.intent.action.VIEW",
                                         "-d", f"http://127.0.0.1:{PORT}/ui/", "-p", "com.android.chrome"],
                                        capture_output=True, text=True, timeout=20)
                print("ANDROID_INTENT", launch.returncode, launch.stdout[:3000], launch.stderr[:3000], flush=True)
            RECEIVED.wait(180 if manual else 60)
        finally:
            server.shutdown()
            server.server_close()
            model.close()
        required = {"android_chrome", "connected", "note_label", "multiline_submitted", "text_selectable",
                    "failure_visible", "no_url_token", "no_csp_violation", "usable_viewport"}
        results = RESULT.get("checks", {})
        passed = set(results) == required and all(v is True for v in results.values())
        passed = passed and len(model.chat_requests) == 1
        summary = {"candidate": PIN, "asset_sha256": hashes, "exact_js_and_css": True,
                   "added_to_html": "same-origin synthetic test script", "real_model_used": False,
                   "intent_exit": launch.returncode if launch is not None else None,
                   "browser_result": RESULT or None, "model_calls": len(model.chat_requests), "visits": VISITS,
                   "verdict": "PASS" if passed else "BLOCKED" if not RESULT else "FAIL"}
        Path(report_file).write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
        print(json.dumps(summary, ensure_ascii=False))
        return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main(*sys.argv[1:]))
