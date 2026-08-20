"""Read-only preflight and dry-run results for SEO execution."""
from __future__ import annotations
from typing import Any, Mapping, Sequence
from seo_improvement_execution_preflight import build_execution_preflight
class SeoExecutionDryRunError(ValueError): pass
def run_read_only_preflight(approval:Mapping[str,Any],candidate:Mapping[str,Any],candidate_input:Mapping[str,Any],latest_snapshot:Mapping[str,Any],*,now:str,used_approval_ids:Sequence[str]=())->dict[str,Any]:
    try: preflight=build_execution_preflight(approval,candidate,candidate_input,latest_snapshot,now=now,used_approval_ids=used_approval_ids)
    except Exception as e: raise SeoExecutionDryRunError("read_only_preflight_failed") from e
    return {"preflight":preflight,"changed_db":False,"rows_written":0,"approval_consumed":False}
def run_dry_run(*args:Any,**kwargs:Any)->dict[str,Any]:
    result=run_read_only_preflight(*args,**kwargs)
    if result["changed_db"] is not False or result["rows_written"]!=0 or result["approval_consumed"] is not False: raise SeoExecutionDryRunError("dry_run_write_boundary_invalid")
    return {"schema_version":"seo-improvement-execution-dry-run-v1",**result}
