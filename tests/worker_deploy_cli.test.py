import importlib.util, pathlib, subprocess, sys, unittest
from unittest.mock import patch

ROOT=pathlib.Path(__file__).parents[1]
for name, filename in [('worker_deploy_wrapper','scripts/worker_deploy_wrapper.py'),('worker_deploy_cli','scripts/worker_deploy_cli.py')]:
 spec=importlib.util.spec_from_file_location(name,ROOT/filename); module=importlib.util.module_from_spec(spec); sys.modules[name]=module; spec.loader.exec_module(module)
w=sys.modules['worker_deploy_wrapper']; cli=sys.modules['worker_deploy_cli']
HEAD='195fc2e7b9787e15bde2cae45d67d61af9be5064'

class WorkerDeployCliTest(unittest.TestCase):
 def kwargs(self, **overrides):
  calls=[]
  def deploy(**kwargs):
   calls.append(kwargs)
   return w.DeployAudit('v',HEAD,w.SCRIPT,w.ACCOUNT,True,True,True,True,0,False,False,'deploy_succeeded')
  base=dict(root=ROOT,cwd=ROOT,home=ROOT,token_provider=lambda:'safe-token',git_head=lambda _:HEAD,tracked_clean=lambda _:True,filesystem_ready=lambda _:True,version_getter=lambda _:w.WRANGLER_VERSION,deploy_function=deploy)
  base.update(overrides); return base,calls
 def command(self, *extra): return ['deploy-once','--expected-head',HEAD,'--expected-account',w.ACCOUNT,'--expected-wrangler-version',w.WRANGLER_VERSION,*extra]
 def test_requires_explicit_subcommand(self):
  k,c=self.kwargs(); self.assertEqual('deploy_command_required',cli.run_cli([],**k)['classification']); self.assertEqual([],c)
 def test_preflights_stop_before_deploy(self):
  cases=[({'git_head':lambda _: 'other'},'git_head_mismatch'),({'tracked_clean':lambda _:False},'tracked_worktree_dirty'),({'cwd':ROOT.parent},'repository_root_mismatch'),({'filesystem_ready':lambda _:False},'filesystem_preflight_failed'),({'version_getter':lambda _:None},'wrangler_version_mismatch'),({'token_provider':lambda:''},'worker_token_missing')]
  for override, expected in cases:
   with self.subTest(expected=expected):
    k,c=self.kwargs(**override); self.assertEqual(expected,cli.run_cli(self.command(),**k)['classification']); self.assertEqual([],c)
 def test_account_and_argument_mismatch_stop(self):
  k,c=self.kwargs(); self.assertEqual('account_mismatch',cli.run_cli(self.command('--expected-account','wrong'),**k)['classification']); self.assertEqual([],c)
 def test_unapproved_expected_head_stops(self):
  k,c=self.kwargs(); bad=['deploy-once','--expected-head','other','--expected-account',w.ACCOUNT,'--expected-wrangler-version',w.WRANGLER_VERSION]
  self.assertEqual('git_head_mismatch',cli.run_cli(bad,**k)['classification']); self.assertEqual([],c)
 def test_success_calls_existing_wrapper_once_without_token_audit(self):
  k,c=self.kwargs(); result=cli.run_cli(self.command(),**k); self.assertEqual('deploy_succeeded_process_level',result['classification']); self.assertEqual(1,len(c)); self.assertNotIn('safe-token',repr(result)); self.assertNotIn('safe-token',repr(c))
 def test_failure_timeout_and_interrupt_never_repeat(self):
  for classification, timed_out, interrupted, expected in [('deploy_failed_before_upload',False,False,'deploy_failed_before_upload'),('process_timeout',True,False,'deploy_outcome_unknown'),('process_interrupted',False,True,'deploy_outcome_unknown')]:
   calls=[]
   def deploy(**kwargs):
    calls.append(kwargs); return w.DeployAudit('v',HEAD,w.SCRIPT,w.ACCOUNT,True,False,False,False,None,timed_out,interrupted,classification)
   k,_=self.kwargs(deploy_function=deploy); self.assertEqual(expected,cli.run_cli(self.command(),**k)['classification']); self.assertEqual(1,len(calls))
 def test_token_is_child_environment_not_argv(self):
  token='not-in-argv'; seen={}
  def deploy(**kwargs):
   seen['runner']=kwargs['runner']; return w.DeployAudit('v',HEAD,w.SCRIPT,w.ACCOUNT,False,False,False,False,None,False,False,'preflight_failed')
  k,_=self.kwargs(token_provider=lambda:token,deploy_function=deploy); cli.run_cli(self.command(),**k)
  # The wrapper receives a fixed command; no token is represented in its audit.
  self.assertNotIn(token,repr(cli.run_cli(self.command(),**self.kwargs(token_provider=lambda:token)[0])))
  self.assertNotIn(token,repr(seen))
 def test_child_runner_uses_official_environment_variable_not_argv(self):
  token='not-in-argv'; observed={}
  def fake_run(args, **kwargs):
   observed['args']=args; observed['env']=kwargs['env']
   return subprocess.CompletedProcess(args, 0, '', '')
  with patch.object(cli.subprocess,'run',fake_run):
   result=cli._deploy_runner(token)(('npx','--no-install','wrangler','deploy'),ROOT)
  self.assertEqual(0,result[0]); self.assertNotIn(token,observed['args'])
  self.assertEqual(token,observed['env']['CLOUDFLARE_API_TOKEN'])

if __name__=='__main__': unittest.main()
