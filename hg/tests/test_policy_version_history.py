"""Opt-in replay of earlier-policy task history as read-only (MAEP-012 migration path).

The policy-version bump itself is not made here: it is simulated by patching
maep.task_store.POLICY_VERSION to "MAEP-1.2.0" over a ledger the real code wrote under
MAEP-1.1.0 (`hg selfcheck`). Defaults are unchanged: without `history_versions`
restore still refuses another version (see test_policy_version_compat).
"""
import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from maep.core import MAEPError, POLICY_VERSION
from maep.task_store import TaskStore
from hg.tests.support import make_task, write_step
from hg.tests.test_gateway import GatewayFixture

REPO_ROOT = Path(__file__).resolve().parents[2]
NEXT = "MAEP-1.2.0"


class PolicyVersionHistoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory(prefix="hg-policy-history-")
        cls.base = Path(cls._tmp.name)
        subprocess.run([sys.executable, "-B", "-m", "hg", "selfcheck", "--workdir", str(cls.base / "wd")],
                       cwd=REPO_ROOT, check=True, capture_output=True, timeout=300)
        cls.source = cls.base / "wd" / "authorized" / "tasks.jsonl"
        cls.count = 0

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def ledger(self, lines=None):
        type(self).count += 1
        path = self.base / f"case-{self.count}" / "tasks.jsonl"
        path.parent.mkdir()
        path.write_text(self.source.read_text(encoding="utf-8") if lines is None else
                        "".join(json.dumps(e, sort_keys=True) + "\n" for e in lines), encoding="utf-8")
        return path

    def events(self):
        return [json.loads(line) for line in self.source.read_text(encoding="utf-8").splitlines()]

    def test_fixture_is_written_under_the_current_policy(self):
        self.assertEqual(POLICY_VERSION, "MAEP-1.1.0")
        self.assertEqual({e["policy_version"] for e in self.events()}, {"MAEP-1.1.0"})

    def test_after_a_bump_the_old_ledger_is_refused_by_default(self):
        with patch("maep.task_store.POLICY_VERSION", NEXT):
            with self.assertRaisesRegex(MAEPError, "MAEP-012"):
                TaskStore.restore(self.ledger())

    def test_declared_history_replays_as_read_only_and_keeps_the_ledger_intact(self):
        path = self.ledger()
        before = path.read_bytes()
        reference = TaskStore.restore(self.ledger()).snapshot("SC-1")          # unpatched baseline
        with patch("maep.task_store.POLICY_VERSION", NEXT):
            store = TaskStore.restore(path, history_versions={"MAEP-1.1.0"})
            view = store.snapshot("SC-1")
            self.assertEqual((view["policy_status"], view["recorded_policy_version"]), ("STALE", "MAEP-1.1.0"))
            self.assertEqual((view["task"], view["version"], view["closure"]),
                             (reference["task"], reference["version"], reference["closure"]))
        self.assertEqual(path.read_bytes(), before)

    def test_historical_task_in_progress_accepts_no_fact_or_transition(self):
        events = self.events()
        cut = next(i for i, e in enumerate(events) if e["type"] == "TRANSITION" and e["data"]["to"] == "RUNNING")
        path = self.ledger(events[:cut + 1])                      # SC-1 stopped while RUNNING
        before = path.read_bytes()
        with patch("maep.task_store.POLICY_VERSION", NEXT):
            store = TaskStore.restore(path, history_versions={"MAEP-1.1.0"})
            view = store.snapshot("SC-1")
            self.assertEqual((view["task"]["state"], view["policy_status"]), ("RUNNING", "STALE"))
            writer = store.claim_writer()
            for call in (lambda: writer.apply_transition("SC-1", "BLOCKED", expected_version=view["version"]),
                         lambda: writer.record_evidence("SC-1", {"evidence_id": "EV-X"}, expected_version=view["version"])):
                with self.assertRaisesRegex(MAEPError, "read-only history"):
                    call()
        self.assertEqual(path.read_bytes(), before)

    def test_new_work_runs_under_the_new_policy_and_survives_restart(self):
        path = self.ledger()
        with patch("maep.task_store.POLICY_VERSION", NEXT):
            store = TaskStore.restore(path, history_versions={"MAEP-1.1.0"})
            task = make_task("T-NEW")
            task["policy_version"] = NEXT
            writer = store.claim_writer()
            writer.create_task(task)
            self.assertNotIn("policy_status", store.snapshot("T-NEW"))
            with self.assertRaisesRegex(MAEPError, "does not match the store policy"):
                writer.create_task(make_task("T-OLD"))            # new work cannot use the old policy
            restarted = TaskStore.restore(path, history_versions={"MAEP-1.1.0"})
            self.assertEqual(restarted.snapshot("SC-1")["policy_status"], "STALE")
            self.assertNotIn("policy_status", restarted.snapshot("T-NEW"))
            with self.assertRaisesRegex(MAEPError, "MAEP-012"):
                TaskStore.restore(path)                     # history not declared -> refused
        with self.assertRaisesRegex(MAEPError, "MAEP-012"):
            TaskStore.restore(path)                         # a 1.1.0 store cannot read 1.2.0 events
        with self.assertRaisesRegex(MAEPError, "not earlier"):
            TaskStore.restore(path, history_versions={NEXT})

    def test_invalid_history_declarations_are_refused(self):
        for value in ("MAEP-1.0.0", {"1.0.0"}, {"MAEP-1.0"}, {"MAEP-01.0.0"}, {POLICY_VERSION}, {"MAEP-9.0.0"}):
            with self.subTest(value=value):
                with self.assertRaises(MAEPError):
                    TaskStore.restore(self.ledger(), history_versions=value)

    def test_a_task_never_mixes_policy_versions_and_history_must_be_self_consistent(self):
        events = self.events()
        mixed = copy.deepcopy(events)
        mixed[-1]["policy_version"] = NEXT                 # a 1.2.0 event on a 1.1.0 task
        with patch("maep.task_store.POLICY_VERSION", NEXT):
            with self.assertRaisesRegex(MAEPError, "mixes policy versions"):
                TaskStore.restore(self.ledger(mixed), history_versions={"MAEP-1.1.0"})
            forged = copy.deepcopy(events)
            forged[0]["data"]["task"]["policy_version"] = NEXT     # created "under 1.1.0" but claims 1.2.0
            with self.assertRaisesRegex(MAEPError, "recorded policy"):
                TaskStore.restore(self.ledger(forged), history_versions={"MAEP-1.1.0"})
            other = copy.deepcopy(events)
            for event in other:
                event["policy_version"] = "MAEP-1.0.0"
                event["data"].get("task", {}).update(policy_version="MAEP-1.0.0") if "task" in event["data"] else None
            with self.assertRaisesRegex(MAEPError, "MAEP-012"):
                TaskStore.restore(self.ledger(other), history_versions={"MAEP-1.1.0"})   # undeclared version

    def test_torn_or_corrupt_ledger_still_fails_closed_with_history(self):
        path = self.ledger()
        path.write_text(path.read_text(encoding="utf-8") + '{"event_id": "SC-1@99"', encoding="utf-8")
        with patch("maep.task_store.POLICY_VERSION", NEXT):
            with self.assertRaisesRegex(MAEPError, "invalid ledger JSON"):
                TaskStore.restore(path, history_versions={"MAEP-1.1.0"})


class StaleTaskEffectTests(GatewayFixture):
    def test_gateway_refuses_effects_for_historical_tasks(self):
        gw = self.running([write_step()])
        self.rt.store._records["T-1"]["policy_status"] = "STALE"      # as restore marks history
        self.rt.store._records["T-1"]["recorded_policy_version"] = "MAEP-1.0.0"
        outcome = gw.execute("T-1", "S-1")
        self.assertEqual(outcome["status"], "BLOCKED")
        self.assertIn("earlier policy", outcome["reason"])
        self.assertFalse(self.target_file().exists())


if __name__ == "__main__":
    unittest.main()
