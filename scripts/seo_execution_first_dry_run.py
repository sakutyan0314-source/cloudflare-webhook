"""Read-only first-execution dry-run after migration 0010 is present."""
from __future__ import annotations
from typing import Any, Mapping, Sequence
from seo_execution_d1_read_adapter import SeoExecutionD1ReadAdapter, SeoExecutionReadAdapterError
from seo_execution_d1_write_adapter import SeoExecutionWriteAdapterError, build_conditional_update_statement
from seo_execution_transaction_repository import SeoExecutionTransactionError
from seo_execution_production_verification import MIGRATION_0010_TABLES, snapshot_from_article_row
from seo_execution_dry_run import SeoExecutionDryRunError, run_dry_run

REPORT_SCHEMA_VERSION="seo-improvement-first-execution-dry-run-v1"
class SeoExecutionFirstDryRunError(ValueError): pass
def _validate_diff(candidate:Mapping[str,Any])->list[str]:
    diff=candidate.get('expected_diff') if isinstance(candidate,Mapping) else None
    if not isinstance(diff,Mapping) or not diff or not set(diff)<={'title','description'}: raise SeoExecutionFirstDryRunError('expected_diff_invalid')
    return sorted(diff)
def run_first_execution_dry_run(adapter:SeoExecutionD1ReadAdapter,approval:Mapping[str,Any],candidate:Mapping[str,Any],candidate_input:Mapping[str,Any],*,now:str,used_approval_ids:Sequence[str]=())->dict[str,Any]:
    try:
        adapter.verify_identity()
        if set(adapter.read_migration_preflight()) != MIGRATION_0010_TABLES: raise SeoExecutionFirstDryRunError('migration_0010_not_ready')
        fields=_validate_diff(candidate)
        article_row=adapter.read_article_snapshot(candidate['article_id'])
        snapshot=snapshot_from_article_row(article_row)
        dry=run_dry_run(approval,candidate,candidate_input,snapshot,now=now,used_approval_ids=used_approval_ids)
        # Shape-only proof: no write request is sent by this runner.
        statement=build_conditional_update_statement(candidate,article_row)
        if statement['set_fields'] != fields: raise SeoExecutionFirstDryRunError('expected_diff_statement_mismatch')
    except (SeoExecutionReadAdapterError, SeoExecutionWriteAdapterError, SeoExecutionTransactionError, SeoExecutionDryRunError, KeyError) as e: raise SeoExecutionFirstDryRunError('first_dry_run_failed') from e
    if dry['changed_db'] is not False or dry['rows_written']!=0 or dry['approval_consumed'] is not False: raise SeoExecutionFirstDryRunError('zero_write_boundary_invalid')
    return {'schema_version':REPORT_SCHEMA_VERSION,'preflight_id':dry['preflight']['preflight_id'],'article_id':candidate['article_id'],'expected_fields':fields,'identity_check':True,'candidate_check':True,'approval_check':True,'stale_check':True,'sql_whitelist_check':True,'changed_db':False,'rows_written':0,'approval_consumed':False,'status':'pass'}
