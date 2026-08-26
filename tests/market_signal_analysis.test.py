import importlib.util, io, json, pathlib, sys, unittest
from urllib.error import HTTPError

ROOT = pathlib.Path(__file__).parents[1]
def load(name):
    spec=importlib.util.spec_from_file_location(name,ROOT/'scripts'/f'{name}.py'); module=importlib.util.module_from_spec(spec); assert spec and spec.loader
    sys.modules[name]=module; spec.loader.exec_module(module); return module

load('search_console_improvement_candidates'); load('topic_candidate'); serp=load('market_signal_serp_adapter'); report=load('market_signal_report')
analysis=load('market_signal_analysis'); adapter=load('market_signal_analysis_adapter'); openai=load('openai_market_signal_analysis_adapter')
FIX=json.loads((ROOT/'tests/fixtures/market-signal-serp-fixture.json').read_text())
POLICY_REPLAY=json.loads((ROOT/'tests/fixtures/market-signal-analysis-policy-replay.json').read_text())

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
        self.assertEqual({'model_id':'gpt-5.6-terra','max_input_tokens':1800,'max_output_tokens':2400,'timeout_seconds':20,'store':False,'tools':None},transport.kwargs)
        self.assertFalse(subject.limits['automatic_retry']); self.assertFalse(subject.limits['automatic_fallback']); self.assertNotIn('url',str(transport.payload)); self.assertNotIn('body_markdown',str(transport.payload))
    def test_strict_enums_candidate_bound_and_human_authorization_boundary(self):
        invalids=[valid_response(common_intents=['invented']), valid_response(candidate_drafts=[valid_response()['candidate_drafts'][0]]*4), valid_response(requires_human_review=False), valid_response(publication_authorized=True), valid_response(candidate_drafts=[{**valid_response()['candidate_drafts'][0],'duplicate_risk':'high'}]), valid_response(candidate_drafts=[{**valid_response()['candidate_drafts'][0],'own_site_gap':'already_covered'}])]
        for value in invalids:
            with self.subTest(value=value):
                with self.assertRaises(adapter.MarketSignalAnalysisAdapterError): self.analyze_fixture(value)

    def test_local_policy_replay_exposes_value_free_candidate_limit_metadata(self):
        with self.assertRaises(adapter.MarketSignalAnalysisAdapterError) as error:
            self.analyze_fixture(POLICY_REPLAY)
        self.assertEqual('schema_or_policy_failure', error.exception.code)
        self.assertEqual({'validation_rule':'candidate_count_invalid','field_name':'candidate_drafts',
                          'expected_type':'array <= 3','actual_type':'array','array_count':4,
                          'policy_code':'candidate_maximum'}, error.exception.diagnostic)
        self.assertNotIn('候補', str(error.exception.diagnostic))

    def test_policy_contract_rejects_unsafe_candidate_enums_before_local_validation(self):
        candidate=openai.RESPONSE_SCHEMA['properties']['candidate_drafts']['items']['properties']
        self.assertEqual(['cluster_sibling','possible_gap'], candidate['own_site_gap']['enum'])
        self.assertEqual(['none','low','medium'], candidate['duplicate_risk']['enum'])
        self.assertIn('at most 3', openai.SYSTEM_INSTRUCTIONS)
        self.assertIn('already_covered', openai.SYSTEM_INSTRUCTIONS)
        self.assertIn('250 characters', openai.SYSTEM_INSTRUCTIONS)

    def test_local_validator_keeps_text_and_duplicate_boundaries_with_safe_metadata(self):
        cases=[
            (valid_response(common_angles=['x'*251]), 'text_length_exceeded', 'common_angle', 'field_length_limit'),
            (valid_response(candidate_drafts=[{**valid_response()['candidate_drafts'][0],'duplicate_risk':'high'}]), 'candidate_high_duplicate_risk_rejected', 'candidate_drafts[].duplicate_risk', 'high_duplicate_risk_rejected'),
            (valid_response(candidate_drafts=[{**valid_response()['candidate_drafts'][0],'own_site_gap':'already_covered'}]), 'candidate_covered_gap_rejected', 'candidate_drafts[].own_site_gap', 'already_covered_candidate_rejected'),
        ]
        for value, rule, field, policy in cases:
            with self.subTest(rule=rule):
                with self.assertRaises(adapter.MarketSignalAnalysisAdapterError) as error:
                    self.analyze_fixture(value)
                self.assertEqual('schema_or_policy_failure', error.exception.code)
                self.assertEqual(rule, error.exception.diagnostic['validation_rule'])
                self.assertEqual(field, error.exception.diagnostic['field_name'])
                self.assertEqual(policy, error.exception.diagnostic['policy_code'])
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
        payload=openai.build_responses_payload({'safe':True},model_id='gpt-5.6-terra',max_output_tokens=2400,store=False,tools=None)
        self.assertFalse(payload['store']); self.assertNotIn('tools',payload); self.assertTrue(payload['text']['format']['strict'])
        self.assertIn('possible_gap',json.dumps(payload)); self.assertIn('hypothesis',json.dumps(payload))
        serialized=json.dumps(payload['text']['format']['schema'])
        for unsupported in ('minLength','maxLength','minItems','maxItems','const'): self.assertNotIn(unsupported,serialized)
        self.assertEqual({'effort':'low'},payload['reasoning'])
        with self.assertRaises(openai.OpenAiMarketSignalAnalysisError): openai.build_responses_payload({},model_id='wrong',max_output_tokens=2400,store=False,tools=None)
    def test_safe_http_diagnostic_truncates_and_redacts_without_retaining_raw_response(self):
        message='token: should-not-appear ' + ('x'*400)
        error=HTTPError('https://api.openai.com/v1/responses',400,'bad',None,io.BytesIO(json.dumps({'error':{'type':'invalid_request_error','code':'invalid_json_schema','message':message}}).encode()))
        diagnostic=openai.safe_http_error_diagnostic(error)
        self.assertEqual(400,diagnostic['http_status']); self.assertEqual('invalid_request_error',diagnostic['error_type']); self.assertEqual('invalid_json_schema',diagnostic['error_code'])
        self.assertNotIn('should-not-appear',diagnostic['error_message']); self.assertLessEqual(len(diagnostic['error_message']),240); self.assertNotIn('raw',diagnostic)
    def test_response_extraction_handles_reasoning_then_message_and_classifies_safe_failures(self):
        success={'status':'completed','response_id':'must-not-appear','usage':{'input_tokens':321,'output_tokens':654,'output_tokens_details':{'reasoning_tokens':500}},'output':[{'type':'reasoning'},{'type':'message','role':'assistant','content':[{'type':'output_text','text':'{"ok":true}'}]}]}
        self.assertEqual('{"ok":true}',openai._output_text(success)); diagnostic=openai.response_structure_diagnostic(success)
        self.assertEqual(['reasoning','message'],diagnostic['output_item_types']); self.assertNotIn('response_id',diagnostic); self.assertNotIn('{"ok":true}',str(diagnostic))
        self.assertEqual({'input_tokens':321,'output_tokens':654,'output_tokens_details':{'reasoning_tokens':500}},diagnostic['usage'])
        cases=[({'status':'incomplete','incomplete_details':{'reason':'max_output_tokens'},'output':[]},'incomplete'),({'status':'failed','output':[]},'non_completed_status'),({'status':'completed','output':[{'type':'message','role':'assistant','content':[{'type':'refusal','refusal':'must-not-appear'}]}]},'refusal'),({'status':'completed','output':[{'type':'message','role':'assistant','content':[]}]},'missing_output_text'),({'status':'completed','output':[{'type':'message','role':'assistant','content':[{'type':'output_text','text':'{}'},{'type':'output_text','text':'{}'}]}]},'ambiguous_output_text'),({'status':'completed','output':[{'type':'tool_call'}]},'unknown_output_type'),({'status':'completed','output':[{'type':'message','role':'assistant','content':[{'type':'output_image'}]}]},'unknown_content_type')]
        for value,code in cases:
            with self.subTest(code=code):
                with self.assertRaises(openai.OpenAiMarketSignalAnalysisResponseError) as error: openai._output_text(value)
                self.assertEqual(code,error.exception.code); self.assertNotIn('must-not-appear',str(error.exception.diagnostic))
    def test_malformed_json_after_one_output_text_is_classified(self):
        diagnostic=openai.response_structure_diagnostic({'status':'completed','output':[{'type':'message','role':'assistant','content':[{'type':'output_text','text':'not-json'}]}]})
        with self.assertRaises(json.JSONDecodeError): json.loads(openai._output_text({'status':'completed','output':[{'type':'message','role':'assistant','content':[{'type':'output_text','text':'not-json'}]}]}))
        self.assertEqual(1,diagnostic['output_text_count'])

    def test_incomplete_usage_diagnostic_is_numeric_and_content_free(self):
        response={'status':'incomplete','incomplete_details':{'reason':'max_output_tokens'},
                  'usage':{'input_tokens':1800,'output_tokens':2400,
                           'output_tokens_details':{'reasoning_tokens':1900},'ignored':'not-exposed'},
                  'output':[],'response_id':'must-not-appear'}
        diagnostic=openai.response_structure_diagnostic(response)
        self.assertEqual('max_output_tokens',diagnostic['incomplete_reason'])
        self.assertEqual({'input_tokens':1800,'output_tokens':2400,
                          'output_tokens_details':{'reasoning_tokens':1900}},diagnostic['usage'])
        self.assertNotIn('response_id',str(diagnostic)); self.assertNotIn('ignored',str(diagnostic))

if __name__=='__main__': unittest.main()
