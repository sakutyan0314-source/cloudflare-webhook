import importlib.util,pathlib,sys,unittest
ROOT=pathlib.Path(__file__).parents[1]
def load(name):
 spec=importlib.util.spec_from_file_location(name,ROOT/'scripts'/(name+'.py'));m=importlib.util.module_from_spec(spec);assert spec and spec.loader;sys.modules[name]=m;spec.loader.exec_module(m);return m
# Load the existing fixture chain without external services.
spec=importlib.util.spec_from_file_location('seo_improvement_execution_preflight_test',ROOT/'tests'/'seo_improvement_execution_preflight.test.py');fixture=importlib.util.module_from_spec(spec);assert spec and spec.loader;sys.modules['seo_improvement_execution_preflight_test']=fixture;spec.loader.exec_module(fixture)
load('seo_improvement_execution_attempt');load('d1_conditional_update_audit');load('d1_read_only_session');load('seo_execution_transaction_repository');read=load('seo_execution_d1_read_adapter');write=load('seo_execution_d1_write_adapter');dry=load('seo_execution_dry_run');operator=load('seo_execution_operator_runner')
class T:
 def __init__(self,identity,query):self.i,self.q=identity,query
 def identity(self):return self.i
 def fixed_select_batch(self,_):return self.q
def payload(rows):return {'success':True,'result':[{'success':True,'meta':{'changed_db':False,'changes':0,'rows_written':0},'results':rows}]}
class TestProductionAdapter(unittest.TestCase):
 def test_identity_mismatch_and_read_only_boundary(self):
  target=read.ProductionD1Target('a','db','name');bad=read.SeoExecutionD1ReadAdapter(target,T({'result':{'name':'name','uuid':'other'}},payload([])))
  with self.assertRaises(read.SeoExecutionReadAdapterError):bad.verify_identity()
  good=read.SeoExecutionD1ReadAdapter(target,T({'result':{'name':'name','uuid':'db'}},payload([])));self.assertEqual([],good.read_migration_preflight())
 def test_sql_whitelist_violation_and_adapter_no_execute(self):
  with self.assertRaises(write.SeoExecutionWriteAdapterError):write.validate_fixed_write({'sql':'DELETE FROM curation_logs','params':[]})
  with self.assertRaises(write.ProductionD1WriteDisabled):write.execution_disabled()
 def test_read_only_runner_dry_run_approval_and_stale(self):
  _,approval,candidate,candidate_input,snapshot=fixture.TestSeoExecutionPreflight().build();result=dry.run_dry_run(approval,candidate,candidate_input,snapshot,now='2026-08-21T02:10:00Z');self.assertFalse(result['changed_db']);self.assertEqual(0,result['rows_written'])
  stale=dict(snapshot,updated_at='2026-08-22T00:00:00Z')
  with self.assertRaises(dry.SeoExecutionDryRunError):dry.run_dry_run(approval,candidate,candidate_input,stale,now='2026-08-21T02:10:00Z')
 def test_operator_is_dry_run_only(self):
  with self.assertRaises(operator.SeoExecutionOperatorError):operator.run_production_execution()
if __name__=='__main__':unittest.main()
