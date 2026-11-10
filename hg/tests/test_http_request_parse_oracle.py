"""WS-04 false-accept oracle: ambiguous HTTP requests never reach the runtime.

Each case sends exact bytes to a real HGHTTPServer and asserts that a request whose target,
framing or body encoding can be read in more than one way is refused (not 200) within 5 s,
and that no effect happened: the planned file is absent and the idempotency key was never
claimed. Controls show the canonical form of each request is still accepted.
"""
import json
import socket
import sqlite3
import threading
import time

from maep.authority.canonical_source import CanonicalManifest
from maep.tests.test_canonical_source import FakeGitHub
from hg.http_api import HGHTTPServer, planned_write_readback_verifier
from hg.runtime import build_runtime
from hg.tests.support import TempDirMixin, make_task, write_step

TOKEN = b"test-token-that-is-long-enough-for-the-boundary"
DEADLINE_S = 5.0


class HTTPRequestParseOracle(TempDirMixin):
    def setUp(self):
        super().setUp()
        gh = FakeGitHub()
        authority = CanonicalManifest.from_github(http_get=gh.get, max_age_s=0, clock=self.clock)
        self.runtime = build_runtime(self.workdir, [], authority=authority, issue_task_grants=True,
                                     clock=self.clock,
                                     verifiers={"AC-READBACK": planned_write_readback_verifier(self.root)})
        self.idem_path = self.workdir / "http-idempotency.sqlite3"
        self.server = HGHTTPServer(
            runtime=self.runtime, token=TOKEN, host="127.0.0.1", port=0, max_body_bytes=4096,
            release_report=lambda: {"result": "VERIFIED", "release_id": "a" * 64},
            trust_report=lambda: {"result": "LOADED", "provenance": {"commit": "b" * 40}},
            idempotency_path=self.idem_path, request_timeout_seconds=2, request_deadline_seconds=4,
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.server.address[1]

    def tearDown(self):
        self.server.shutdown()
        self.thread.join(timeout=2)
        self.server.server_close()
        super().tearDown()

    def body(self, content="xin chao", tag="1"):
        task = make_task(task_id=f"HTTP-ORACLE-{tag}")
        task["acceptance_criteria"] = [{
            "criterion_id": "AC-READBACK", "description": "write content can be read back exactly",
            "mandatory": True, "evidence_types": ["TEST_RESULT"],
        }]
        payload = {"task": task, "steps": [write_step(authorization_id=f"HTTP-ORACLE-A-{tag}", content=content)]}
        return json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")

    def send(self, method, target, headers, body=b""):
        lines = [f"{method} {target} HTTP/1.1"]
        lines += [f"{name}: {value}" for name, value in headers]
        raw = ("\r\n".join(lines) + "\r\n\r\n").encode("latin-1") + body
        started = time.monotonic()
        with socket.create_connection(("127.0.0.1", self.port), timeout=DEADLINE_S) as sock:
            sock.sendall(raw)
            chunks = []
            while True:
                chunk = sock.recv(65536)
                if not chunk:
                    break
                chunks.append(chunk)
        elapsed = time.monotonic() - started
        response = b"".join(chunks)
        status = int(response.split(b" ", 2)[1]) if response.startswith(b"HTTP/") else None
        return status, elapsed

    def base_headers(self, body, *, key, content_type="application/json"):
        return [("Host", f"127.0.0.1:{self.port}"), ("Authorization", "Bearer " + TOKEN.decode()),
                ("Content-Type", content_type), ("Content-Length", str(len(body))),
                ("Idempotency-Key", key)]

    def claimed_keys(self):
        if not self.idem_path.exists():
            return set()
        with sqlite3.connect(f"file:{self.idem_path}?mode=ro", uri=True) as db:
            return {row[0] for row in db.execute("SELECT idem_key FROM requests")}

    def assert_refused_without_effect(self, method, target, headers, body, key):
        written = self.root / "out/hello.txt"
        if written.exists():          # left by an earlier accepted case; each case starts clean
            written.unlink()
        status, elapsed = self.send(method, target, headers, body)
        self.assertLess(elapsed, DEADLINE_S)
        self.assertNotEqual(status, 200)
        self.assertFalse((self.root / "out/hello.txt").exists())
        self.assertNotIn(key, self.claimed_keys())

    # --- request target: only the origin-form path is the route ---------------------------

    def test_non_origin_form_targets_are_refused(self):
        body = self.body()
        targets = [
            "http://attacker.example/v1/tasks",          # absolute-form naming another authority
            f"http://127.0.0.1:{self.port}/v1/tasks",    # absolute-form (proxy form) for this listener
            "//attacker.example/v1/tasks",               # network-path reference parsed as authority
            "x:/v1/tasks",                               # scheme prefix dropped by urlsplit
            "/v1/tasks?",                                # empty query
            "/v1/tasks#",                                # empty fragment
        ]
        for n, target in enumerate(targets):
            with self.subTest(target=target):
                key = f"target-{n}"
                body = self.body(tag=key)
                self.assert_refused_without_effect("POST", target, self.base_headers(body, key=key), body, key)

    def test_non_origin_form_get_targets_are_refused(self):
        for target in ("http://attacker.example/v1/health/live", "//attacker.example/v1/health/live",
                       "/v1/health/live?", "/v1/health/live#"):
            with self.subTest(target=target):
                status, elapsed = self.send("GET", target, [("Host", f"127.0.0.1:{self.port}"),
                                                            ("Authorization", "Bearer " + TOKEN.decode())])
                self.assertLess(elapsed, DEADLINE_S)
                self.assertNotEqual(status, 200)

    # --- framing: Content-Length is the only framing ------------------------------------

    def test_any_transfer_encoding_header_is_refused(self):
        body = self.body()
        variants = [[("Transfer-Encoding", "")],
                    [("Transfer-Encoding", ""), ("Transfer-Encoding", "chunked")],
                    [("Transfer-Encoding", "identity")]]
        for n, extra in enumerate(variants):
            with self.subTest(extra=extra):
                key = f"te-{n}"
                body = self.body(tag=key)
                self.assert_refused_without_effect("POST", "/v1/tasks",
                                                   self.base_headers(body, key=key) + extra, body, key)

    # --- body encoding: the body is read as UTF-8, so no other charset may be declared ----

    def test_declared_non_utf8_charset_is_refused(self):
        # These bytes are valid UTF-8 ("é") and valid Latin-1 ("Ã©"): the declared charset
        # and the decoding the server applies would give two different task contents.
        body = self.body(content="é")
        for n, ctype in enumerate(("application/json; charset=latin-1", "application/json; charset=iso-8859-1",
                                   "application/json; charset=utf-16", "application/json; charset=utf-8; charset=latin-1",
                                   "application/json; charset=\"latin-1\"")):
            with self.subTest(content_type=ctype):
                key = f"charset-{n}"
                body = self.body(content="é", tag=key)
                self.assert_refused_without_effect("POST", "/v1/tasks",
                                                   self.base_headers(body, key=key, content_type=ctype), body, key)

    # --- controls -------------------------------------------------------------------------

    def test_control_origin_form_utf8_request_is_accepted(self):
        for n, ctype in enumerate(("application/json", "application/json; charset=utf-8",
                                   "Application/JSON; Charset=UTF-8")):
            with self.subTest(content_type=ctype):
                target = self.root / "out/hello.txt"
                if target.exists():
                    target.unlink()
                body = self.body(content=f"é {n}", tag=f"C{n}")
                key = f"control-{n}"
                status, _ = self.send("POST", "/v1/tasks", self.base_headers(body, key=key, content_type=ctype), body)
                self.assertEqual(status, 200)
                self.assertEqual(target.read_text(encoding="utf-8"), f"é {n}")
                self.assertIn(key, self.claimed_keys())

    def test_control_get_origin_form_is_accepted(self):
        status, _ = self.send("GET", "/v1/health/live", [("Host", f"127.0.0.1:{self.port}"),
                                                          ("Authorization", "Bearer " + TOKEN.decode())])
        self.assertEqual(status, 200)


if __name__ == "__main__":
    import unittest
    unittest.main()
