"""Unit refusals of ReadbackAcceptanceProvider with in-memory sources."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from maep.native_authority import AuthorityError
from runtime.acceptance import ReadbackAcceptanceProvider
from tools_automation.file_write_adapter import RootedFileWriteAdapter

CAND = "cand-1"
CRITERION = {"criterion_id": "AC-1", "mandatory": True, "evidence_types": ["TEST_RESULT"]}


class Reader:
    def __init__(self, evidence_ids):
        self.evidence_ids = evidence_ids

    def get_task(self, task_id):
        return {"task": {"task_id": task_id, "acceptance_criteria": [CRITERION,
                         {"criterion_id": "AC-OPT", "mandatory": False}]}, "candidate_ref": CAND}

    def get_events(self, task_id, *, limit):
        return [{"event_type": "evidence.recorded", "payload": {"evidence_id": e}} for e in self.evidence_ids]


class Resolver:
    def __init__(self, records):
        self.records = records

    def resolve_task_evidence(self, task_id, evidence_id, *, candidate_ref=None):
        return self.records.get(evidence_id)


class Provenance:
    def __init__(self, approved):
        self.approved = approved

    def validate_record_provenance(self, record, *, record_type, root, policy):
        return record["evidence_id"] in self.approved


class Source:
    def __init__(self, value):
        self.value = value

    def load_active(self, *args):
        if isinstance(self.value, Exception):
            raise self.value
        return self.value


class Receipts:
    def __init__(self, rows):
        self.rows = rows

    def read_all(self):
        return list(self.rows)


def evidence(evidence_id, *, status="PASS", criteria=("AC-1",), etype="TEST_RESULT"):
    return {"evidence_id": evidence_id, "candidate_ref": CAND, "evidence_type": etype,
            "result": json.dumps({"status": status, "criterion_refs": list(criteria)})}


def effect(outcome="SUCCESS", *, adapter="fs.write", path="out/a.txt", digest=None, candidate=CAND, task="T-1"):
    payload = {"receipt_id": "effect:k", "task_ref": task, "adapter": adapter, "outcome": outcome,
               "candidate_ref": candidate,
               "adapter_receipt": {"outcome": outcome, "path": path, "provider_ref": digest}}
    return {"event_type": "brain.effect.receipt", "payload": payload}


class AcceptanceProviderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="hg-accept-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "out").mkdir()
        (self.root / "out/a.txt").write_text("A")
        self.digest = "sha256:" + hashlib.sha256(b"A").hexdigest()

    def provider(self, *, records=None, approved=("EV-R",), rows=(), policy=None):
        records = records if records is not None else {"EV-R": evidence("EV-R")}
        return ReadbackAcceptanceProvider(
            reader=Reader(list(records)), record_resolver=Resolver(records), provenance_verifier=Provenance(set(approved)),
            root_store=Source("root"), policy_provider=Source(policy or {"version": "v"}),
            receipt_sink=Receipts(rows), file_adapters={"fs.write": RootedFileWriteAdapter(self.root)})

    def gate(self, provider, target="ACCEPTED"):
        context = provider("T-1", target)
        [gate] = context["mandatory_gates"]          # optional criteria get no gate
        return gate, context

    def test_pass_requires_approved_matching_evidence_and_readback(self):
        gate, context = self.gate(self.provider(rows=[effect(digest=self.digest)]))
        self.assertEqual((gate["status"], gate["evidence_refs"], gate["readback"]["checked"]), ("PASS", ["EV-R"], 1))
        self.assertEqual(context["closure"]["criteria_results"][0]["status"], "PASS")

    def test_evidence_that_does_not_qualify_is_not_counted(self):
        for records, approved, cited in (({"EV-R": evidence("EV-R")}, (), []),             # not approved (D4)
                                         ({"EV-R": evidence("EV-R", status="FAIL")}, ("EV-R",), ["EV-R"]),
                                         ({"EV-R": evidence("EV-R", criteria=("AC-2",))}, ("EV-R",), []),
                                         ({"EV-R": evidence("EV-R", etype="OBSERVATION")}, ("EV-R",), []),
                                         ({"EV-R": dict(evidence("EV-R"), result="not json")}, ("EV-R",), []),
                                         ({}, (), [])):
            with self.subTest(records=records, approved=approved):
                gate, context = self.gate(self.provider(records=records, approved=approved))
                # a failing result is cited by the FAIL gate; non-qualifying records are not
                self.assertEqual((gate["status"], gate["evidence_refs"], context["closure"]), ("FAIL", cited, None))

    def test_failing_evidence_fails_even_beside_a_pass(self):
        records = {"EV-R": evidence("EV-R"), "EV-F": evidence("EV-F", status="FAIL")}
        gate, context = self.gate(self.provider(records=records, approved=("EV-R", "EV-F")))
        self.assertEqual((gate["status"], gate["evidence_refs"], context["closure"]), ("FAIL", ["EV-F", "EV-R"], None))
        # an unapproved failing record does not count either way
        gate, _ = self.gate(self.provider(records=records, approved=("EV-R",)))
        self.assertEqual(gate["status"], "PASS")

    def test_readback_failures(self):
        cases = {
            "content changed": ([effect(digest="sha256:" + "0" * 64)], "FAIL"),
            "other candidate": ([effect(digest=self.digest, candidate="cand-2")], "FAIL"),
            "file missing": ([effect(digest=self.digest, path="out/missing.txt")], "FAIL"),
            "escaping path": ([effect(digest=self.digest, path="../a.txt")], "FAIL"),
            "unknown outcome": ([effect("UNKNOWN")], "BLOCKED"),
            "no verifier for adapter": ([effect(adapter="shell.exec", digest=self.digest)], "BLOCKED"),
        }
        for name, (rows, expected) in cases.items():
            with self.subTest(name):
                gate, context = self.gate(self.provider(rows=rows))
                self.assertEqual((gate["status"], context["closure"]), (expected, None))
        # another task's effects and non-effect receipts are ignored
        gate, _ = self.gate(self.provider(rows=[effect("UNKNOWN", task="T-2"),
                                                {"event_type": "brain.effect.receipt",
                                                 "payload": {"receipt_id": "deny:x", "task_ref": "T-1"}}]))
        self.assertEqual(gate["status"], "PASS")

    def test_latest_write_per_path_decides(self):
        rows = [effect(digest="sha256:" + "0" * 64), effect(digest=self.digest)]
        self.assertEqual(self.gate(self.provider(rows=rows))[0]["status"], "PASS")

    def test_fail_closed_on_bad_sources_and_targets(self):
        with self.assertRaises(AuthorityError):
            self.provider(rows=[{"event_type": "other", "payload": {}}])("T-1", "ACCEPTED")
        with self.assertRaises(AuthorityError):
            self.provider()("T-1", "RUNNING")
        provider = self.provider()
        provider.policy_provider = Source(AuthorityError("policy not approved"))
        with self.assertRaises(AuthorityError):
            provider("T-1", "ACCEPTED")
        with self.assertRaises(AuthorityError):
            ReadbackAcceptanceProvider(reader=object(), record_resolver=None, provenance_verifier=None,
                                       root_store=None, policy_provider=None, receipt_sink=None, file_adapters={})


if __name__ == "__main__":
    unittest.main()
