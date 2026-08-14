import importlib.util, json, pathlib, sys, tempfile, unittest
ROOT=pathlib.Path(__file__).parents[1]
def load(name):
 spec=importlib.util.spec_from_file_location(name,ROOT/'scripts'/f'{name}.py');mod=importlib.util.module_from_spec(spec);sys.modules[name]=mod;spec.loader.exec_module(mod);return mod
load('search_console_collector');schema=load('ai_recommendation_schema');load('ai_recommendation_rules');analysis=load('ai_recommendation_analysis');load('ai_recommendation_adapter');provider=load('openai_recommendation_adapter');audit=load('openai_recommendation_run_audit');runner=load('openai_recommendation_eval_runner')
fixture=json.loads((ROOT/'tests/fixtures/openai-recommendation-eval-fixtures.json').read_text())[0]
def response(): return {'recommendation_type':'improve_internal_links','priority':'medium','confidence':'medium','evidence':[{'field':'observation.impressions','value':100}],'reasons':'入力値を根拠に人間レビューで確認する。','suggested_action':'内部リンクを人間レビューで確認する。','expected_effect':'関連導線の理解を改善できる可能性を観測する。','risk_level':'low'}
class Transport:
 def __init__(self,result=None,error=None):self.result=result;self.error=error;self.last_response_diagnostic={'usage':{'input_tokens':10,'output_tokens':5}};self.last_request_metadata={'server_request_id':'req_safe'}
 def propose(self,*args,**kwargs):
  if self.error: raise self.error
  return self.result
class RunnerTest(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.plan=audit.build_request_plan('v2a-eval-r3-luna','gpt-5.6-luna',['high_value','traffic_only']);self.ledger=audit.RunAuditLedger.create(self.temp.name,ROOT,'v2a-eval-r3-luna',self.plan);self.payload=analysis.build_input(fixture['article'],fixture['observation'])
 def tearDown(self):self.temp.cleanup()
 def test_success_records_before_and_after_one_send(self):
  calls=[];subject=runner.SafeEvalExecutor(self.ledger,lambda model,request:(calls.append((model,request)) or Transport(response())))
  result=subject.execute_one(self.plan[0],self.payload,generated_at='2026-08-14T00:00:00Z');self.assertTrue(result['recommendation_generated']);self.assertEqual(1,len(calls));self.assertEqual('result_known',self.ledger.states()[self.plan[0]['client_request_id']])
 def test_timeout_is_unknown_and_duplicate_is_not_resent(self):
  calls=[];subject=runner.SafeEvalExecutor(self.ledger,lambda model,request:(calls.append(request) or Transport(error=TimeoutError())))
  with self.assertRaises(runner.EvalExecutionError):subject.execute_one(self.plan[0],self.payload,generated_at='2026-08-14T00:00:00Z')
  with self.assertRaises(Exception):subject.execute_one(self.plan[0],self.payload,generated_at='2026-08-14T00:00:00Z')
  self.assertEqual(1,len(calls));self.assertEqual('outcome_unknown',self.ledger.states()[self.plan[0]['client_request_id']])
 def test_http_failure_is_known_and_audit_failure_prevents_send(self):
  subject=runner.SafeEvalExecutor(self.ledger,lambda model,request:Transport(error=provider.OpenAiRecommendationHttpError(400,'invalid_request_error',None,None,'safe')))
  with self.assertRaises(runner.EvalExecutionError):subject.execute_one(self.plan[0],self.payload,generated_at='2026-08-14T00:00:00Z')
  self.assertEqual('result_known',self.ledger.states()[self.plan[0]['client_request_id']])
  self.ledger.path.unlink();calls=[];blocked=runner.SafeEvalExecutor(self.ledger,lambda model,request:(calls.append(request) or Transport(response())))
  with self.assertRaises(Exception):blocked.execute_one(self.plan[1],self.payload,generated_at='2026-08-14T00:00:00Z')
  self.assertEqual([],calls)
 def test_evidence_and_prohibited_outputs_are_known_safe_failures(self):
  bad_evidence=response();bad_evidence['evidence']=[{'field':'observation.impressions','value':999}]
  forbidden=response();forbidden['reasons']='CVRを改善する。'
  results=iter([Transport(bad_evidence),Transport(forbidden)]);subject=runner.SafeEvalExecutor(self.ledger,lambda model,request:next(results))
  for item in self.plan:
   with self.assertRaises(runner.EvalExecutionError):subject.execute_one(item,self.payload,generated_at='2026-08-14T00:00:00Z')
  self.assertEqual({'result_known'},set(self.ledger.states().values()));text=self.ledger.path.read_text();self.assertIn('evidence_invalid',text);self.assertIn('prohibited_cvr_term',text);self.assertNotIn('999',text);self.assertNotIn('CVR',text)
if __name__=='__main__':unittest.main()
