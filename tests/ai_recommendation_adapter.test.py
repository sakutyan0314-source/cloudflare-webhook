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
    def test_evidence_diagnostics_are_value_free_and_numeric_safe(self):
        valid = schema.diagnose_evidence([{'field':'observation.search_clicks','value':1.0}], payload())
        self.assertIsNone(valid['code']); self.assertEqual('number', valid['items'][0]['expected_type']); self.assertTrue(valid['items'][0]['matches'])
        unknown = schema.diagnose_evidence([{'field':'observation.not_real','value':1}], payload())
        self.assertEqual('unknown_field', unknown['code']); self.assertFalse(unknown['items'][0]['field_exists'])
        null_payload = payload(); null_payload['observation']['position'] = None
        null = schema.diagnose_evidence([{'field':'observation.position','value':'null'}], null_payload)
        self.assertEqual('null_mismatch', null['code']); self.assertEqual('null', null['items'][0]['expected_type']); self.assertEqual('string', null['items'][0]['actual_type'])
        threshold = schema.diagnose_evidence([{'field':'observation.impressions','operator':'>=','value':10}], payload())
        self.assertEqual('operator_invalid', threshold['code'])
    def test_complete_article_and_observation_paths_are_required(self):
        self.assertIsNone(schema.diagnose_evidence([{'field':'article.article_id','value':17}, {'field':'observation.impressions','value':100}], payload())['code'])
        for invalid in ('article_id', 'impressions', 'observation.data_row_counts.page_daily'):
            self.assertEqual('unknown_field', schema.diagnose_evidence([{'field':invalid,'value':1}], payload())['code'])
    def test_unsafe_text_diagnostics_are_value_free_and_fail_closed(self):
        cases = [
            ('affiliate clickを購入率として扱う。', 'prohibited_affiliate_conversion_term'),
            ('purchase behaviorを増やす。', 'prohibited_purchase_term'),
            ('sales growthを増やす。', 'prohibited_sales_term'),
            ('revenue growthを増やす。', 'prohibited_revenue_term'),
            ('CVRを改善する。', 'prohibited_cvr_term'),
            ('api_key: hidden', 'suspected_api_key'),
            ('Authorization: hidden', 'suspected_authorization_header'),
            ('token: hidden', 'suspected_token'),
            ('private_key: hidden', 'suspected_secret'),
        ]
        for text, expected in cases:
            diagnostic = schema.diagnose_unsafe_ai_text({'reasons': text})
            self.assertTrue(diagnostic['blocked']); self.assertIn(expected, diagnostic['codes'])
            self.assertEqual(['reasons'], diagnostic['fields']); self.assertNotIn(text, str(diagnostic))
        normal = schema.diagnose_unsafe_ai_text({'reasons': '入力値だけを根拠に人間レビューする。'})
        self.assertFalse(normal['blocked']); self.assertEqual([], normal['codes'])
        both = schema.diagnose_unsafe_ai_text({'reasons': 'CVRと売上を扱う。', 'suggested_action': 'token: hidden'})
        self.assertEqual({'prohibited_expression', 'secret'}, set(both['categories']))
        with self.assertRaises(schema.UnsafeAiResponseError):
            schema.validate_ai_response(response(reasons='CVRを改善する。'), payload())
if __name__ == '__main__': unittest.main()
