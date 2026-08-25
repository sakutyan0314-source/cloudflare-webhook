import importlib.util, io, json, pathlib, sys, unittest
from urllib.error import HTTPError

ROOT = pathlib.Path(__file__).parents[1]
def load(name):
    spec=importlib.util.spec_from_file_location(name,ROOT/'scripts'/f'{name}.py'); module=importlib.util.module_from_spec(spec); assert spec and spec.loader
    sys.modules[name]=module; spec.loader.exec_module(module); return module

load('search_console_improvement_candidates'); load('topic_candidate'); serp=load('market_signal_serp_adapter'); report=load('market_signal_report')
analysis=load('market_signal_analysis'); adapter=load('market_signal_analysis_adapter'); openai=load('openai_market_signal_analysis_adapter')
FIX=json.loads((ROOT/'tests/fixtures/market-signal-serp-fixture.json').read_text())

class Transport:
    def __init__(self,value): self.value,self.calls,self.kwargs=value,0,None
    def analyze(self,payload,**kwargs): self.calls+=1; self.payload,self.kwargs=payload,kwargs; return self.value

def valid_response(**changes):
    value={'schema_version':'market-signal-analysis-v1','query':'Microsoft 365 Copilot エージェント','common_intents':['how','problem'],'common_angles':['導入','ガバナンス'],'uncovered_questions':[{'question':'棚卸しの実務手順は何か','classification':'possible_gap'}],'own_site_gap_assessment':{'classification':'cluster_sibling','rationale':'ガバナンス記事と隣接する。'},'candidate_drafts':[{'topic':'Microsoft 365 Copilot エージェントの棚卸し手順','reason':'導入時の管理課題を検討する。','market_evidence':'SERP metadata shows governance and introduction angles.','common_intent':'how','own_site_gap':'cluster_sibling','target_audience':'Microsoft 365 管理者','user_problem':'エージェントの棚卸し方法が分からない。','monetization_relevance':'not_evaluated','duplicate_risk':'low','confidence':'medium','requires_human_review':True}],'confidence':'medium','requires_human_review':True,'content_generation_authorized':False,'publication_authorized':False,'execution_authorized':False}
    value.update(changes); return value

class TestMarketSignalAnalysis(unittest.TestCase):
    def own(self):
        return report.build_own_site_signal(query='Microsoft 365 Copilot エージェント',articles=[{'article_id':40,'title':'Microsoft 365 Copilot エージェント導入ガバナンス','description':'権限と棚卸し','category':'security-governance'}],page_daily=[],affiliate_events=[{'article_id':40,'placement':'article'},{'article_id':40,'placement':'discord'}])
    def analyze_fixture(self,response=None):
        transport=Transport(response or valid_response()); subject=adapter.MarketSignalAnalysisAdapter(transport)
        output=subject.analyze(query='Microsoft 365 Copilot エージェント',observed_at='2026-08-25T00:00:00Z',serp_results=serp.normalize_serp_response(FIX),own_site_signal=self.own())
        return output,transport,subject
    def test_valid_analysis_is_single_call_limited_and_metadata_only(self):
        output,transport,subject=self.analyze_fixture()
        self.assertEqual('market-signal-analysis-v1',output['schema_version']); self.assertEqual(1,transport.calls)
        self.assertEqual({'model_id':'gpt-5.6-terra','max_input_tokens':1800,'max_output_tokens':600,'timeout_seconds':20,'store':False,'tools':None},transport.kwargs)
        self.assertFalse(subject.limits['automatic_retry']); self.assertFalse(subject.limits['automatic_fallback']); self.assertNotIn('url',str(transport.payload)); self.assertNotIn('body_markdown',str(transport.payload))
    def test_strict_enums_candidate_bound_and_human_authorization_boundary(self):
        invalids=[valid_response(common_intents=['invented']), valid_response(candidate_drafts=[valid_response()['candidate_drafts'][0]]*4), valid_response(requires_human_review=False), valid_response(publication_authorized=True), valid_response(candidate_drafts=[{**valid_response()['candidate_drafts'][0],'duplicate_risk':'high'}]), valid_response(candidate_drafts=[{**valid_response()['candidate_drafts'][0],'own_site_gap':'already_covered'}])]
        for value in invalids:
            with self.subTest(value=value):
                with self.assertRaises(adapter.MarketSignalAnalysisAdapterError): self.analyze_fixture(value)
    def test_questions_require_hypothesis_label_and_reject_secret_or_article_like_prose(self):
        for value in [valid_response(uncovered_questions=[{'question':'質問','classification':'confirmed_gap'}]), valid_response(candidate_drafts=[{**valid_response()['candidate_drafts'][0],'reason':'api_key: prohibited'}]), valid_response(common_angles=['# 記事タイトル'])]:
            with self.subTest(value=value):
                with self.assertRaises(adapter.MarketSignalAnalysisAdapterError): self.analyze_fixture(value)
    def test_malformed_json_shape_and_query_mismatch_are_rejected_once(self):
        for value in ['not-json', {'query':'x'}, valid_response(query='different')]:
            transport=Transport(value); subject=adapter.MarketSignalAnalysisAdapter(transport)
            with self.assertRaises(adapter.MarketSignalAnalysisAdapterError): subject.analyze(query='Microsoft 365 Copilot エージェント',observed_at='2026-08-25T00:00:00Z',serp_results=serp.normalize_serp_response(FIX),own_site_signal=self.own())
            self.assertEqual(1,transport.calls)
    def test_openai_payload_is_strict_store_false_and_has_no_tools(self):
        payload=openai.build_responses_payload({'safe':True},model_id='gpt-5.6-terra',max_output_tokens=600,store=False,tools=None)
        self.assertFalse(payload['store']); self.assertNotIn('tools',payload); self.assertTrue(payload['text']['format']['strict'])
        self.assertIn('possible_gap',json.dumps(payload)); self.assertIn('hypothesis',json.dumps(payload))
        serialized=json.dumps(payload['text']['format']['schema'])
        for unsupported in ('minLength','maxLength','minItems','maxItems','const'): self.assertNotIn(unsupported,serialized)
        self.assertEqual({'effort':'low'},payload['reasoning'])
        with self.assertRaises(openai.OpenAiMarketSignalAnalysisError): openai.build_responses_payload({},model_id='wrong',max_output_tokens=600,store=False,tools=None)
    def test_safe_http_diagnostic_truncates_and_redacts_without_retaining_raw_response(self):
        message='token: should-not-appear ' + ('x'*400)
        error=HTTPError('https://api.openai.com/v1/responses',400,'bad',None,io.BytesIO(json.dumps({'error':{'type':'invalid_request_error','code':'invalid_json_schema','message':message}}).encode()))
        diagnostic=openai.safe_http_error_diagnostic(error)
        self.assertEqual(400,diagnostic['http_status']); self.assertEqual('invalid_request_error',diagnostic['error_type']); self.assertEqual('invalid_json_schema',diagnostic['error_code'])
        self.assertNotIn('should-not-appear',diagnostic['error_message']); self.assertLessEqual(len(diagnostic['error_message']),240); self.assertNotIn('raw',diagnostic)

if __name__=='__main__': unittest.main()
