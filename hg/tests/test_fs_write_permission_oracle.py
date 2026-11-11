"""WS-04 oracle: an fs.write that fails is FAILED only when it provably had no effect.

On the owner's phone HG runs as an ordinary Termux UID (10460), so permission errors are
real: a directory that is not writable made `tempfile.mkstemp` raise PermissionError, the
gateway recorded UNKNOWN, the action stayed pending and the task was BLOCKED, although no
file was created. The adapter must classify each filesystem error by what it proves:

* before any effect (inspection, creating a parent directory, creating or writing the
  temporary file, a rename that did not happen): undo what the attempt created (its own
  empty directories, its temporary file) and report a known failure (`FAILED`), leaving
  nothing pending, so the task's further attempts reach the adapter;
* once the rename may have happened (the temporary name is gone) or after it (syncing the
  directory): the effect may exist, so the outcome stays UNKNOWN and pending until
  reconcile() inspects the file. Not every OSError is a known failure.

Permission cases need a non-root UID (root ignores mode bits) and are skipped as root;
fault-injection cases run everywhere. Every case goes BrainOrchestrator -> ActionGateway ->
adapter.
"""
import errno
import os
import tempfile
import unittest
from unittest import mock

from hg.tests.test_file_adapter_path_oracle import Base, outcomes, step

ROOT = hasattr(os, "geteuid") and os.geteuid() == 0
NEEDS_UID = unittest.skipIf(ROOT, "root ignores permission bits; run as an ordinary UID")


class FsWritePermissionOracle(Base):
    def tearDown(self):
        for path, _dirs, _files in os.walk(self.root):
            try:
                os.chmod(path, 0o700)
            except OSError:
                pass
        super().tearDown()

    def write(self, path, content="xin chao"):
        return self.run_steps([step("fs.write", "WRITE", path, content=content)],
                              verifiers={"AC-1": lambda _s: (True, "any")})

    def statuses(self, rt):
        return [p["status"] for p in outcomes(rt) if p["step_id"] == "S-1"]

    def temp_files(self):
        return [str(p) for p in self.root.rglob(".hg-tmp-*")]

    def assert_known_failure_without_effect(self, path):
        rt, final = self.write(path)
        self.assert_refused(rt, final)
        done = self.statuses(rt)
        # Every attempt reached the adapter and failed knowingly: the first failure left
        # nothing pending, so the retries were not refused as "unreconciled".
        self.assertGreaterEqual(len(done), 2, done)
        self.assertEqual(set(done), {"FAILED"}, done)
        self.assertEqual(rt.gateway.pending_actions("T-1"), [])
        refused = [e["payload"].get("reason", "") for e in rt.actions.events("ACTION_REFUSED")]
        self.assertFalse([r for r in refused if "unreconciled" in r], refused)
        self.assertFalse((self.root / path).exists())
        self.assertEqual(self.temp_files(), [])
        return rt, final

    def assert_unknown_until_reconciled(self, path, expected_finding):
        rt, final = self.write(path)
        self.assert_not_closed(final)
        self.assertEqual(self.statuses(rt), ["UNKNOWN"])
        pending = rt.gateway.pending_actions("T-1")
        self.assertEqual(len(pending), 1)
        result = rt.gateway.reconcile(pending[0]["action_id"])
        self.assertEqual(result["finding"], expected_finding)
        self.assertEqual(rt.gateway.pending_actions("T-1"), [])
        return rt

    # ---- real permission errors (ordinary UID) ----

    @NEEDS_UID
    def test_existing_directory_without_write_permission(self):
        target_dir = self.root / "out" / "ro"
        target_dir.mkdir()
        os.chmod(target_dir, 0o555)
        self.assert_known_failure_without_effect("out/ro/x.txt")
        self.assertEqual(os.listdir(target_dir), [])

    @NEEDS_UID
    def test_parent_directory_cannot_be_created(self):
        locked = self.root / "out" / "ro"
        locked.mkdir()
        os.chmod(locked, 0o555)
        self.assert_known_failure_without_effect("out/ro/new/deeper/x.txt")
        self.assertEqual(os.listdir(locked), [])

    @NEEDS_UID
    def test_control_writable_directory_still_closes(self):
        rt, final = self.write("out/ok/x.txt", "ok")
        self.assertEqual(final["task"]["state"], "CLOSED_VERIFIED")
        self.assertEqual((self.root / "out" / "ok" / "x.txt").read_text(encoding="utf-8"), "ok")
        self.assertEqual(self.temp_files(), [])

    # ---- fault injection: before the rename, nothing is left behind ----

    def test_temp_file_creation_denied_removes_the_directories_it_created(self):
        with mock.patch("tempfile.mkstemp", side_effect=PermissionError(errno.EACCES, "Permission denied")):
            self.assert_known_failure_without_effect("out/new/deeper/x.txt")
        self.assertEqual(os.listdir(self.root / "out"), [])

    def test_temp_file_write_failure_removes_the_temp_file(self):
        real_mkstemp, real_fsync = tempfile.mkstemp, os.fsync
        temps = []

        def recording_mkstemp(*args, **kwargs):
            fd, name = real_mkstemp(*args, **kwargs)
            temps.append(os.fstat(fd).st_ino)
            return fd, name

        def failing_fsync(fd):
            if os.fstat(fd).st_ino in temps:
                raise OSError(errno.ENOSPC, "No space left on device")
            return real_fsync(fd)
        with mock.patch("tempfile.mkstemp", recording_mkstemp), mock.patch("os.fsync", failing_fsync):
            self.assert_known_failure_without_effect("out/x.txt")
        self.assertTrue(temps)

    def test_rename_that_did_not_happen_is_a_known_failure(self):
        existing = self.root / "out" / "x.txt"
        existing.write_text("old", encoding="utf-8")
        with mock.patch("os.replace", side_effect=PermissionError(errno.EACCES, "Permission denied")):
            rt, final = self.write("out/x.txt", "new")
        self.assert_refused(rt, final)
        self.assertEqual(set(self.statuses(rt)), {"FAILED"})
        self.assertEqual(rt.gateway.pending_actions("T-1"), [])
        self.assertEqual(existing.read_text(encoding="utf-8"), "old")
        self.assertEqual(self.temp_files(), [])

    # ---- fault injection: once the rename may have happened, it stays UNKNOWN ----

    def test_error_after_the_rename_happened_is_not_called_failed(self):
        real_replace = os.replace

        def replace_then_fail(src, dst):
            real_replace(src, dst)
            raise OSError(errno.EIO, "Input/output error")
        with mock.patch("os.replace", replace_then_fail):
            self.assert_unknown_until_reconciled("out/x.txt", "APPLIED")
        self.assertEqual((self.root / "out" / "x.txt").read_text(encoding="utf-8"), "xin chao")

    def test_directory_sync_failure_after_the_rename_is_not_called_failed(self):
        real_fsync = os.fsync
        out_ino = os.stat(self.root / "out").st_ino

        def fsync(fd):
            if os.fstat(fd).st_ino == out_ino:
                raise OSError(errno.EIO, "Input/output error")
            return real_fsync(fd)
        with mock.patch("os.fsync", fsync):
            self.assert_unknown_until_reconciled("out/x.txt", "APPLIED")


if __name__ == "__main__":
    unittest.main()
