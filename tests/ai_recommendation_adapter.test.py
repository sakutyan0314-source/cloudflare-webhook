import importlib.util, json, pathlib, sys, unittest
ROOT = pathlib.Path(__file__).parents[1]
def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / f'{name}.py'); mod = importlib.util.module_from_spec(spec); sys.modules[name] = mod; spec.loader.exec_module(mod); return mod
schema=load('ai_recommendation_schema'); adapter_mod=load('ai_recommendation_adapter')
fixture=json.loads((ROOT/'tests/fixtures/ai-recommendation-fixture.json').read_text())
def payload():
    return schema.validate_input({'schema_version':schema.INPUT_SCHEMA_VERSION, **fixture, 'rule_assessment': {'ai_eligible': True, 'data_sufficiency':'sufficient', 'candidate_types':['improve_affiliate_cta'], 'reasons':['fixed_thresholds_met']}})
def response(**changes):
    value={'recommendation_type':'improve_affiliate_cta','priority':'medium','confidence':'medium','evidence':[{'field':'observation.search_clicks','value':1}], 'reasons':'検索クリックは観測されているが、導線文言の改善仮説を確認する。','suggested_action':'Amazon導線の説明文を人間レビューで見直す。','expected_effect':'クリック導線の理解を改善できる可能性を観測する。','risk_level':'low'}; value.update(changes); return value
class Transport:
    def __init__(self, result): self.result=result; self.calls=0
    def propose(self, payload, **kwargs): self.calls+=1; return self.result
class AdapterTest(unittest.TestCase):
    def test_accepts_constrained_response_and_limits_cost(self):
        transport=Transport(response()); subject=adapter_mod.AiRecommendationAdapter(transport); result=subject.recommend(payload()); self.assertEqual('medium', result['priority']); self.assertEqual(1,transport.calls); self.assertFalse(subject.limits['automatic_retry'])
    def test_rejects_hallucinated_evidence_cvr_purchase_secret_and_bad_schema(self):
        for bad in [response(evidence=[{'field':'observation.impressions','value':999}]), response(reasons='CVRと購入率を改善する。'), response(expected_effect='売上を増やす。'), response(suggested_action='Authorization: Bearer x')]:
            with self.assertRaises(adapter_mod.AiRecommendationError): adapter_mod.AiRecommendationAdapter(Transport(bad)).recommend(payload())
        subject = adapter_mod.AiRecommendationAdapter(Transport(response(reasons='CVRと購入率を改善する。')))
        with self.assertRaises(adapter_mod.AiRecommendationError): subject.recommend(payload())
        self.assertEqual('prohibited_expression_or_secret', subject.last_rejection_code)
    def test_timeout_and_ai_ineligible_stop_without_retry(self):
        class Timeout:
            def propose(self,*args,**kwargs): raise TimeoutError()
        with self.assertRaises(adapter_mod.AiRecommendationError): adapter_mod.AiRecommendationAdapter(Timeout()).recommend(payload())
        class ServerError:
            def propose(self,*args,**kwargs): raise RuntimeError('provider 5xx response body must not escape')
        with self.assertRaises(adapter_mod.AiRecommendationError): adapter_mod.AiRecommendationAdapter(ServerError()).recommend(payload())
        denied=payload(); denied['rule_assessment']['ai_eligible']=False
        with self.assertRaises(adapter_mod.AiRecommendationError): adapter_mod.AiRecommendationAdapter(Transport(response())).recommend(denied)
if __name__ == '__main__': unittest.main()
