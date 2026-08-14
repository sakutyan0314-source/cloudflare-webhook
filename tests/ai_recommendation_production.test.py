import importlib.util, pathlib, sys, tempfile, unittest
ROOT=pathlib.Path(__file__).parents[1]
def load(name):
 spec=importlib.util.spec_from_file_location(name,ROOT/'scripts'/f'{name}.py');mod=importlib.util.module_from_spec(spec);sys.modules[name]=mod;spec.loader.exec_module(mod);return mod
load('search_console_collector');load('search_console_d1_reader');load('search_console_affiliate_analysis');load('search_console_page_daily_analysis');load('ai_recommendation_schema');load('ai_recommendation_rules');load('ai_recommendation_analysis');load('ai_recommendation_review');load('ai_recommendation_adapter');load('openai_recommendation_adapter');audit=load('openai_recommendation_run_audit');load('openai_recommendation_eval_runner');production=load('ai_recommendation_production')
PAGES=[{'metric_date':f'2026-08-{day:02d}','page_url':'https://x/article/17','url_kind':'article','article_id':17,'clicks':0,'impressions':12,'position':6} for day in range(2,9)]
ARTICLES=[{'article_id':17,'title':'題名','description':'説明','category':'ai-automation','published_at':'2026-01-01','updated_at':'2026-01-01'}]
class Transport:
 last_response_diagnostic={'usage':{'input_tokens':1,'output_tokens':1}};last_request_metadata={}
 def propose(self,*args,**kwargs):return {'recommendation_type':'improve_title','priority':'medium','confidence':'high','evidence':[{'field':'observation.impressions','value':84}],'reasons':'入力値を根拠に人間レビューする。','suggested_action':'題名を人間レビューする。','expected_effect':'理解を改善できる可能性を観測する。','risk_level':'low'}
class ProductionTest(unittest.TestCase):
 def test_terra_only_snapshot_and_cost_guards(self):
  self.assertEqual('gpt-5.6-terra',production.production_provider_config()['model_id'])
  for value in ('gpt-5.6','gpt-5.6-luna','gpt-5.6-sol'):
   with self.assertRaises(Exception):production.production_provider_config(model_id=value)
  with self.assertRaises(Exception):production.production_provider_config(snapshot_id='invented')
  self.assertLessEqual(production.estimate_batch_cost(10),.12)
 def test_full_in_memory_path_produces_review_json_without_d1_write(self):
  inputs=production.build_production_inputs(PAGES,[],ARTICLES,'2026-08-02','2026-08-08');self.assertEqual(1,len(inputs));plan=production.prepare_terra_request_plan('v2a-prod-local',inputs)
  with tempfile.TemporaryDirectory() as temp:
   ledger=audit.RunAuditLedger.create(temp,ROOT,'v2a-prod-local',plan)
   output=production.run_review_only_batch(inputs,plan,ledger,lambda *_:Transport(),generated_at='2026-08-14T00:00:00Z')
  self.assertEqual(1,len(output));self.assertEqual('pending',output[0]['review_status']);self.assertTrue(output[0]['requires_human_review'])
 def test_too_many_articles_and_missing_metadata_stop_before_ai(self):
  rows=[dict(ARTICLES[0],article_id=index,title=f'題{index}') for index in range(1,12)]
  pages=[dict(PAGES[-1],article_id=index,page_url=f'https://x/article/{index}') for index in range(1,12)]
  with self.assertRaises(Exception):production.build_production_inputs(pages,[],rows,'2026-08-02','2026-08-08')
  with self.assertRaises(Exception):production.build_production_inputs(PAGES,[],[],'2026-08-02','2026-08-08')
 def test_reader_is_the_only_source_boundary(self):
  class Reader:
   calls=0
   def fetch_source(self,*args):self.calls+=1;return PAGES,[],ARTICLES
  source=Reader();inputs=production.read_and_build_production_inputs(source,'https://example.test/','web','2026-08-02','2026-08-08');self.assertEqual(1,source.calls);self.assertEqual(1,len(inputs))
  with self.assertRaises(Exception):production.read_and_build_production_inputs(object(),'https://example.test/','web','2026-08-02','2026-08-08')
if __name__=='__main__':unittest.main()
