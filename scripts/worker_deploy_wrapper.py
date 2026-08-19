"""One-attempt, secret-free Worker deploy process classifier."""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import re
import subprocess
from typing import Callable, Sequence

ACCOUNT='29837b450b7135d3766c22160e3a2504'; SCRIPT='cloudflare-webhook'
WRANGLER_VERSION='4.120.0'
WRANGLER_CLI_RELATIVE_PATH=Path('node_modules/wrangler/wrangler-dist/cli.js')
@dataclass(frozen=True)
class DeployAudit:
 schema_version:str; git_head:str; target_script:str; target_account:str; process_started:bool; build_stage_observed:bool; upload_stage_observed:bool; cloudflare_response_observed:bool; exit_code:int|None; timed_out:bool; interrupted:bool; classification:str
 argv_classification:str='fixed_node_local_wrangler_cli_deploy'; cwd_classification:str='repository_root'; config_discovery_classification:str='repository_wrangler_toml'; child_environment_classification:str='not_asserted'; stdin_managed:bool=False
 build_stage_classification:str='build_stage_unknown'
 dry_run_marker_observed:bool=False
 autoconfig_aborted_observed:bool=False
 opennext_delegation_observed:bool=False
 config_redirect_observed:bool=False
 version_marker_observed:bool=False
 signal_terminated:bool=False


def _strip_ansi(value: str) -> str:
 """Use process output only for in-memory fixed-marker checks."""
 return re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", value)
def run_deploy(*,root:Path,git_head:str,account:str,runner:Callable[[Sequence[str],Path],tuple[int,str,str]],version_getter:Callable[[],str],timeout_seconds:int=180,child_environment_classification:str='not_asserted',stdin_managed:bool=False)->DeployAudit:
 meta=( 'fixed_node_local_wrangler_cli_deploy','repository_root','repository_wrangler_toml' if (root/'wrangler.toml').is_file() else 'config_discovery_unknown',child_environment_classification,stdin_managed)
 if root.resolve()!=Path(__file__).parents[1].resolve() or account!=ACCOUNT:return DeployAudit('worker-deploy-audit-v1',git_head,SCRIPT,account,False,False,False,False,None,False,False,'preflight_failed',*meta)
 if version_getter()!=WRANGLER_VERSION:return DeployAudit('worker-deploy-audit-v1',git_head,SCRIPT,account,False,False,False,False,None,False,False,'wrangler_version_mismatch',*meta)
 cli_entrypoint=root/WRANGLER_CLI_RELATIVE_PATH
 if not cli_entrypoint.is_file():return DeployAudit('worker-deploy-audit-v1',git_head,SCRIPT,ACCOUNT,False,False,False,False,None,False,False,'local_wrangler_cli_missing',*meta)
 try:
  # Use the pinned CLI entrypoint directly. bin/wrangler.js converts a
  # signalled inner process (code=None) to an outer exit status of 0.
  code,out,err=runner(('node','--no-warnings',str(cli_entrypoint),'deploy'),root)
 except (TimeoutError,subprocess.TimeoutExpired):return DeployAudit('worker-deploy-audit-v1',git_head,SCRIPT,ACCOUNT,True,False,False,False,None,True,False,'process_timeout',*meta)
 except KeyboardInterrupt:return DeployAudit('worker-deploy-audit-v1',git_head,SCRIPT,ACCOUNT,True,False,False,False,None,False,True,'process_interrupted',*meta)
 except OSError:return DeployAudit('worker-deploy-audit-v1',git_head,SCRIPT,ACCOUNT,False,False,False,False,None,False,False,'wrangler_start_failed',*meta)
 text=_strip_ansi((out or '')+'\n'+(err or ''))
 # These are value-free, documented Wrangler 4.120.0 lifecycle markers. The
 # generic "Compiled Worker successfully" text belongs to a different build
 # path, so a Worker deploy build is deliberately classified as unknown.
 build=False
 upload=bool(re.search(r"(?m)^Uploaded\s+\S+", text))
 response='Current Version ID:' in text or 'Worker Version ID:' in text
 confirmation_prompt='Would you like to continue?' in text or 'Do you want to continue?' in text
 deployment_aborted='Aborting deploy...' in text
 dry_run='--dry-run: exiting now.' in text
 # The only non-interactive autoconfig abort evidence emitted by Wrangler is
 # the Pages confirmation with an explicit fallback of "no". Do not infer an
 # abort from the Pages warning or prompt by itself.
 autoconfig_aborted=('Are you sure that you want to proceed?' in text and 'Using fallback value in non-interactive context: no' in text)
 opennext_delegation='OpenNext project detected, calling `opennextjs-cloudflare deploy`' in text
 config_redirect='Using redirected Wrangler configuration.' in text
 if code is not None and code<0: classification='process_signal_terminated'
 elif code==0 and response: classification='deploy_succeeded'
 elif deployment_aborted: classification='deploy_confirmation_declined_or_aborted'
 elif confirmation_prompt: classification='deploy_confirmation_required'
 elif code==0: classification='process_succeeded_unobserved'
 elif upload: classification='deploy_failed_after_upload'
 else: classification='deploy_failed_before_upload'
 return DeployAudit('worker-deploy-audit-v1',git_head,SCRIPT,ACCOUNT,True,build,upload,response,code,False,False,classification,*meta,'build_stage_unknown',dry_run,autoconfig_aborted,opennext_delegation,config_redirect,response,code is not None and code<0)
