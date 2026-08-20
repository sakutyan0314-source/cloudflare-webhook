import hashlib,importlib.util,pathlib,sys,tempfile,unittest
ROOT=pathlib.Path(__file__).parents[1]
def load(name):
 spec=importlib.util.spec_from_file_location(name,ROOT/'scripts'/(name+'.py'));m=importlib.util.module_from_spec(spec);assert spec and spec.loader;sys.modules[name]=m;spec.loader.exec_module(m);return m
fixture_spec=importlib.util.spec_from_file_location('seo_improvement_execution_preflight_test',ROOT/'tests'/'seo_improvement_execution_preflight.test.py');fixture=importlib.util.module_from_spec(fixture_spec);assert fixture_spec and fixture_spec.loader;sys.modules['seo_improvement_execution_preflight_test']=fixture;fixture_spec.loader.exec_module(fixture)
load('d1_read_only_session');load('seo_execution_d1_read_adapter');load('d1_conditional_update_audit');load('seo_improvement_execution_attempt');load('seo_execution_transaction_repository');load('seo_execution_d1_write_adapter');load('seo_execution_dry_run');load('seo_execution_production_verification');prep=load('seo_execution_migration_preparation');target=sys.modules['seo_execution_d1_read_adapter'].ProductionD1Target('a','db','name');path=ROOT/'migrations'/'0010_seo_execution_transactions.sql'
def args():return {'target':target,'migration_path':path,'expected_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'identity':{'result':{'name':'name','uuid':'db'}},'backup_evidence':{'bookmark':'bookmark','export_sha256':'a'*64,'export_size':1,'captured_at':'2026-08-21T00:00:00Z','database_id':'db','restore_plan_verified':True},'observed_new_tables':[],'foreign_key_rows':[],'existing_schema_drift':False}
class TestMigrationPreparation(unittest.TestCase):
 def test_checklist_is_dry_run_only(self):
  item=prep.build_migration_apply_checklist(**args());self.assertTrue(item['dry_run_only']);self.assertFalse(item['apply_authorized'])
 def test_target_and_hash_mismatch(self):
  values=args();values['identity']={'result':{'name':'name','uuid':'other'}}
  with self.assertRaises(prep.SeoExecutionMigrationPreparationError):prep.build_migration_apply_checklist(**values)
  values=args();values['expected_sha256']='0'*64
  with self.assertRaises(prep.SeoExecutionMigrationPreparationError):prep.build_migration_apply_checklist(**values)
 def test_schema_backup_and_foreign_key_fail_closed(self):
  for key,value in (('observed_new_tables',['seo_execution_attempts']),('foreign_key_rows',[{'table':'x'}]),('existing_schema_drift',True)):
   values=args();values[key]=value
   with self.assertRaises(prep.SeoExecutionMigrationPreparationError):prep.build_migration_apply_checklist(**values)
  values=args();values['backup_evidence']={}
  with self.assertRaises(prep.SeoExecutionMigrationPreparationError):prep.build_migration_apply_checklist(**values)
if __name__=='__main__':unittest.main()
