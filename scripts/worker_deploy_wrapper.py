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
 error_classification:str='not_applicable'
 error_stage:str='not_applicable'
 error_code:str|None=None
 error_name:str|None=None
 error_summary:str='not_applicable'
 # Process-local fact only. It intentionally says nothing about whether a
 # Cloudflare Worker Version was ultimately created; that is a CLI post-check.
 process_result:str='not_started'


def _strip_ansi(value: str) -> str:
 """Use process output only for in-memory fixed-marker checks."""
 return re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", value)
def _safe_error_details(value:str)->tuple[str,str,str|None,str|None,str]:
 """Return fixed diagnostics only; never retain a raw Wrangler stream."""
 text=value.lower()
 patterns=(
  ('filesystem_permission_error','wrangler_runtime','filesystem_permission_failure',('eperm','eacces','permission denied','failed to write to log file','read-only file system')),
  ('authentication_error','authentication','authentication_failure',('authentication error','not authenticated','invalid api token','api token is invalid','unauthorized')),
  ('account_error','account_selection','account_selection_failure',('account id','account configuration','could not find account','account is required')),
  ('config_error','config_load','configuration_failure',('wrangler.toml','wrangler.json','configuration file','configuration error','must provide a name')),
  ('module_resolution_error','module_resolution','module_resolution_failure',('could not resolve','module not found','cannot find module','failed to resolve module')),
  ('typescript_or_syntax_error','build','source_syntax_failure',('typescript error','syntax error','unexpected token','tsconfig')),
  ('compatibility_error','config_validation','compatibility_configuration_failure',('compatibility_date','compatibility date','compatibility flag')),
  ('build_error','build','worker_build_failure',('build failed','esbuild','failed to build','build error')),
  ('network_error','cloudflare_transport','network_transport_failure',('network error','fetch failed','econnrefused','enotfound','etimedout','socket hang up')),
  ('api_error','cloudflare_api','cloudflare_api_failure',('cloudflare api','api request failed','api error','error code:')),
  ('wrangler_internal_error','wrangler_runtime','wrangler_internal_failure',('wrangler internal error','internal error','unexpected wrangler error')),
 )
 code_match=re.search(r'(?i)\b(?:error\s+code|code)\s*[:=]?\s*(\d{3,6})\b',value)
 name_match=re.search(r'\b(EPERM|EACCES|ENOTFOUND|ECONNREFUSED|ETIMEDOUT|EAI_AGAIN)\b',value)
 code=code_match.group(1) if code_match else None
 name=name_match.group(1) if name_match else None
 for classification,stage,summary,markers in patterns:
  if any(marker in text for marker in markers):return classification,stage,code,name,summary
 return 'unknown_preupload_error','preupload_unknown',code,name,'unclassified_preupload_failure'
def run_deploy(*,root:Path,git_head:str,account:str,runner:Callable[[Sequence[str],Path],tuple[int,str,str]],version_getter:Callable[[],str],timeout_seconds:int=180,child_environment_classification:str='not_asserted',stdin_managed:bool=False)->DeployAudit:
 meta=( 'fixed_node_local_wrangler_cli_deploy','repository_root','repository_wrangler_toml' if (root/'wrangler.toml').is_file() else 'config_discovery_unknown',child_environment_classification,stdin_managed)
 if root.resolve()!=Path(__file__).parents[1].resolve() or account!=ACCOUNT:return DeployAudit('worker-deploy-audit-v1',git_head,SCRIPT,account,False,False,False,False,None,False,False,'preflight_failed',*meta)
 if version_getter()!=WRANGLER_VERSION:return DeployAudit('worker-deploy-audit-v1',git_head,SCRIPT,account,False,False,False,False,None,False,False,'wrangler_version_mismatch',*meta)
 cli_entrypoint=root/WRANGLER_CLI_RELATIVE_PATH
 if not cli_entrypoint.is_file():return DeployAudit('worker-deploy-audit-v1',git_head,SCRIPT,ACCOUNT,False,False,False,False,None,False,False,'local_wrangler_cli_missing',*meta)
 try:
  # Use the pinned CLI entrypoint directly. bin/wrangler.js converts a
  # signalled inner process (code=None) to an outer exit status of 0.
  code,out,err=runner(('node','--no-warnings',str(cli_entrypoint),'deploy','--config','./wrangler.toml'),root)
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
 if code is not None and code<0: classification='process_signal_terminated'; process_result='signal_terminated'
 elif code==0 and response: classification='deploy_succeeded'; process_result='completed_with_version_marker'
 elif deployment_aborted: classification='deploy_confirmation_declined_or_aborted'; process_result='failed_before_upload'
 elif confirmation_prompt: classification='deploy_confirmation_required'; process_result='failed_before_upload'
 elif code==0: classification='process_succeeded_unobserved'; process_result='completed_without_version_marker'
 elif upload: classification='deploy_failed_after_upload'; process_result='failed_after_upload'
 else: classification='deploy_failed_before_upload'; process_result='failed_before_upload'
 if code==0 or code is None or code<0:
  error_classification,error_stage,error_code,error_name,error_summary='not_applicable','not_applicable',None,None,'not_applicable'
 else:
  error_classification,error_stage,error_code,error_name,error_summary=_safe_error_details(text)
 return DeployAudit('worker-deploy-audit-v1',git_head,SCRIPT,ACCOUNT,True,build,upload,response,code,False,False,classification,*meta,'build_stage_unknown',dry_run,autoconfig_aborted,opennext_delegation,config_redirect,response,code is not None and code<0,error_classification,error_stage,error_code,error_name,error_summary,process_result)
