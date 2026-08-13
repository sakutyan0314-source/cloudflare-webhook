import importlib.util,json,pathlib,sys,unittest
ROOT=pathlib.Path(__file__).parents[1]
def load(name):
 spec=importlib.util.spec_from_file_location(name,ROOT/'scripts'/f'{name}.py');mod=importlib.util.module_from_spec(spec);sys.modules[name]=mod;spec.loader.exec_module(mod);return mod
load('ai_recommendation_schema');load('ai_recommendation_rules');load('ai_recommendation_analysis');load('ai_recommendation_adapter');schema=load('openai_recommendation_eval_schema');ev=load('openai_recommendation_eval')
FIX=json.loads((ROOT/'tests/fixtures/openai-recommendation-eval-fixtures.json').read_text())
class FakeAdapter:
 def recommend(self,p):
  typ=p['rule_assessment']['candidate_types'][0];field='observation.search_clicks';value=p['observation']['search_clicks'];return {'recommendation_type':typ,'priority':'medium','confidence':'medium','evidence':[{'field':field,'value':value}],'reasons':'入力値を根拠に人間レビューで改善を検討する。','suggested_action':'人間レビューで改善候補を確認する。','expected_effect':'改善仮説を継続観測する。','risk_level':'low'}
class Factory:
 def create(self,c):return FakeAdapter()
class EvalTest(unittest.TestCase):
 def test_candidate_config_and_bounded_eval(self):
  plan={'schema_version':schema.EVAL_SCHEMA_VERSION,'models':[{'key':c.key,'model_id':c.model_id,'snapshot_id':c.snapshot_id,'input_usd_per_million':c.input_usd_per_million,'output_usd_per_million':c.output_usd_per_million} for c in schema.DEFAULT_CANDIDATES]};r=ev.run_eval(plan,FIX,Factory());self.assertEqual(18,r['call_budget']['actual_calls']);self.assertEqual(3,len(r['models']));self.assertGreaterEqual(r['models'][0]['metrics']['server_schema_pass_rate'],0);self.assertEqual('pending',r['models'][0]['metrics']['human_review_quality'])
 def test_refuses_unapproved_model_and_budget_overrun(self):
  with self.assertRaises(schema.EvalConfigurationError):schema.validate_eval_plan({'schema_version':schema.EVAL_SCHEMA_VERSION,'models':[{'key':'x','model_id':'bad','snapshot_id':None,'input_usd_per_million':1,'output_usd_per_million':1}]})
  with self.assertRaises(ValueError):ev.run_eval({'schema_version':schema.EVAL_SCHEMA_VERSION,'models':[]},FIX,Factory())
if __name__=='__main__':unittest.main()
