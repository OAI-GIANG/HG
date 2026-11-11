"""WS-04 oracle: fs.write has exactly the planned effect, or a known failure with none.

`fs.write` ("Atomically write UTF-8 text to a file under the adapter root") is exposed by
the HTTP service. The planned effect (its intent) is: the file at the authorized path holds
these bytes. The oracle checks the effect the runtime records against what happened:

* a write that cannot happen and changed nothing (the path is a directory, or a parent of
  it is a regular file) is a known failure (`FAILED`), not `UNKNOWN`: an UNKNOWN action
  stays pending (unreconciled) and blocks further effects, although nothing was or could
  be written;
* replacing an existing file changes its content only: its permission bits are kept (an
  executable script must not lose its execute bit, a shared file must not become private);
* `SUCCEEDED` is recorded only after the replacement is durable: the parent directory,
  which holds the new name, is fsynced after the rename, not only the file data.

Each case runs a real `fs.write` task through BrainOrchestrator -> ActionGateway -> adapter.
Controls: ordinary writes (new file, nested new directories, CRLF, non-ASCII, empty
content, replacing a file) close CLOSED_VERIFIED byte-exact and leave no temporary file.
"""
import os
import stat
import unittest
from unittest import mock

from hg.tests.test_file_adapter_path_oracle import Base, outcomes, step


class FsWriteEffectOracle(Base):
    def write(self, path, content="xin chao"):
        return self.run_steps([step("fs.write", "WRITE", path, content=content)],
                              verifiers={"AC-1": lambda _s: (True, "any")})

    def statuses(self, rt):
        return [p["status"] for p in outcomes(rt) if p["step_id"] == "S-1"]

    def assert_no_temp_files(self):
        left = [str(p) for p in self.root.rglob(".hg-tmp-*")]
        self.assertEqual(left, [])

    def assert_known_failure(self, path):
        rt, final = self.write(path)
        self.assert_refused(rt, final)
        done = self.statuses(rt)          # a known failure may be retried; every attempt is FAILED
        self.assertTrue(done)
        self.assertEqual(set(done), {"FAILED"}, done)
        self.assertEqual(rt.gateway.pending_actions("T-1"), [])   # nothing left unreconciled
        self.assert_no_temp_files()
        return rt, final

    # ---- nothing can be written: a known failure, not UNKNOWN ----

    def test_existing_directory_is_a_known_failure(self):
        target = self.root / "out" / "d"
        target.mkdir()
        (target / "keep.txt").write_text("keep", encoding="utf-8")
        self.assert_known_failure("out/d")
        self.assertTrue(target.is_dir())
        self.assertEqual((target / "keep.txt").read_text(encoding="utf-8"), "keep")

    def test_scope_directory_itself_is_a_known_failure(self):
        self.assert_known_failure("out")
        self.assertTrue((self.root / "out").is_dir())

    def test_parent_that_is_a_file_is_a_known_failure(self):
        blocker = self.root / "out" / "f"
        blocker.write_text("data", encoding="utf-8")
        self.assert_known_failure("out/f/x.txt")
        self.assertEqual(blocker.read_text(encoding="utf-8"), "data")

    def test_deeper_parent_that_is_a_file_is_a_known_failure(self):
        blocker = self.root / "out" / "f"
        blocker.write_text("data", encoding="utf-8")
        self.assert_known_failure("out/f/a/b/x.txt")
        self.assertEqual(blocker.read_text(encoding="utf-8"), "data")

    # ---- the effect is the content only ----

    def assert_mode_kept(self, mode):
        target = self.root / "out" / "run.sh"
        target.write_text("old", encoding="utf-8")
        os.chmod(target, mode)
        rt, final = self.write("out/run.sh", "new")
        self.assertEqual(final["task"]["state"], "CLOSED_VERIFIED")
        self.assertEqual(target.read_text(encoding="utf-8"), "new")
        self.assertEqual(oct(stat.S_IMODE(os.stat(target).st_mode)), oct(mode))
        self.assert_no_temp_files()

    def test_executable_file_keeps_its_mode(self):
        self.assert_mode_kept(0o755)

    def test_shared_file_keeps_its_mode(self):
        self.assert_mode_kept(0o644)

    def test_private_file_keeps_its_mode(self):
        self.assert_mode_kept(0o600)

    # ---- SUCCEEDED only after the rename is durable ----

    def test_parent_directory_is_fsynced_after_the_rename(self):
        target = self.root / "out" / "new" / "doc.txt"
        real_fsync = os.fsync
        calls = []

        def recording_fsync(fd):
            st = os.fstat(fd)
            on_disk = target.read_bytes() if target.exists() else None
            calls.append((stat.S_ISDIR(st.st_mode), st.st_ino, on_disk))
            return real_fsync(fd)
        with mock.patch("os.fsync", recording_fsync):
            rt, final = self.write("out/new/doc.txt", "durable")
        self.assertEqual(final["task"]["state"], "CLOSED_VERIFIED")
        parent_ino = os.stat(target.parent).st_ino
        self.assertIn((True, parent_ino, b"durable"), calls)

    # ---- controls ----

    def assert_written_exactly(self, path, content):
        rt, final = self.write(path, content)
        self.assertEqual(final["task"]["state"], "CLOSED_VERIFIED")
        self.assertEqual(self.statuses(rt), ["SUCCEEDED"])
        self.assertEqual((self.root / path).read_bytes(), content.encode("utf-8"))
        self.assert_no_temp_files()

    def test_control_non_ascii_text_in_new_nested_directories(self):
        self.assert_written_exactly("out/a/b/doc.txt", "Tiếng Việt — 漢字 🙂\n")

    def test_control_crlf_and_cr_are_written_exactly(self):
        self.assert_written_exactly("out/doc.txt", "a\r\nb\rc")

    def test_control_empty_content(self):
        self.assert_written_exactly("out/empty.txt", "")

    def test_control_replacing_a_file_closes(self):
        target = self.root / "out" / "hello.txt"
        target.write_text("old", encoding="utf-8")
        rt, final = self.write("out/hello.txt", "new")
        self.assertEqual(final["task"]["state"], "CLOSED_VERIFIED")
        self.assertEqual(target.read_text(encoding="utf-8"), "new")
        self.assert_secret_untouched(rt)
        self.assert_no_temp_files()


if __name__ == "__main__":
    unittest.main()
