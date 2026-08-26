"""CLI-level contract test for the complete cache-to-report Market Analysis path."""
import importlib.util, io, json, pathlib, sys, tempfile, unittest
from contextlib import redirect_stdout
from datetime import datetime, timezone

ROOT=pathlib.Path(__file__).parents[1]
def load(name):
 spec=importlib.util.spec_from_file_location(name,ROOT/'scripts'/f'{name}.py');mod=importlib.util.module_from_spec(spec);assert spec and spec.loader;sys.modules[name]=mod;spec.loader.exec_module(mod);return mod
load('search_console_improvement_candidates');load('topic_candidate');serp=load('market_signal_serp_adapter');load('market_signal_report');load('market_signal_analysis');load('market_signal_analysis_adapter');openai=load('openai_market_signal_analysis_adapter');load('search_console_collector');load('search_console_d1_reader');load('ai_recommendation_d1_reader');load('search_console_affiliate_reader');load('search_console_improvement_candidate_review');load('phase2a_candidate_read_cli');cli=load('market_signal_report_cli')

QUERY='Microsoft 365 Copilot エージェント'; OBSERVED='2026-08-25T00:00:00Z'
def results():
 return [{'schema_version':'market-signal-serp-result-v1','position':i,'title':f'Copilot エージェント導入 {i}','url':f'https://example{i}.test/copilot-agent','domain':f'example{i}.test','snippet':'導入とガバナンスの概要','published_at':None} for i in range(1,10)]
def analysis(**changes):
 value={'schema_version':'market-signal-analysis-v1','query':QUERY,'common_intents':['how'],'common_angles':['導入'],'uncovered_questions':[{'question':'棚卸しの進め方','classification':'hypothesis'}],'own_site_gap_assessment':{'classification':'cluster_sibling','rationale':'既存記事と隣接する。'},'candidate_drafts':[{'topic':'Copilot エージェントの棚卸し','reason':'metadata only','market_evidence':'SERP metadata','common_intent':'how','own_site_gap':'cluster_sibling','target_audience':'管理者','user_problem':'手順不明','monetization_relevance':'not_evaluated','duplicate_risk':'low','confidence':'low','requires_human_review':True}],'confidence':'low','requires_human_review':True,'content_generation_authorized':False,'publication_authorized':False,'execution_authorized':False};value.update(changes);return value
def response(value):
 return {'status':'completed','response_id':'must-not-output','usage':{'input_tokens':321,'output_tokens':654,'output_tokens_details':{'reasoning_tokens':500}},'output':[{'type':'reasoning'},{'type':'message','role':'assistant','content':[{'type':'output_text','text':json.dumps(value,ensure_ascii=False)}]}]}
class RawResponseTransport:
 def __init__(self,raw):self.raw,self.calls,self.last_diagnostic=raw,0,None
 def analyze(self,*_args,**_kwargs):
  self.calls+=1
  if isinstance(self.raw,Exception):raise self.raw
  self.last_diagnostic=openai.response_structure_diagnostic(self.raw)
  try:return json.loads(openai._output_text(self.raw))
  except openai.OpenAiMarketSignalAnalysisResponseError:raise
  except json.JSONDecodeError as error:raise openai.OpenAiMarketSignalAnalysisResponseError('malformed_json',self.last_diagnostic) from error

class E2E(unittest.TestCase):
 def run_cli(self,raw,*,planning=None):
  original=cli.OpenAiMarketSignalAnalysisTransport; holder=[]
  def factory(): item=RawResponseTransport(raw);holder.append(item);return item
  cli.OpenAiMarketSignalAnalysisTransport=factory
  with tempfile.TemporaryDirectory() as directory:
   cache=serp.LocalNormalizedSerpCache(pathlib.Path(directory),ttl_seconds=604800);cache.put(serp.serp_cache_key(query=QUERY,locale='ja',region='jp',result_count=10),results(),now=datetime(2026,8,25,tzinfo=timezone.utc))
   args=['--query',QUERY,'--observed-at',OBSERVED,'--live-serp','--live-analysis','--own-site-fixture','tests/fixtures/market-signal-own-site-fixture.json','--cache-dir',directory,'--cache-ttl-seconds','604800','--format','json']
   if planning is not None:
    path=pathlib.Path(directory)/'planning.json';path.write_text(json.dumps(planning));args+=['--planning-fixture',str(path)]
   output=io.StringIO()
   try:
    with redirect_stdout(output): rc=cli.main(args)
   finally: cli.OpenAiMarketSignalAnalysisTransport=original
  return rc,json.loads(output.getvalue()),holder
 def test_complete_cache_to_report_path_uses_one_mock_call(self):
  rc,value,holder=self.run_cli(response(analysis()))
  self.assertEqual(0,rc);self.assertEqual('market-signal-report-v1',value['schema_version']);self.assertEqual('serpapi_cache',value['source']['provider']);self.assertEqual(1,len(holder));self.assertEqual(1,holder[0].calls);self.assertEqual(1,len(value['candidate_drafts']));self.assertTrue(value['requires_human_review']);self.assertFalse(value['execution_authorized']);self.assertEqual({'input_tokens':321,'output_tokens':654,'output_tokens_details':{'reasoning_tokens':500}},value['market_analysis_usage']);self.assertNotIn('must-not-output',str(value))
 def test_failure_contracts_stop_at_cli_boundary(self):
  cases=[
   ({'status':'incomplete','incomplete_details':{'reason':'max_output_tokens'},'output':[]},'incomplete'),
   ({'status':'completed','output':[{'type':'message','role':'assistant','content':[{'type':'refusal','refusal':'hidden'}]}]},'refusal'),
   ({'status':'completed','output':[{'type':'message','role':'assistant','content':[]}]},'missing_output_text'),
   ({'status':'completed','output':[{'type':'message','role':'assistant','content':[{'type':'output_text','text':'{}'},{'type':'output_text','text':'{}'}]}]},'ambiguous_output_text'),
   ({'status':'completed','output':[{'type':'unknown_output','content':[]}]},'unknown_output_type'),
   ({'status':'completed','output':[{'type':'message','role':'assistant','content':[{'type':'unknown_content'}]}]},'unknown_content_type'),
   ({'status':'completed','output':[{'type':'message','role':'assistant','content':[{'type':'output_text','text':'not-json'}]}]},'malformed_json'),
   (type('HttpFailure',(Exception,),{'code':'http_error','diagnostic':{'http_status':400}})(),'http_error'),
  ]
  for raw,code in cases:
   with self.subTest(code=code):
    rc,value,_=self.run_cli(raw);self.assertEqual(1,rc);self.assertEqual(code,value['failure_classification']);self.assertNotIn('hidden',str(value));self.assertNotIn('response_id',str(value))
 def test_validator_and_planning_contract_fail_closed(self):
  missing_confidence=analysis();del missing_confidence['confidence']
  for value in (analysis(schema_version='market-signal-analysis-v0'),missing_confidence,analysis(candidate_drafts=[analysis()['candidate_drafts'][0]]*4),analysis(publication_authorized=True),analysis(candidate_drafts=[{**analysis()['candidate_drafts'][0],'duplicate_risk':'high'}])):
   with self.subTest(value=value):
    rc,out,_=self.run_cli(response(value));self.assertEqual(1,rc);self.assertEqual('schema_or_policy_failure',out['failure_classification'])
  rc,out,_=self.run_cli(response(analysis(candidate_drafts=[analysis()['candidate_drafts'][0]]*4)))
  self.assertEqual('candidate_count_invalid',out['validation_rule']);self.assertEqual('candidate_drafts',out['field_name']);self.assertEqual('candidate_maximum',out['policy_code'])
  self.assertNotIn('response_structure_diagnostic',out)
  rc,out,_=self.run_cli(response(analysis()),planning={'bad':True});self.assertEqual(1,rc);self.assertEqual('market_signal_input_invalid',out['error_class'])

if __name__=='__main__':unittest.main()
