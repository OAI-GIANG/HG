"""hg serve: total request-read deadline and connection cap (raw-socket tests).

The 5 s socket timeout bounds silence only. A client that sends a byte just before each
timeout could keep a connection (and, with block_on_close, server shutdown) waiting.
Measured on runtime.service (same transport pattern): 4 bytes at 4 s intervals -> 17.03 s.
"""
import json
import socket
import threading
import time
import unittest

from hg.http_api import HGHTTPServer
from hg.tests import test_http_api as http_api_tests

TOKEN = http_api_tests.TOKEN

READ_TIMEOUT, DEADLINE, DRIP = 0.6, 1.2, 0.3


class _Base(http_api_tests.HTTPAPITests):
    """Reuse the HTTP API fixture (real runtime, fake GitHub trust); swap in a test server."""
    server_kwargs = {"request_timeout_seconds": READ_TIMEOUT, "request_deadline_seconds": DEADLINE}

    def setUp(self):
        super().setUp()
        self.server.shutdown()
        self.thread.join(timeout=2)
        self.server.server_close()
        self.server = HGHTTPServer(
            runtime=self.runtime, token=TOKEN, host="127.0.0.1", port=0, max_body_bytes=2048,
            release_report=lambda: {"result": "VERIFIED", "release_id": "a" * 64},
            trust_report=lambda: {"result": "LOADED", "provenance": {"commit": "b" * 40}},
            idempotency_path=self.workdir / "deadline-idempotency.sqlite3", **self.server_kwargs)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.host, self.port = self.server.address

    def connect(self):
        client = socket.create_connection((self.host, self.port), timeout=10)
        self.addCleanup(client.close)
        return client

    @staticmethod
    def drain(client):
        data = b""
        while True:
            try:
                chunk = client.recv(4096)
            except (ConnectionResetError, BrokenPipeError):
                break
            if not chunk:
                break
            data += chunk
        return data

    @staticmethod
    def drip(client, payload):
        for byte in payload:
            try:
                client.sendall(bytes([byte]))
            except OSError:
                return
            time.sleep(DRIP)

    def head(self, length, path="/v1/tasks"):
        return ("POST %s HTTP/1.1\r\nHost: 127.0.0.1:%d\r\nAuthorization: Bearer %s\r\n"
                "Idempotency-Key: deadline-1\r\nContent-Type: application/json\r\n"
                "Content-Length: %d\r\n\r\n" % (path, self.port, TOKEN.decode(), length)).encode()


# Do not re-run the inherited HTTP API tests from this module.
for _name in [n for n in dir(http_api_tests.HTTPAPITests) if n.startswith("test_")]:
    setattr(_Base, _name, None)


class RequestDeadlineTests(_Base):
    def test_slow_drip_body_is_cut_at_the_total_deadline(self):
        body = json.dumps(self.payload(content="x" * 40)).encode()
        client = self.connect()
        client.sendall(self.head(len(body)))
        started = time.monotonic()
        threading.Thread(target=self.drip, args=(client, body), daemon=True).start()
        response = self.drain(client)
        self.assertLess(time.monotonic() - started, DEADLINE + READ_TIMEOUT + 1.0)
        self.assertIn(b" 408 ", response.split(b"\r\n", 1)[0])
        self.assertIn(b"request_deadline_exceeded", response)
        self.assertFalse((self.root / "out").exists() and any((self.root / "out").iterdir()))

    def test_slow_drip_headers_without_token_are_cut(self):
        client = self.connect()
        started = time.monotonic()
        threading.Thread(target=self.drip, args=(client, b"GET /v1/health/live HTTP/1.1\r\nX-Pad: "
                                                 + b"p" * 40 + b"\r\n\r\n"), daemon=True).start()
        self.assertEqual(self.drain(client), b"")
        self.assertLess(time.monotonic() - started, DEADLINE + READ_TIMEOUT + 1.0)

    def test_silent_body_gets_408_not_500(self):
        client = self.connect()
        client.sendall(self.head(50) + b'{"task"')
        response = self.drain(client)
        self.assertIn(b" 408 ", response.split(b"\r\n", 1)[0])
        self.assertIn(b"request_timeout", response)

    def test_shutdown_is_not_held_open_by_a_dripping_client(self):
        client = self.connect()
        threading.Thread(target=self.drip, args=(client, b"GET /v1/health/live HTTP/1.1\r\n" * 5),
                         daemon=True).start()
        time.sleep(0.2)
        started = time.monotonic()
        self.server.shutdown()
        self.thread.join(timeout=10)
        self.server.server_close()               # block_on_close joins handler threads
        self.assertLess(time.monotonic() - started, DEADLINE + READ_TIMEOUT + 1.0)
        self.server = HGHTTPServer(runtime=self.runtime, token=TOKEN, host="127.0.0.1", port=0,
                                   idempotency_path=self.workdir / "after.sqlite3")
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def test_prompt_request_still_works(self):
        status, body = self.request("GET", "/v1/health/live")
        self.assertEqual((status, body["status"]), (200, "LIVE"))

    def test_configuration_is_bounded(self):
        for kwargs, code in (({"request_deadline_seconds": 0.1}, "request_deadline_seconds"),
                             ({"request_deadline_seconds": 121}, "request_deadline_seconds"),
                             ({"request_timeout_seconds": 0}, "request_timeout_seconds"),
                             ({"request_timeout_seconds": True}, "request_timeout_seconds"),
                             ({"max_connections": 0}, "max_connections"),
                             ({"max_connections": 257}, "max_connections")):
            with self.assertRaisesRegex(ValueError, code):
                HGHTTPServer(runtime=self.runtime, token=TOKEN, host="127.0.0.1", port=0, **kwargs)


class ConnectionCapTests(_Base):
    server_kwargs = {"request_timeout_seconds": 1.0, "request_deadline_seconds": 1.5, "max_connections": 2}

    def test_connections_beyond_the_cap_get_503_then_slots_free(self):
        held = [self.connect(), self.connect()]
        for client in held:
            client.sendall(b"GET /v1/health/live HTTP/1.1\r\n")
        time.sleep(0.2)
        refused = self.connect()
        refused.sendall(b"GET /v1/health/live HTTP/1.1\r\n\r\n")
        response = self.drain(refused)
        self.assertIn(b" 503 ", response.split(b"\r\n", 1)[0])
        self.assertIn(b"server_busy", response)
        for client in held:
            self.drain(client)
        time.sleep(0.2)
        status, body = self.request("GET", "/v1/health/live")
        self.assertEqual((status, body["status"]), (200, "LIVE"))


if __name__ == "__main__":
    unittest.main()
