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


spec = importlib.util.spec_from_file_location("seo_improvement_execution_approval_test", ROOT / "tests" / "seo_improvement_execution_approval.test.py")
fixture = importlib.util.module_from_spec(spec)
assert spec and spec.loader
sys.modules["seo_improvement_execution_approval_test"] = fixture
spec.loader.exec_module(fixture)
load("seo_improvement_execution_preflight")
qualification = load("seo_execution_candidate_qualification")
proposal = sys.modules["seo_improvement_proposal"]
proposal_review = sys.modules["seo_improvement_proposal_review_workflow"]
plans = sys.modules["seo_improvement_change_plan"]
plan_review = sys.modules["seo_improvement_change_plan_review_workflow"]
candidate = sys.modules["seo_improvement_change_candidate"]
candidate_review = sys.modules["seo_improvement_change_candidate_review_workflow"]
execution = sys.modules["seo_improvement_execution_candidate"]


def artifacts():
    envelope = {
        "schema_version": sys.modules["search_console_improvement_candidate_review"].REVIEW_SCHEMA_VERSION,
        "status": "pending_review", "article_id": 1, "title": "Current title has enough length",
        "category": "saas-cloud", "recommendation_type": "seo_review",
        "reason_code": "position_opportunity_with_low_ctr",
        "current_metrics": {"start": "2026-08-08", "end": "2026-08-14", "clicks": 1, "impressions": 70, "ctr": .01, "position": 10},
        "previous_metrics": {"start": "2026-08-01", "end": "2026-08-07", "clicks": 2, "impressions": 80, "ctr": .02, "position": 9},
        "evidence": {"current_period": {}, "previous_period": {}, "delta": {}, "data_status": "sufficient"},
        "requires_human_review": True,
    }
    envelope["candidate_fingerprint"] = sys.modules["search_console_improvement_candidate_review"].candidate_fingerprint(envelope)
    seo_review = sys.modules["search_console_improvement_candidate_review_workflow"].build_review_record(envelope, {"status": "accepted", "candidate_fingerprint": envelope["candidate_fingerprint"], "article_id": 1, "candidate_reason_code": envelope["reason_code"], "reviewer_id": "operator", "reviewed_at": "2026-08-21T01:00:00Z", "review_reason_code": "improvement_generation_candidate_approved", "previous_review_id": None})
    proposal_input = proposal.build_proposal_input(envelope, seo_review, model_version="gpt-5.6-terra")
    item = proposal.build_mock_proposal(proposal_input, {"improvement_hypothesis": "検索結果における選択理由を明確にする。", "proposed_changes": [{"scope": "snippet", "rationale": "反応を検証する。", "suggested_direction": "対象課題を明確にする。"}], "expected_impact": "反応変化を観測できる。", "risk": "low"})
    proposal_review_record = proposal_review.build_review_record(item, proposal_input, {"status": "accepted", "proposal_id": item["proposal_id"], "proposal_fingerprint": proposal_review.proposal_fingerprint(item, proposal_input), "article_id": 1, "candidate_fingerprint": item["candidate_fingerprint"], "accepted_review_id": item["accepted_review_id"], "reviewer_id": "operator", "reviewed_at": "2026-08-21T01:02:00Z", "review_reason_code": "proposal_approved_for_change_plan", "previous_review_id": None})
    plan_input = plans.build_change_plan_input(item, proposal_input, [proposal_review_record])
    plan = plans.build_pending_change_plan(plan_input)
    plan_review_record = plan_review.build_review_record(plan, plan_input, {**{key: plan[key] for key in plan_review._SOURCE_FIELDS}, "status": "accepted", "reviewer_id": "operator", "reviewed_at": "2026-08-21T01:03:00Z", "review_reason_code": "change_candidate_creation_approved", "previous_review_id": None})
    snapshot = {"article_id": 1, "title": "Current title has enough length", "description": "Current description is sufficiently long to satisfy the snapshot validation requirement.", "category": "saas-cloud", "content_sha256": "a" * 64, "body_markdown_sha256": "b" * 64, "published_at": "2026-01-01T00:00:00Z", "updated_at": "2026-01-02T00:00:00Z", "seo_status": "ready"}
    change_input = candidate.build_change_candidate_input(plan, plan_input, [plan_review_record], snapshot, {"title": "Improved title that is sufficiently descriptive"})
    change = candidate.build_change_candidate(change_input)
    change_review = candidate_review.build_review_record(change, change_input, {**{key: change[key] for key in candidate_review._SOURCE}, "status": "accepted", "reviewer_id": "operator", "reviewed_at": "2026-08-21T01:04:00Z", "review_reason_code": "execution_candidate_creation_approved", "previous_review_id": None})
    execution_input = execution.build_execution_candidate_input(change, change_input, [change_review])
    execution_candidate = execution.build_execution_candidate(execution_input)
    approval = fixture.source()[0]
    return {"envelope": envelope, "seo_review_records": [seo_review], "proposal_input": proposal_input, "proposal": item, "proposal_review_records": [proposal_review_record], "plan_input": plan_input, "plan": plan, "plan_review_records": [plan_review_record], "change_candidate_input": change_input, "change_candidate": change, "change_candidate_review_records": [change_review], "execution_candidate_input": execution_input, "execution_candidate": execution_candidate, "execution_approval": approval, "latest_snapshot": snapshot}


class TestFirstExecutionQualification(unittest.TestCase):
    def test_full_accepted_chain_qualifies_without_write(self):
        value = artifacts()
        result = qualification.qualify_first_execution_candidate(value, now="2026-08-21T02:10:00Z")
        self.assertEqual("qualified", result["status"])
        self.assertFalse(result["changed_db"])
        self.assertEqual(0, result["rows_written"])
        self.assertFalse(result["approval_consumed"])

    def test_rejects_nonaccepted_chain_stale_and_consumed_approval(self):
        value = artifacts()
        value["seo_review_records"] = []
        with self.assertRaises(qualification.SeoExecutionCandidateQualificationError):
            qualification.qualify_first_execution_candidate(value, now="2026-08-21T02:10:00Z")
        value = artifacts()
        value["latest_snapshot"] = {**value["latest_snapshot"], "updated_at": "2026-01-03T00:00:00Z"}
        with self.assertRaises(qualification.SeoExecutionCandidateQualificationError):
            qualification.qualify_first_execution_candidate(value, now="2026-08-21T02:10:00Z")
        value = artifacts()
        with self.assertRaises(qualification.SeoExecutionCandidateQualificationError):
            qualification.qualify_first_execution_candidate(value, now="2026-08-21T02:10:00Z", used_approval_ids=[value["execution_approval"]["execution_approval_id"]])


if __name__ == "__main__":
    unittest.main()
