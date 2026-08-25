import importlib.util, json, pathlib, sys, tempfile, unittest
from contextlib import redirect_stdout
import io
from datetime import datetime, timezone
ROOT=pathlib.Path(__file__).parents[1]
def load(name):
 spec=importlib.util.spec_from_file_location(name,ROOT/'scripts'/f'{name}.py'); module=importlib.util.module_from_spec(spec); assert spec and spec.loader; sys.modules[name]=module; spec.loader.exec_module(module); return module
load('search_console_improvement_candidates'); load('topic_candidate'); serp=load('market_signal_serp_adapter'); report=load('market_signal_report'); load('market_signal_analysis'); load('market_signal_analysis_adapter'); load('openai_market_signal_analysis_adapter')
load('search_console_collector'); load('search_console_d1_reader'); load('ai_recommendation_d1_reader'); load('search_console_affiliate_reader'); load('search_console_improvement_candidate_review'); load('phase2a_candidate_read_cli'); cli=load('market_signal_report_cli')
FIX=json.loads((ROOT/'tests/fixtures/market-signal-serp-fixture.json').read_text())
class TestMarketSignal(unittest.TestCase):
 def own(self):
  return report.build_own_site_signal(query='Microsoft 365 Copilot エージェント',articles=[{'article_id':40,'title':'Microsoft 365 Copilot エージェント導入ガバナンス','description':'権限と棚卸し','category':'security-governance'}],page_daily=[],affiliate_events=[{'article_id':40,'placement':'article'},{'article_id':40,'placement':'discord'}])
 def build(self, opportunities=None):
  return report.build_market_signal_report(query='Microsoft 365 Copilot エージェント',observed_at='2026-08-25T00:00:00Z',source={'provider':'fixture_only','engine':'google','locale':'ja-JP','region':'JP','requested_result_count':10},serp_results=serp.normalize_serp_response(FIX),analysis={'common_intents':['how'],'common_angles':['導入','ガバナンス'],'uncovered_questions':['中小企業の棚卸し']},own_site_signal=self.own(),opportunities=opportunities or [{'topic':'Copilot導入前の棚卸し','reason':'gap','market_evidence':'SERP','own_site_gap':'checklist missing','expected_search_intent':'how','target_audience':'管理者','monetization_relevance':'not_evaluated','duplicate_risk':'low'}])
 def test_serp_normalization_drops_malformed_and_duplicate_url(self):
  rows=serp.normalize_serp_response(FIX); self.assertEqual(2,len(rows)); self.assertEqual('security.example.jp',rows[1]['domain']); self.assertEqual('https://security.example.jp/agent-permissions',rows[1]['url'])
 def test_own_site_search_is_insufficient_and_discord_is_not_usable(self):
  own=self.own(); self.assertEqual('insufficient_data',own['search_console_signal']['status']); self.assertEqual(1,own['affiliate_signal']['article_click_count']); self.assertEqual(1,own['affiliate_signal']['discord_click_count']); self.assertEqual(1,own['affiliate_signal']['usable_click_count']); self.assertIn('unknown',own['affiliate_signal']['reliability_status'])
 def test_report_schema_and_human_review_boundary(self):
  item=self.build(); self.assertEqual(report.REPORT_SCHEMA_VERSION,item['schema_version']); self.assertTrue(item['requires_human_review']); self.assertFalse(item['content_generation_authorized']); self.assertIn('MARKET SIGNAL REPORT',report.render_human_report(item)); self.assertEqual(64,len(item['report_fingerprint'].split('_',2)[2]))
 def test_candidate_drafts_are_bounded_and_non_executable(self):
  prototype={'topic':'T','reason':'r','market_evidence':'m','own_site_gap':'g','expected_search_intent':'how','target_audience':'a','monetization_relevance':'not_evaluated','duplicate_risk':'low'}
  items=report.build_candidate_drafts([dict(prototype,topic=f'T{i}') for i in range(4)]); self.assertEqual(3,len(items)); self.assertTrue(all(x['requires_human_review'] and not x['execution_authorized'] for x in items))
 def test_analysis_input_is_content_free_metadata(self):
  value=report.build_market_analysis_input(query='q',observed_at='2026-08-25T00:00:00Z',results=serp.normalize_serp_response(FIX)); self.assertEqual('market-signal-analysis-input-v1',value['schema_version']); self.assertNotIn('raw_response',str(value))
 def test_fixture_cli_emits_json_without_external_serp_call(self):
  output=io.StringIO()
  with redirect_stdout(output):
   self.assertEqual(0,cli.main(['--query','Microsoft 365 Copilot エージェント','--observed-at','2026-08-25T00:00:00Z','--serp-fixture','tests/fixtures/market-signal-serp-fixture.json','--own-site-fixture','tests/fixtures/market-signal-own-site-fixture.json','--format','json']))
  self.assertIn('market-signal-report-v1',output.getvalue())
 def test_fixture_analysis_integrates_validated_drafts_without_provider_call(self):
  response={'schema_version':'market-signal-analysis-v1','query':'Microsoft 365 Copilot エージェント','common_intents':['how'],'common_angles':['導入'],'uncovered_questions':[{'question':'棚卸しの手順','classification':'hypothesis'}],'own_site_gap_assessment':{'classification':'possible_gap','rationale':'metadata only'},'candidate_drafts':[{'topic':'Copilot棚卸し','reason':'metadata','market_evidence':'SERP metadata','common_intent':'how','own_site_gap':'possible_gap','target_audience':'管理者','user_problem':'手順不明','monetization_relevance':'not_evaluated','duplicate_risk':'low','confidence':'low','requires_human_review':True}],'confidence':'low','requires_human_review':True,'content_generation_authorized':False,'publication_authorized':False,'execution_authorized':False}
  with tempfile.TemporaryDirectory() as directory:
   path=pathlib.Path(directory)/'analysis.json'; path.write_text(json.dumps(response))
   output=io.StringIO()
   with redirect_stdout(output): self.assertEqual(0,cli.main(['--query','Microsoft 365 Copilot エージェント','--observed-at','2026-08-25T00:00:00Z','--serp-fixture','tests/fixtures/market-signal-serp-fixture.json','--own-site-fixture','tests/fixtures/market-signal-own-site-fixture.json','--analysis-response-fixture',str(path),'--format','json']))
   parsed=json.loads(output.getvalue()); self.assertEqual('how',parsed['candidate_drafts'][0]['common_intent']); self.assertTrue(parsed['candidate_drafts'][0]['requires_human_review'])
 def test_own_site_transport_is_fixed_select_and_rejects_writes(self):
  class Done:
   returncode=0
   stdout=json.dumps([{'results':[],'meta':{'changed_db':False,'rows_written':0}}])
  seen=[]
  transport=cli.FixedSelectTransport(runner=lambda command,**_: (seen.append(command) or Done()))
  articles,pages,affiliate=cli.read_own_site('https://example.test/','2026-08-01','2026-08-14',transport)
  self.assertEqual(([],[],[]),(articles,pages,affiliate)); self.assertEqual(3,len(seen)); self.assertTrue(all('SELECT' in command[command.index('--command')+1].upper() for command in seen))
  class Changed:
   returncode=0
   stdout=json.dumps([{'results':[],'meta':{'changed_db':True,'rows_written':1}}])
  with self.assertRaises(cli.MarketSignalReadError): cli.read_own_site('https://example.test/','2026-08-01','2026-08-14',cli.FixedSelectTransport(runner=lambda *_,**__:Changed()))
 def test_live_adapter_missing_key_fails_before_transport_and_does_not_disclose(self):
  calls=[]; adapter=serp.SerpApiGoogleSearchAdapter(api_key='',transport=lambda *args: calls.append(args))
  with self.assertRaises(serp.SerpApiSafetyError) as error: adapter.search(query='Microsoft 365 Copilot')
  self.assertEqual('api_key_missing',str(error.exception)); self.assertEqual([],calls); self.assertNotIn('SERP',str(error.exception))
 def test_live_adapter_builds_one_japanese_google_request_and_normalizes(self):
  calls=[]
  def transport(url,timeout): calls.append((url,timeout)); return 200,json.dumps(FIX).encode()
  adapter=serp.SerpApiGoogleSearchAdapter(api_key='test-key-not-disclosed',transport=transport)
  rows,mode=adapter.search(query='Microsoft 365 Copilot')
  self.assertEqual('live_request',mode); self.assertEqual(1,len(calls)); self.assertIn('engine=google',calls[0][0]); self.assertIn('hl=ja',calls[0][0]); self.assertIn('gl=jp',calls[0][0]); self.assertEqual(2,len(rows))
  with self.assertRaises(serp.SerpApiSafetyError): adapter.search(query='second query')
 def test_live_adapter_http_provider_and_malformed_fail_closed(self):
  for response,expected in (((500,b''),'http_failure'),((200,b'{"error":"bad"}'),'provider_error'),((200,b'not-json'),'response_malformed'),((200,b'{"organic_results":[{}]}'),'response_malformed')):
   with self.subTest(expected=expected):
    adapter=serp.SerpApiGoogleSearchAdapter(api_key='x',transport=lambda *_:response)
    with self.assertRaises(serp.SerpApiSafetyError) as error: adapter.search(query='q')
    self.assertEqual(expected,str(error.exception))
 def test_cache_hit_uses_zero_request_and_cache_miss_uses_one(self):
  with tempfile.TemporaryDirectory() as directory:
   cache=serp.LocalNormalizedSerpCache(pathlib.Path(directory),ttl_seconds=604800); now=datetime(2026,8,25,tzinfo=timezone.utc); calls=[]
   adapter=serp.SerpApiGoogleSearchAdapter(api_key='x',cache=cache,transport=lambda *args:(calls.append(args) or (200,json.dumps(FIX).encode())))
   self.assertEqual('live_request',adapter.search(query='q',now=now)[1]); self.assertEqual(1,len(calls))
   second=serp.SerpApiGoogleSearchAdapter(api_key='',cache=cache,transport=lambda *_:self.fail('cache hit must not transport'))
   self.assertEqual('cache_hit',second.search(query='q',now=now)[1]); self.assertEqual(0,second.request_count)
if __name__=='__main__': unittest.main()
