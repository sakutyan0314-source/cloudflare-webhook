import copy
import importlib.util
import pathlib
import sys
import unittest


ROOT = pathlib.Path(__file__).parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


envelope_module = load("search_console_improvement_candidate_review")
workflow = load("search_console_improvement_candidate_review_workflow")


def envelope():
    value = {
        "schema_version": envelope_module.REVIEW_SCHEMA_VERSION, "status": "pending_review",
        "article_id": 1, "title": "Ready", "category": "saas-cloud",
        "recommendation_type": "seo_review", "reason_code": "position_opportunity_with_low_ctr",
        "current_metrics": {"start": "2026-08-08", "end": "2026-08-14", "clicks": 1, "impressions": 70, "ctr": 0.014286, "position": 10.0},
        "previous_metrics": {"start": "2026-08-01", "end": "2026-08-07", "clicks": 2, "impressions": 80, "ctr": 0.025, "position": 9.0},
        "evidence": {"current_period": {}, "previous_period": {}, "delta": {}, "data_status": "sufficient"},
        "requires_human_review": True,
    }
    value["candidate_fingerprint"] = envelope_module.candidate_fingerprint(value)
    return value


def decision(status="pending_review", **changes):
    reasons = {
        "pending_review": "candidate_created",
        "accepted": "improvement_generation_candidate_approved",
        "rejected": "not_selected_for_improvement",
        "deferred": "deferred_for_later_review",
    }
    value = {"status": status, "candidate_fingerprint": envelope()["candidate_fingerprint"], "article_id": 1,
             "candidate_reason_code": "position_opportunity_with_low_ctr", "reviewer_id": "operator_primary",
             "reviewed_at": "2026-08-20T01:02:03Z", "review_reason_code": reasons.get(status, "unknown"), "previous_review_id": None}
    return {**value, **changes}


class SeoImprovementReviewWorkflowTest(unittest.TestCase):
    def record(self, status="pending_review", **changes):
        return workflow.build_review_record(envelope(), decision(status, **changes))

    def test_each_known_status_builds_a_non_executable_record(self):
        for status in ("pending_review", "accepted", "rejected", "deferred"):
            record = self.record(status)
            self.assertEqual(status, record["status"])
            self.assertTrue(all(record[key] is False for key in ("ai_generation_authorized", "article_change_authorized", "publication_authorized", "execution_authorized")))

    def test_unknown_status_fingerprint_article_and_reason_are_rejected(self):
        with self.assertRaises(workflow.SeoImprovementReviewWorkflowError): self.record("unknown")
        with self.assertRaises(workflow.SeoImprovementReviewWorkflowError): self.record(candidate_fingerprint="0" * 64)
        with self.assertRaises(workflow.SeoImprovementReviewWorkflowError): self.record(article_id=2)
        with self.assertRaises(workflow.SeoImprovementReviewWorkflowError): self.record(candidate_reason_code="unknown")

    def test_append_only_order_and_latest_status(self):
        first = self.record()
        chain = workflow.append_review_record([], first)
        second = self.record("deferred", previous_review_id=first["review_id"], reviewed_at="2026-08-20T01:03:03Z")
        updated = workflow.append_review_record(chain, second)
        self.assertEqual([first, second], updated)
        self.assertEqual("deferred", workflow.latest_review_status(updated))
        self.assertEqual("pending_review", workflow.latest_review_status([first]))
        with self.assertRaises(workflow.SeoImprovementReviewWorkflowError): workflow.append_review_record(updated, first)

    def test_record_validation_detects_forged_fingerprint(self):
        record = self.record()
        forged = copy.deepcopy(record); forged["candidate_fingerprint"] = "0" * 64
        with self.assertRaises(workflow.SeoImprovementReviewWorkflowError): workflow.validate_review_record(forged)


if __name__ == "__main__":
    unittest.main()
