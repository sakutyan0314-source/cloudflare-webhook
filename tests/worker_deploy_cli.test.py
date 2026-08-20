import importlib.util, io, pathlib, subprocess, sys, unittest
from unittest.mock import patch

ROOT=pathlib.Path(__file__).parents[1]
def load(name, filename):
 spec=importlib.util.spec_from_file_location(name,ROOT/filename); module=importlib.util.module_from_spec(spec); sys.modules[name]=module; spec.loader.exec_module(module); return module
diag=load('worker_deployment_diagnostics','scripts/worker_deployment_diagnostics.py')
w=load('worker_deploy_wrapper','scripts/worker_deploy_wrapper.py')
cli=load('worker_deploy_cli','scripts/worker_deploy_cli.py')
HEAD='9079be7296f29028cdddade1c78db8f7c347933b'; PRE='old-version'

class WorkerDeployCliTest(unittest.TestCase):
 def kwargs(self, **overrides):
  calls=[]
  def deploy(**kwargs):
   calls.append(kwargs); return w.DeployAudit('v',HEAD,w.SCRIPT,w.ACCOUNT,True,False,True,True,0,False,False,'deploy_succeeded')
  latest=diag.LatestDeployment(1,(diag.DeploymentTraffic('new-version',100.0),),100.0)
  base=dict(root=ROOT,cwd=ROOT,home=ROOT,token_provider=lambda:'safe-token',git_head=lambda _:HEAD,tracked_clean=lambda _:True,filesystem_ready=lambda _:True,version_getter=lambda _:w.WRANGLER_VERSION,deploy_function=deploy,post_deploy_fetcher=lambda _:latest,environment={})
  base.update(overrides); return base,calls
 def command(self,*extra): return ['deploy-once','--expected-head',HEAD,'--expected-account',w.ACCOUNT,'--expected-wrangler-version',w.WRANGLER_VERSION,'--pre-deploy-version',PRE,*extra]
 def test_requires_explicit_subcommand(self):
  k,c=self.kwargs(); self.assertEqual('deploy_command_required',cli.run_cli([],**k)['classification']); self.assertEqual([],c)
 def test_preflights_stop_before_deploy(self):
  cases=[({'git_head':lambda _: 'other'},'git_head_mismatch'),({'tracked_clean':lambda _:False},'tracked_worktree_dirty'),({'cwd':ROOT.parent},'repository_root_mismatch'),({'filesystem_ready':lambda _:False},'filesystem_preflight_failed'),({'version_getter':lambda _:None},'wrangler_version_mismatch'),({'token_provider':lambda:''},'worker_token_missing'),({'environment':{'CLOUDFLARE_ENV':'preview'}},'unapproved_wrangler_environment'),({'environment':{'CLOUDFLARE_ACCOUNT_ID':'wrong'}},'account_environment_mismatch')]
  for override,expected in cases:
   with self.subTest(expected=expected):
    k,c=self.kwargs(**override); self.assertEqual(expected,cli.run_cli(self.command(),**k)['classification']); self.assertEqual([],c)
 def test_missing_pre_version_stops_before_deploy(self):
  k,c=self.kwargs(); self.assertEqual('pre_deploy_version_required',cli.run_cli(self.command()[:-2],**k)['classification']); self.assertEqual([],c)
 def test_direct_cli_normal_exit_and_postcheck_new_version_succeeds_once(self):
  k,c=self.kwargs(); result=cli.run_cli(self.command(),**k)
  self.assertEqual('deploy_succeeded_verified',result['classification']); self.assertEqual('succeeded',result['deployment_outcome']); self.assertEqual(1,len(c)); self.assertTrue(result['post_deploy_check']['version_changed']); self.assertNotIn('safe-token',repr(result))
 def test_direct_signal_exit_is_unknown_and_skips_postcheck(self):
  post=[]
  def deploy(**kwargs): return w.DeployAudit('v',HEAD,w.SCRIPT,w.ACCOUNT,True,False,False,False,-15,False,False,'process_signal_terminated',signal_terminated=True)
  k,c=self.kwargs(deploy_function=deploy,post_deploy_fetcher=lambda _:post.append(1)); self.assertEqual('deploy_outcome_unknown',cli.run_cli(self.command(),**k)['classification']); self.assertEqual(0,len(c)); self.assertEqual([],post)
 def test_exit_zero_without_version_marker_is_unknown_and_skips_postcheck(self):
  post=[]
  def deploy(**kwargs): return w.DeployAudit('v',HEAD,w.SCRIPT,w.ACCOUNT,True,False,False,False,0,False,False,'process_succeeded_unobserved')
  k,c=self.kwargs(deploy_function=deploy,post_deploy_fetcher=lambda _:post.append(1)); self.assertEqual('deploy_outcome_unknown',cli.run_cli(self.command(),**k)['classification']); self.assertEqual(0,len(c)); self.assertEqual([],post)
 def test_postcheck_version_unchanged_is_unknown(self):
  latest=diag.LatestDeployment(1,(diag.DeploymentTraffic(PRE,100.0),),100.0)
  k,c=self.kwargs(post_deploy_fetcher=lambda _:latest); result=cli.run_cli(self.command(),**k)
  self.assertEqual('deploy_outcome_unknown',result['classification']); self.assertEqual('post_deploy_state_mismatch',result['post_deploy_check']['classification']); self.assertEqual(1,len(c))
 def test_postcheck_unavailable_is_unknown(self):
  def fail(_): raise diag.DeploymentShapeError('x')
  k,c=self.kwargs(post_deploy_fetcher=fail); result=cli.run_cli(self.command(),**k)
  self.assertEqual('deploy_outcome_unknown',result['classification']); self.assertEqual('post_deploy_check_unavailable',result['post_deploy_check']['classification']); self.assertEqual(1,len(c))
 def test_failure_timeout_and_interrupt_never_repeat(self):
  for classification,timed_out,interrupted,expected in [('deploy_failed_before_upload',False,False,'deploy_failed_before_upload'),('process_timeout',True,False,'deploy_outcome_unknown'),('process_interrupted',False,True,'deploy_outcome_unknown')]:
   calls=[]
   def deploy(**kwargs): calls.append(kwargs); return w.DeployAudit('v',HEAD,w.SCRIPT,w.ACCOUNT,True,False,False,False,None,timed_out,interrupted,classification)
   k,_=self.kwargs(deploy_function=deploy); self.assertEqual(expected,cli.run_cli(self.command(),**k)['classification']); self.assertEqual(1,len(calls))
 def test_before_upload_failure_has_known_failed_outcome(self):
  def deploy(**kwargs): return w.DeployAudit('v',HEAD,w.SCRIPT,w.ACCOUNT,True,False,False,False,1,False,False,'deploy_failed_before_upload',process_result='failed_before_upload')
  k,_=self.kwargs(deploy_function=deploy); result=cli.run_cli(self.command(),**k)
  self.assertEqual('deploy_failed_before_upload',result['classification']); self.assertEqual('failed',result['deployment_outcome']); self.assertEqual('failed_before_upload',result['audit']['process_result'])
 def test_unknown_is_a_nonzero_outer_cli_exit(self):
  with patch.object(cli,'run_cli',return_value={'classification':'deploy_outcome_unknown'}),patch.object(cli.sys,'stdout',io.StringIO()): self.assertEqual(2,cli.main())
  with patch.object(cli,'run_cli',return_value={'classification':'deploy_succeeded_verified'}),patch.object(cli.sys,'stdout',io.StringIO()): self.assertEqual(0,cli.main())
  with patch.object(cli,'run_cli',return_value={'classification':'deploy_failed_before_upload','deployment_outcome':'failed'}),patch.object(cli.sys,'stdout',io.StringIO()): self.assertEqual(2,cli.main())
 def test_token_is_child_environment_not_argv(self):
  token='not-in-argv'; observed={}
  def fake_run(args,**kwargs): observed.update(args=args,env=kwargs['env'],stdin=kwargs['stdin']); return subprocess.CompletedProcess(args,0,'','')
  with patch.object(cli.subprocess,'run',fake_run): result=cli._deploy_runner(token,{'CLOUDFLARE_ENV':'preview','CF_API_TOKEN':'old'})(('node','--no-warnings','cli.js','deploy'),ROOT)
  self.assertEqual(0,result[0]); self.assertNotIn(token,observed['args']); self.assertEqual(token,observed['env']['CLOUDFLARE_API_TOKEN']); self.assertNotIn('CLOUDFLARE_ENV',observed['env']); self.assertIs(subprocess.DEVNULL,observed['stdin'])
 def test_safe_audit_never_includes_raw_or_token(self):
  k,_=self.kwargs(); result=cli.run_cli(self.command(),**k); self.assertNotIn('safe-token',repr(result)); self.assertNotIn('Authorization',repr(result)); self.assertNotIn('raw',repr(result))
 def test_safe_error_classification_is_exposed_without_error_stream(self):
  def deploy(**kwargs): return w.DeployAudit('v',HEAD,w.SCRIPT,w.ACCOUNT,True,False,False,False,1,False,False,'deploy_failed_before_upload',error_classification='filesystem_permission_error')
  k,_=self.kwargs(deploy_function=deploy); result=cli.run_cli(self.command(),**k)
  self.assertEqual('filesystem_permission_error',result['audit']['error_classification']); self.assertNotIn('secret',repr(result))

if __name__=='__main__': unittest.main()
