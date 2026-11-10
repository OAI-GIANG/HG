import copy
import unittest

from hg.memory.curation import CurationInputError, analyze_memories

AS_OF = "2026-11-01T00:00:00Z"


def rec(mid, *, subject="xe", content="thay dầu xe ngày 15/09", value=None,
        layer="SEMANTIC", kind="NOTE", status="ACTIVE", **extra):
    row = {"memory_id": mid, "layer": layer, "kind": kind, "subject": subject,
           "content": content, "value": value, "status": status,
           "source": "USER", "source_ref": "fixture", "evidence_refs": []}
    row.update(extra)
    return row


class CurationTests(unittest.TestCase):
    def test_exact_duplicate_same_scope_is_candidate_not_merge(self):
        report = analyze_memories([rec("M1"), rec("M2")], as_of=AS_OF)
        self.assertEqual(report["exact_duplicate_groups"][0]["memory_ids"], ["M1", "M2"])
        self.assertFalse(report["policy"]["auto_merge"])

    def test_same_text_different_subject_is_reviewed_but_never_merged(self):
        rows = [rec("M1", subject="xe", source_ref="src:a", evidence_refs=["EV-A"]),
                rec("M2", subject="oto", source_ref="src:b", evidence_refs=["EV-B"])]
        report = analyze_memories(rows, as_of=AS_OF)
        self.assertEqual(report["exact_duplicate_groups"], [])
        self.assertEqual(len(report["cross_subject_candidates"]), 1)
        finding = report["cross_subject_candidates"][0]
        self.assertEqual(finding["type"], "CROSS_SUBJECT_REVIEW")
        self.assertEqual(finding["subjects"], ["oto", "xe"])
        self.assertEqual({p["source_ref"] for p in finding["provenance"]}, {"src:a", "src:b"})
        self.assertFalse(report["policy"]["cross_subject_auto_merge"])

    def test_cross_subject_different_values_need_compatible_content_context(self):
        report = analyze_memories([
            rec("M1", subject="hoa-don", kind="FACT", content="địa chỉ nhận hóa đơn của cửa hàng", value="18 Lê Lợi"),
            rec("M2", subject="lich-vuon", kind="FACT", content="cách chăm sóc hoa lan trong mùa lạnh", value="25 độ C"),
        ], as_of=AS_OF)
        self.assertEqual(report["cross_subject_candidates"], [])

    def test_same_text_different_kind_is_not_merged(self):
        report = analyze_memories([rec("M1", kind="NOTE"), rec("M2", kind="FACT")], as_of=AS_OF)
        self.assertEqual(report["exact_duplicate_groups"], [])

    def test_same_text_different_structured_value_is_not_exact_duplicate(self):
        report = analyze_memories([rec("M1", kind="FACT", value="18:00"),
                                   rec("M2", kind="FACT", value="19:00")], as_of=AS_OF)
        self.assertEqual(report["exact_duplicate_groups"], [])
        self.assertTrue(report["conflict_candidates"])

    def test_same_text_in_disjoint_valid_periods_is_not_merged(self):
        report = analyze_memories([
            rec("M1", valid_from="2025-01-01", valid_to="2025-06-01"),
            rec("M2", valid_from="2026-01-01", valid_to="2026-06-01"),
        ], as_of=AS_OF)
        self.assertEqual(report["exact_duplicate_groups"], [])

    def test_exact_duplicate_candidates_do_not_chain_disjoint_valid_intervals(self):
        rows = [
            rec("M1", valid_from="2026-01-01", valid_to="2026-03-01"),
            rec("M2", valid_from="2026-02-01", valid_to="2026-05-01"),
            rec("M3", valid_from="2026-04-01", valid_to="2026-06-01"),
        ]
        report = analyze_memories(rows, as_of="2026-02-15T00:00:00Z")
        pairs = {tuple(row["memory_ids"]) for row in report["exact_duplicate_groups"]}
        self.assertEqual(pairs, {("M1", "M2"), ("M2", "M3")})
        self.assertNotIn(("M1", "M3"), pairs)
        self.assertFalse(any(len(row["memory_ids"]) > 2 for row in report["exact_duplicate_groups"]))

    def test_single_digit_time_change_is_not_exact_or_near_duplicate(self):
        report = analyze_memories([
            rec("M1", subject="lich-hen", content="hẹn khám răng lúc 9 giờ sáng thứ hai"),
            rec("M2", subject="lich-hen", content="hẹn khám răng lúc 7 giờ sáng thứ hai"),
        ], as_of=AS_OF)
        self.assertEqual(report["exact_duplicate_groups"], [])
        self.assertEqual(report["near_duplicate_pairs"], [])
        self.assertTrue(any(x["classification"] == "NUMERIC_VALUE_DIVERGENCE_CANDIDATE"
                            for x in report["conflict_candidates"]))

    def test_curation_pair_comparison_is_bounded_and_reports_truncation(self):
        rows = [rec(f"M{i:04d}", content=f"ghi chú lịch bảo dưỡng xe số {i}") for i in range(200)]
        report = analyze_memories(rows, as_of=AS_OF, max_pair_comparisons=100, max_findings=20)
        self.assertLessEqual(report["comparisons_evaluated"], 100)
        self.assertTrue(report["truncated"])
        self.assertEqual(report["resource_limits"]["max_pair_comparisons"], 100)

    def test_max_findings_caps_staleness_candidates_and_reports_truncation(self):
        rows = [rec(f"M{i:03d}", subject=f"s{i}", content=f"expiredunique{i}",
                    expires_at="2026-10-01") for i in range(12)]
        report = analyze_memories(rows, as_of=AS_OF, max_findings=3)
        total = sum(len(report[key]) for key in (
            "exact_duplicate_groups", "near_duplicate_pairs", "staleness_candidates",
            "conflict_candidates", "cross_subject_candidates"))
        self.assertEqual(total, 3)
        self.assertEqual(report["findings_emitted"], 3)
        self.assertEqual(len(report["staleness_candidates"]), 3)
        self.assertTrue(report["truncated"])

    def test_max_findings_is_global_across_staleness_and_duplicate_classes(self):
        rows = [
            rec("S1", subject="expired-1", content="expireduniqueone", expires_at="2026-10-01"),
            rec("S2", subject="expired-2", content="expireduniquetwo", expires_at="2026-10-01"),
            rec("D1", subject="duplicate-a", content="tokenalpha duplicate"),
            rec("D2", subject="duplicate-a", content="tokenalpha duplicate"),
            rec("D3", subject="duplicate-b", content="tokenbeta duplicate"),
            rec("D4", subject="duplicate-b", content="tokenbeta duplicate"),
        ]
        report = analyze_memories(rows, as_of=AS_OF, max_findings=3)
        total = sum(len(report[key]) for key in (
            "exact_duplicate_groups", "near_duplicate_pairs", "staleness_candidates",
            "conflict_candidates", "cross_subject_candidates"))
        self.assertEqual(total, 3)
        self.assertEqual(report["findings_emitted"], 3)
        self.assertEqual(len(report["staleness_candidates"]), 2)
        self.assertEqual(len(report["exact_duplicate_groups"]), 1)
        self.assertTrue(report["truncated"])

    def test_near_duplicate_is_only_a_review_candidate(self):
        report = analyze_memories([
            rec("M1", content="xe máy thay dầu ngày 15 tháng 9 năm 2026"),
            rec("M2", content="xe máy thay dầu vào ngày 15 tháng 9 năm 2026"),
        ], as_of=AS_OF, near_duplicate_threshold=0.70)
        self.assertTrue(report["near_duplicate_pairs"])
        self.assertIn("NEVER_AUTO_MERGE", report["near_duplicate_pairs"][0]["recommended_review"])

    def test_near_duplicate_is_not_flagged_across_disjoint_valid_periods(self):
        report = analyze_memories([
            rec("M1", content="xe máy của chủ nhân cần thay dầu định kỳ sau mỗi 3000 kilomet",
                valid_from="2025-01-01", valid_to="2025-06-01"),
            rec("M2", content="xe máy của chủ nhân cần thay dầu định kỳ sau mỗi 3500 kilomet",
                valid_from="2026-01-01", valid_to="2026-06-01"),
        ], as_of=AS_OF)
        self.assertEqual(report["near_duplicate_pairs"], [])

    def test_explicit_expiry_is_flagged(self):
        report = analyze_memories([rec("M1", expires_at="2026-10-01")], as_of=AS_OF)
        self.assertEqual(report["staleness_candidates"][0]["type"], "EXPIRED_CANDIDATE")

    def test_old_record_without_expiry_is_not_called_stale(self):
        report = analyze_memories([rec("M1", created_at="2001-01-01T00:00:00Z")], as_of=AS_OF)
        self.assertEqual(report["staleness_candidates"], [])

    def test_future_valid_from_is_not_yet_valid(self):
        report = analyze_memories([rec("M1", valid_from="2027-01-01")], as_of=AS_OF)
        self.assertEqual(report["staleness_candidates"][0]["type"], "NOT_YET_VALID")

    def test_different_non_overlapping_periods_are_not_conflict(self):
        report = analyze_memories([
            rec("M1", kind="FACT", value="Q1", valid_from="2026-01-01", valid_to="2026-04-01"),
            rec("M2", kind="FACT", value="Q2", valid_from="2026-04-01", valid_to="2026-07-01"),
        ], as_of=AS_OF)
        self.assertEqual(report["conflict_candidates"], [])

    def test_overlapping_different_structured_values_flag_conflict(self):
        report = analyze_memories([
            rec("M1", kind="FACT", value="18:00"), rec("M2", kind="FACT", value="19:00"),
        ], as_of=AS_OF)
        self.assertEqual(report["conflict_candidates"][0]["classification"], "STRUCTURED_VALUE_DISAGREEMENT")

    def test_positive_past_tense_is_not_mistaken_for_negation(self):
        report = analyze_memories([
            rec("M1", content="họp dự án HG đã diễn ra thứ năm"),
            rec("M2", content="họp dự án HG diễn ra thứ năm"),
        ], as_of=AS_OF)
        self.assertFalse(any(x["classification"] == "POLARITY_DISAGREEMENT_CANDIDATE"
                             for x in report["conflict_candidates"]))

    def test_opposite_negation_is_only_a_candidate(self):
        report = analyze_memories([
            rec("M1", content="cuộc họp dự án HG diễn ra thứ năm"),
            rec("M2", content="cuộc họp dự án HG không diễn ra thứ năm"),
        ], as_of=AS_OF)
        self.assertTrue(any(x["classification"] == "POLARITY_DISAGREEMENT_CANDIDATE"
                            for x in report["conflict_candidates"]))

    def test_inactive_records_are_preserved_but_not_compared(self):
        report = analyze_memories([
            rec("M1", status="SUPERSEDED"), rec("M2", content="nội dung mới"),
        ], as_of=AS_OF)
        self.assertEqual(report["inactive_records_preserved"], 1)
        self.assertEqual(report["exact_duplicate_groups"], [])

    def test_input_records_are_not_mutated(self):
        rows = [rec("M1"), rec("M2")]
        before = copy.deepcopy(rows)
        analyze_memories(rows, as_of=AS_OF)
        self.assertEqual(rows, before)

    def test_invalid_interval_fails_closed(self):
        with self.assertRaises(CurationInputError):
            analyze_memories([rec("M1", valid_from="2026-08-01", valid_to="2026-07-01")], as_of=AS_OF)

    def test_duplicate_ids_are_rejected(self):
        with self.assertRaises(CurationInputError):
            analyze_memories([rec("M1"), rec("M1", content="other")], as_of=AS_OF)

    def test_unknown_date_age_is_not_inferred_from_free_text(self):
        report = analyze_memories([rec("M1", content="bảo hiểm hết hạn ngày 2020-01-01")], as_of=AS_OF)
        self.assertEqual(report["staleness_candidates"], [])


if __name__ == "__main__":
    unittest.main(verbosity=2)


class BrainEpisodeCurationTests(unittest.TestCase):
    def test_brain_episodes_do_not_create_cross_subject_conflicts_but_exact_matches_remain_visible(self):
        import tempfile
        from pathlib import Path
        from hg.memory.store import MemoryStore

        with tempfile.TemporaryDirectory(prefix="hg-brain-curation-") as tmp:
            store = MemoryStore(Path(tmp) / "memory.jsonl")
            states = ("CLOSED_VERIFIED", "CLOSED_VERIFIED", "FAILED", "CANCELLED", "CLOSED_VERIFIED")
            for index, state in enumerate(states, 1):
                store.record_task_outcome({
                    "task": {"task_id": f"T-BRAIN-{index}", "state": state,
                             "objective": "Tạo báo cáo tổng hợp tiến độ dự án HG"},
                    "version": 1, "result": {}, "evidence": {},
                })

            brain_rows = store.all_records()
            self.assertEqual(len(brain_rows), 5)
            report = analyze_memories(brain_rows, as_of=AS_OF)
            self.assertEqual(report["conflict_candidates"], [])
            self.assertEqual(report["cross_subject_candidates"], [])

            # Keep exact cross-subject episode matches discoverable; do not disable
            # cross-subject review for the entire EPISODIC/EVENT domain.
            duplicate_value = {"state": "CLOSED_VERIFIED", "candidate_ref": None}
            first = store.remember(
                layer="EPISODIC", kind="EVENT", subject="task:DUP-A",
                content="Task event: verified handoff completed", value=duplicate_value,
                source="SYSTEM", source_ref="fixture:duplicate-a")
            second = store.remember(
                layer="EPISODIC", kind="EVENT", subject="task:DUP-B",
                content="Task event: verified handoff completed", value=duplicate_value,
                source="SYSTEM", source_ref="fixture:duplicate-b")
            report = analyze_memories(store.all_records(), as_of=AS_OF)
            matches = [row for row in report["cross_subject_candidates"]
                       if row["memory_ids"] == [first["memory_id"], second["memory_id"]]]
            self.assertEqual(len(matches), 1)
            self.assertEqual(matches[0]["classification"], "EXACT_CONTENT_MATCH")
            self.assertEqual(report["conflict_candidates"], [])
