"""Candidate D3 session source: positive and negative tests (ADR-012 switch gate 2 style)."""
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from email.message import Message
from pathlib import Path
from threading import Thread

from maep.local_runtime_providers import LocalPrincipalProvider
from maep.native_authority import AuthorityError
from runtime.session_auth import (SESSION_SCHEMA, SessionContext, TokenSessionSource,
                                  issue_session, main, revoke_session)

CAPS = ["READ", "WRITE"]
RES = ["memory:task/T-1"]
SCOPES = ["memory:task:T-1:read"]


def headers(*values):
    message = Message()
    for value in values:
        message["Authorization"] = value
    return message


class SessionSourceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="hg-session-")
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        self.session, self.token_file, self.revocations = base / "session.json", base / "token", base / "revoked.json"
        self.issued = issue_session(session_path=self.session, token_path=self.token_file,
                                    revocation_path=self.revocations, principal_id="STT", valid_days=30,
                                    capabilities=CAPS, resource_scopes=RES, allowed_scopes=SCOPES)
        self.token = self.token_file.read_text().strip()
        self.source = TokenSessionSource(session_path=self.session, revocation_path=self.revocations)

    def rewrite(self, **changes):
        record = json.loads(self.session.read_text())
        record.update(changes)
        self.session.write_text(json.dumps(record))

    def test_issue_writes_private_files_and_never_stores_the_token(self):
        for path in (self.session, self.token_file, self.revocations):
            self.assertEqual(os.stat(path).st_mode & 0o777, 0o600, path.name)
        self.assertEqual(len(self.token), 64)
        self.assertNotIn(self.token, self.session.read_text())
        self.assertNotIn(self.token, json.dumps(self.issued))
        self.assertNotIn(self.token, repr(self.source))
        self.assertEqual(json.loads(self.session.read_text())["schema"], SESSION_SCHEMA)

    def test_issue_refuses_to_overwrite(self):
        with self.assertRaisesRegex(AuthorityError, "refusing to overwrite"):
            issue_session(session_path=self.session, token_path=Path(self.tmp.name) / "t2",
                          revocation_path=self.revocations, principal_id="STT", valid_days=1,
                          capabilities=CAPS, resource_scopes=RES, allowed_scopes=SCOPES)

    def test_valid_token_authenticates_to_the_runtime_bound_context(self):
        context = self.source.authenticate_request(headers("Bearer " + self.token))
        self.assertEqual(context, SessionContext(self.issued["session_id"], "STT"))
        self.assertEqual(context, self.source.authenticated_context())

    def test_session_resolves_to_a_principal_the_native_engine_accepts(self):
        context = self.source.authenticated_context()
        principal = LocalPrincipalProvider(self.source).resolve(context)
        self.assertEqual(principal["principal_id"], "STT")
        self.assertEqual((principal["status"], principal["verified"], principal["revoked"]), ("ACTIVE", True, False))
        self.assertTrue(principal["identity_evidence_ref"].startswith("hg-session-record:sha256:"))
        self.assertEqual(principal["capabilities"], CAPS)

    def test_bad_authorization_headers_are_rejected(self):
        for value in ([], ["Bearer " + "x" * 64], ["Basic " + self.token], ["Bearer short"],
                      ["Bearer " + self.token, "Bearer " + self.token], ["bearer " + self.token],
                      ["Bearer " + self.token + " "]):
            with self.assertRaises(AuthorityError, msg=repr(value[:1])):
                self.source.authenticate_request(headers(*value))

    def test_expired_and_not_yet_valid_sessions_are_rejected(self):
        later = datetime.now(timezone.utc) + timedelta(days=31)
        with self.assertRaisesRegex(AuthorityError, "expired"):
            self.source.authenticate_request(headers("Bearer " + self.token), now=later)
        with self.assertRaisesRegex(AuthorityError, "expired"):
            self.source.authenticated_context(now=later)
        past = (datetime.now(timezone.utc) - timedelta(days=10)).replace(microsecond=0)
        self.rewrite(issued_at=(past - timedelta(days=5)).isoformat(), expires_at=past.isoformat())
        self.assertIsNone(LocalPrincipalProvider(self.source).resolve(
            SessionContext(self.issued["session_id"], "STT")))
        future = datetime.now(timezone.utc) + timedelta(days=1)
        self.rewrite(issued_at=future.isoformat(), expires_at=(future + timedelta(days=1)).isoformat())
        with self.assertRaises(AuthorityError):
            self.source.authenticate_request(headers("Bearer " + self.token))

    def test_revocation_applies_immediately(self):
        context = self.source.authenticated_context()
        revoke_session(revocation_path=self.revocations, session_id=self.issued["session_id"])
        self.assertEqual(os.stat(self.revocations).st_mode & 0o777, 0o600)
        with self.assertRaisesRegex(AuthorityError, "revoked"):
            self.source.authenticate_request(headers("Bearer " + self.token))
        resolved = self.source.resolve_authenticated_session(context)
        self.assertEqual((resolved["status"], resolved["revoked"]), ("REVOKED", True))
        self.assertIsNone(LocalPrincipalProvider(self.source).resolve(context))

    def test_other_or_forged_contexts_resolve_to_nothing(self):
        for context in (SessionContext("hg-session-other", "STT"),
                        SessionContext(self.issued["session_id"], "OWNER"),
                        {"session_id": self.issued["session_id"], "principal_id": "STT"}, "STT", None):
            self.assertIsNone(self.source.resolve_authenticated_session(context))

    def test_tampered_or_unsafe_records_fail_closed(self):
        cases = [
            lambda: self.rewrite(token_sha256="sha256:" + "0" * 63),
            lambda: self.rewrite(extra="field"),
            lambda: self.rewrite(capabilities=[]),
            lambda: self.rewrite(allowed_scopes=["a", "a"]),
            lambda: self.rewrite(expires_at=json.loads(self.session.read_text())["issued_at"]),
            lambda: self.rewrite(issued_at="2026-01-01T00:00:00"),
            lambda: self.session.write_text('{"schema": "x", "schema": "y"}'),
            lambda: os.chmod(self.session, 0o644),
            lambda: self.revocations.write_text('{"schema": "hg-runtime-session-revocations-v1"}'),
            lambda: self.revocations.unlink(),
        ]
        original_session, original_rev = self.session.read_text(), self.revocations.read_text()
        for index, damage in enumerate(cases):
            damage()
            with self.assertRaises(AuthorityError, msg=f"case {index}"):
                self.source.authenticate_request(headers("Bearer " + self.token))
            os.chmod(self.session, 0o600)
            self.session.write_text(original_session)
            if not self.revocations.exists():
                fd = os.open(self.revocations, os.O_WRONLY | os.O_CREAT, 0o600)
                os.close(fd)
            self.revocations.write_text(original_rev)
            os.chmod(self.revocations, 0o600)
        self.assertEqual(self.source.authenticate_request(headers("Bearer " + self.token)).principal_id, "STT")

    def test_symlinked_session_record_is_rejected(self):
        link = Path(self.tmp.name) / "link.json"
        link.symlink_to(self.session)
        with self.assertRaises(AuthorityError):
            TokenSessionSource(session_path=link, revocation_path=self.revocations)

    def test_relative_paths_and_bad_issue_arguments_are_rejected(self):
        with self.assertRaises(AuthorityError):
            TokenSessionSource(session_path="session.json", revocation_path=self.revocations)
        for kwargs in ({"principal_id": "bad id"}, {"valid_days": 0}, {"valid_days": 367},
                       {"capabilities": []}):
            args = dict(session_path=Path(self.tmp.name) / "s2.json", token_path=Path(self.tmp.name) / "t2",
                        revocation_path=self.revocations, principal_id="STT", valid_days=1,
                        capabilities=CAPS, resource_scopes=RES, allowed_scopes=SCOPES)
            args.update(kwargs)
            with self.assertRaises(AuthorityError):
                issue_session(**args)

    def test_cli_issue_prints_no_token_and_blocks_on_overwrite(self):
        import contextlib
        import io
        base = Path(self.tmp.name)
        out = io.StringIO()
        argv = ["issue", "--session-file", str(base / "c.json"), "--token-file", str(base / "c.token"),
                "--revocation-file", str(base / "c-rev.json"), "--principal", "STT", "--days", "7",
                "--capability", "READ", "--resource-scope", "memory:task/T-1",
                "--allowed-scope", "memory:task:T-1:read"]
        with contextlib.redirect_stdout(out):
            self.assertEqual(main(argv), 0)
        self.assertNotIn((base / "c.token").read_text().strip(), out.getvalue())
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main(argv), 78)


class SessionSourceHTTPIntegrationTests(unittest.TestCase):
    """The candidate plugs into HGHTTPServer's existing runtime-bound context check."""

    def setUp(self):
        import http.client  # noqa: F401
        from types import SimpleNamespace
        from runtime.http_server import HGHTTPServer
        base_tests = __import__("test_http_server").HTTPServerTests("test_non_loopback_bind_is_rejected")
        base_tests.setUp()
        self.addCleanup(base_tests.tearDown)
        self.tmp = tempfile.TemporaryDirectory(prefix="hg-session-http-")
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        issue_session(session_path=base / "s.json", token_path=base / "t", revocation_path=base / "r.json",
                      principal_id="STT", valid_days=1, capabilities=CAPS, resource_scopes=RES,
                      allowed_scopes=SCOPES)
        self.token = (base / "t").read_text().strip()
        self.revocations = base / "r.json"
        self.source = TokenSessionSource(session_path=base / "s.json", revocation_path=base / "r.json")
        runtime = SimpleNamespace(**vars(base_tests.runtime))
        runtime.authenticated_context_provider = self.source.authenticated_context
        self.server = HGHTTPServer(runtime=runtime, authenticate_request=self.source.authenticate_request,
                                   host="127.0.0.1", port=0)
        self.thread = Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(lambda: (self.server.shutdown(), self.thread.join(timeout=2)))
        self.memory = base_tests.memory

    def get(self, token):
        import http.client
        conn = http.client.HTTPConnection(*self.server.address[:2], timeout=5)
        conn.request("GET", "/api/tasks/T-1", headers={} if token is None else {"Authorization": "Bearer " + token})
        response = conn.getresponse()
        body = json.loads(response.read())
        conn.close()
        return response.status, body

    def test_valid_session_token_reaches_the_protected_route(self):
        status, body = self.get(self.token)
        self.assertEqual(status, 200, body)
        self.assertEqual(self.memory.calls, [("get_task", "T-1")])

    def test_wrong_missing_and_revoked_tokens_are_denied_before_memory(self):
        self.assertEqual(self.get("y" * 64)[0], 401)
        self.assertEqual(self.get(None)[0], 401)
        revoke_session(revocation_path=self.revocations, session_id=self.source.authenticated_context().session_id)
        self.assertEqual(self.get(self.token)[0], 401)
        self.assertEqual(self.memory.calls, [])


if __name__ == "__main__":
    unittest.main()


class SessionSourceReviewFixTests(unittest.TestCase):
    """Defects found reviewing PR #24 (startup validation, partial issuance)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="hg-session-review-")
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)

    def issue(self, name="s"):
        return issue_session(session_path=self.base / f"{name}.json", token_path=self.base / f"{name}.token",
                             revocation_path=self.base / "revoked.json", principal_id="STT", valid_days=1,
                             capabilities=CAPS, resource_scopes=RES, allowed_scopes=SCOPES)

    def test_missing_or_malformed_revocation_list_blocks_construction(self):
        self.issue()
        (self.base / "revoked.json").unlink()
        with self.assertRaises(AuthorityError):
            TokenSessionSource(session_path=self.base / "s.json", revocation_path=self.base / "revoked.json")
        fd = os.open(self.base / "revoked.json", os.O_WRONLY | os.O_CREAT, 0o600)
        os.write(fd, b'{"schema":"hg-runtime-session-revocations-v1","revoked_session_ids":"x"}')
        os.close(fd)
        with self.assertRaises(AuthorityError):
            TokenSessionSource(session_path=self.base / "s.json", revocation_path=self.base / "revoked.json")

    def test_failed_issuance_leaves_no_usable_or_orphan_files(self):
        from unittest import mock
        from runtime import session_auth
        real = session_auth._write_new_json

        def fail_on_session(path, body, *args, **kwargs):
            if Path(path).name == "s.json":
                raise OSError("disk full")
            return real(path, body, *args, **kwargs)

        with mock.patch.object(session_auth, "_write_new_json", side_effect=fail_on_session):
            with self.assertRaises(OSError):
                self.issue()
        self.assertFalse((self.base / "s.token").exists(), "orphan token left after failed issuance")
        self.assertFalse((self.base / "s.json").exists())
        self.issue()                                   # a retry with the same paths succeeds
        self.assertTrue((self.base / "s.token").exists())
