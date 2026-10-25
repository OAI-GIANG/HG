"""_write_new_json must work where os.link does not exist (Termux/Android Python)."""
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from maep import local_runtime_providers as lrp
from maep.native_authority import AuthorityError, load_json_strict


class WriteNewJsonTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="hg-write-new-")
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)

    def check_publish(self):
        target = self.base / "sub" / "record.json"
        lrp._write_new_json(target, {"a": 1})
        self.assertEqual(load_json_strict(target), {"a": 1})
        self.assertEqual(stat.S_IMODE(os.stat(target).st_mode), 0o600)
        with self.assertRaisesRegex(AuthorityError, "refusing to overwrite"):
            lrp._write_new_json(target, {"a": 2})
        self.assertEqual(load_json_strict(target), {"a": 1})
        link = self.base / "link.json"
        link.symlink_to(self.base / "elsewhere.json")
        with self.assertRaisesRegex(AuthorityError, "refusing to overwrite"):
            lrp._write_new_json(link, {"a": 3})
        self.assertFalse((self.base / "elsewhere.json").exists())
        self.assertEqual([p.name for p in target.parent.iterdir()], ["record.json"])   # no temp left

    def test_publishes_with_hard_link_when_available(self):
        if not callable(getattr(os, "link", None)):
            self.skipTest("platform has no os.link")
        self.check_publish()

    def test_publishes_without_os_link(self):
        with mock.patch.object(lrp.os, "link", None, create=True):
            self.check_publish()


if __name__ == "__main__":
    unittest.main()
