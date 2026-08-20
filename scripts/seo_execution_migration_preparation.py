"""Read-only preparation checks for applying SEO execution migration 0010."""
from __future__ import annotations
from hashlib import sha256
from pathlib import Path
from typing import Any, Mapping, Sequence
from seo_execution_d1_read_adapter import ProductionD1Target
from seo_execution_production_verification import SeoExecutionProductionVerificationError, validate_migration_0010_preflight

MIGRATION_FILENAME="0010_seo_execution_transactions.sql"
CHECKLIST_SCHEMA_VERSION="seo-improvement-migration-apply-checklist-v1"
class SeoExecutionMigrationPreparationError(ValueError): pass
def migration_sha256(path:Path)->str:
    if not isinstance(path,Path) or path.name!=MIGRATION_FILENAME or not path.is_file(): raise SeoExecutionMigrationPreparationError("migration_file_invalid")
    return sha256(path.read_bytes()).hexdigest()
def validate_migration_sha(path:Path,expected_sha256:object)->str:
    actual=migration_sha256(path)
    if not isinstance(expected_sha256,str) or actual!=expected_sha256: raise SeoExecutionMigrationPreparationError("migration_hash_mismatch")
    return actual
def validate_target_identity(target:ProductionD1Target,identity:Mapping[str,Any])->None:
    result=identity.get("result") if isinstance(identity,Mapping) else None
    if not isinstance(result,Mapping) or result.get("name")!=target.database_name or result.get("uuid")!=target.database_id: raise SeoExecutionMigrationPreparationError("target_identity_mismatch")
def validate_backup_evidence(evidence:Mapping[str,Any],target:ProductionD1Target)->None:
    required={"bookmark","export_sha256","export_size","captured_at","database_id","restore_plan_verified"}
    if not isinstance(evidence,Mapping) or set(evidence)!=required or not all(isinstance(evidence.get(k),str) and evidence[k] for k in ("bookmark","export_sha256","captured_at","database_id")) or len(evidence["export_sha256"])!=64 or not isinstance(evidence.get("export_size"),int) or evidence["export_size"]<=0 or evidence.get("database_id")!=target.database_id or evidence.get("restore_plan_verified") is not True: raise SeoExecutionMigrationPreparationError("backup_evidence_invalid")
def validate_schema_preflight(*,observed_new_tables:Sequence[object],foreign_key_rows:Sequence[object],existing_schema_drift:bool)->None:
    try: validate_migration_0010_preflight(observed_new_tables)
    except SeoExecutionProductionVerificationError as e: raise SeoExecutionMigrationPreparationError("migration_schema_drift") from e
    if not isinstance(foreign_key_rows,Sequence) or isinstance(foreign_key_rows,(str,bytes)) or foreign_key_rows: raise SeoExecutionMigrationPreparationError("foreign_key_check_failed")
    if existing_schema_drift is not False: raise SeoExecutionMigrationPreparationError("existing_schema_drift")
def build_migration_apply_checklist(target:ProductionD1Target,migration_path:Path,expected_sha256:str,identity:Mapping[str,Any],backup_evidence:Mapping[str,Any],*,observed_new_tables:Sequence[object],foreign_key_rows:Sequence[object],existing_schema_drift:bool)->dict[str,Any]:
    sha=validate_migration_sha(migration_path,expected_sha256);validate_target_identity(target,identity);validate_backup_evidence(backup_evidence,target);validate_schema_preflight(observed_new_tables=observed_new_tables,foreign_key_rows=foreign_key_rows,existing_schema_drift=existing_schema_drift)
    return {"schema_version":CHECKLIST_SCHEMA_VERSION,"migration_filename":MIGRATION_FILENAME,"migration_sha256":sha,"environment":target.environment,"database_id":target.database_id,"database_name":target.database_name,"backup_bookmark_present":True,"backup_export_verified":True,"foreign_key_check_passed":True,"schema_preflight_passed":True,"dry_run_only":True,"apply_authorized":False}
