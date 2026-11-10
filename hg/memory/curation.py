"""Read-only curation signals for HG memory.

This module analyzes one already-authorized memory domain at a time. It never mutates
records, selects a canonical survivor, merges, supersedes, retracts, or deletes.
All findings are review candidates, not truth verdicts.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timezone
import hashlib
import json
import re
import unicodedata
from typing import Any, Iterable


class CurationInputError(ValueError):
    """Malformed input or temporal metadata; fail closed."""


_NEGATION = {
    "không", "chưa", "khỏi", "never", "not", "no", "false", "disabled",
    "hủy", "huy", "bỏ", "bo", "ngừng", "ngung",
}
_TOKEN = re.compile(r"[^\W_]+", re.UNICODE)
_NUMBER = re.compile(r"\d+(?:[.,]\d+)?")
DEFAULT_MAX_PAIR_COMPARISONS = 20000
DEFAULT_MAX_FINDINGS = 500
MAX_RECORDS = 10000


def _normalise(text: str) -> str:
    text = unicodedata.normalize("NFC", text).casefold()
    return " ".join(text.split())


def _tokens(text: str) -> set[str]:
    # Keep one-digit numbers: dropping them made "9 giờ" and "7 giờ" look identical.
    return {t for t in _TOKEN.findall(_normalise(text)) if len(t) > 1 or t.isdigit()}


def _parse_instant(value: Any, field: str, memory_id: str):
    if value in (None, ""):
        return None
    if not isinstance(value, str):
        raise CurationInputError(f"{memory_id}.{field} must be ISO-8601 text")
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            parsed = datetime.combine(date.fromisoformat(value), datetime.min.time(), tzinfo=timezone.utc)
        else:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                raise ValueError("timezone required")
            parsed = parsed.astimezone(timezone.utc)
        return parsed
    except ValueError as exc:
        raise CurationInputError(f"{memory_id}.{field} must be valid timezone-aware ISO-8601") from exc


def _interval(record: dict):
    mid = record["memory_id"]
    start = _parse_instant(record.get("valid_from"), "valid_from", mid)
    end = _parse_instant(record.get("valid_to"), "valid_to", mid)
    expiry = _parse_instant(record.get("expires_at"), "expires_at", mid)
    if start is not None and end is not None and end <= start:
        raise CurationInputError(f"{mid} has an empty or reversed valid-time interval")
    return start, end, expiry


def _overlap(a: dict, b: dict) -> bool:
    a0, a1, _ = _interval(a)
    b0, b1, _ = _interval(b)
    left = max(x for x in (a0, b0) if x is not None) if a0 is not None or b0 is not None else None
    right_candidates = [x for x in (a1, b1) if x is not None]
    right = min(right_candidates) if right_candidates else None
    return right is None or left is None or left < right


def _record_digest(record: dict) -> str:
    payload = {
        "layer": record.get("layer"), "kind": record.get("kind"),
        "subject": _normalise(record.get("subject", "")),
        "content": _normalise(record.get("content", "")), "value": record.get("value"),
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _pair_conflict(a: dict, b: dict) -> dict | None:
    if not _overlap(a, b):
        return None
    av, bv = a.get("value"), b.get("value")
    if av is not None and bv is not None and av != bv:
        return {
            "classification": "STRUCTURED_VALUE_DISAGREEMENT",
            "confidence": "HIGH_FOR_REVIEW_ONLY",
            "reason": "same scope/subject has unequal structured values in overlapping or unspecified valid-time intervals",
        }
    at, bt = _tokens(a.get("content", "")), _tokens(b.get("content", ""))
    if not at or not bt:
        return None
    content_a, content_b = _normalise(a.get("content", "")), _normalise(b.get("content", ""))
    neg_a, neg_b = bool(at & _NEGATION), bool(bt & _NEGATION)
    similarity = len(at & bt) / max(1, len(at | bt))
    numbers_a = _NUMBER.findall(content_a)
    numbers_b = _NUMBER.findall(content_b)
    if numbers_a and numbers_b and numbers_a != numbers_b and similarity >= 0.55:
        return {
            "classification": "NUMERIC_VALUE_DIVERGENCE_CANDIDATE",
            "confidence": "MEDIUM_FOR_REVIEW_ONLY",
            "reason": "shared context with different numeric tokens; preserve the original values and review units/time scope",
        }
    if neg_a != neg_b and similarity >= 0.55:
        return {
            "classification": "POLARITY_DISAGREEMENT_CANDIDATE",
            "confidence": "MEDIUM_FOR_REVIEW_ONLY",
            "reason": "similar wording with asymmetric negation marker; semantic interpretation is not established",
        }
    if content_a != content_b:
        return {
            "classification": "SAME_SUBJECT_DIVERGENCE",
            "confidence": "LOW_FOR_REVIEW_ONLY",
            "reason": "different assertions share a subject; they may differ by scope, wording, correction or contradiction",
        }
    return None


def analyze_memories(records: Iterable[dict], *, as_of: str, near_duplicate_threshold: float = 0.88,
                     max_pair_comparisons: int = DEFAULT_MAX_PAIR_COMPARISONS,
                     max_findings: int = DEFAULT_MAX_FINDINGS) -> dict:
    """Return bounded, deterministic review candidates. Never writes or resolves a record."""
    if not (0.50 <= near_duplicate_threshold <= 1.0):
        raise CurationInputError("near_duplicate_threshold must be between 0.50 and 1.0")
    if not isinstance(max_pair_comparisons, int) or not 1 <= max_pair_comparisons <= 100000:
        raise CurationInputError("max_pair_comparisons must be between 1 and 100000")
    if not isinstance(max_findings, int) or not 1 <= max_findings <= 2000:
        raise CurationInputError("max_findings must be between 1 and 2000")
    now = _parse_instant(as_of, "as_of", "<request>")
    if now is None:
        raise CurationInputError("as_of is required")

    checked, seen_ids = [], set()
    for item in records:
        if len(checked) >= MAX_RECORDS:
            raise CurationInputError(f"record count exceeds safety limit {MAX_RECORDS}")
        if not isinstance(item, dict):
            raise CurationInputError("each memory record must be an object")
        mid = item.get("memory_id")
        if not isinstance(mid, str) or not mid:
            raise CurationInputError("each record needs a non-empty memory_id")
        if mid in seen_ids:
            raise CurationInputError(f"duplicate memory_id: {mid}")
        seen_ids.add(mid)
        for field in ("layer", "kind", "subject", "content", "status"):
            if not isinstance(item.get(field), str) or not item[field].strip():
                raise CurationInputError(f"{mid}.{field} must be a non-empty string")
        _interval(item)
        checked.append(item)

    active = [r for r in checked if r["status"] == "ACTIVE" and r["layer"] != "WORKING"]
    by_scope_subject, by_layer_kind, stale = defaultdict(list), defaultdict(list), []
    for r in active:
        scope = (r["layer"], r["kind"], _normalise(r["subject"]))
        by_scope_subject[scope].append(r)
        by_layer_kind[(r["layer"], r["kind"])].append(r)
        start, end, expiry = _interval(r)
        boundary = min((x for x in (end, expiry) if x is not None), default=None)
        if boundary is not None and now >= boundary:
            stale.append({"type": "EXPIRED_CANDIDATE", "memory_ids": [r["memory_id"]],
                          "boundary": boundary.isoformat(),
                          "reason": "explicit valid_to/expires_at metadata has passed; do not infer expiry from age alone",
                          "recommended_review": "OWNER_OR_POLICY_REVIEW_BEFORE_STATUS_CHANGE"})
        elif start is not None and now < start:
            stale.append({"type": "NOT_YET_VALID", "memory_ids": [r["memory_id"]],
                          "boundary": start.isoformat(), "reason": "explicit valid_from metadata is in the future",
                          "recommended_review": "EXCLUDE_FROM_CURRENT_STATE_UNLESS_QUERY_ASKS_FUTURE"})

    exact_duplicates, near_duplicates, conflicts, cross_subject = [], [], [], []
    comparisons = 0
    truncated = len(exact_duplicates) >= max_findings
    stop = truncated

    def reached_limit():
        nonlocal truncated, stop
        total = len(exact_duplicates) + len(near_duplicates) + len(conflicts) + len(cross_subject)
        if total >= max_findings or comparisons >= max_pair_comparisons:
            truncated = True
            stop = True
            return True
        return False

    # Same-subject near duplicates and contradictions.
    for scope, group in sorted(by_scope_subject.items()):
        ordered = sorted(group, key=lambda r: r["memory_id"])
        for i, a in enumerate(ordered):
            ta = _tokens(a.get("content", ""))
            for b in ordered[i + 1:]:
                comparisons += 1
                if not _overlap(a, b):
                    if comparisons >= max_pair_comparisons:
                        truncated = stop = True
                        break
                    continue
                tb = _tokens(b.get("content", ""))
                similarity = len(ta & tb) / max(1, len(ta | tb))
                same_content = _normalise(a.get("content", "")) == _normalise(b.get("content", ""))
                value_a = json.dumps(a.get("value"), ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":"), default=str)
                value_b = json.dumps(b.get("value"), ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":"), default=str)
                if same_content and value_a == value_b:
                    exact_duplicates.append({
                        "type": "EXACT_DUPLICATE_CANDIDATE",
                        "memory_ids": [a["memory_id"], b["memory_id"]],
                        "scope": {"layer": scope[0], "kind": scope[1], "subject": scope[2]},
                        "content_digest": _record_digest(a),
                        "recommended_review": "COMPARE_VALID_TIME_AND_PROVENANCE; NEVER_AUTO_MERGE",
                    })
                if (not same_content
                        and ta and tb and similarity >= near_duplicate_threshold):
                    near_duplicates.append({"type": "NEAR_DUPLICATE_CANDIDATE",
                                            "memory_ids": [a["memory_id"], b["memory_id"]],
                                            "lexical_jaccard": round(similarity, 4),
                                            "recommended_review": "COMPARE_CLAIMS_SCOPE_TIME_AND_PROVENANCE; NEVER_AUTO_MERGE"})
                if a["kind"] in {"FACT", "DECISION", "NOTE", "PREFERENCE"}:
                    finding = _pair_conflict(a, b)
                    if finding:
                        conflicts.append({"type": "CONFLICT_REVIEW_CANDIDATE",
                                          "memory_ids": [a["memory_id"], b["memory_id"]], **finding,
                                          "recommended_review": "PRESERVE_BOTH; RESOLVE_ONLY_WITH_NEW_ELIGIBLE_EVIDENCE_OR_OWNER_DECISION"})
                if reached_limit():
                    break
            if stop:
                break
        if stop:
            break

    # Cross-subject review: same layer/kind only, temporal overlap required, no resolution.
    if not stop:
        for scope, group in sorted(by_layer_kind.items()):
            ordered = sorted(group, key=lambda r: (r["subject"], r["memory_id"]))
            for i, a in enumerate(ordered):
                ta = _tokens(a.get("content", ""))
                for b in ordered[i + 1:]:
                    if _normalise(a["subject"]) == _normalise(b["subject"]):
                        continue
                    comparisons += 1
                    if not _overlap(a, b):
                        if comparisons >= max_pair_comparisons:
                            truncated = stop = True
                            break
                        continue
                    tb = _tokens(b.get("content", ""))
                    similarity = len(ta & tb) / max(1, len(ta | tb))
                    same_text = _normalise(a["content"]) == _normalise(b["content"])
                    # Cross-subject comparisons require shared content context; layer/kind
                    # alone is not enough to infer that two unrelated values conflict.
                    exact_match = same_text and a.get("value") == b.get("value")
                    conflict_eligible = a["kind"] in {"FACT", "DECISION", "NOTE", "PREFERENCE"}
                    # EPISODIC/EVENT rows describe different executions, not competing
                    # assertions about one fact. Only byte-normalised exact content + value
                    # matches are useful cross-subject review candidates for them.
                    if exact_match:
                        classification, confidence = "EXACT_CONTENT_MATCH", "HIGH_FOR_REVIEW_ONLY"
                    elif a["kind"] in {"EPISODIC", "EVENT"}:
                        classification = confidence = None
                    else:
                        finding = (_pair_conflict(a, b)
                                   if conflict_eligible and (same_text or similarity >= 0.55) else None)
                        if finding:
                            classification, confidence = finding["classification"], finding["confidence"]
                        elif ta and tb and similarity >= near_duplicate_threshold:
                            classification, confidence = "NEAR_CONTENT_MATCH", "MEDIUM_FOR_REVIEW_ONLY"
                        else:
                            classification = confidence = None
                    if classification:
                        cross_subject.append({
                            "type": "CROSS_SUBJECT_REVIEW", "memory_ids": [a["memory_id"], b["memory_id"]],
                            "subjects": [a["subject"], b["subject"]], "classification": classification,
                            "confidence": confidence, "lexical_jaccard": round(similarity, 4),
                            "provenance": [
                                {"memory_id": r["memory_id"], "source": r.get("source"),
                                 "source_ref": r.get("source_ref"), "evidence_refs": list(r.get("evidence_refs") or []),
                                 "created_at": r.get("created_at")}
                                for r in (a, b)],
                            "recommended_review": "CROSS_SUBJECT_REVIEW_ONLY; KEEP_SUBJECTS_AND_RECORDS_SEPARATE; NEVER_AUTO_MERGE"})
                    if reached_limit():
                        break
                if stop:
                    break
            if stop:
                break

    # If there were more candidate pairs after the cap, the report explicitly says it is partial.
    # Apply max_findings to every finding class, including staleness and exact groups.
    # Round-robin trimming keeps a dense class (for example, expired records) from
    # silently starving all other review classes. The source records remain untouched.
    finding_sets = [
        ("staleness_candidates", stale),
        ("exact_duplicate_groups", exact_duplicates),
        ("near_duplicate_pairs", near_duplicates),
        ("conflict_candidates", conflicts),
        ("cross_subject_candidates", cross_subject),
    ]
    finding_total = sum(len(rows) for _, rows in finding_sets)
    if finding_total > max_findings:
        kept = {name: [] for name, _ in finding_sets}
        indexes = {name: 0 for name, _ in finding_sets}
        while sum(len(rows) for rows in kept.values()) < max_findings:
            progressed = False
            for name, rows in finding_sets:
                index = indexes[name]
                if index < len(rows):
                    kept[name].append(rows[index])
                    indexes[name] += 1
                    progressed = True
                    if sum(len(items) for items in kept.values()) >= max_findings:
                        break
            if not progressed:
                break
        for name, _ in finding_sets:
            if name == "staleness_candidates":
                stale = kept[name]
            elif name == "exact_duplicate_groups":
                exact_duplicates = kept[name]
            elif name == "near_duplicate_pairs":
                near_duplicates = kept[name]
            elif name == "conflict_candidates":
                conflicts = kept[name]
            elif name == "cross_subject_candidates":
                cross_subject = kept[name]
        truncated = True

    findings_emitted = sum(len(rows) for rows in (
        stale, exact_duplicates, near_duplicates, conflicts, cross_subject
    ))
    return {
        "schema": "HG-MEMORY-CURATION-REPORT/2", "mode": "READ_ONLY_REVIEW_CANDIDATES",
        "as_of": now.isoformat(), "records_seen": len(checked),
        "active_non_working_records": len(active),
        "inactive_records_preserved": sum(r["status"] != "ACTIVE" for r in checked),
        "exact_duplicate_groups": exact_duplicates, "near_duplicate_pairs": near_duplicates,
        "staleness_candidates": stale, "conflict_candidates": conflicts,
        "cross_subject_candidates": cross_subject,
        "findings_emitted": findings_emitted,
        "comparisons_evaluated": comparisons, "truncated": truncated,
        "resource_limits": {"max_records": MAX_RECORDS, "max_pair_comparisons": max_pair_comparisons,
                            "max_findings": max_findings},
        "policy": {"auto_delete": False, "auto_merge": False, "auto_supersede": False,
                   "auto_resolve_conflict": False, "cross_subject_auto_merge": False,
                   "age_alone_means_stale": False, "all_results_are_candidates_not_truth_verdicts": True},
    }
