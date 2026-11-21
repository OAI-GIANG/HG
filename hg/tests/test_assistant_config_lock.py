"""config.load() reads under the shared HG_HOME lock and config.save() writes under the exclusive one.

PR #77 was cut before the lock existed on main (commit c9bce9f); these tests keep it from being lost again."""
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from hg.assistant import config as cfg
from hg.assistant.home import Busy, ensure_home, locked


class ConfigLockTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="hg-cfg-lock-")
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name) / "home"
        ensure_home(self.home)

    def spy(self, **override):
        calls, real = [], cfg.locked

        def wrapper(home, **kw):
            calls.append(dict(kw))
            return real(home, **{**kw, **override})
        return calls, mock.patch.object(cfg, "locked", wrapper)

    def hold(self, exclusive):
        """Hold the HOME lock from another thread until released; returns the release callable."""
        ready, release = threading.Event(), threading.Event()

        def holder():
            with locked(self.home, exclusive=exclusive):
                ready.set()
                release.wait(10)
        thread = threading.Thread(target=holder, daemon=True)
        thread.start()
        self.assertTrue(ready.wait(5))

        def done():
            release.set()
            thread.join(5)
        self.addCleanup(done)
        return done

    def test_load_takes_the_shared_lock_and_forwards_wait_s(self):
        calls, patch = self.spy()
        with patch:
            cfg.load(self.home, wait_s=1.5)
        self.assertEqual(calls, [{"exclusive": False, "wait_s": 1.5}])

    def test_save_takes_the_exclusive_lock(self):
        calls, patch = self.spy()
        with patch:
            cfg.save(self.home, dict(cfg.DEFAULTS, model="m-test"))
        self.assertEqual(calls, [{"exclusive": True}])

    def test_load_is_refused_while_another_holder_writes(self):
        release = self.hold(exclusive=True)
        with self.assertRaises(Busy):
            cfg.load(self.home, wait_s=0.2)
        release()
        self.assertEqual(cfg.load(self.home, wait_s=1)["model"], cfg.DEFAULTS["model"])

    def test_loads_coexist_with_a_reader(self):
        self.hold(exclusive=False)
        self.assertEqual(cfg.load(self.home, wait_s=1)["model"], cfg.DEFAULTS["model"])

    def test_save_is_refused_while_another_holder_reads(self):
        release = self.hold(exclusive=False)
        _, patch = self.spy(wait_s=0.2)
        with patch, self.assertRaises(Busy):
            cfg.save(self.home, dict(cfg.DEFAULTS, model="m-test"))
        self.assertFalse((self.home / "config.json").exists())      # refused before anything was written
        release()

    def test_no_lock_is_left_behind_after_load_or_save(self):
        cfg.save(self.home, dict(cfg.DEFAULTS, model="m-test"))
        cfg.load(self.home)
        with locked(self.home, exclusive=True, wait_s=0.2):         # would raise Busy if a lease leaked
            pass

    def test_concurrent_saves_and_loads_never_see_a_torn_file(self):
        errors, stop = [], threading.Event()

        def writer():
            index = 0
            while not stop.is_set():
                index += 1
                try:
                    cfg.save(self.home, dict(cfg.DEFAULTS, model=f"m-{index}", num_ctx=1000 + index))
                except Busy:
                    pass
                except Exception as exc:                       # pragma: no cover - failure path
                    errors.append(exc)
                    return
        thread = threading.Thread(target=writer, daemon=True)
        thread.start()
        try:
            for _ in range(60):
                try:
                    conf = cfg.load(self.home, wait_s=2)
                except Busy:
                    continue
                if conf["model"].startswith("m-"):                 # a pair written together is read together
                    self.assertEqual(conf["num_ctx"] - 1000, int(conf["model"].split("-")[1]))
        finally:
            stop.set()
            thread.join(10)
        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
