"""Sanitized, zero-write readiness check before a first SEO execution."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from seo_execution_candidate_qualification import qualify_first_execution_candidate
from seo_execution_d1_read_adapter import SeoExecutionD1ReadAdapter, SeoExecutionReadAdapterError
from seo_execution_production_verification import MIGRATION_0010_TABLES, snapshot_from_article_row


READINESS_SCHEMA_VERSION = "seo-improvement-first-production-execution-readiness-v1"


class SeoExecutionProductionReadinessError(ValueError):
    """Production readiness must fail closed without exposing source data."""


def run_first_production_execution_readiness(
    adapter: SeoExecutionD1ReadAdapter,
    artifacts: Mapping[str, Any],
    *,
    now: str,
    used_approval_ids: Sequence[str] = (),
) -> dict[str, Any]:
    """Check one approved candidate using only the adapter's fixed SELECTs."""
    try:
        if not isinstance(artifacts, Mapping):
            raise SeoExecutionProductionReadinessError("artifacts_invalid")
        execution_candidate = artifacts["execution_candidate"]
        article_id = execution_candidate["article_id"]
        if not isinstance(article_id, int) or article_id < 1:
            raise SeoExecutionProductionReadinessError("article_id_invalid")
        adapter.verify_identity()
        if set(adapter.read_migration_preflight()) != MIGRATION_0010_TABLES:
            raise SeoExecutionProductionReadinessError("migration_0010_not_ready")
        latest_snapshot = snapshot_from_article_row(adapter.read_article_snapshot(article_id))
        scoped_artifacts = {**artifacts, "latest_snapshot": latest_snapshot}
        qualification = qualify_first_execution_candidate(scoped_artifacts, now=now, used_approval_ids=used_approval_ids)
        fields = sorted(execution_candidate["expected_diff"])
        if not fields or set(fields) - {"title", "description"}:
            raise SeoExecutionProductionReadinessError("scope_not_allowed")
        approval_id = artifacts["execution_approval"]["execution_approval_id"]
        if adapter.read_approval_attempts(approval_id):
            raise SeoExecutionProductionReadinessError("approval_already_reserved")
    except (SeoExecutionReadAdapterError, SeoExecutionProductionReadinessError, KeyError, TypeError, ValueError) as error:
        if isinstance(error, SeoExecutionProductionReadinessError):
            raise
        raise SeoExecutionProductionReadinessError("readiness_failed") from error
    return {
        "schema_version": READINESS_SCHEMA_VERSION,
        "status": "pass",
        "article_id": article_id,
        "execution_candidate_id": execution_candidate["execution_candidate_id"],
        "execution_approval_id": approval_id,
        "preflight_id": qualification["preflight"]["preflight_id"],
        "target_identity_check": True,
        "migration_readiness_check": True,
        "candidate_identity_check": True,
        "approval_identity_check": True,
        "ttl_single_use_check": True,
        "stale_check": True,
        "expected_diff_check": True,
        "allowed_scope": fields,
        "changed_db": False,
        "rows_written": 0,
        "approval_consumed": False,
    }
