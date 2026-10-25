"""Guard: the committed owner manifest must load under the policy the code enforces.

The trust anchor rejects a manifest whose policy_version differs from SUPPORTED_POLICY,
and authorize() rejects requests whose policy_version (maep.core.POLICY_VERSION) differs
from the manifest. Fixture-based tests cannot see a mismatch between the code and the
committed maep/authority/owner-grants.json, so this test reads the real file.
"""
from pathlib import Path
import unittest

from maep.authority import trust_anchor
from maep.core import POLICY_VERSION

MANIFEST = Path(__file__).resolve().parents[2] / "maep" / "authority" / "owner-grants.json"


class CommittedOwnerManifestPolicyTests(unittest.TestCase):
    def test_code_policy_versions_agree(self):
        self.assertEqual(POLICY_VERSION, trust_anchor.SUPPORTED_POLICY)

    def test_committed_manifest_loads_under_supported_policy(self):
        body = MANIFEST.read_text(encoding="utf-8")
        doc = trust_anchor.load_manifest(lambda path: (200, body))
        self.assertEqual(doc["policy_version"], trust_anchor.SUPPORTED_POLICY)
        self.assertEqual(doc["policy_version"], POLICY_VERSION)


if __name__ == "__main__":
    unittest.main()
