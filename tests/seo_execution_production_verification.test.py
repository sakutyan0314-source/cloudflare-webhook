import importlib.util,pathlib,sys,unittest
ROOT=pathlib.Path(__file__).parents[1]
def load(name):
 spec=importlib.util.spec_from_file_location(name,ROOT/'scripts'/(name+'.py'));m=importlib.util.module_from_spec(spec);assert spec and spec.loader;sys.modules[name]=m;spec.loader.exec_module(m);return m
# Dependency chain uses only fixtures and injected transport.
spec=importlib.util.spec_from_file_location('seo_execution_production_adapter_test',ROOT/'tests'/'seo_execution_production_adapter.test.py');fixture=importlib.util.module_from_spec(spec);assert spec and spec.loader;sys.modules['seo_execution_production_adapter_test']=fixture;spec.loader.exec_module(fixture)
verify=load('seo_execution_production_verification');read=sys.modules['seo_execution_d1_read_adapter'];write=sys.modules['seo_execution_d1_write_adapter']
def payload(rows):return {'success':True,'result':[{'success':True,'meta':{'changed_db':False,'changes':0,'rows_written':0},'results':rows}]}
class Transport:
 def __init__(self,row):self.row=row
 def identity(self):return {'result':{'name':'name','uuid':'db'}}
 def fixed_select_batch(self,statements):
  sql=statements[0]['sql']
  return payload([] if 'sqlite_master' in sql else [self.row])
class TestProductionVerification(unittest.TestCase):
 def source(self):
  _,approval,candidate,candidate_input,snapshot=fixture.fixture.TestSeoExecutionPreflight().build();row={'id':1,'title':snapshot['title'],'description':snapshot['description'],'category':snapshot['category'],'content':'fixture content','body_markdown':'fixture body','published_at':snapshot['published_at'],'updated_at':snapshot['updated_at'],'seo_status':'ready'};return approval,candidate,candidate_input,row
 def test_target_migration_and_sql_drift_rejected(self):
  with self.assertRaises(verify.SeoExecutionProductionVerificationError):verify.validate_migration_0010_preflight(['seo_execution_attempts'])
  with self.assertRaises(verify.SeoExecutionProductionVerificationError):verify.verify_fixed_sql_whitelist([{'sql':'DELETE FROM curation_logs','params':[]}])
 def test_operator_preflight_zero_write_and_stale(self):
  approval,candidate,candidate_input,row=self.source();snapshot=candidate['before_snapshot'];original=verify.snapshot_from_article_row;verify.snapshot_from_article_row=lambda _:snapshot
  try:
   adapter=read.SeoExecutionD1ReadAdapter(read.ProductionD1Target('a','db','name'),Transport(row));report=verify.run_operator_preflight(adapter,approval,candidate,candidate_input,now='2026-08-21T02:10:00Z');self.assertFalse(report['changed_db']);self.assertEqual('pass',report['status'])
   stale=dict(snapshot,updated_at='2026-08-22T00:00:00Z');verify.snapshot_from_article_row=lambda _:stale
   with self.assertRaises(verify.SeoExecutionProductionVerificationError):verify.run_operator_preflight(read.SeoExecutionD1ReadAdapter(read.ProductionD1Target('a','db','name'),Transport(row)),approval,candidate,candidate_input,now='2026-08-21T02:10:00Z')
  finally: verify.snapshot_from_article_row=original
 def test_approval_mismatch_is_rejected(self):
  approval,candidate,candidate_input,row=self.source();approval=dict(approval,execution_candidate_fingerprint='0'*64)
  with self.assertRaises(verify.SeoExecutionProductionVerificationError):verify.run_operator_preflight(read.SeoExecutionD1ReadAdapter(read.ProductionD1Target('a','db','name'),Transport(row)),approval,candidate,candidate_input,now='2026-08-21T02:10:00Z')
if __name__=='__main__':unittest.main()
