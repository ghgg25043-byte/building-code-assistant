import copy
import tempfile
import unittest
from pathlib import Path

from quality import (
    REVIEWS_PATH, audit_corpus, capture_result_rows, corpus_fingerprint,
    prepare_rows, read_reviews, review_metrics, write_reviews,
    _hash_json, _snapshot_payload,
)
from search_engine import load_corpus
from source_review import audit_register, template_rows


CORPUS = load_corpus()


class QualityTests(unittest.TestCase):
    def test_expert_sheet_hides_developer_answers_and_assistant_output(self):
        rows = prepare_rows(CORPUS)
        self.assertEqual(len(rows), 12)
        self.assertNotIn("candidate_references", rows[0])
        self.assertEqual(rows[0]["expected_references"], "")
        self.assertEqual(rows[0]["should_abstain"], "")
        self.assertEqual(rows[0]["result_json"], "")
        self.assertEqual(rows[0]["corpus_sha256"], corpus_fingerprint(CORPUS))

    def test_blank_field_template_contains_no_fabricated_questions(self):
        rows = prepare_rows(CORPUS, blank_count=50)
        self.assertEqual(len(rows), 50)
        self.assertEqual(rows[0]["case_id"], "FIELD-001")
        self.assertEqual(rows[-1]["case_id"], "FIELD-050")
        self.assertTrue(all(not row["question"] for row in rows))
        self.assertEqual(review_metrics(rows, CORPUS)["field_question_count"], 0)

    def test_metrics_require_independent_labels_and_result_snapshot(self):
        rows = prepare_rows(CORPUS)
        rows[0].update({
            "should_abstain": "no", "expected_references": "DEMO-ARCH-001#D-11",
            "citation_correct": "yes", "applicability_correct": "yes",
            "manual_minutes": "8", "assistant_minutes": "3",
            "reviewer": "测试专家", "reviewed_on": "2026-09-26",
        })
        rows[9].update({
            "should_abstain": "yes", "reviewer": "测试专家",
            "reviewed_on": "2026-09-26",
        })
        rows[1]["should_abstain"] = "no"
        before = review_metrics(rows, CORPUS)
        self.assertEqual(before["reviewed_count"], 2)
        self.assertEqual(before["snapshotted_reviewed_count"], 0)
        self.assertIsNone(before["top3_reference_recall"])
        self.assertEqual(before["unsnapshotted_reviewed_ids"], ["DEV-001", "DEV-010"])
        with self.assertRaisesRegex(ValueError, "DEV-002"):
            capture_result_rows(rows, CORPUS)
        captured = capture_result_rows([rows[0], rows[9]], CORPUS)
        metrics = review_metrics([*captured, rows[1]], CORPUS)
        self.assertEqual(metrics["reviewed_count"], 2)
        self.assertEqual(metrics["snapshotted_reviewed_count"], 2)
        self.assertEqual(metrics["incomplete_ids"], ["DEV-002"])
        self.assertEqual(metrics["top3_reference_recall"], 1)
        self.assertEqual(metrics["abstention_accuracy"], 1)
        self.assertEqual(metrics["citation_correct_rate"], 1)
        self.assertEqual(metrics["average_minutes_saved"], 5)
        self.assertEqual(metrics["evaluation_basis"], "current_version_result_snapshots")

    def test_mixed_version_snapshots_are_not_pooled(self):
        rows = prepare_rows(CORPUS)
        rows[0].update({"should_abstain": "no", "expected_references": "DEMO-ARCH-001#D-11",
                        "reviewer": "测试专家", "reviewed_on": "2026-09-26"})
        rows[9].update({"should_abstain": "yes", "reviewer": "测试专家",
                        "reviewed_on": "2026-09-26"})
        captured = capture_result_rows([rows[0], rows[9]], CORPUS)
        captured[1]["retriever_sha256"] = "prior-retriever"
        captured[1]["result_snapshot_id"] = _hash_json(_snapshot_payload(captured[1]))
        metrics = review_metrics(captured, CORPUS)
        self.assertTrue(metrics["mixed_snapshot_versions"])
        self.assertEqual(metrics["snapshotted_reviewed_count"], 2)
        self.assertEqual(metrics["current_version_scored_count"], 1)
        self.assertEqual(metrics["outdated_snapshot_ids"], ["DEV-010"])
        self.assertIsNone(metrics["abstention_accuracy"])
        self.assertEqual(metrics["top3_reference_recall"], 1)

    def test_source_register_remains_incomplete_until_human_review(self):
        rows = template_rows(CORPUS)
        self.assertEqual(len(rows), 14)
        self.assertEqual(audit_register(rows, CORPUS)["ready_count"], 0)
        rows[0].update({"official_text_url": "https://example.com/official.pdf",
                        "official_page_or_section": "p. 1", "version_status": "current_verified",
                        "version_checked_on": "2026-09-26", "version_reviewer": "示例复核人",
                        "text_location_checked": "yes", "text_location_reviewer": "示例复核人",
                        "text_location_checked_on": "2026-09-26",
                        "applicability_notes": "仅用于测试字段完整性",
                        "applicability_reviewer": "示例复核人", "applicability_checked_on": "2026-09-26",
                        "summary_checked": "yes", "summary_reviewer": "示例复核人",
                        "summary_checked_on": "2026-09-26", "use_permission_notes": "仅用于测试"})
        self.assertEqual(audit_register(rows, CORPUS)["ready_count"], 1)

    def test_tampered_result_is_excluded(self):
        rows = prepare_rows(CORPUS)
        rows[0].update({
            "should_abstain": "no", "expected_references": "DEMO-ARCH-001#D-11",
            "reviewer": "测试专家", "reviewed_on": "2026-09-26",
        })
        captured = capture_result_rows([rows[0]], CORPUS)
        captured[0]["question"] = "被修改的问题"
        metrics = review_metrics(captured, CORPUS)
        self.assertEqual(metrics["invalid_snapshot_ids"], ["DEV-001"])
        self.assertIsNone(metrics["top3_reference_recall"])

    def test_changed_blind_reference_after_capture_is_excluded(self):
        rows = prepare_rows(CORPUS)
        rows[0].update({
            "should_abstain": "no", "expected_references": "DEMO-ARCH-001#D-11",
            "reviewer": "测试专家", "reviewed_on": "2026-09-26",
        })
        captured = capture_result_rows([rows[0]], CORPUS)
        captured[0]["expected_references"] = "DEMO-ARCH-001#D-01"
        self.assertEqual(review_metrics(captured, CORPUS)["invalid_snapshot_ids"], ["DEV-001"])

    def test_old_sheet_can_be_read_without_overwriting(self):
        rows = read_reviews(REVIEWS_PATH)
        self.assertEqual(len(rows), 12)
        self.assertEqual(rows[0]["result_snapshot_id"], "")
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "reviews.csv"
            write_reviews(path, rows)
            with self.assertRaises(FileExistsError):
                write_reviews(path, rows)

    def test_corpus_hash_mismatch_blocks_new_snapshot(self):
        rows = prepare_rows(CORPUS)
        changed = copy.deepcopy(CORPUS)
        changed["dataset_id"] = "different"
        with self.assertRaises(ValueError):
            capture_result_rows(rows, changed)

    def test_incomplete_blind_labels_block_snapshot(self):
        rows = prepare_rows(CORPUS)
        with self.assertRaisesRegex(ValueError, "DEV-001"):
            capture_result_rows(rows, CORPUS)
        field_rows = prepare_rows(CORPUS, blank_count=2)
        self.assertFalse(any(row["result_snapshot_id"] for row in
                             capture_result_rows(field_rows, CORPUS)))

    def test_audit_reports_unverified_state_without_claiming_validity(self):
        audit = audit_corpus(CORPUS)
        self.assertEqual(audit["errors"], [])
        self.assertFalse(audit["version_verified"])
        self.assertEqual(audit["expert_reviewed_clauses"], 0)
        self.assertEqual(audit["unreviewed_summary_clauses"], 0)
        self.assertTrue(audit["fictional_demo"])
        self.assertEqual(audit["source_location_verified_clauses"], 0)
        self.assertEqual(audit["applicability_reviewed_clauses"], 0)
        self.assertTrue(audit["warnings"])


if __name__ == "__main__":
    unittest.main()
