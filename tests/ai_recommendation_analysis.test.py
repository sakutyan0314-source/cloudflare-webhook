import importlib.util, json, pathlib, sys, unittest
ROOT=pathlib.Path(__file__).parents[1]
def load(name):
 spec=importlib.util.spec_from_file_location(name,ROOT/'scripts'/f'{name}.py');mod=importlib.util.module_from_spec(spec);sys.modules[name]=mod;spec.loader.exec_module(mod);return mod
schema=load('ai_recommendation_schema');load('ai_recommendation_rules');analysis=load('ai_recommendation_analysis')
fixture=json.loads((ROOT/'tests/fixtures/ai-recommendation-fixture.json').read_text())
class Adapter:
 def __init__(self): self.calls=0
 def recommend(self,payload): self.calls+=1; return {'recommendation_type':'improve_affiliate_cta','priority':'medium','confidence':'medium','evidence':[{'field':'observation.search_clicks','value':1}],'reasons':'数値を根拠に、人間レビューで導線文言を検討する。','suggested_action':'導線文言をレビューする。','expected_effect':'導線の理解を改善できる可能性を観測する。','risk_level':'low'}
class AnalysisTest(unittest.TestCase):
 def test_reconstructs_server_state_and_is_deterministic(self):
  adapter=Adapter(); first=analysis.analyze(fixture['article'],fixture['observation'],adapter,generated_at='2026-08-13T00:00:00Z'); second=analysis.analyze(fixture['article'],fixture['observation'],adapter,generated_at='2026-08-13T00:00:00Z'); self.assertEqual(first['recommendation_id'],second['recommendation_id']);self.assertEqual(2,adapter.calls);self.assertEqual(1,first['current_state']['search_clicks']);self.assertTrue(first['requires_human_review'])
 def test_insufficient_does_not_call_ai(self):
  observation=dict(fixture['observation']);observation['impressions']=1;adapter=Adapter();result=analysis.analyze(fixture['article'],observation,adapter,generated_at='2026-08-13T00:00:00Z');self.assertEqual(0,adapter.calls);self.assertEqual('insufficient_data',result['recommendation_type']);self.assertEqual('observe',result['priority'])
 def test_invalid_data_stops_before_ai(self):
  observation=dict(fixture['observation']);observation['search_clicks']=-1
  with self.assertRaises(Exception): analysis.analyze(fixture['article'],observation,Adapter())
 def test_high_value_affiliate_only_and_zero_values_are_safe(self):
  high=dict(fixture['observation']);high.update({'affiliate_click_count':2,'affiliate_click_rate':2.0,'search_affiliate_classification':'high_value'})
  result=analysis.analyze(fixture['article'],high,None,generated_at='2026-08-13T00:00:00Z');self.assertEqual('improve_internal_links',result['recommendation_type'])
  affiliate_only=dict(fixture['observation']);affiliate_only.update({'impressions':0,'search_clicks':0,'affiliate_click_count':1,'affiliate_click_rate':None,'position':None,'search_affiliate_classification':'insufficient_data'})
  result=analysis.analyze(fixture['article'],affiliate_only,None,generated_at='2026-08-13T00:00:00Z');self.assertEqual('insufficient_data',result['recommendation_type'])
if __name__=='__main__':unittest.main()
