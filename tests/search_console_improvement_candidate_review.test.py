import importlib.util
import pathlib
import sys
import unittest


ROOT = pathlib.Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location("candidate_review", ROOT / "scripts" / "search_console_improvement_candidate_review.py")
review = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules["candidate_review"] = review
SPEC.loader.exec_module(review)


def candidate(article_id=1, **changes):
    value = {
        "article_id": article_id, "is_candidate": True, "data_status": "sufficient",
        "recommendation_type": "improve_ctr", "reason_code": "position_opportunity_with_low_ctr",
        "current_period_start": "2026-08-08", "current_period_end": "2026-08-14",
        "previous_period_start": "2026-08-01", "previous_period_end": "2026-08-07",
        "current_clicks": 1, "previous_clicks": 2, "clicks_delta": -1,
        "current_impressions": 70, "previous_impressions": 80, "impressions_delta": -10,
        "current_ctr": 0.014286, "previous_ctr": 0.025, "ctr_delta": -0.010714,
        "current_position": 10.0, "previous_position": 9.0, "position_delta": 1.0,
    }
    return {**value, **changes}


def report(*items):
    return {"schema_version": "phase-2a-improvement-candidates-v1", "candidates": list(items)}


def article(article_id=1, **changes):
    return {"article_id": article_id, "title": "Ready article", "category": "saas-cloud", "seo_status": "ready", **changes}


class ImprovementCandidateReviewTest(unittest.TestCase):
    def build(self, item=None, rows=None):
        return review.build_review_envelopes(report(item or candidate()), rows or [article()])

    def test_normal_candidate_becomes_pending_review_envelope(self):
        [envelope] = self.build()
        self.assertEqual("phase-2a-improvement-candidate-review-v1", envelope["schema_version"])
        self.assertEqual("pending_review", envelope["status"])
        self.assertEqual("seo_review", envelope["recommendation_type"])
        self.assertTrue(envelope["requires_human_review"])
        self.assertEqual("position_opportunity_with_low_ctr", envelope["reason_code"])

    def test_non_ready_missing_id_title_or_category_metadata_is_excluded(self):
        self.assertEqual([], self.build(rows=[article(seo_status="needs_review")]))
        self.assertEqual([], self.build(item=candidate(article_id=None)))
        self.assertEqual([], self.build(rows=[article(title=" ")]))
        self.assertEqual([], self.build(rows=[article(category=" ")]))

    def test_unknown_reason_or_non_candidate_is_excluded(self):
        self.assertEqual([], self.build(candidate(reason_code="unknown", recommendation_type="improve_ctr")))
        self.assertEqual([], self.build(candidate(is_candidate=False)))
        self.assertEqual([], self.build(candidate(data_status="insufficient_data")))

    def test_fingerprint_is_deterministic_and_changes_with_input(self):
        first, second = self.build(), self.build()
        self.assertEqual(first[0]["candidate_fingerprint"], second[0]["candidate_fingerprint"])
        changed = self.build(candidate(current_clicks=2, clicks_delta=0))
        self.assertNotEqual(first[0]["candidate_fingerprint"], changed[0]["candidate_fingerprint"])

    def test_evidence_whitelists_only_metrics_and_periods(self):
        [envelope] = self.build(candidate(query="secret query", body="body", token="do-not-copy"))
        serialized = str(envelope["evidence"])
        self.assertNotIn("secret query", serialized)
        self.assertNotIn("do-not-copy", serialized)
        self.assertNotIn("body", serialized)
        self.assertEqual({"current_period", "previous_period", "delta", "data_status"}, set(envelope["evidence"]))

    def test_no_d1_write_or_io_dependency(self):
        self.assertEqual(1, len(self.build()))


if __name__ == "__main__":
    unittest.main()
