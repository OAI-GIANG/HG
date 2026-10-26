"""acceptance-provider for runtime.service: approved evidence per criterion + independent read-back.

MAEP-022 decision EXTEND_EXISTING (gate record:
docs/architecture/MAEP022_GATE_RECORD_FS_WRITE_ACCEPTANCE_20261026.md). Semantics follow
the deployed `hg serve` acceptance (`hg/verification/evidence.py` AcceptanceGate with
`planned_write_readback_verifier`): one gate per mandatory criterion, built only from
candidate-bound evidence of the matching type that names the criterion, and no gate
passes unless every effect the task produced has been read back independently from
live state. Memory then re-checks coverage, evaluate_gate and validate_closure itself.

What counts as evidence for criterion C of task T:
  * a Memory evidence record of T, bound to T's candidate and to an intact ledger event,
  * approved by the configured approved-memory-record verifier (D4) under the active,
    D2-verified policy and root (the same provenance check authority uses),
  * evidence_type listed in C.evidence_types, and `result` a JSON object naming C's id
    in `criterion_refs`; `"status": "PASS"` supports C, any other status is a failing
    result, and one failing result fails C even beside a passing one (as on main).

Independent read-back (verifier `hg.runtime.acceptance.readback-v1`): every effect
receipt of T in the receipt ledger is inspected. An UNKNOWN outcome (unreconciled)
blocks every gate; a SUCCESS from an adapter with no read-back verifier blocks; for
each written path the latest SUCCESS digest must equal the file's live SHA-256 under
the adapter's root, else every gate FAILs. The provider never writes anything.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from typing import Any

from maep.core import POLICY_VERSION
from maep.native_authority import AuthorityError

VERIFIER = "hg.runtime.acceptance.readback-v1"
_LIMITATIONS = [
    "Read-back proves the live file content equals the recorded effect digest at acceptance time only.",
    "Evidence approval is as strong as the configured approved-memory-record verifier (D4).",
]


class ReadbackAcceptanceProvider:
    def __init__(self, *, reader: Any, record_resolver: Any, provenance_verifier: Any, root_store: Any,
                 policy_provider: Any, receipt_sink: Any, file_adapters: dict[str, Any]):
        for name, value, method in (("reader", reader, "get_task"), ("reader", reader, "get_events"),
                                    ("record_resolver", record_resolver, "resolve_task_evidence"),
                                    ("provenance_verifier", provenance_verifier, "validate_record_provenance"),
                                    ("root_store", root_store, "load_active"),
                                    ("policy_provider", policy_provider, "load_active"),
                                    ("receipt_sink", receipt_sink, "read_all")):
            if not callable(getattr(value, method, None)):
                raise AuthorityError(f"acceptance provider requires {name}.{method}")
        if not isinstance(file_adapters, dict) or any(
                not callable(getattr(adapter, "relative", None)) for adapter in file_adapters.values()):
            raise AuthorityError("acceptance provider file adapters must expose relative()")
        self.reader, self.record_resolver = reader, record_resolver
        self.provenance_verifier, self.root_store = provenance_verifier, root_store
        self.policy_provider, self.receipt_sink = policy_provider, receipt_sink
        self.file_adapters = dict(file_adapters)

    # -- independent read-back ---------------------------------------------------------
    def readback(self, task_id: str, candidate_ref: str) -> dict[str, Any]:
        # Rows are BrainOrchestrator envelopes {"event_type": "brain.effect.receipt", "payload": receipt}
        # in an integrity-checked ledger (read_all verifies the digest chain).
        receipts, reconciliations = [], []
        for row in self.receipt_sink.read_all():
            payload = row.get("payload") if isinstance(row, dict) else None
            if row.get("event_type") != "brain.effect.receipt" or not isinstance(payload, dict):
                raise AuthorityError("receipt ledger contains an unexpected record")
            if payload.get("task_ref") == task_id and str(payload.get("receipt_id", "")).startswith("effect:"):
                receipts.append(payload)
            elif payload.get("task_ref") == task_id and str(payload.get("receipt_id", "")).startswith("reconcile:"):
                reconciliations.append(payload)
        findings = {r.get("idempotency_key"): r.get("finding") for r in reconciliations}
        latest: dict[tuple[str, str], tuple[str, str]] = {}
        for receipt in receipts:
            outcome = receipt.get("outcome")
            result = receipt.get("adapter_receipt") or {}
            if outcome == "UNKNOWN":
                finding = findings.get(receipt.get("idempotency_key"))
                if finding == "NOT_APPLIED":
                    continue
                if finding != "APPLIED":
                    return {"status": "BLOCKED", "reason": "unreconciled UNKNOWN effect", "checked": 0}
                intent = receipt.get("intent") or {}
                path, digest = intent.get("path"), intent.get("sha256")    # live state confirmed the intent
            elif outcome == "SUCCESS":
                path, digest = result.get("path"), result.get("provider_ref")
            else:
                continue
            if receipt.get("adapter") not in self.file_adapters:
                return {"status": "BLOCKED", "reason": "no read-back verifier for adapter "
                        + str(receipt.get("adapter")), "checked": 0}
            if receipt.get("candidate_ref") != candidate_ref:
                return {"status": "FAIL", "reason": "effect belongs to another candidate", "checked": 0}
            latest[(receipt["adapter"], str(path))] = (str(path), digest)
        for (name, _key), (path, digest) in sorted(latest.items()):
            try:
                _rel, full = self.file_adapters[name].relative(path)
                observed = "sha256:" + hashlib.sha256(full.read_bytes()).hexdigest()
            except Exception:
                return {"status": "FAIL", "reason": f"written file unreadable: {path}", "checked": 0}
            if observed != digest:
                return {"status": "FAIL", "reason": f"live content differs from the recorded effect: {path}",
                        "checked": 0}
        return {"status": "PASS", "reason": "all effects read back", "checked": len(latest)}

    # -- evidence ------------------------------------------------------------------------
    def _approved_evidence(self, task_id: str, candidate_ref: str, root: Any, policy: dict) -> dict[str, dict]:
        ids: list[str] = []
        for event in self.reader.get_events(task_id, limit=1000):
            payload = event.get("payload") if isinstance(event, dict) else None
            if event.get("event_type") == "evidence.recorded" and isinstance(payload, dict):
                evidence_id = payload.get("evidence_id")
                if isinstance(evidence_id, str) and evidence_id not in ids:
                    ids.append(evidence_id)
        approved = {}
        for evidence_id in ids:
            record = self.record_resolver.resolve_task_evidence(task_id, evidence_id, candidate_ref=candidate_ref)
            if record is not None and self.provenance_verifier.validate_record_provenance(
                    record, record_type="ACCEPTANCE_EVIDENCE", root=root, policy=policy) is True:
                approved[evidence_id] = record
        return approved

    @staticmethod
    def _verdict(record: dict, criterion: dict) -> str | None:
        """PASS/FAIL when the record is evidence of the criterion's type naming it, else None."""
        if record.get("evidence_type") not in (criterion.get("evidence_types") or []):
            return None
        try:
            result = json.loads(record.get("result"))
        except (TypeError, ValueError):
            return None
        if (not isinstance(result, dict) or not isinstance(result.get("criterion_refs"), list)
                or criterion.get("criterion_id") not in result["criterion_refs"]):
            return None
        return "PASS" if result.get("status") == "PASS" else "FAIL"

    def __call__(self, task_id: str, target: str) -> dict[str, Any]:
        if target not in {"ACCEPTED", "CLOSED_VERIFIED"}:
            raise AuthorityError("acceptance is only evaluated for ACCEPTED or CLOSED_VERIFIED")
        root = self.root_store.load_active()
        policy = self.policy_provider.load_active(root)          # D2: unapproved policy raises
        snapshot = self.reader.get_task(task_id)
        task, candidate_ref = snapshot["task"], snapshot["candidate_ref"]
        approved = self._approved_evidence(task_id, candidate_ref, root, policy)
        readback = self.readback(task_id, candidate_ref)
        gates, results = [], []
        for criterion in task.get("acceptance_criteria", []):
            if not isinstance(criterion, dict) or criterion.get("mandatory") is not True:
                continue
            verdicts = {eid: self._verdict(record, criterion) for eid, record in approved.items()}
            refs = sorted(eid for eid, verdict in verdicts.items() if verdict == "PASS")
            failing = any(verdict == "FAIL" for verdict in verdicts.values())   # a FAIL beside a PASS fails
            status = ("BLOCKED" if readback["status"] == "BLOCKED"
                      else "PASS" if refs and not failing and readback["status"] == "PASS" else "FAIL")
            if status != "PASS":
                refs = sorted(eid for eid, verdict in verdicts.items() if verdict is not None)
            gates.append({"gate_id": f"acceptance:{task_id}:{criterion['criterion_id']}", "task_id": task_id,
                          "candidate_ref": candidate_ref, "required": True, "status": status,
                          "criteria_refs": [criterion["criterion_id"]], "evidence_refs": refs,
                          "verifier": VERIFIER, "readback": dict(readback)})
            results.append({"criterion_id": criterion["criterion_id"], "status": status, "evidence_refs": refs})
        closure = None
        if gates and all(gate["status"] == "PASS" for gate in gates):
            closure = {"task_id": task_id, "final_state": "CLOSED_VERIFIED", "candidate_ref": candidate_ref,
                       "policy_version": POLICY_VERSION, "criteria_results": results,
                       "evidence_refs": sorted({ref for item in results for ref in item["evidence_refs"]}),
                       "limitations": list(_LIMITATIONS), "verifier": VERIFIER,
                       "closed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")}
        return {"candidate_ref": candidate_ref, "policy_version": POLICY_VERSION,
                "mandatory_gates": gates, "closure": closure}


def build_acceptance_provider(*, config: dict[str, Any], policy_verifier: Any, memory_verifier: Any,
                              file_adapters: dict[str, Any]) -> ReadbackAcceptanceProvider:
    """Builder used by compose callers: same root/policy/Memory/receipt sources as the runtime."""
    from maep.local_authority_store import LocalRootStore
    from maep.local_runtime_providers import LocalPolicyProvider, LocalReceiptSink
    from maep.memory_evidence_providers import (CanonicalMemoryTaskSelectors, MemoryLedgerProvenanceVerifier,
                                                MemoryMAEPRecordResolver)
    from memory import AuthorityEvidenceReader

    reader = AuthorityEvidenceReader(config["memory_db"])
    selectors = CanonicalMemoryTaskSelectors(memory_store=reader, canonical_task_id_source=reader)
    return ReadbackAcceptanceProvider(
        reader=reader, record_resolver=MemoryMAEPRecordResolver(memory_store=reader, selectors=selectors),
        provenance_verifier=MemoryLedgerProvenanceVerifier(memory_verifier),
        root_store=LocalRootStore(config["authority_dir"]),
        policy_provider=LocalPolicyProvider(config["policy_path"], policy_verifier),
        receipt_sink=LocalReceiptSink(config["receipts_dir"]), file_adapters=file_adapters)
