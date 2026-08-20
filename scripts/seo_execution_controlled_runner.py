"""One-shot, injected boundary for a separately approved SEO snippet update.

It has no credential source, HTTP client, Worker route, Cron entry point, or
retry loop.  A production transport must be supplied by a later operator-only
integration; tests use an in-memory mock.
"""

from __future__ import annotations

from typing import Any, Mapping, Protocol, Sequence

from seo_execution_candidate_qualification import qualify_first_execution_candidate
from seo_execution_d1_write_adapter import build_conditional_update_statement
from seo_execution_transaction_repository import validate_conditional_returning
from seo_improvement_execution_attempt import build_execution_attempt, build_post_verification


class SeoControlledExecutionError(ValueError):
    """A controlled execution must stop without retrying or rolling back."""


class ControlledExecutionTransport(Protocol):
    """Fixed operations only; implementations must not expose arbitrary SQL."""
    def reserve_attempt(self, attempt: Mapping[str, Any]) -> None: ...
    def transition(self, attempt: Mapping[str, Any], state: str, classification: str, *, reason_code: str | None = None) -> None: ...
    def conditional_snippet_update(self, statement: Mapping[str, Any]) -> Mapping[str, Any]: ...
    def read_article_snapshot(self, article_id: int) -> Mapping[str, Any]: ...
    def save_post_verification(self, verification: Mapping[str, Any]) -> None: ...


def _attempt(preflight: Mapping[str, Any], artifacts: Mapping[str, Any], snapshot: Mapping[str, Any], *, now: str, state: str, classification: str, completed_at: str | None, changed_db: bool | None, changes: int | None, returned_article_id: int | None, used: Sequence[str]) -> dict[str, Any]:
    return build_execution_attempt(
        preflight, artifacts["execution_approval"], artifacts["execution_candidate"],
        artifacts["execution_candidate_input"], snapshot,
        {"state": state, "classification": classification, "started_at": now,
         "completed_at": completed_at, "changed_db": changed_db, "changes": changes,
         "returned_article_id": returned_article_id}, now=now, used_approval_ids=used,
    )


def run_first_controlled_execution(
    artifacts: Mapping[str, Any],
    current_row: Mapping[str, Any],
    transport: ControlledExecutionTransport,
    *,
    target_article_id: int,
    now: str,
    execute: bool = False,
    used_approval_ids: Sequence[str] = (),
) -> dict[str, Any]:
    """Execute exactly one title/description candidate, with no retry or rollback.

    ``execute=True`` is an explicit operator boundary.  Any exception after an
    update start is reported as ``outcome_unknown`` and never retried here.
    """
    if execute is not True:
        raise SeoControlledExecutionError("explicit_execution_confirmation_required")
    if not isinstance(artifacts, Mapping) or target_article_id != artifacts.get("execution_candidate", {}).get("article_id"):
        raise SeoControlledExecutionError("target_article_mismatch")
    try:
        qualification = qualify_first_execution_candidate(artifacts, now=now, used_approval_ids=used_approval_ids)
        candidate = artifacts["execution_candidate"]
        preflight = qualification["preflight"]
        statement = build_conditional_update_statement(candidate, current_row)
        if set(statement["set_fields"]) - {"title", "description"} or not statement["set_fields"]:
            raise SeoControlledExecutionError("snippet_scope_invalid")
        planned = _attempt(preflight, artifacts, artifacts["latest_snapshot"], now=now, state="planned", classification="not_started", completed_at=None, changed_db=False, changes=0, returned_article_id=None, used=used_approval_ids)
    except (KeyError, TypeError, ValueError) as error:
        if isinstance(error, SeoControlledExecutionError):
            raise
        raise SeoControlledExecutionError("final_preflight_failed") from error

    transport.reserve_attempt(planned)
    reserved = _attempt(preflight, artifacts, artifacts["latest_snapshot"], now=now, state="approval_reserved", classification="approval_reserved", completed_at=None, changed_db=False, changes=0, returned_article_id=None, used=used_approval_ids)
    transport.transition(reserved, "approval_reserved", "approval_reserved")
    started = _attempt(preflight, artifacts, artifacts["latest_snapshot"], now=now, state="update_started", classification="update_started", completed_at=None, changed_db=False, changes=0, returned_article_id=None, used=used_approval_ids)
    transport.transition(started, "update_started", "update_started")

    try:
        result = validate_conditional_returning(transport.conditional_snippet_update(statement), target_article_id)
    except Exception:
        unknown = _attempt(preflight, artifacts, artifacts["latest_snapshot"], now=now, state="outcome_unknown", classification="outcome_unknown", completed_at=now, changed_db=None, changes=None, returned_article_id=None, used=used_approval_ids)
        try:
            transport.transition(unknown, "outcome_unknown", "outcome_unknown", reason_code="outcome_unknown")
        except Exception:
            pass
        return {"status": "outcome_unknown", "execution_attempt_id": planned["execution_attempt_id"], "approval_consumed": True, "changed_db": None, "rows_written": None}

    success = _attempt(preflight, artifacts, artifacts["latest_snapshot"], now=now, state="outcome_known_success", classification="success", completed_at=now, changed_db=result.changed_db, changes=result.changes, returned_article_id=result.returned_id, used=used_approval_ids)
    try:
        observed = transport.read_article_snapshot(target_article_id)
        verification = build_post_verification(success, candidate, observed)
        transport.save_post_verification(verification)
        if verification["classification"] != "pass":
            raise SeoControlledExecutionError("post_verification_mismatch")
        transport.transition(success, "outcome_known_success", "success")
    except Exception:
        failure = _attempt(preflight, artifacts, artifacts["latest_snapshot"], now=now, state="outcome_known_failure", classification="known_failure", completed_at=now, changed_db=False, changes=0, returned_article_id=None, used=used_approval_ids)
        try:
            transport.transition(failure, "outcome_known_failure", "known_failure", reason_code="transaction_failed")
        except Exception:
            pass
        return {"status": "outcome_known_failure", "execution_attempt_id": planned["execution_attempt_id"], "approval_consumed": True, "changed_db": True, "rows_written": result.rows_written}
    return {"status": "outcome_known_success", "execution_attempt_id": planned["execution_attempt_id"], "approval_consumed": True, "changed_db": True, "rows_written": result.rows_written, "post_verification_id": verification["post_verification_id"]}
