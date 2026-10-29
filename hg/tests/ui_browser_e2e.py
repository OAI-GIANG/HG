"""Real-browser end-to-end check of the web UI (manual tool; not collected by unittest discovery).

usage: python -m hg.tests.ui_browser_e2e OUT_DIR

Starts HGHTTPServer on a loopback port with the real ChatService over a temporary assistant home
and a fake Ollama server over real HTTP (so OllamaProvider, ModelRouter, grounding and receipts all
run), then drives headless Chromium with Playwright:
  1. opens http://127.0.0.1:<port>/ui/ (no token: the page itself loads; CSP is enforced by the browser)
  2. without a token, Chat refuses to send and asks for the token
  3. a wrong token -> the UI shows 401 honestly
  4. the right token -> health READY
  5. sends one general question and one note question with the Send button; waits for the answers
     rendered from POST /v1/chat; checks labels [?] and [N1·dd/mm]
  6. Enter in the composer inserts a newline and sends nothing
  7. no console errors, no CSP violations, every request went to the page's own origin
The page's CSP forbids eval, so the checks use Playwright locators only (no page.evaluate /
wait_for_function with strings: Chromium itself refuses those under script-src 'self').
Writes OUT_DIR/ui-e2e-report.json and screenshots. Exit 0 only if every check passed.
Requires: pip install playwright, and a Chromium for it (PLAYWRIGHT_BROWSERS_PATH).
"""
import json
import shutil
import sys
import tempfile
import threading
from pathlib import Path


def main(out_dir):
    from playwright.sync_api import sync_playwright

    from maep.authority.canonical_source import CanonicalManifest
    from maep.tests.test_canonical_source import FakeGitHub
    from hg.assistant.notes import Notebook
    from hg.chat import ChatService
    from hg.http_api import HGHTTPServer
    from hg.runtime import build_runtime
    from hg.tests.support import Clock
    from hg.tests.test_chat_service import DIGEST, MODEL, FakeOllama

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix="hg-ui-e2e-"))
    token = "ui-e2e-token-" + "x" * 40
    report = {"checks": {}, "requests": [], "console": [], "csp_violations": []}

    def check(name, ok, detail=""):
        report["checks"][name] = {"ok": bool(ok), "detail": detail}

    home = tmp / "home"
    home.mkdir(mode=0o700)
    ollama = FakeOllama("Paris là thủ đô của Pháp.")
    (home / "config.json").write_text(json.dumps({"ollama_url": ollama.url, "model": MODEL,
                                                  "model_digest": DIGEST, "timeout_s": 10}), encoding="utf-8")
    (home / "config.json").chmod(0o600)
    Notebook(home).add("Xe máy thay dầu lần cuối ngày 2026-09-15 ở mốc 18.200 km.", origin="test")
    clock = Clock()
    authority = CanonicalManifest.from_github(http_get=FakeGitHub().get, max_age_s=0, clock=clock)
    runtime = build_runtime(tmp / "state", [], authority=authority, issue_task_grants=True, clock=clock)
    server = HGHTTPServer(runtime=runtime, token=token.encode(), port=0,
                          release_report=lambda: {"result": "VERIFIED", "release_id": "e" * 64},
                          trust_report=lambda: {"result": "LOADED", "provenance": {"commit": "c" * 40}},
                          idempotency_path=tmp / "state" / "idem.sqlite3",
                          chat=ChatService(home, release_id="e" * 64))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    origin = f"http://127.0.0.1:{server.address[1]}"
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page(viewport={"width": 412, "height": 915})   # phone-sized
            page.on("console", lambda m: report["console"].append({"type": m.type, "text": m.text}))
            page.on("request", lambda r: report["requests"].append({"method": r.method, "url": r.url}))
            page.goto(origin + "/ui/")
            check("page_loads_without_token", page.title().startswith("HG"), page.title())

            page.click("#bottom-nav [data-root-nav=chat]")
            page.fill("#chat-input", "Thủ đô của Pháp là gì?")
            page.click("#chat-send-btn")
            check("no_token_refuses_to_send", page.locator("#screen-settings.active").count() == 1
                  and "token" in page.inner_text("#global-toast").lower())

            page.fill("#token-input", "wrong-token-" + "y" * 40)
            page.click("#btn-save-token")
            page.locator("#token-status", has_text="401").wait_for()   # locators: no eval, CSP stays strict
            check("wrong_token_shows_401", "401" in page.inner_text("#token-status"), page.inner_text("#token-status"))

            page.fill("#token-input", token)
            page.click("#btn-save-token")
            page.locator("#service-badge", has_text="SẴN SÀNG").wait_for()
            check("right_token_health_ready", page.inner_text("#service-badge") == "SẴN SÀNG",
                  page.inner_text("#token-status"))
            check("stale_warning_cleared_after_connect", page.locator("#global-toast").is_hidden())
            page.screenshot(path=str(out / "ui-1-connected.png"), full_page=True)

            page.click("#back-btn")                                   # settings -> chat (navigation stack)
            check("back_returns_to_chat", page.locator("#screen-chat.active").count() == 1)
            page.fill("#chat-input", "Thủ đô của Pháp là gì?")
            page.press("#chat-input", "Enter")
            check("enter_does_not_send", page.locator(".msg").count() == 0 and "\n" in page.input_value("#chat-input"))
            page.fill("#chat-input", "Thủ đô của Pháp là gì?")
            page.click("#chat-send-btn")
            page.wait_for_selector(".msg[data-outcome]", timeout=20000)
            first = page.locator(".msg[data-outcome]").nth(0)
            check("general_answer_rendered",
                  first.get_attribute("data-outcome") == "ANSWERED"
                  and "Paris là thủ đô của Pháp." in first.inner_text() and "[?]" in first.inner_text(),
                  first.inner_text())

            ollama.text = "Bạn thay dầu xe lần cuối ngày 2026-09-15 ở mốc 18.200 km [N1]."
            page.uncheck("#chat-general")
            page.fill("#chat-input", "lan cuoi thay dau xe khi nao")
            page.click("#chat-send-btn")
            page.locator(".msg[data-outcome]").nth(1).wait_for(timeout=20000)
            second = page.locator(".msg[data-outcome]").nth(1)
            text = second.inner_text()
            label = second.locator(".sentence").first.get_attribute("data-label")
            check("note_answer_labelled_NOTE", label == "NOTE" and "[N1·" in text and "18.200 km" in text, text)
            page.screenshot(path=str(out / "ui-2-chat.png"), full_page=True)

            check("all_requests_same_origin", all(r["url"].startswith(origin + "/") for r in report["requests"]),
                  sorted({r["url"].split("/")[2] for r in report["requests"]}))
            chat_posts = [r for r in report["requests"] if r["method"] == "POST" and r["url"] == origin + "/v1/chat"]
            check("chat_posts_reached_v1_chat", len(chat_posts) == 2, len(chat_posts))
            check("model_called_twice", len(ollama.chat_requests) == 2, len(ollama.chat_requests))
            errors = [m for m in report["console"] if m["type"] == "error"]
            # The deliberate wrong-token probe logs one 401 resource error in Chromium; anything else fails.
            unexpected = [m for m in errors if "401" not in m["text"]]
            check("no_unexpected_console_errors", not unexpected, unexpected)
            check("no_csp_violations", not any("Content Security Policy" in m["text"] for m in report["console"]))
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
        ollama.close()
        shutil.rmtree(tmp, ignore_errors=True)
    report["result"] = "PASS" if all(c["ok"] for c in report["checks"].values()) else "FAIL"
    (out / "ui-e2e-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"result": report["result"], "checks": {k: v["ok"] for k, v in report["checks"].items()}},
                     ensure_ascii=False))
    return 0 if report["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else "ui-e2e-out"))
