"""WS-04 oracle: fs.read returns the file it read, exactly, or a known failure.

`fs.read` ("Read a UTF-8 text file under the adapter root") is exposed by the HTTP service
and feeds research documents. Its outcome carries the file's `sha256`/`bytes` and its
`content`. The content must be the exact text of those bytes: a file that is not valid
UTF-8 must not be returned as a different, "repaired" text (U+FFFD in place of bytes) under
the digest of the original bytes, and the task must not close on it. A file larger than
the adapter bound must be refused before it is read into memory (the phone has little).

Each case runs a real `fs.read` task through BrainOrchestrator -> ActionGateway -> adapter.
Controls: UTF-8 non-ASCII text, CRLF/CR, a BOM, an empty file and a file of exactly the
bound are returned byte-exact and the task closes CLOSED_VERIFIED.
"""
import hashlib
import tracemalloc

from hg.tests.test_file_adapter_path_oracle import Base, outcomes, step
from hg.tools.gateway import LocalFileReadAdapter

PATH = "out/doc.txt"


class FsReadContentOracle(Base):
    def read(self, data):
        (self.root / PATH).write_bytes(data)
        seen = []

        def verifier(snapshot):
            seen.extend(snapshot["outcomes"])
            return True, "any"
        rt, final = self.run_steps([step("fs.read", "READ", PATH)], verifiers={"AC-1": verifier})
        return rt, final, seen

    def assert_exact(self, data):
        rt, final, seen = self.read(data)
        self.assertEqual(final["task"]["state"], "CLOSED_VERIFIED")
        observed = [o["observed"] for o in seen if o.get("tool") == "fs.read"]
        self.assertEqual(len(observed), 1)
        self.assertEqual(observed[0]["content"].encode("utf-8"), data)
        self.assertEqual(observed[0]["sha256"], hashlib.sha256(data).hexdigest())
        self.assertEqual(observed[0]["bytes"], len(data))

    def assert_refused_without_text(self, data):
        rt, final, seen = self.read(data)
        self.assert_refused(rt, final)
        for outcome in seen:
            self.assertNotIn("�", repr(outcome))
            self.assertIsNone((outcome.get("observed") or {}).get("content"))
        for payload in outcomes(rt):
            self.assertNotIn("\\ufffd", repr(payload))
        return rt, final

    # ---- not UTF-8: one reading or none ----

    def test_invalid_utf8_bytes_are_not_returned_as_replaced_text(self):
        self.assert_refused_without_text(b"timeout = 30 \xff\xfe end\n")

    def test_truncated_multibyte_sequence_is_refused(self):
        self.assert_refused_without_text("xin chà".encode("utf-8")[:-1])

    def test_encoded_surrogate_is_refused(self):
        self.assert_refused_without_text(b"a\xed\xa0\x80b")

    def test_overlong_encoding_is_refused(self):
        self.assert_refused_without_text(b"a\xc0\xafb")

    def test_latin1_file_is_refused(self):
        self.assert_refused_without_text("café".encode("latin-1"))

    # ---- bounded ----

    def test_file_over_the_bound_is_refused_before_it_is_read(self):
        limit = LocalFileReadAdapter.MAX_BYTES
        size = max(limit + 1, 24 * 1024 * 1024)
        with open(self.root / PATH, "wb") as fh:
            fh.truncate(size)            # sparse: costs no disk
        tracemalloc.start()
        try:
            rt, final = self.run_steps([step("fs.read", "READ", PATH)],
                                       verifiers={"AC-1": lambda _s: (True, "any")})
            _current, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        self.assert_refused(rt, final)
        self.assertLess(peak, 8 * 1024 * 1024, f"traced peak {peak} bytes")

    def test_file_one_byte_over_the_bound_is_refused(self):
        self.assert_refused_without_text(b"a" * (LocalFileReadAdapter.MAX_BYTES + 1))

    # ---- controls ----

    def test_control_utf8_non_ascii_is_exact(self):
        self.assert_exact("Xin chào, thế giới 🌏\n".encode("utf-8"))

    def test_control_crlf_and_cr_are_exact(self):
        self.assert_exact(b"a\r\nb\rc\n")

    def test_control_bom_is_kept(self):
        self.assert_exact(b"\xef\xbb\xbfhello")

    def test_control_empty_file(self):
        self.assert_exact(b"")

    def test_control_file_of_exactly_the_bound(self):
        self.assert_exact(b"a" * LocalFileReadAdapter.MAX_BYTES)
