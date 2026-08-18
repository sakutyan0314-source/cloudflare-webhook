"""One-attempt, secret-free Worker deploy process classifier."""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

ACCOUNT='29837b450b7135d3766c22160e3a2504'; SCRIPT='cloudflare-webhook'
@dataclass(frozen=True)
class DeployAudit:
 schema_version:str; git_head:str; target_script:str; target_account:str; process_started:bool; build_stage_observed:bool; upload_stage_observed:bool; cloudflare_response_observed:bool; exit_code:int|None; timed_out:bool; interrupted:bool; classification:str
def run_deploy(*,root:Path,git_head:str,account:str,runner:Callable[[Sequence[str],Path],tuple[int,str,str]],timeout_seconds:int=180)->DeployAudit:
 if root.resolve()!=Path(__file__).parents[1].resolve() or account!=ACCOUNT:return DeployAudit('worker-deploy-audit-v1',git_head,SCRIPT,account,False,False,False,False,None,False,False,'preflight_failed')
 try:
  # Account is verified at the wrapper boundary.  No unverified Wrangler CLI
  # account flag is invented here; deployment invocation remains explicit.
  code,out,err=runner(('npx','wrangler','deploy'),root)
 except TimeoutError:return DeployAudit('worker-deploy-audit-v1',git_head,SCRIPT,ACCOUNT,True,False,False,False,None,True,False,'process_timeout')
 except KeyboardInterrupt:return DeployAudit('worker-deploy-audit-v1',git_head,SCRIPT,ACCOUNT,True,False,False,False,None,False,True,'process_interrupted')
 except OSError:return DeployAudit('worker-deploy-audit-v1',git_head,SCRIPT,ACCOUNT,False,False,False,False,None,False,False,'wrangler_start_failed')
 text=(out or '')+'\n'+(err or ''); build='Total Upload:' in text or 'Compiled Worker' in text; upload='Uploading' in text or 'Total Upload:' in text; response='Current Deployment ID:' in text or 'Deployed' in text
 classification='deploy_succeeded' if code==0 and response else ('deploy_failed_after_upload' if upload else ('build_failed' if build else 'deploy_failed_before_upload'))
 return DeployAudit('worker-deploy-audit-v1',git_head,SCRIPT,ACCOUNT,True,build,upload,response,code,False,False,classification)
