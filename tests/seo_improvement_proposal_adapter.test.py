import importlib.util
import pathlib
import sys
import unittest


ROOT = pathlib.Path(__file__).parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / (name + ".py"))
    module = importlib.util.module_from_spec(spec); assert spec and spec.loader
    sys.modules[name] = module; spec.loader.exec_module(module); return module


envelope_module = load("search_console_improvement_candidate_review")
workflow = load("search_console_improvement_candidate_review_workflow")
proposal = load("seo_improvement_proposal")
adapter_module = load("seo_improvement_proposal_adapter")
openai = load("openai_seo_improvement_proposal_adapter")


def envelope():
    value = {"schema_version": envelope_module.REVIEW_SCHEMA_VERSION, "status": "pending_review", "article_id": 1, "title": "Ready", "category": "saas-cloud", "recommendation_type": "seo_review", "reason_code": "position_opportunity_with_low_ctr", "current_metrics": {"start": "2026-08-08", "end": "2026-08-14", "clicks": 1, "impressions": 70, "ctr": 0.014286, "position": 10.0}, "previous_metrics": {"start": "2026-08-01", "end": "2026-08-07", "clicks": 2, "impressions": 80, "ctr": 0.025, "position": 9.0}, "evidence": {"current_period": {"clicks": 1}, "previous_period": {"clicks": 2}, "delta": {"clicks": -1}, "data_status": "sufficient"}, "requires_human_review": True}
    value["candidate_fingerprint"] = envelope_module.candidate_fingerprint(value); return value


def accepted(value):
    return workflow.build_review_record(value, {"status": "accepted", "candidate_fingerprint": value["candidate_fingerprint"], "article_id": 1, "candidate_reason_code": value["reason_code"], "reviewer_id": "operator", "reviewed_at": "2026-08-20T01:02:03Z", "review_reason_code": "improvement_generation_candidate_approved", "previous_review_id": None})


def response(**changes):
    return {"improvement_hypothesis": "検索結果での選択理由を明確にする。", "proposed_changes": [{"scope": "snippet", "rationale": "表示機会に対する反応を確認する。", "suggested_direction": "対象課題を明確に示す。"}], "expected_impact": "クリック反応の変化を観測できる。", "risk": "low", **changes}


class Transport:
    def __init__(self, value): self.value, self.calls, self.kwargs = value, 0, None
    def propose(self, payload, **kwargs): self.calls += 1; self.payload, self.kwargs = payload, kwargs; return self.value


class TestProposalAdapter(unittest.TestCase):
    def make_subject(self, transport):
        value = envelope(); return adapter_module.SeoImprovementProposalAdapter(transport), value, accepted(value)

    def test_mock_response_generates_valid_proposal_with_fixed_config(self):
        transport = Transport(response()); subject, value, review = self.make_subject(transport)
        result = subject.generate(value, review)
        self.assertEqual("seo-improvement-proposal-v1", result["schema_version"]); self.assertEqual(1, transport.calls)
        self.assertEqual({"model_id": "gpt-5.6-terra", "max_input_tokens": 900, "max_output_tokens": 500, "timeout_seconds": 20, "store": False, "tools": None}, transport.kwargs)
        self.assertFalse(subject.limits["automatic_retry"]); self.assertFalse(subject.limits["automatic_fallback"])

    def test_invalid_json_shape_evidence_or_permission_mutation_are_rejected_once(self):
        for invalid in ("not-json", {"unexpected": True}, response(evidence_summary={}), response(article_change_authorized=True)):
            transport = Transport(invalid); subject, value, review = self.make_subject(transport)
            with self.assertRaises(adapter_module.SeoImprovementProposalAdapterError): subject.generate(value, review)
            self.assertEqual(1, transport.calls)

    def test_timeout_and_secret_text_stop_without_retry(self):
        class Timeout:
            def __init__(self): self.calls = 0
            def propose(self, *_args, **_kwargs): self.calls += 1; raise TimeoutError()
        transport = Timeout(); subject, value, review = self.make_subject(transport)
        with self.assertRaises(adapter_module.SeoImprovementProposalAdapterError): subject.generate(value, review)
        self.assertEqual("timeout", subject.last_rejection_code); self.assertEqual(1, transport.calls)
        transport = Transport(response(improvement_hypothesis="token: forbidden")); subject, value, review = self.make_subject(transport)
        with self.assertRaises(adapter_module.SeoImprovementProposalAdapterError): subject.generate(value, review)
        self.assertEqual(1, transport.calls)

    def test_openai_payload_is_structured_store_false_and_tools_omitted(self):
        payload = openai.build_responses_payload({"safe": True}, model_id="gpt-5.6-terra", max_output_tokens=500, store=False, tools=None)
        self.assertFalse(payload["store"]); self.assertNotIn("tools", payload); self.assertTrue(payload["text"]["format"]["strict"])
        with self.assertRaises(openai.OpenAiSeoImprovementProposalError): openai.build_responses_payload({}, model_id="other", max_output_tokens=500, store=False, tools=None)


if __name__ == "__main__":
    unittest.main(defaultTest="TestProposalAdapter")
