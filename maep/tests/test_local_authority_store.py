"""Isolated tests for the local file-backed authority stores."""
from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest

from maep.local_authority_store import LocalEvidenceSink, LocalRootStore
from maep.native_authority import AuthorityError, TrustRootManager
from maep.local_owner_authority import LocalOwnerApprovalSource


class TempOwnerSource:
    def __init__(self, source):
        self.source = source

    def validate_owner_approval(self, canonical_payload, approval):
        return self.source.validate_owner_approval(canonical_payload, approval)


class LocalAuthorityStoreTests(unittest.TestCase):
    def test_bootstrap_root_readback_and_evidence_integrity_in_temp_directory(self):
        with tempfile.TemporaryDirectory(prefix="hg-authority-test-") as temp:
            temp_path = Path(temp)
            source_path = temp_path / "owner-bootstrap.json"
            source_data = {
                "schema_version": "hg.local-owner-bootstrap-source.v1",
                "repository": "OAI-GIANG/HG",
                "device_scope": "this-phone-local-only",
                "decision": "APPROVE",
                "action": "bootstrap_initial_trust_root",
                "authorization_basis": "isolated unit test",
                "authorization_ref": "owner-local:test",
                "approved_at": "2026-10-23T00:00:00Z",
                "root_payload": {
                    "root_id": "hg-test-root",
                    "generation": 1,
                    "created_at": "2026-10-23T00:00:00Z",
                    "bootstrap_authorization_ref": "owner-local:test",
                    "verification_method": "local-owner-source-v1",
                    "verification_material_ref": "file://test-owner-source",
                    "policy_change_rule_ref": "file://test-policy-rule",
                    "previous_root_digest": None,
                },
                "activation_status": "SOURCE_CREATED_ROOT_NOT_PROVISIONED",
                "limitations": "test-only",
            }
            source_path.write_text(json.dumps(source_data), encoding="utf-8")
            source_path.chmod(0o600)
            owner_source = LocalOwnerApprovalSource(source_path)
            root_store = LocalRootStore(temp_path / "root-store")
            evidence = LocalEvidenceSink(temp_path / "evidence")
            manager = TrustRootManager(root_store, TempOwnerSource(owner_source), evidence)

            root = manager.bootstrap(source_data["root_payload"], source_data)
            self.assertTrue(root.verify_integrity())
            reloaded = root_store.load_active()
            self.assertIsNotNone(reloaded)
            self.assertEqual(reloaded.record_digest, root.record_digest)
            self.assertTrue(evidence.verify_integrity())
            self.assertEqual(len(evidence._read_events()), 1)
            self.assertIn("hg-local-evidence:1:", root.evidence_ref)

            with self.assertRaisesRegex(AuthorityError, "already exists"):
                manager.bootstrap(source_data["root_payload"], source_data)

    def test_root_tamper_is_detected(self):
        with tempfile.TemporaryDirectory(prefix="hg-root-tamper-") as temp:
            store = LocalRootStore(temp)
            from maep.native_authority import TrustRootRecord
            root = TrustRootRecord.create(
                root_id="root-test", generation=1, created_at="2026-10-23T00:00:00Z",
                bootstrap_authorization_ref="owner:test",
                verification_method="test", verification_material_ref="test://material",
                policy_change_rule_ref="test://policy", evidence_ref="test://evidence",
            )
            store.store_active(root)
            value = json.loads(store.root_path.read_text(encoding="utf-8"))
            value["root_id"] = "tampered"
            store.root_path.write_text(json.dumps(value), encoding="utf-8")
            store.root_path.chmod(0o600)
            with self.assertRaises(AuthorityError):
                store.load_active()

    def test_evidence_tamper_is_detected(self):
        with tempfile.TemporaryDirectory(prefix="hg-evidence-tamper-") as temp:
            sink = LocalEvidenceSink(temp)
            sink.append({"event_type": "test", "payload": {"x": 1}})
            self.assertTrue(sink.verify_integrity())
            lines = sink.ledger_path.read_text(encoding="utf-8").splitlines()
            event = json.loads(lines[0])
            event["payload"]["x"] = 2
            sink.ledger_path.write_text(json.dumps(event) + "\n", encoding="utf-8")
            sink.ledger_path.chmod(0o600)
            with self.assertRaises(AuthorityError):
                sink.verify_integrity()

    def test_concurrent_evidence_appends_keep_ledger_sequential_and_intact(self):
        # runtime.http_server uses ThreadingHTTPServer and NativePolicyEngine appends
        # evidence on every decision, so concurrent appends must not corrupt the ledger.
        import threading
        with tempfile.TemporaryDirectory(prefix="hg-evidence-concurrency-") as temp:
            workers, per_worker = 12, 15
            barrier = threading.Barrier(workers)
            refs: list[str] = []
            errors: list[BaseException] = []
            guard = threading.Lock()

            def worker(index: int) -> None:
                sink = LocalEvidenceSink(temp)  # separate instance per caller
                try:
                    barrier.wait()
                    for step in range(per_worker):
                        ref = sink.append({"event_type": "concurrency.test",
                                           "payload": {"worker": index, "step": step}})
                        with guard:
                            refs.append(ref)
                except BaseException as exc:  # recorded and asserted below
                    with guard:
                        errors.append(exc)

            threads = [threading.Thread(target=worker, args=(i,)) for i in range(workers)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=60)
            self.assertFalse(any(thread.is_alive() for thread in threads))
            self.assertEqual(errors, [])
            total = workers * per_worker
            self.assertEqual(len(refs), total)
            self.assertEqual(len(set(refs)), total)
            reopened = LocalEvidenceSink(temp)
            self.assertTrue(reopened.verify_integrity())
            events = reopened._read_events()
            self.assertEqual([event["sequence"] for event in events], list(range(1, total + 1)))
            # The ledger stays usable after the concurrent burst.
            reopened.append({"event_type": "concurrency.after", "payload": {}})
            self.assertTrue(LocalEvidenceSink(temp).verify_integrity())

    def test_concurrent_evidence_appends_from_separate_processes_stay_intact(self):
        import subprocess
        import sys
        with tempfile.TemporaryDirectory(prefix="hg-evidence-processes-") as temp:
            repo_root = str(Path(__file__).resolve().parents[2])
            script = (
                "import sys\n"
                "from maep.local_authority_store import LocalEvidenceSink\n"
                "sink = LocalEvidenceSink(sys.argv[1])\n"
                "for step in range(25):\n"
                "    sink.append({'event_type': 'process.test', 'payload': {'step': step}})\n"
            )
            env = dict(os.environ, PYTHONPATH=repo_root, PYTHONDONTWRITEBYTECODE="1")
            procs = [subprocess.Popen([sys.executable, "-c", script, temp], env=env,
                                      stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                     for _ in range(4)]
            results = [proc.communicate(timeout=120) for proc in procs]
            for proc, (_, stderr) in zip(procs, results):
                self.assertEqual(proc.returncode, 0, stderr.decode("utf-8", "replace")[-400:])
            sink = LocalEvidenceSink(temp)
            self.assertTrue(sink.verify_integrity())
            self.assertEqual([event["sequence"] for event in sink._read_events()],
                             list(range(1, 101)))

    def test_symlinked_evidence_ledger_is_refused_without_writing_target(self):
        with tempfile.TemporaryDirectory(prefix="hg-evidence-symlink-") as temp:
            target = Path(temp) / "elsewhere.jsonl"
            target.write_text("", encoding="utf-8")
            directory = Path(temp) / "evidence"
            directory.mkdir()
            (directory / "evidence.jsonl").symlink_to(target)
            with self.assertRaises(AuthorityError):
                LocalEvidenceSink(directory).append({"event_type": "test", "payload": {}})
            self.assertEqual(target.read_text(encoding="utf-8"), "")
            self.assertFalse((directory / "evidence-head.json").exists())

    def test_root_store_refuses_overwrite(self):
        with tempfile.TemporaryDirectory(prefix="hg-root-no-overwrite-") as temp:
            from maep.native_authority import TrustRootRecord
            store = LocalRootStore(temp)
            root = TrustRootRecord.create(
                root_id="root-test", generation=1, created_at="2026-10-23T00:00:00Z",
                bootstrap_authorization_ref="owner:test",
                verification_method="test", verification_material_ref="test://material",
                policy_change_rule_ref="test://policy", evidence_ref="test://evidence",
            )
            store.store_active(root)
            with self.assertRaisesRegex(AuthorityError, "overwrite"):
                store.store_active(root)



class FindDecisionTests(unittest.TestCase):
    def append(self, sink, event_type, **payload):
        sink.append({"event_type": event_type, "payload": payload})

    def test_finds_only_allow_decisions_in_an_intact_ledger(self):
        with tempfile.TemporaryDirectory() as temp:
            sink = LocalEvidenceSink(temp)
            digest = "sha256:" + "a" * 64
            self.assertIsNone(sink.find_decision(digest))            # no ledger yet
            self.append(sink, "authorization.deny", decision="DENY", decision_digest=digest)
            self.assertIsNone(sink.find_decision(digest))            # non-ALLOW events never match
            self.append(sink, "authorization.decision", decision="ALLOW", decision_digest=digest)
            self.assertEqual(sink.find_decision(digest)["decision"], "ALLOW")
            for bad in ("", "sha256:" + "A" * 64, "md5:" + "a" * 64, None, "sha256:" + "a" * 63):
                with self.assertRaises(AuthorityError):
                    sink.find_decision(bad)

    def test_head_mismatch_or_symlinked_ledger_blocks(self):
        with tempfile.TemporaryDirectory() as temp:
            sink = LocalEvidenceSink(Path(temp) / "a")
            digest = "sha256:" + "b" * 64
            self.append(sink, "authorization.decision", decision="ALLOW", decision_digest=digest)
            sink.head_path.write_text(json.dumps({"last_sequence": 9, "last_event_digest": None}))
            with self.assertRaises(AuthorityError):
                sink.find_decision(digest)
            other = LocalEvidenceSink(Path(temp) / "b")
            other.directory.mkdir()
            other.ledger_path.symlink_to(sink.ledger_path)
            with self.assertRaises(AuthorityError):
                other.find_decision(digest)


if __name__ == "__main__":
    unittest.main()
