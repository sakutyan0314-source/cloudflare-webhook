import importlib.util,pathlib,sys,unittest
ROOT=pathlib.Path(__file__).parents[1]
def load(n):
 s=importlib.util.spec_from_file_location(n,ROOT/'scripts'/(n+'.py'));m=importlib.util.module_from_spec(s);assert s and s.loader;sys.modules[n]=m;s.loader.exec_module(m);return m
spec=importlib.util.spec_from_file_location('seo_execution_production_verification_test',ROOT/'tests'/'seo_execution_production_verification.test.py');fx=importlib.util.module_from_spec(spec);assert spec and spec.loader;sys.modules['seo_execution_production_verification_test']=fx;spec.loader.exec_module(fx)
runner=load('seo_execution_first_dry_run');read=sys.modules['seo_execution_d1_read_adapter'];verify=sys.modules['seo_execution_production_verification']
def payload(rows):return {'success':True,'result':[{'success':True,'meta':{'changed_db':False,'changes':0,'rows_written':0},'results':rows}]}
class T:
 def __init__(self,row,tables):self.row,self.tables=row,tables
 def identity(self):return {'result':{'name':'name','uuid':'db'}}
 def fixed_select_batch(self,s):return payload([{'name':name} for name in self.tables] if 'sqlite_master' in s[0]['sql'] else [self.row])
class TestFirstDryRun(unittest.TestCase):
 def test_read_only_dry_run_and_stale_failure(self):
  approval,candidate,ci,row=fx.TestProductionVerification().source();original=runner.snapshot_from_article_row;original_statement=runner.build_conditional_update_statement;runner.snapshot_from_article_row=lambda _:candidate['before_snapshot'];runner.build_conditional_update_statement=lambda c,_:{'set_fields':sorted(c['expected_diff'])}
  try:
   adapter=read.SeoExecutionD1ReadAdapter(read.ProductionD1Target('a','db','name'),T(row,sorted(verify.MIGRATION_0010_TABLES)));result=runner.run_first_execution_dry_run(adapter,approval,candidate,ci,now='2026-08-21T02:10:00Z');self.assertFalse(result['changed_db']);self.assertEqual(0,result['rows_written'])
   runner.snapshot_from_article_row=lambda _:dict(candidate['before_snapshot'],updated_at='2026-08-22T00:00:00Z')
   with self.assertRaises(runner.SeoExecutionFirstDryRunError):runner.run_first_execution_dry_run(adapter,approval,candidate,ci,now='2026-08-21T02:10:00Z')
  finally:runner.snapshot_from_article_row=original;runner.build_conditional_update_statement=original_statement
 def test_migration_and_approval_mismatch_rejected(self):
  approval,candidate,ci,row=fx.TestProductionVerification().source();adapter=read.SeoExecutionD1ReadAdapter(read.ProductionD1Target('a','db','name'),T(row,[]))
  with self.assertRaises(runner.SeoExecutionFirstDryRunError):runner.run_first_execution_dry_run(adapter,approval,candidate,ci,now='2026-08-21T02:10:00Z')
  candidate=dict(candidate);approval=dict(approval,execution_candidate_fingerprint='0'*64);adapter=read.SeoExecutionD1ReadAdapter(read.ProductionD1Target('a','db','name'),T(row,sorted(verify.MIGRATION_0010_TABLES)))
  with self.assertRaises(runner.SeoExecutionFirstDryRunError):runner.run_first_execution_dry_run(adapter,approval,candidate,ci,now='2026-08-21T02:10:00Z')
if __name__=='__main__':unittest.main()
