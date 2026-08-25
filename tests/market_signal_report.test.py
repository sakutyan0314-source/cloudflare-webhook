import importlib.util, json, pathlib, sys, unittest
from contextlib import redirect_stdout
import io
ROOT=pathlib.Path(__file__).parents[1]
def load(name):
 spec=importlib.util.spec_from_file_location(name,ROOT/'scripts'/f'{name}.py'); module=importlib.util.module_from_spec(spec); assert spec and spec.loader; sys.modules[name]=module; spec.loader.exec_module(module); return module
load('search_console_improvement_candidates'); load('topic_candidate'); serp=load('market_signal_serp_adapter'); report=load('market_signal_report')
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
if __name__=='__main__': unittest.main()
