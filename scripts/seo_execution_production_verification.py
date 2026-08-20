"""Read-only production-readiness checks for the SEO execution boundary."""
from __future__ import annotations
from hashlib import sha256
from typing import Any, Mapping, Sequence
from seo_execution_d1_read_adapter import ProductionD1Target, SeoExecutionD1ReadAdapter, SeoExecutionReadAdapterError
from seo_execution_d1_write_adapter import SeoExecutionWriteAdapterError, validate_fixed_write
from seo_execution_dry_run import SeoExecutionDryRunError, run_dry_run

DRY_RUN_REPORT_SCHEMA_VERSION="seo-improvement-production-dry-run-report-v1"
MIGRATION_0010_TABLES=frozenset({"seo_execution_attempts","seo_execution_attempt_events","seo_execution_post_verifications"})
class SeoExecutionProductionVerificationError(ValueError): pass
def validate_migration_0010_preflight(observed_tables:Sequence[object])->None:
    if not isinstance(observed_tables,Sequence) or isinstance(observed_tables,(str,bytes)) or any(not isinstance(x,str) for x in observed_tables): raise SeoExecutionProductionVerificationError("migration_preflight_shape_invalid")
    found=set(observed_tables)&MIGRATION_0010_TABLES
    if found: raise SeoExecutionProductionVerificationError("migration_0010_already_or_partially_present")
def verify_fixed_sql_whitelist(statements:Sequence[Mapping[str,Any]])->None:
    if not isinstance(statements,Sequence) or isinstance(statements,(str,bytes)) or not statements: raise SeoExecutionProductionVerificationError("sql_whitelist_input_invalid")
    try:
        for statement in statements: validate_fixed_write(statement)
    except SeoExecutionWriteAdapterError as e: raise SeoExecutionProductionVerificationError("sql_whitelist_violation") from e
def snapshot_from_article_row(row:Mapping[str,Any])->dict[str,Any]:
    required={"id","title","description","category","content","body_markdown","published_at","updated_at","seo_status"}
    if not isinstance(row,Mapping) or set(row)!=required or not isinstance(row["content"],str) or not isinstance(row["body_markdown"],str): raise SeoExecutionProductionVerificationError("article_snapshot_read_invalid")
    return {"article_id":row["id"],"title":row["title"],"description":row["description"],"category":row["category"],"content_sha256":sha256(row["content"].encode()).hexdigest(),"body_markdown_sha256":sha256(row["body_markdown"].encode()).hexdigest(),"published_at":row["published_at"],"updated_at":row["updated_at"],"seo_status":row["seo_status"]}
def build_dry_run_report(target:ProductionD1Target,dry_run:Mapping[str,Any])->dict[str,Any]:
    if not isinstance(dry_run,Mapping) or dry_run.get("changed_db") is not False or dry_run.get("rows_written")!=0 or dry_run.get("approval_consumed") is not False or not isinstance(dry_run.get("preflight"),Mapping): raise SeoExecutionProductionVerificationError("dry_run_zero_write_invalid")
    return {"schema_version":DRY_RUN_REPORT_SCHEMA_VERSION,"environment":target.environment,"database_id":target.database_id,"database_name":target.database_name,"preflight_id":dry_run["preflight"].get("preflight_id"),"article_id":dry_run["preflight"].get("article_id"),"changed_db":False,"rows_written":0,"approval_consumed":False,"status":"pass"}
def run_operator_preflight(adapter:SeoExecutionD1ReadAdapter,approval:Mapping[str,Any],candidate:Mapping[str,Any],candidate_input:Mapping[str,Any],*,now:str,used_approval_ids:Sequence[str]=())->dict[str,Any]:
    try:
        adapter.verify_identity(); validate_migration_0010_preflight(adapter.read_migration_preflight())
        snapshot=snapshot_from_article_row(adapter.read_article_snapshot(candidate["article_id"]))
        dry=run_dry_run(approval,candidate,candidate_input,snapshot,now=now,used_approval_ids=used_approval_ids)
    except (SeoExecutionReadAdapterError,SeoExecutionDryRunError,KeyError) as e: raise SeoExecutionProductionVerificationError("operator_preflight_failed") from e
    return build_dry_run_report(adapter.target,dry)
