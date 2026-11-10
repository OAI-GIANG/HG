"""False-accept oracle for installed-release reads (WS-04).

`verify_root` is what the service calls on every `/ready` and `/v1/integrity`
request, and what deploy calls before and after sealing; `verify_archive` checks a
built archive before install. Each case starts from a release built and installed
from a real Git commit, then damages the installed tree, the manifest or the archive.
The expected outcome comes from how the case was built: no damaged input may yield
VERIFIED. Controls show that the undamaged release still verifies, so a verifier that
rejects everything cannot satisfy the oracle. A read must also fail promptly: a special
file planted at the manifest or archive path must not block the caller (a blocked
`/ready` thread never answers).

Not covered by design: owner write bits on installed files (deploy verifies before
sealing, so `verify_root` checks content, not seal state) and extra empty directories
(no bytes, nothing importable that shadows a real module).
"""
import json
import os
import shutil
import tempfile
import threading
import time
import unittest
from pathlib import Path

from hg.release import ReleaseError, verify_archive, verify_root
from hg.tests.release_helpers import make_tiny_release

_PROMPT_SECONDS = 5.0


def _call_with_deadline(fn, release_path=None):
    out = {}

    def run():
        try:
            out["value"] = fn()
        except Exception as exc:  # inspected below
            out["error"] = exc

    thread = threading.Thread(target=run, daemon=True)
    started = time.monotonic()
    thread.start()
    thread.join(_PROMPT_SECONDS)
    hung = thread.is_alive()
    if hung and release_path is not None:
        try:
            fd = os.open(release_path, os.O_WRONLY | os.O_NONBLOCK)
            os.close(fd)
        except OSError:
            pass
        thread.join(_PROMPT_SECONDS)
    return hung, out, time.monotonic() - started


def _make_writable(path):
    path = Path(path)
    if not path.exists() and not path.is_symlink():
        return
    for p in [path, *path.rglob("*")]:
        if not p.is_symlink():
            p.chmod(p.stat().st_mode | 0o700 if p.is_dir() else p.stat().st_mode | 0o200)


class ReleaseReadFalseAcceptOracle(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._base = tempfile.TemporaryDirectory(prefix="hg-release-oracle-base-")
        cls.base = make_tiny_release(Path(cls._base.name) / "fixture")

    @classmethod
    def tearDownClass(cls):
        cls._base.cleanup()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="hg-release-oracle-")
        self.dir = Path(self.temp.name)
        self.root = self.dir / "release-root"
        shutil.copytree(self.base["root"], self.root, symlinks=True)
        self.manifest = self.dir / "release-manifest.json"
        shutil.copyfile(self.base["manifest"], self.manifest)
        self.archive = self.dir / "release.tar.gz"
        shutil.copyfile(self.base["archive"], self.archive)
        self.release_id = self.base["doc"]["release_id"]

    def tearDown(self):
        _make_writable(self.dir)
        self.temp.cleanup()

    def _verify_root(self):
        return verify_root(self.root, self.manifest, self.release_id)

    def _verify_archive(self):
        return verify_archive(self.base["repo"], self.archive, self.manifest)

    def _assert_refused(self, fn, release_path=None):
        hung, out, elapsed = _call_with_deadline(fn, release_path)
        self.assertFalse(hung, f"read blocked for more than {_PROMPT_SECONDS}s")
        self.assertLess(elapsed, _PROMPT_SECONDS)
        self.assertNotIn("value", out, f"damaged release was accepted: {out.get('value')!r}")
        self.assertIsInstance(out.get("error"), ReleaseError, repr(out.get("error")))

    # --- controls -------------------------------------------------------------------
    def test_control_intact_release_verifies(self):
        self.assertEqual(self._verify_root()["result"], "VERIFIED")
        self.assertEqual(self._verify_archive()["result"], "VERIFIED")

    # --- installed tree -------------------------------------------------------------
    def test_installed_tree_damage_is_never_accepted(self):
        readme = "README.md"

        def flip(root):
            p = root / readme
            data = bytearray(p.read_bytes())
            data[0] ^= 0x01
            p.write_bytes(bytes(data))

        def fifo_in_tree(root):
            os.mkfifo(root / "hg" / "pipe")

        def file_to_dir(root):
            (root / readme).unlink()
            (root / readme).mkdir()

        def symlink_file(root):
            outside = self.dir / "outside.md"
            outside.write_bytes((root / readme).read_bytes())
            (root / readme).unlink()
            (root / readme).symlink_to(outside)

        def symlink_dir(root):
            outside = self.dir / "outside-hg"
            shutil.copytree(root / "hg", outside)
            shutil.rmtree(root / "hg")
            (root / "hg").symlink_to(outside, target_is_directory=True)

        cases = {
            "flipped_byte": flip,
            "truncated": lambda r: (r / readme).write_bytes((r / readme).read_bytes()[:-1]),
            "appended": lambda r: (r / readme).write_bytes((r / readme).read_bytes() + b"x"),
            "emptied": lambda r: (r / readme).write_bytes(b""),
            "swapped_contents": lambda r: (r / readme).write_bytes((r / "hg/runtime.py").read_bytes()),
            "missing_file": lambda r: (r / readme).unlink(),
            "extra_file": lambda r: (r / "hg" / "extra.py").write_text("x = 1\n", encoding="utf-8"),
            "injected_bytecode": lambda r: ((r / "hg" / "__pycache__").mkdir(),
                                            (r / "hg" / "__pycache__" / "runtime.cpython-312.pyc").write_bytes(b"x")),
            "exec_bit_added": lambda r: (r / readme).chmod(0o755),
            "exec_bit_removed": lambda r: (r / "bin/check").chmod(0o644),
            "fifo_in_tree": fifo_in_tree,
            "file_replaced_by_dir": file_to_dir,
            "symlinked_file": symlink_file,
            "symlinked_dir": symlink_dir,
        }
        for name, damage in cases.items():
            with self.subTest(name):
                self.tearDown()
                self.setUp()
                damage(self.root)
                self._assert_refused(self._verify_root)

    def test_symlinked_root_is_never_accepted(self):
        link = self.dir / "root-link"
        link.symlink_to(self.root, target_is_directory=True)
        self._assert_refused(lambda: verify_root(link, self.manifest, self.release_id))

    def test_wrong_expected_release_id_is_never_accepted(self):
        self._assert_refused(lambda: verify_root(self.root, self.manifest, "0" * 64))

    # --- manifest -------------------------------------------------------------------
    def _manifest_cases(self):
        raw = self.manifest.read_bytes()
        doc = json.loads(raw)

        def rewrite(mutator):
            def apply():
                d = json.loads(raw)
                mutator(d)
                self.manifest.write_text(json.dumps(d, sort_keys=True), encoding="utf-8")
            return apply

        def dup_key():
            text = raw.decode("utf-8").rstrip()
            assert text.endswith("}")
            self.manifest.write_text(text[:-1] + ',"schema":"x"}', encoding="utf-8")

        def fifo():
            self.manifest.unlink()
            os.mkfifo(self.manifest)

        def symlink():
            outside = self.dir / "outside-manifest.json"
            outside.write_bytes(raw)
            self.manifest.unlink()
            self.manifest.symlink_to(outside)

        def directory():
            self.manifest.unlink()
            self.manifest.mkdir()

        def flip():
            data = bytearray(raw)
            data[len(data) // 2] ^= 0x01
            self.manifest.write_bytes(bytes(data))

        def drop_row(d):
            d["files"] = d["files"][1:]

        def row_digest(d):
            d["files"][0]["sha256"] = "0" * 64

        return {
            "flipped_byte": flip,
            "truncated": lambda: self.manifest.write_bytes(raw[:-5]),
            "empty": lambda: self.manifest.write_bytes(b""),
            "non_utf8": lambda: self.manifest.write_bytes(raw[:10] + b"\xff" + raw[10:]),
            "bom": lambda: self.manifest.write_bytes(b"\xef\xbb\xbf" + raw),
            "not_object": lambda: self.manifest.write_text(json.dumps([doc]), encoding="utf-8"),
            "duplicate_key": dup_key,
            "row_dropped_digest_stale": rewrite(drop_row),
            "row_digest_changed_digest_stale": rewrite(row_digest),
            "nan_constant": lambda: self.manifest.write_bytes(raw.replace(b'"bytes":', b'"bytes":NaN,"x":', 1)),
            "fifo": fifo,
            "symlink": symlink,
            "directory": directory,
        }

    def test_manifest_damage_is_never_accepted_by_verify_root(self):
        for name, damage in self._manifest_cases().items():
            with self.subTest(name):
                self.tearDown()
                self.setUp()
                self._manifest_cases()[name]()
                self._assert_refused(self._verify_root, release_path=self.manifest)

    def test_manifest_damage_is_never_accepted_by_verify_archive(self):
        for name in self._manifest_cases():
            with self.subTest(name):
                self.tearDown()
                self.setUp()
                self._manifest_cases()[name]()
                self._assert_refused(self._verify_archive, release_path=self.manifest)

    # --- archive --------------------------------------------------------------------
    def test_archive_damage_is_never_accepted(self):
        raw = self.archive.read_bytes()

        def fifo():
            self.archive.unlink()
            os.mkfifo(self.archive)

        def symlink():
            outside = self.dir / "outside.tar.gz"
            outside.write_bytes(raw)
            self.archive.unlink()
            self.archive.symlink_to(outside)

        def directory():
            self.archive.unlink()
            self.archive.mkdir()

        cases = {
            "flipped_byte": lambda: self.archive.write_bytes(raw[:-9] + bytes([raw[-9] ^ 1]) + raw[-8:]),
            "truncated": lambda: self.archive.write_bytes(raw[:-1]),
            "appended": lambda: self.archive.write_bytes(raw + b"\0"),
            "empty": lambda: self.archive.write_bytes(b""),
            "fifo": fifo,
            "symlink": symlink,
            "directory": directory,
        }
        for name, damage in cases.items():
            with self.subTest(name):
                self.tearDown()
                self.setUp()
                damage()
                self._assert_refused(self._verify_archive, release_path=self.archive)


if __name__ == "__main__":
    unittest.main()
