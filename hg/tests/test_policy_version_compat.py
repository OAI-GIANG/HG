"""Policy-version compatibility of persisted hg runtime state (migration guard).

hg serve restores tasks.jsonl through maep.task_store.TaskStore.restore, which rejects any
event recorded under another policy version (MAEP-012). So a POLICY_VERSION change on main
cannot reuse an existing state directory: it needs a fresh state directory (the old one
kept as archive) or an explicit, versioned ledger migration. This test pins that at the
runtime startup path so a version change cannot silently skip the migration decision.
"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from maep.core import MAEPError, POLICY_VERSION
from hg.runtime import build_runtime

REPO_ROOT = Path(__file__).resolve().parents[2]


class PolicyVersionCompatibilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory(prefix="hg-policy-compat-")
        cls.base = Path(cls._tmp.name)
        subprocess.run([sys.executable, "-B", "-m", "hg", "selfcheck", "--workdir", str(cls.base / "wd")],
                       cwd=REPO_ROOT, check=True, capture_output=True, timeout=300)
        cls.state = cls.base / "wd" / "authorized"

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def copy_state(self, name, *, policy_version=None):
        target = self.base / name
        target.mkdir()
        for ledger in ("tasks.jsonl", "actions.jsonl"):
            lines = (self.state / ledger).read_text(encoding="utf-8").splitlines()
            if ledger == "tasks.jsonl" and policy_version is not None:
                events = [json.loads(line) for line in lines if line.strip()]
                for event in events:
                    event["policy_version"] = policy_version
                lines = [json.dumps(event, sort_keys=True) for event in events]
            (target / ledger).write_text("\n".join(lines) + "\n", encoding="utf-8")
        return target

    def test_state_written_under_the_current_policy_restores(self):
        versions = {json.loads(line)["policy_version"] for line in
                    (self.state / "tasks.jsonl").read_text().splitlines() if line.strip()}
        self.assertEqual(versions, {POLICY_VERSION})
        build_runtime(self.copy_state("same"), [], allow_fixture_grants=True)

    def test_state_written_under_another_policy_blocks_startup(self):
        for other in ("MAEP-1.0.0", "MAEP-1.2.0"):
            with self.subTest(recorded_under=other):
                with self.assertRaisesRegex(MAEPError, "MAEP-012"):
                    build_runtime(self.copy_state("other-" + other, policy_version=other), [],
                                  allow_fixture_grants=True)

    def test_a_fresh_state_directory_starts_under_the_current_policy(self):
        fresh = self.base / "fresh"
        fresh.mkdir()
        build_runtime(fresh, [], allow_fixture_grants=True)

    def test_only_the_task_ledger_is_policy_version_bound(self):
        # Migration scope today: actions.jsonl events carry no policy_version field.
        events = [json.loads(line) for line in (self.state / "actions.jsonl").read_text().splitlines() if line.strip()]
        self.assertTrue(events)
        self.assertFalse(any("policy_version" in event for event in events))


if __name__ == "__main__":
    unittest.main()
