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


env = load("search_console_improvement_candidate_review")
candidate_review = load("search_console_improvement_candidate_review_workflow")
proposal = load("seo_improvement_proposal")
proposal_review = load("seo_improvement_proposal_review_workflow")
plans = load("seo_improvement_change_plan")
plan_review = load("seo_improvement_change_plan_review_workflow")
load("ai_recommendation_review")
load("ai_recommendation_review_workflow")
load("ai_change_plan")
candidate = load("seo_improvement_change_candidate")
workflow = load("seo_improvement_change_candidate_review_workflow")
execution = load("seo_improvement_execution_candidate")


def source(changes=None):
    envelope = {
        "schema_version": env.REVIEW_SCHEMA_VERSION, "status": "pending_review", "article_id": 1,
        "title": "Current title has enough length", "category": "saas-cloud", "recommendation_type": "seo_review",
        "reason_code": "position_opportunity_with_low_ctr",
        "current_metrics": {"start": "2026-08-08", "end": "2026-08-14", "clicks": 1, "impressions": 70, "ctr": .01, "position": 10},
        "previous_metrics": {"start": "2026-08-01", "end": "2026-08-07", "clicks": 2, "impressions": 80, "ctr": .02, "position": 9},
        "evidence": {"current_period": {}, "previous_period": {}, "delta": {}, "data_status": "sufficient"}, "requires_human_review": True,
    }
    envelope["candidate_fingerprint"] = env.candidate_fingerprint(envelope)
    accepted = candidate_review.build_review_record(envelope, {"status": "accepted", "candidate_fingerprint": envelope["candidate_fingerprint"], "article_id": 1, "candidate_reason_code": envelope["reason_code"], "reviewer_id": "operator", "reviewed_at": "2026-08-21T01:00:00Z", "review_reason_code": "improvement_generation_candidate_approved", "previous_review_id": None})
    proposal_input = proposal.build_proposal_input(envelope, accepted, model_version="gpt-5.6-terra")
    item = proposal.build_mock_proposal(proposal_input, {"improvement_hypothesis": "検索結果における選択理由を明確にする。", "proposed_changes": [{"scope": "snippet", "rationale": "反応を検証する。", "suggested_direction": "対象課題を明確にする。"}], "expected_impact": "反応変化を観測できる。", "risk": "low"})
    accepted_proposal = proposal_review.build_review_record(item, proposal_input, {"status": "accepted", "proposal_id": item["proposal_id"], "proposal_fingerprint": proposal_review.proposal_fingerprint(item, proposal_input), "article_id": 1, "candidate_fingerprint": item["candidate_fingerprint"], "accepted_review_id": item["accepted_review_id"], "reviewer_id": "operator", "reviewed_at": "2026-08-21T01:02:00Z", "review_reason_code": "proposal_approved_for_change_plan", "previous_review_id": None})
    plan_input = plans.build_change_plan_input(item, proposal_input, [accepted_proposal])
    plan = plans.build_pending_change_plan(plan_input)
    accepted_plan = plan_review.build_review_record(plan, plan_input, {**{key: plan[key] for key in plan_review._SOURCE_FIELDS}, "status": "accepted", "reviewer_id": "operator", "reviewed_at": "2026-08-21T01:03:00Z", "review_reason_code": "change_candidate_creation_approved", "previous_review_id": None})
    snapshot = {"article_id": 1, "title": "Current title has enough length", "description": "Current description is sufficiently long to satisfy the snapshot validation requirement.", "category": "saas-cloud", "content_sha256": "a" * 64, "body_markdown_sha256": "b" * 64, "published_at": "2026-01-01T00:00:00Z", "updated_at": "2026-01-02T00:00:00Z", "seo_status": "ready"}
    change_input = candidate.build_change_candidate_input(plan, plan_input, [accepted_plan], snapshot, changes or {"title": "Improved title that is sufficiently descriptive"})
    change = candidate.build_change_candidate(change_input)
    accepted_change = workflow.build_review_record(change, change_input, {**{key: change[key] for key in workflow._SOURCE}, "status": "accepted", "reviewer_id": "operator", "reviewed_at": "2026-08-21T01:04:00Z", "review_reason_code": "execution_candidate_creation_approved", "previous_review_id": None})
    return change, change_input, [accepted_change], snapshot


class TestSeoExecutionCandidate(unittest.TestCase):
    def build(self, changes=None):
        change, change_input, reviews, snapshot = source(changes)
        execution_input = execution.build_execution_candidate_input(change, change_input, reviews)
        return execution.build_execution_candidate(execution_input), execution_input, change, change_input, reviews, snapshot

    def test_accepted_candidate_review_generates_title_or_description_snapshot(self):
        item, _, _, _, _, _ = self.build()
        self.assertEqual("Improved title that is sufficiently descriptive", item["after_snapshot"]["title"])
        item, _, _, _, _, _ = self.build({"description": "Improved description contains enough useful detail for the search result snippet."})
        self.assertIn("description", item["expected_diff"])

    def test_fingerprint_stability_change_and_deterministic_identity(self):
        item, input_value, *_ = self.build()
        self.assertEqual(item["execution_candidate_fingerprint"], execution.execution_candidate_fingerprint(copy.deepcopy(item)))
        second, *_ = self.build({"title": "Different improved title that remains sufficiently descriptive"})
        self.assertNotEqual(item["execution_candidate_fingerprint"], second["execution_candidate_fingerprint"])
        self.assertEqual(item["execution_candidate_id"], execution.build_execution_candidate(copy.deepcopy(input_value))["execution_candidate_id"])

    def test_stale_snapshot_and_source_mismatch_are_rejected(self):
        item, input_value, _, _, _, snapshot = self.build()
        stale = copy.deepcopy(snapshot)
        stale["updated_at"] = "2026-01-03T00:00:00Z"
        with self.assertRaises(execution.SeoImprovementExecutionCandidateError):
            execution.validate_execution_candidate(item, input_value, current_snapshot=stale)
        for field, value in (("candidate_fingerprint", "0" * 64), ("plan_id", "other"), ("proposal_id", "other")):
            forged = copy.deepcopy(item)
            forged[field] = value
            with self.assertRaises(execution.SeoImprovementExecutionCandidateError):
                execution.validate_execution_candidate(forged, input_value)

    def test_body_sql_and_authorization_changes_are_rejected(self):
        change, change_input, reviews, _ = source()
        for field in ("body_markdown", "sql"):
            forged_input = copy.deepcopy(change_input)
            forged_input["proposed_changes"] = {field: "forbidden"}
            with self.assertRaises(execution.SeoImprovementExecutionCandidateError):
                execution.build_execution_candidate_input(change, forged_input, reviews)
        item, input_value, *_ = self.build()
        forged = copy.deepcopy(item)
        forged["execution_authorized"] = True
        with self.assertRaises(execution.SeoImprovementExecutionCandidateError):
            execution.validate_execution_candidate(forged, input_value)

    def test_latest_review_must_be_accepted_and_no_d1_write_dependency(self):
        change, change_input, reviews, _ = source()
        deferred = workflow.build_review_record(change, change_input, {**{key: change[key] for key in workflow._SOURCE}, "status": "deferred", "reviewer_id": "operator", "reviewed_at": "2026-08-21T01:05:00Z", "review_reason_code": "candidate_deferred", "previous_review_id": reviews[-1]["candidate_review_id"]})
        chain = workflow.append_review_record(reviews, deferred, change, change_input)
        with self.assertRaises(execution.SeoImprovementExecutionCandidateError):
            execution.build_execution_candidate_input(change, change_input, chain)
        item, input_value, *_ = self.build()
        execution.validate_execution_candidate(item, input_value)


if __name__ == "__main__":
    unittest.main()
