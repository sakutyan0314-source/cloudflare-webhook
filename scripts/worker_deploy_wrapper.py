"""One-attempt, secret-free Worker deploy process classifier."""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

ACCOUNT='29837b450b7135d3766c22160e3a2504'; SCRIPT='cloudflare-webhook'
WRANGLER_VERSION='4.120.0'
@dataclass(frozen=True)
class DeployAudit:
 schema_version:str; git_head:str; target_script:str; target_account:str; process_started:bool; build_stage_observed:bool; upload_stage_observed:bool; cloudflare_response_observed:bool; exit_code:int|None; timed_out:bool; interrupted:bool; classification:str
 argv_classification:str='fixed_npx_no_install_wrangler_deploy'; cwd_classification:str='repository_root'; config_discovery_classification:str='repository_wrangler_toml'; child_environment_classification:str='not_asserted'; stdin_managed:bool=False
def run_deploy(*,root:Path,git_head:str,account:str,runner:Callable[[Sequence[str],Path],tuple[int,str,str]],version_getter:Callable[[],str],timeout_seconds:int=180,child_environment_classification:str='not_asserted',stdin_managed:bool=False)->DeployAudit:
 meta=( 'fixed_npx_no_install_wrangler_deploy','repository_root','repository_wrangler_toml' if (root/'wrangler.toml').is_file() else 'config_discovery_unknown',child_environment_classification,stdin_managed)
 if root.resolve()!=Path(__file__).parents[1].resolve() or account!=ACCOUNT:return DeployAudit('worker-deploy-audit-v1',git_head,SCRIPT,account,False,False,False,False,None,False,False,'preflight_failed',*meta)
 if version_getter()!=WRANGLER_VERSION:return DeployAudit('worker-deploy-audit-v1',git_head,SCRIPT,account,False,False,False,False,None,False,False,'wrangler_version_mismatch',*meta)
 try:
  # Account is verified at the wrapper boundary.  No unverified Wrangler CLI
  # account flag is invented here; deployment invocation remains explicit.
  code,out,err=runner(('npx','--no-install','wrangler','deploy'),root)
 except TimeoutError:return DeployAudit('worker-deploy-audit-v1',git_head,SCRIPT,ACCOUNT,True,False,False,False,None,True,False,'process_timeout',*meta)
 except KeyboardInterrupt:return DeployAudit('worker-deploy-audit-v1',git_head,SCRIPT,ACCOUNT,True,False,False,False,None,False,True,'process_interrupted',*meta)
 except OSError:return DeployAudit('worker-deploy-audit-v1',git_head,SCRIPT,ACCOUNT,False,False,False,False,None,False,False,'wrangler_start_failed',*meta)
 text=(out or '')+'\n'+(err or '')
 # Wrangler 4.120.0 emits these lifecycle messages for ``wrangler deploy``.
 # We retain only their boolean presence, never the raw process streams.
 build='Compiled Worker successfully' in text
 upload='Uploading' in text or 'Uploaded ' in text
 response='Current Version ID:' in text or 'Worker Version ID:' in text
 confirmation_prompt='Would you like to continue?' in text or 'Do you want to continue?' in text
 deployment_aborted='Aborting deploy...' in text
 if code==0 and response: classification='deploy_succeeded'
 elif deployment_aborted: classification='deploy_confirmation_declined_or_aborted'
 elif confirmation_prompt: classification='deploy_confirmation_required'
 elif code==0: classification='process_succeeded_unobserved'
 elif upload: classification='deploy_failed_after_upload'
 elif build: classification='build_failed'
 else: classification='deploy_failed_before_upload'
 return DeployAudit('worker-deploy-audit-v1',git_head,SCRIPT,ACCOUNT,True,build,upload,response,code,False,False,classification,*meta)
