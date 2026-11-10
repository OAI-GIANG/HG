"""False-accept oracle for the assistant home readers: `hg repair` and config.json (WS-04).

Each case starts from a home written through the assistant (notes by the Notebook, settings
by ``config.save``) and then damages a file in it. The expected outcome comes from how the
case was built:

- ``hg repair`` may rewrite a ledger only when its sole defect is a torn last record, the
  one thing an interrupted append can leave (C1: a record is committed only with its "\\n").
  Anything the ledger reader refuses for another reason (special file, symlink, a file other
  users can write, a terminated but invalid last record, a damaged earlier record) must be
  reported and left byte-for-byte unchanged, and nothing outside the home may be read into
  it. ``repair`` holds the home's exclusive lock, so it must also return promptly: a FIFO
  must not hang it (and with it every `hg ask`, `hg note` and chat request).
- ``config.json`` is loaded the way the ledgers are: an owner-owned regular file no other
  user can write, read without following links or waiting on a FIFO, and a key that appears
  twice is ambiguous and refused (json.loads would silently keep the last value).

Controls show that a genuinely torn tail is still repaired and that a valid config still
loads, so a reader that rejects everything cannot satisfy the oracle.
"""
import json
import os
import shutil
import tempfile
import threading
import unittest
from pathlib import Path

from hg.assistant import config as cfg
from hg.assistant.notes import Notebook
from hg.assistant.repair import inspect, repair

_PROMPT_SECONDS = 5.0


def _call_with_deadline(fn, release_path=None):
    """Run fn in a daemon thread; report whether it returned within the deadline."""
    out = {}

    def run():
        try:
            out["value"] = fn()
        except Exception as exc:  # inspected by the caller
            out["error"] = exc

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    thread.join(_PROMPT_SECONDS)
    hung = thread.is_alive()
    if hung and release_path is not None:
        try:
            os.close(os.open(release_path, os.O_WRONLY | os.O_NONBLOCK))
        except OSError:
            pass
        thread.join(_PROMPT_SECONDS)
    return hung, out


class _HomeBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve()
        self.home = self.root / "home"
        self.nb = Notebook(self.home)
        self.nb.add("Ghi chú một.", origin="test")
        self.nb.add("Ghi chú hai.", origin="test")
        self.notes = self.home / "notes.jsonl"
        self.good = self.notes.read_bytes()

    def _snapshot(self):
        return {p.name: (p.lstat().st_mode, p.read_bytes() if p.is_file() and not p.is_symlink() else None)
                for p in sorted(self.home.iterdir())}


class RepairOracleTests(_HomeBase):
    def _report(self, name):
        hung, out = _call_with_deadline(lambda: repair(self.home), self.home / name)
        self.assertFalse(hung, "repair blocked on a special file while holding the home lock")
        self.assertNotIn("error", out, f"repair crashed instead of reporting: {out.get('error')!r}")
        return next(r for r in out["value"] if r["file"] == name)

    def _assert_left_alone(self, name, before):
        report = self._report(name)
        self.assertNotIn(report["status"], ("OK", "TORN_LAST_LINE", "REPAIRED"), report)
        self.assertEqual(self._snapshot(), before, "repair changed or added files for a refused ledger")
        return report

    # Controls -------------------------------------------------------------------------
    def test_control_undamaged_ledger_is_ok(self):
        self.assertEqual(self._report("notes.jsonl")["status"], "OK")

    def test_control_torn_tail_is_still_repaired(self):
        with self.notes.open("ab") as stream:
            stream.write(b'{"event_id": "torn", "se')
        report = self._report("notes.jsonl")
        self.assertEqual(report["status"], "REPAIRED")
        self.assertEqual(self.notes.read_bytes(), self.good)

    # Special files --------------------------------------------------------------------
    def test_fifo_ledger_is_reported_not_waited_on(self):
        os.mkfifo(self.home / "asks-2026-11.jsonl", 0o600)
        self._assert_left_alone("asks-2026-11.jsonl", self._snapshot())

    def test_directory_named_like_a_ledger_is_reported(self):
        (self.home / "asks-2026-11.jsonl").mkdir(mode=0o700)
        self._assert_left_alone("asks-2026-11.jsonl", self._snapshot())

    def test_symlink_to_a_torn_file_outside_home_is_not_adopted(self):
        outside = self.root / "outside.jsonl"
        outside.write_bytes(self.good + b'{"event_id": "x", "se')
        outside.chmod(0o600)
        os.unlink(self.notes)
        self.notes.symlink_to(outside)
        before = self._snapshot()
        self._assert_left_alone("notes.jsonl", before)
        self.assertTrue(self.notes.is_symlink())
        self.assertEqual(outside.read_bytes(), self.good + b'{"event_id": "x", "se')

    def test_symlink_to_an_intact_ledger_outside_home_is_not_ok(self):
        outside = self.root / "outside.jsonl"
        shutil.copy2(self.notes, outside)
        os.unlink(self.notes)
        self.notes.symlink_to(outside)
        self._assert_left_alone("notes.jsonl", self._snapshot())

    # Permissions ----------------------------------------------------------------------
    def test_group_writable_torn_ledger_is_not_laundered(self):
        with self.notes.open("ab") as stream:
            stream.write(b'{"event_id": "torn", "se')
        self.notes.chmod(0o620)
        self._assert_left_alone("notes.jsonl", self._snapshot())

    def test_world_writable_torn_ledger_is_not_laundered(self):
        with self.notes.open("ab") as stream:
            stream.write(b'{"event_id": "torn", "se')
        self.notes.chmod(0o606)
        self._assert_left_alone("notes.jsonl", self._snapshot())

    # Records --------------------------------------------------------------------------
    def test_terminated_invalid_last_record_is_not_dropped(self):
        # An interrupted append never ends with "\n"; a complete bad line is damage.
        for tail in (b"garbage\n", b'{"seq": 3}\n', b"[1, 2]\n", b'"text"\n'):
            with self.subTest(tail=tail):
                self.notes.write_bytes(self.good + tail)
                self._assert_left_alone("notes.jsonl", self._snapshot())

    def test_torn_tail_after_a_damaged_earlier_record_is_not_repaired(self):
        lines = self.good.split(b"\n")
        for name, bad in (
            ("duplicate key", lines[0][:-1] + b', "event_id": "other"}'),
            ("blank line", b""),
            ("not utf-8", lines[0][:-1] + b', "x": "\xff"}'),
            ("duplicate event_id", lines[0] + b"\n" + lines[0]),
        ):
            with self.subTest(name=name):
                damaged = b"\n".join([bad] + lines[1:]) + b'{"event_id": "torn", "se'
                self.notes.write_bytes(damaged)
                self._assert_left_alone("notes.jsonl", self._snapshot())
                self.assertEqual(self.notes.read_bytes(), damaged)

    def test_torn_tail_after_a_sequence_gap_is_not_repaired(self):
        lines = [json.loads(line) for line in self.good.splitlines()]
        lines[1]["seq"] = 7
        body = "".join(json.dumps(e, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n" for e in lines)
        damaged = body.encode("utf-8") + b'{"event_id": "torn", "se'
        self.notes.write_bytes(damaged)
        self._assert_left_alone("notes.jsonl", self._snapshot())

    def test_inspect_alone_is_prompt_and_read_only_for_a_fifo(self):
        fifo = self.home / "asks-2026-11.jsonl"
        os.mkfifo(fifo, 0o600)
        hung, out = _call_with_deadline(lambda: inspect(fifo), fifo)
        self.assertFalse(hung, "inspect blocked on a FIFO")
        self.assertNotIn("error", out, repr(out.get("error")))
        self.assertEqual(out["value"]["status"], "DAMAGED")


class ConfigOracleTests(_HomeBase):
    def setUp(self):
        super().setUp()
        cfg.save(self.home, dict(cfg.DEFAULTS, model="qwen3:1.7b", num_thread=2))
        self.path = self.home / "config.json"

    def _load(self):
        hung, out = _call_with_deadline(lambda: cfg.load(self.home, wait_s=1.0), self.path)
        self.assertFalse(hung, "config.load blocked on a special file")
        return out

    def _assert_refused(self):
        out = self._load()
        self.assertNotIn("value", out, f"damaged config.json was accepted: {out.get('value')!r}")
        self.assertIsInstance(out["error"], cfg.ConfigError, repr(out["error"]))

    def test_control_saved_config_loads(self):
        out = self._load()
        self.assertEqual(out["value"]["num_thread"], 2)

    def test_duplicate_key_is_refused(self):
        self.path.write_text('{"ollama_url": "http://127.0.0.1:11434", "ollama_url": "http://127.0.0.1:9"}\n',
                             encoding="utf-8")
        self._assert_refused()

    def test_repeated_identical_key_is_refused(self):
        self.path.write_text('{"num_thread": 2, "num_thread": 2}\n', encoding="utf-8")
        self._assert_refused()

    def test_group_or_world_writable_config_is_refused(self):
        for mode in (0o620, 0o602, 0o666):
            with self.subTest(mode=oct(mode)):
                self.path.chmod(mode)
                self._assert_refused()

    def test_fifo_config_is_refused_promptly(self):
        os.unlink(self.path)
        os.mkfifo(self.path, 0o600)
        self._assert_refused()

    def test_symlinked_config_is_refused(self):
        outside = self.root / "outside.json"
        outside.write_text("{}\n", encoding="utf-8")
        os.unlink(self.path)
        self.path.symlink_to(outside)
        self._assert_refused()

    def test_non_utf8_config_is_refused(self):
        self.path.write_bytes(b'{"model": "\xff"}\n')
        self._assert_refused()


if __name__ == "__main__":
    unittest.main()
