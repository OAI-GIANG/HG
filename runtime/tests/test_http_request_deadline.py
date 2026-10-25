"""Total request deadline vs per-read socket timeout (raw-socket regression tests).

A per-read timeout only bounds silence. A client that sends one byte just before each
timeout ("slow drip") kept a handler thread for as long as it liked: STT measured a
4-byte drip at 4 s intervals answered only after 17.03 s with a 5 s timeout. The server
must also enforce a monotonic deadline for reading the whole request.
"""
import json
import socket
import time
import unittest
from threading import Thread

from runtime.http_server import HGHTTPServer, HTTPBoundaryError

HTTP_SERVER_TESTS = __import__("test_http_server")

READ_TIMEOUT = 0.6     # per-read inactivity timeout used by these tests
DEADLINE = 1.2         # total time allowed to read request line, headers and body
DRIP = 0.3             # < READ_TIMEOUT: each read alone never times out


class RequestDeadlineTests(unittest.TestCase):
    def setUp(self):
        self.base = HTTP_SERVER_TESTS.HTTPServerTests("test_non_loopback_bind_is_rejected")
        self.base.setUp()
        self.addCleanup(self.base.tearDown)
        self.server = HGHTTPServer(
            runtime=self.base.runtime, authenticate_request=self.base.authenticate,
            host="127.0.0.1", port=0, max_body_bytes=4096,
            request_timeout_seconds=READ_TIMEOUT, request_deadline_seconds=DEADLINE)
        self.thread = Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self._stop)
        self.address = self.server.address[:2]

    def _stop(self):
        self.server.shutdown()
        self.thread.join(timeout=2)

    def _connect(self):
        client = socket.create_connection(self.address, timeout=10)
        self.addCleanup(client.close)
        return client

    @staticmethod
    def _drain(client):
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
    def _drip(client, payload):
        """Send one byte every DRIP seconds; stop when the server closes the connection."""
        sent = 0
        for byte in payload:
            try:
                client.sendall(bytes([byte]))
            except OSError:                 # server closed, or the test already closed it
                break
            sent += 1
            time.sleep(DRIP)
        return sent

    def _post_head(self, length):
        return (b"POST /api/no-such-route HTTP/1.1\r\nHost: x\r\nAuthorization: Bearer test-only\r\n"
                b"Content-Type: application/json\r\nContent-Length: " + str(length).encode() + b"\r\n\r\n")

    def test_slow_drip_body_is_cut_at_the_total_deadline(self):
        body = b'{"padding":"' + b"a" * 30 + b'"}'          # 44 bytes * 0.3 s = 13 s of dripping
        client = self._connect()
        client.sendall(self._post_head(len(body)))
        started = time.monotonic()
        Thread(target=self._drip, args=(client, body), daemon=True).start()
        response = self._drain(client)
        elapsed = time.monotonic() - started
        self.assertLess(elapsed, DEADLINE + READ_TIMEOUT + 1.0, "request outlived the deadline")
        self.assertIn(b" 408 ", response.split(b"\r\n", 1)[0])
        self.assertIn(b"request_deadline_exceeded", response)
        self.assertEqual(self.base.fixture.adapter.calls, 0)

    def test_slow_drip_headers_are_cut_at_the_total_deadline(self):
        head = (b"GET /api/tasks/T-1 HTTP/1.1\r\nHost: x\r\nX-Pad: " + b"b" * 40 + b"\r\n\r\n")
        client = self._connect()
        started = time.monotonic()
        Thread(target=self._drip, args=(client, head), daemon=True).start()
        response = self._drain(client)                    # closed without a response
        self.assertLess(time.monotonic() - started, DEADLINE + READ_TIMEOUT + 1.0)
        self.assertEqual(response, b"")
        self.assertEqual(self.base.memory.calls, [])

    def test_stalled_body_still_times_out_per_read(self):
        client = self._connect()
        client.sendall(self._post_head(20) + b'{"a"')
        started = time.monotonic()
        response = self._drain(client)
        self.assertLess(time.monotonic() - started, DEADLINE)
        self.assertIn(b" 408 ", response.split(b"\r\n", 1)[0])
        self.assertIn(b"request_body_timeout", response)

    def test_prompt_valid_request_is_unaffected(self):
        body = json.dumps({"x": "y"}).encode()
        client = self._connect()
        client.sendall(self._post_head(len(body)) + body)
        response = self._drain(client)
        status = response.split(b"\r\n", 1)[0]
        self.assertIn(b" 404 ", status)                   # body read in full, route resolved
        self.assertIn(b"NOT_FOUND", response)

    def test_request_split_into_a_few_quick_parts_is_unaffected(self):
        body = json.dumps({"x": "y"}).encode()
        raw = self._post_head(len(body)) + body
        client = self._connect()
        for start in range(0, len(raw), 25):
            client.sendall(raw[start:start + 25])
            time.sleep(0.05)
        self.assertIn(b" 404 ", self._drain(client).split(b"\r\n", 1)[0])

    def test_oversized_body_is_rejected_before_reading(self):
        client = self._connect()
        client.sendall(self._post_head(5000))
        response = self._drain(client)
        self.assertIn(b" 413 ", response.split(b"\r\n", 1)[0])

    def test_client_disconnect_mid_body_leaves_server_serving(self):
        import contextlib
        import io
        errors = io.StringIO()
        with contextlib.redirect_stderr(errors):
            client = socket.create_connection(self.address, timeout=5)
            client.sendall(self._post_head(40) + b'{"partial"')
            client.close()
            time.sleep(0.3)
        self.assertNotIn("Traceback", errors.getvalue())   # disconnect handled, not crashed
        body = json.dumps({"x": "y"}).encode()
        other = self._connect()
        other.sendall(self._post_head(len(body)) + body)
        self.assertIn(b" 404 ", self._drain(other).split(b"\r\n", 1)[0])
        self.assertEqual(self.base.fixture.adapter.calls, 0)

    def test_deadline_configuration_is_bounded(self):
        for timeout, deadline in ((5.0, 4.0), (5.0, 0), (5.0, 121), (5.0, True), (5.0, "15")):
            with self.assertRaisesRegex(HTTPBoundaryError, "invalid_request_deadline"):
                HGHTTPServer(runtime=self.base.runtime, authenticate_request=self.base.authenticate,
                             host="127.0.0.1", port=0, request_timeout_seconds=timeout,
                             request_deadline_seconds=deadline)


if __name__ == "__main__":
    unittest.main()
