import importlib.util, json, pathlib, sys, tempfile, unittest
ROOT=pathlib.Path(__file__).parents[1]
def load(name):
 spec=importlib.util.spec_from_file_location(name,ROOT/'scripts'/f'{name}.py');mod=importlib.util.module_from_spec(spec);sys.modules[name]=mod;spec.loader.exec_module(mod);return mod
audit=load('openai_recommendation_run_audit')
class RunAuditTest(unittest.TestCase):
 def setUp(self): self.temp=tempfile.TemporaryDirectory();self.run='v2a-eval-r2-luna';self.plan=audit.build_request_plan(self.run,'gpt-5.6-luna',['high_value','traffic_only']);self.ledger=audit.RunAuditLedger.create(self.temp.name,ROOT,self.run,self.plan)
 def tearDown(self): self.temp.cleanup()
 def test_manifest_is_external_private_and_tracks_final_result(self):
  self.assertEqual(0o600,self.ledger.path.stat().st_mode & 0o777);rid=self.plan[0]['client_request_id'];self.ledger.begin_request(rid);self.ledger.finalize(rid,'result_known',http_status=200,classification='recommendation_generated',input_tokens=10,output_tokens=5,server_request_id='req_safe');self.assertEqual('result_known',self.ledger.states()[rid]);text=self.ledger.path.read_text();self.assertNotIn('Authorization',text);self.assertNotIn('evidence',text)
 def test_duplicate_and_crash_recovery_never_resend(self):
  rid=self.plan[0]['client_request_id'];self.ledger.begin_request(rid);self.assertEqual('outcome_unknown',self.ledger.states()[rid]);
  with self.assertRaises(audit.AuditError): self.ledger.begin_request(rid)
 def test_creation_or_transition_failure_stops_before_send(self):
  with self.assertRaises(audit.AuditError): audit.RunAuditLedger.create(ROOT,ROOT,self.run,self.plan)
  self.ledger.path.unlink()
  with self.assertRaises(audit.AuditError): self.ledger.begin_request(self.plan[0]['client_request_id'])
 def test_known_http_and_timeout_outcomes_are_distinct(self):
  first,second=(item['client_request_id'] for item in self.plan);self.ledger.begin_request(first);self.ledger.finalize(first,'result_known',http_status=400,classification='http_error');self.ledger.begin_request(second);self.ledger.finalize(second,'outcome_unknown',http_status=None,classification='timeout');self.assertEqual({'result_known','outcome_unknown'},set(self.ledger.states().values()))
if __name__=='__main__':unittest.main()
