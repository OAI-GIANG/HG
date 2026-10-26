"""Adapters from HG's existing Memory evidence ledger to MAEP-022 providers.

These adapters feed NativePolicyEngine while it is deciding, so they read through
``memory.AuthorityEvidenceReader`` (read-only, same integrity checks as the
authorized API) and never through MemoryStore's authorizing API: that API asks the
same engine for permission and re-enters authorize(). They do not create a parallel
governance ledger. Provenance validation requires an explicit approved-source
verifier; Memory persistence/integrity alone is not proof of external authority.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from maep.native_authority import AuthorityError, TrustRootRecord
from maep.core import POLICY_VERSION
from maep.trust_source_contracts import require_trust_source_contract
from memory.store import MemoryStore


def _reject_authorizing_memory_api(memory_store: Any) -> None:
    # MemoryStore's public reads call its policy evaluator, which in the runtime graph
    # is NativePolicyEngine itself. Used as the authority's record source it recurses.
    if isinstance(memory_store, MemoryStore):
        raise AuthorityError("authority evidence read path must be memory.AuthorityEvidenceReader; "
                             "the authorizing MemoryStore API re-enters authority")


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def _digest(value: Any) -> str:
    # MemoryStore's internal evidence digest is lowercase hex without an algorithm prefix.
    return hashlib.sha256(_canonical(value)).hexdigest()


class MemoryMAEPRecordResolver:
    """Resolve applicability/gate/evidence records from the canonical Memory ledger.

    `selectors` must read record references from an existing canonical task/authority
    record, never from untrusted request claims. This adapter fails closed if a selector
    cannot resolve a reference or if the persisted record is stale/misbound.
    """
    def __init__(self, *, memory_store: Any, selectors: Any):
        _reject_authorizing_memory_api(memory_store)
        if memory_store is None or not callable(getattr(memory_store, "get_evidence", None)):
            raise AuthorityError("authorized Memory evidence lookup API is required")
        required = ("resolve_applicability_ref", "resolve_gate_ref", "resolve_evidence_task")
        if selectors is None or any(not callable(getattr(selectors, name, None)) for name in required):
            raise AuthorityError("canonical task/evidence selectors are required")
        self.memory_store = memory_store
        self.selectors = selectors

    def _load(self, task_id: str, evidence_ref: str, *, candidate_ref: str | None = None,
              policy_version: str | None = None) -> dict[str, Any] | None:
        try:
            stored = self.memory_store.get_evidence(task_id, evidence_ref)
        except Exception as exc:
            raise AuthorityError("canonical Memory evidence lookup failed") from exc
        if stored is None:
            return None
        if (stored.get("task_id") != task_id or stored.get("evidence_id") != evidence_ref
                or not isinstance(stored.get("evidence"), dict)):
            raise AuthorityError("Memory evidence identity/binding is invalid")
        if candidate_ref is not None and stored.get("candidate_ref") != candidate_ref:
            raise AuthorityError("Memory evidence belongs to another candidate")
        if policy_version is not None and stored.get("policy_version") != policy_version:
            raise AuthorityError("Memory evidence belongs to another policy version")
        evidence = stored["evidence"]
        # Verify the evidence row is represented in the append-only task event ledger.
        try:
            events = self.memory_store.get_events(task_id, limit=1000)
            integrity = self.memory_store.check_integrity(task_id=task_id)
        except Exception as exc:
            raise AuthorityError("Memory evidence event-chain verification failed") from exc
        matches = [event for event in events if event.get("event_type") == "evidence.recorded"
                   and isinstance(event.get("payload"), dict)
                   and event["payload"].get("evidence_id") == evidence_ref]
        if (integrity.get("status") != "PASS" or not matches
                or matches[-1]["payload"].get("evidence_digest") != _digest(evidence)):
            raise AuthorityError("Memory evidence is not bound to an intact append-only ledger event")
        return {
            "evidence_id": evidence_ref, "task_id": task_id,
            "candidate_ref": stored["candidate_ref"],
            "policy_version": stored["policy_version"],
            "source_ref": evidence["source_ref"],
            "evidence_type": evidence["evidence_type"],
            "collected_at": evidence["collected_at"],
            "result": evidence["result"],
            "limitations": list(evidence["limitations"]),
            "_memory_binding": {
                "task_id": task_id, "evidence_id": evidence_ref,
                "candidate_ref": stored["candidate_ref"],
                "policy_version": stored["policy_version"],
                "created_at": stored["created_at"],
                "evidence_digest": _digest(evidence),
                "event_digest": matches[-1].get("event_digest"),
                # Decision that authorized the write (D4-a verifies it in the authority ledger).
                "authorization_id": matches[-1]["payload"].get("authorization_id"),
                "memory_integrity": "PASS",
            },
            "_evidence_record": evidence,
        }

    def resolve_applicability(self, request: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any] | None:
        task_id = request.get("task_ref")
        candidate_ref = candidate.get("candidate_ref")
        if not isinstance(task_id, str) or not task_id or not isinstance(candidate_ref, str) or not candidate_ref:
            raise AuthorityError("canonical task and candidate refs are required for applicability lookup")
        task_exists = getattr(self.selectors, "task_exists", None)
        if callable(task_exists) and task_exists(task_id) is False:
            # The canonical store, after its integrity checks, has no such task (e.g.
            # the task is being created): there is no task-level record to apply.
            return None
        ref = self.selectors.resolve_applicability_ref(request, candidate)
        if not isinstance(ref, str) or not ref:
            return None
        record = self._load(task_id, ref, candidate_ref=candidate_ref)
        if record is None:
            return None
        payload = record["result"]
        if not isinstance(payload, str):
            raise AuthorityError("applicability evidence result must contain canonical JSON")
        try:
            decoded = json.loads(payload)
        except (TypeError, json.JSONDecodeError) as exc:
            raise AuthorityError("applicability evidence result is not valid JSON") from exc
        if not isinstance(decoded, dict):
            raise AuthorityError("applicability evidence result must be an object")
        if decoded.get("candidate_ref") != candidate_ref:
            raise AuthorityError("applicability record candidate does not match current candidate")
        if decoded.get("evidence_id", ref) != ref:
            raise AuthorityError("applicability record identity differs from ledger reference")
        decoded.setdefault("evidence_id", ref)
        decoded.setdefault("policy_version", record["policy_version"])
        decoded.setdefault("applicability_id", ref)
        decoded["_memory_binding"] = record["_memory_binding"]
        decoded["_evidence_record"] = record["_evidence_record"]
        return decoded

    def resolve_gate(self, request: dict[str, Any], candidate: dict[str, Any], policy: dict[str, Any]) -> dict[str, Any] | None:
        task_id = request.get("task_ref")
        candidate_ref = candidate.get("candidate_ref")
        policy_version = policy.get("version")
        if not all(isinstance(v, str) and v for v in (task_id, candidate_ref, policy_version)):
            raise AuthorityError("canonical task/candidate/policy refs are required for gate lookup")
        ref = self.selectors.resolve_gate_ref(request, candidate, policy)
        if not isinstance(ref, str) or not ref:
            return None
        record = self._load(task_id, ref, candidate_ref=candidate_ref, policy_version=policy_version)
        if record is None:
            return None
        payload = record["result"]
        try:
            decoded = json.loads(payload)
        except (TypeError, json.JSONDecodeError) as exc:
            raise AuthorityError("MAEP-022 gate evidence result is not canonical JSON") from exc
        if not isinstance(decoded, dict):
            raise AuthorityError("MAEP-022 gate record must be an object")
        if decoded.get("candidate_ref") != candidate_ref or decoded.get("policy_version") != policy_version:
            raise AuthorityError("MAEP-022 gate candidate/policy binding mismatch")
        if decoded.get("evidence_id", ref) != ref:
            raise AuthorityError("MAEP-022 gate record identity differs from ledger reference")
        decoded.setdefault("evidence_id", ref)
        decoded.setdefault("decision_id", ref)
        decoded["_memory_binding"] = record["_memory_binding"]
        decoded["_evidence_record"] = record["_evidence_record"]
        return decoded

    def resolve_task_evidence(self, task_id: str, evidence_ref: str, *, candidate_ref: str | None = None) -> dict[str, Any] | None:
        """Ledger-bound record of one evidence item of a known canonical task (acceptance)."""
        if not isinstance(task_id, str) or not task_id or not isinstance(evidence_ref, str) or not evidence_ref:
            raise AuthorityError("task and evidence references are required")
        return self._load(task_id, evidence_ref, candidate_ref=candidate_ref)

    def resolve_evidence(self, evidence_ref: str) -> dict[str, Any] | None:
        if not isinstance(evidence_ref, str) or not evidence_ref:
            raise AuthorityError("evidence reference is required")
        task_id = self.selectors.resolve_evidence_task(evidence_ref)
        if not isinstance(task_id, str) or not task_id:
            return None
        return self._load(task_id, evidence_ref)


class CanonicalMemoryTaskSelectors:
    """Select MAEP-022 evidence references from authorized canonical task records.

    Task `inputs` are the only selector source. Their `ref_id` values are resolved
    against the same task's database-bound Memory evidence. Descriptions must use
    the exact role tokens `maep022:applicability` or `maep022:gate`; request fields
    and candidate/policy dictionaries never supply evidence references. To resolve an
    arbitrary evidence reference back to its task, an explicit canonical task-ID
    enumerator is required; there is no guessed/global scan fallback.
    """
    def __init__(self, *, memory_store: Any, canonical_task_id_source: Any = None,
                 index_scope_task_id: str | None = None, page_size: int = 100):
        _reject_authorizing_memory_api(memory_store)
        if memory_store is None or not callable(getattr(memory_store, "get_task", None)):
            raise AuthorityError("authorized canonical task lookup API is required")
        if canonical_task_id_source is not None and not callable(
                getattr(canonical_task_id_source, "list_canonical_task_ids", None)):
            raise AuthorityError("canonical task ID source contract is invalid")
        if not isinstance(page_size, int) or isinstance(page_size, bool) or not 1 <= page_size <= 500:
            raise AuthorityError("canonical task index page size is invalid")
        self.memory_store = memory_store
        self.canonical_task_id_source = canonical_task_id_source
        self.index_scope_task_id = index_scope_task_id
        self.page_size = page_size

    def _canonical_task_ids(self) -> list[str]:
        """Enumerate IDs only via the authorized Memory index API or an injected source."""
        if self.canonical_task_id_source is not None:
            source = self.canonical_task_id_source
            try:
                result = source.list_canonical_task_ids()
            except Exception as exc:
                raise AuthorityError("canonical task ID source failed") from exc
            if not isinstance(result, (list, tuple)):
                raise AuthorityError("canonical task ID source returned invalid data")
            task_ids = list(result)
        else:
            index_api = getattr(self.memory_store, "list_tasks", None)
            if not callable(index_api) or not isinstance(self.index_scope_task_id, str) or not self.index_scope_task_id.strip():
                raise AuthorityError("authorized canonical Memory task index unavailable")
            task_ids = []
            offset = 0
            while True:
                try:
                    page = index_api(index_scope_task_id=self.index_scope_task_id,
                                     limit=self.page_size, offset=offset)
                except Exception as exc:
                    raise AuthorityError("authorized canonical Memory task index denied or invalid") from exc
                if (not isinstance(page, dict) or page.get("integrity_status") != "PASS"
                        or page.get("policy_version") != POLICY_VERSION
                        or not isinstance(page.get("tasks"), list)
                        or page.get("offset") != offset
                        or page.get("limit") != self.page_size
                        or page.get("returned") != len(page.get("tasks"))
                        or type(page.get("has_more")) is not bool):
                    raise AuthorityError("canonical Memory task index page integrity/binding failed")
                page_ids = []
                for snapshot in page["tasks"]:
                    if (not isinstance(snapshot, dict) or not isinstance(snapshot.get("task"), dict)
                            or snapshot.get("policy_status") != "CURRENT"
                            or snapshot["task"].get("policy_version") != POLICY_VERSION):
                        raise AuthorityError("canonical Memory task index contains stale/malformed task")
                    task_id = snapshot["task"].get("task_id")
                    if not isinstance(task_id, str) or not task_id.strip():
                        raise AuthorityError("canonical Memory task index contains invalid task identity")
                    page_ids.append(task_id)
                if len(page_ids) != len(set(page_ids)):
                    raise AuthorityError("canonical Memory task index contains duplicate task identity")
                task_ids.extend(page_ids)
                if page["has_more"] is False:
                    if page["returned"] == self.page_size:
                        # Exact-full final page is ambiguous; require an explicit empty page
                        # to prove exhaustion rather than treating page length as completeness.
                        offset += self.page_size
                        continue
                    break
                if page["returned"] != self.page_size:
                    raise AuthorityError("canonical Memory task index pagination is inconsistent")
                offset += self.page_size
        if any(not isinstance(item, str) or not item.strip() for item in task_ids):
            raise AuthorityError("canonical task ID source returned invalid data")
        if len(task_ids) != len(set(task_ids)):
            raise AuthorityError("canonical task ID source contains duplicate task identity")
        return task_ids

    def task_exists(self, task_id: str) -> bool:
        """Strict existence check; requires a store that can say a task is absent."""
        if not isinstance(task_id, str) or not task_id.strip():
            raise AuthorityError("canonical task ID is required")
        has_task = getattr(self.memory_store, "has_task", None)
        if not callable(has_task):
            raise AuthorityError("canonical task existence check unavailable")
        try:
            result = has_task(task_id)
        except Exception as exc:
            raise AuthorityError("canonical task existence check failed") from exc
        if not isinstance(result, bool):
            raise AuthorityError("canonical task existence check returned invalid data")
        return result

    def _task(self, task_id: str) -> dict[str, Any]:
        if not isinstance(task_id, str) or not task_id.strip():
            raise AuthorityError("canonical task ID is required")
        try:
            snapshot = self.memory_store.get_task(task_id)
        except Exception as exc:
            raise AuthorityError("canonical task lookup failed") from exc
        if (not isinstance(snapshot, dict) or not isinstance(snapshot.get("task"), dict)
                or snapshot["task"].get("task_id") != task_id
                or snapshot.get("policy_status") != "CURRENT"):
            raise AuthorityError("canonical task record missing, stale or misbound")
        return snapshot

    @staticmethod
    def _role_refs(task: dict[str, Any], role: str) -> list[str]:
        refs = []
        for item in task.get("inputs", []):
            if not isinstance(item, dict) or item.get("kind") != "EVIDENCE":
                continue
            description = item.get("description", "")
            tokens = {part.strip() for part in description.split(";") if part.strip()}
            if role in tokens:
                ref = item.get("ref_id")
                if not isinstance(ref, str) or not ref.strip():
                    raise AuthorityError("canonical task evidence reference is malformed")
                refs.append(ref)
        if len(refs) > 1:
            raise AuthorityError("canonical task has ambiguous references for role " + role)
        return refs

    def resolve_applicability_ref(self, request: dict[str, Any], candidate: dict[str, Any]) -> str | None:
        task_id = request.get("task_ref")
        snapshot = self._task(task_id)
        if snapshot.get("candidate_ref") != candidate.get("candidate_ref"):
            raise AuthorityError("canonical task candidate binding mismatch")
        refs = self._role_refs(snapshot["task"], "maep022:applicability")
        return refs[0] if refs else None

    def resolve_gate_ref(self, request: dict[str, Any], candidate: dict[str, Any], policy: dict[str, Any]) -> str | None:
        task_id = request.get("task_ref")
        snapshot = self._task(task_id)
        if (snapshot.get("candidate_ref") != candidate.get("candidate_ref")
                or snapshot["task"].get("policy_version") != policy.get("version")):
            raise AuthorityError("canonical task candidate/policy binding mismatch")
        refs = self._role_refs(snapshot["task"], "maep022:gate")
        return refs[0] if refs else None

    def resolve_evidence_task(self, evidence_ref: str) -> str | None:
        if not isinstance(evidence_ref, str) or not evidence_ref.strip():
            raise AuthorityError("evidence reference is required")
        task_ids = self._canonical_task_ids()
        matches = []
        for task_id in task_ids:
            snapshot = self._task(task_id)
            if any(isinstance(item, dict) and item.get("kind") == "EVIDENCE"
                   and item.get("ref_id") == evidence_ref for item in snapshot["task"].get("inputs", [])):
                stored = self.memory_store.get_evidence(task_id, evidence_ref)
                if stored is not None:
                    matches.append(task_id)
        if len(matches) > 1:
            raise AuthorityError("evidence reference is ambiguous across canonical tasks")
        return matches[0] if matches else None


class MemoryLedgerProvenanceVerifier:
    """Verify ledger linkage, then defer source authority to an explicit verifier.

    The approved_source_verifier must expose `verify_approved_memory_record(record, ...)`.
    This class intentionally never equates a valid local digest with source authority.
    """
    def __init__(self, approved_source_verifier: Any):
        require_trust_source_contract(approved_source_verifier, "verify_approved_memory_record",
                                      source_name="approved-memory-record-verifier")
        self.approved_source_verifier = approved_source_verifier

    def validate_record_provenance(self, record: dict[str, Any], *, record_type: str,
                                   root: TrustRootRecord, policy: dict[str, Any]) -> bool:
        if not isinstance(root, TrustRootRecord) or not root.verify_integrity():
            return False
        if (not isinstance(policy, dict) or policy.get("status") != "ACTIVE"
                or policy.get("root_generation") != root.generation
                or not isinstance(policy.get("version"), str)):
            return False
        binding = record.get("_memory_binding")
        evidence = record.get("_evidence_record")
        if (not isinstance(binding, dict) or not isinstance(evidence, dict)
                or binding.get("memory_integrity") != "PASS"
                or binding.get("evidence_id") != record.get("evidence_id")
                or binding.get("candidate_ref") != record.get("candidate_ref")
                or binding.get("policy_version") != policy.get("version")
                or binding.get("evidence_digest") != _digest(evidence)):
            return False
        try:
            return self.approved_source_verifier.verify_approved_memory_record(
                record, record_type=record_type, root=root, policy=policy,
            ) is True
        except Exception:
            return False
