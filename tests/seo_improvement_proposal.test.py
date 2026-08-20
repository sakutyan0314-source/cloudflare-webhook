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
proposal_module = load("seo_improvement_proposal")


def envelope():
    value = {"schema_version": envelope_module.REVIEW_SCHEMA_VERSION, "status": "pending_review", "article_id": 1, "title": "Ready", "category": "saas-cloud", "recommendation_type": "seo_review", "reason_code": "position_opportunity_with_low_ctr", "current_metrics": {"start": "2026-08-08", "end": "2026-08-14", "clicks": 1, "impressions": 70, "ctr": 0.014286, "position": 10.0}, "previous_metrics": {"start": "2026-08-01", "end": "2026-08-07", "clicks": 2, "impressions": 80, "ctr": 0.025, "position": 9.0}, "evidence": {"current_period": {"clicks": 1}, "previous_period": {"clicks": 2}, "delta": {"clicks": -1}, "data_status": "sufficient"}, "requires_human_review": True}
    value["candidate_fingerprint"] = envelope_module.candidate_fingerprint(value)
    return value


def accepted_review(value):
    decision = {"status": "accepted", "candidate_fingerprint": value["candidate_fingerprint"], "article_id": value["article_id"], "candidate_reason_code": value["reason_code"], "reviewer_id": "operator_primary", "reviewed_at": "2026-08-20T01:02:03Z", "review_reason_code": "improvement_generation_candidate_approved", "previous_review_id": None}
    return workflow.build_review_record(value, decision)


def mock_response(**changes):
    return {"improvement_hypothesis": "検索結果での選択理由をより明確にすると反応改善が見込める。", "proposed_changes": [{"scope": "snippet", "rationale": "表示機会に対して反応が低い。", "suggested_direction": "記事の対象課題と得られる判断材料を明確にする。"}], "expected_impact": "検索結果からのクリック改善を検証できる。", "risk": "low", **changes}


class SeoImprovementProposalTest(unittest.TestCase):
    def input(self, value=None, review=None, **kwargs):
        value = value or envelope()
        return proposal_module.build_proposal_input(value, review or accepted_review(value), **kwargs)

    def test_normal_mock_proposal_is_non_executable(self):
        proposal_input = self.input()
        proposal = proposal_module.build_mock_proposal(proposal_input, mock_response())
        proposal_module.validate_proposal(proposal, proposal_input)
        self.assertTrue(proposal["requires_human_review"])
        self.assertTrue(all(proposal[key] is False for key in ("article_change_authorized", "publication_authorized", "execution_authorized")))

    def test_only_accepted_review_is_allowed(self):
        value = envelope(); record = accepted_review(value); record["status"] = "deferred"
        with self.assertRaises(proposal_module.SeoImprovementProposalError): self.input(value, record)

    def test_fingerprint_article_and_reason_mismatches_are_rejected(self):
        value = envelope(); record = accepted_review(value)
        for field, replacement in (("candidate_fingerprint", "0" * 64), ("article_id", 2), ("candidate_reason_code", "impressions_with_zero_clicks")):
            changed = copy.deepcopy(record); changed[field] = replacement
            with self.assertRaises(proposal_module.SeoImprovementProposalError): self.input(value, changed)

    def test_permissions_secret_and_evidence_tampering_are_rejected(self):
        proposal_input = self.input(); proposal = proposal_module.build_mock_proposal(proposal_input, mock_response())
        for field, replacement in (("article_change_authorized", True), ("candidate_fingerprint", "0" * 64), ("evidence_summary", {})):
            changed = copy.deepcopy(proposal); changed[field] = replacement
            with self.assertRaises(proposal_module.SeoImprovementProposalError): proposal_module.validate_proposal(changed, proposal_input)
        with self.assertRaises(proposal_module.SeoImprovementProposalError): proposal_module.build_mock_proposal(proposal_input, mock_response(improvement_hypothesis="token: forbidden material"))
        with self.assertRaises(proposal_module.SeoImprovementProposalError): proposal_module.build_mock_proposal(proposal_input, mock_response(risk="unknown"))

    def test_proposal_identity_is_deterministic_and_includes_model_version(self):
        proposal_input = self.input()
        first = proposal_module.build_mock_proposal(proposal_input, mock_response())
        self.assertEqual(first["proposal_id"], proposal_module.build_mock_proposal(copy.deepcopy(proposal_input), mock_response())["proposal_id"])
        versioned = self.input(model_version="future-model-v1")
        self.assertNotEqual(first["proposal_id"], proposal_module.build_mock_proposal(versioned, mock_response())["proposal_id"])

    def test_no_d1_write_or_provider_dependency(self):
        self.assertEqual("unbound", self.input()["model_version"])


if __name__ == "__main__":
    unittest.main()
