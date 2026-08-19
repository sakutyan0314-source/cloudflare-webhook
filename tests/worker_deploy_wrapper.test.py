import importlib.util,pathlib,sys,unittest
p=pathlib.Path(__file__).parents[1]/'scripts/worker_deploy_wrapper.py';s=importlib.util.spec_from_file_location('w',p);w=importlib.util.module_from_spec(s);sys.modules['w']=w;s.loader.exec_module(w)
ROOT=pathlib.Path(__file__).parents[1]
class T(unittest.TestCase):
 def execute(self,code=0,out='Uploaded cloudflare-webhook\nCurrent Version ID: version-id',err='',exc=None):
  calls=[]
  def f(args,cwd):
   calls.append(args)
   if exc: raise exc
   return code,out,err
  x=w.run_deploy(root=ROOT,git_head='h',account=w.ACCOUNT,runner=f,version_getter=lambda:w.WRANGLER_VERSION);return x,calls
 def test_success_and_one_attempt(self):x,c=self.execute();self.assertEqual('deploy_succeeded',x.classification);self.assertEqual(1,len(c));self.assertNotIn('Deployed',repr(x))
 def test_wrangler_4_120_markers_and_stages(self):
  self.assertEqual('deploy_succeeded',self.execute(0,'Uploaded cloudflare-webhook\nCurrent Version ID: x')[0].classification)
  self.assertEqual('deploy_succeeded',self.execute(0,'Uploaded cloudflare-webhook\nWorker Version ID: x')[0].classification)
  for out,expected in [('', 'deploy_failed_before_upload'),('Compiled Worker successfully','deploy_failed_before_upload'),('Uploaded cloudflare-webhook','deploy_failed_after_upload')]:self.assertEqual(expected,self.execute(1,out)[0].classification)
 def test_build_is_explicitly_unknown_and_upload_ignores_pre_upload_warning(self):
  x,_=self.execute(1,'Compiled Worker successfully\nUploading the Worker will override remote configuration')
  self.assertFalse(x.build_stage_observed); self.assertEqual('build_stage_unknown',x.build_stage_classification)
  self.assertFalse(x.upload_stage_observed); self.assertEqual('deploy_failed_before_upload',x.classification)
 def test_exit_zero_without_confirmed_version_is_unknown(self):
  x,_=self.execute(0,'Compiled Worker successfully');self.assertEqual('process_succeeded_unobserved',x.classification);self.assertEqual('build_stage_unknown',x.build_stage_classification)
 def test_confirmation_classifications_are_safe_and_distinct(self):
  self.assertEqual('deploy_confirmation_required',self.execute(1,'Would you like to continue?')[0].classification)
  self.assertEqual('deploy_confirmation_declined_or_aborted',self.execute(0,'Would you like to continue?\nAborting deploy...')[0].classification)
 def test_safe_branch_markers_are_boolean_only(self):
  x,_=self.execute(0,'--dry-run: exiting now.')
  self.assertTrue(x.dry_run_marker_observed); self.assertFalse(x.autoconfig_aborted_observed)
  x,_=self.execute(0,'? Are you sure that you want to proceed?\nUsing fallback value in non-interactive context: no')
  self.assertTrue(x.autoconfig_aborted_observed)
  x,_=self.execute(0,'OpenNext project detected, calling `opennextjs-cloudflare deploy`\nUsing redirected Wrangler configuration.')
  self.assertTrue(x.opennext_delegation_observed); self.assertTrue(x.config_redirect_observed)
 def test_safe_execution_metadata(self):
  x,c=self.execute(); self.assertEqual('fixed_node_local_wrangler_cli_deploy',x.argv_classification); self.assertEqual(('node','--no-warnings',str(ROOT/w.WRANGLER_CLI_RELATIVE_PATH),'deploy'),c[0]); self.assertEqual('repository_root',x.cwd_classification); self.assertEqual('repository_wrangler_toml',x.config_discovery_classification)
 def test_direct_cli_signal_is_never_a_success(self):
  x,_=self.execute(-15,''); self.assertTrue(x.signal_terminated); self.assertEqual('process_signal_terminated',x.classification)
 def test_timeout_interrupt_start(self):
  self.assertEqual('process_timeout',self.execute(exc=TimeoutError())[0].classification)
  self.assertEqual('process_timeout',self.execute(exc=__import__('subprocess').TimeoutExpired(('node',),180))[0].classification)
  self.assertEqual('process_interrupted',self.execute(exc=KeyboardInterrupt())[0].classification);self.assertEqual('wrangler_start_failed',self.execute(exc=OSError())[0].classification)
 def test_preflight(self):
  x=w.run_deploy(root=ROOT,git_head='h',account='wrong',runner=lambda *_:(_ for _ in ()).throw(Exception()),version_getter=lambda:w.WRANGLER_VERSION);self.assertEqual('preflight_failed',x.classification)
 def test_version_mismatch_stops_before_runner(self):
  x=w.run_deploy(root=ROOT,git_head='h',account=w.ACCOUNT,runner=lambda *_:self.fail(),version_getter=lambda:'0.0.0');self.assertEqual('wrangler_version_mismatch',x.classification)
 def test_secret_output_not_retained(self):x,_=self.execute(1,'Authorization: Bearer secret','token=secret');self.assertNotIn('secret',repr(x));self.assertIsInstance(x.exit_code,int)
if __name__=='__main__':unittest.main()
