"""Pure, non-executing approval records for SEO execution candidates."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import re
from typing import Any, Mapping, Sequence

from seo_improvement_execution_candidate import (
    SeoImprovementExecutionCandidateError,
    validate_execution_candidate,
)


EXECUTION_APPROVAL_SCHEMA_VERSION = "seo-improvement-execution-approval-v1"
EXECUTION_APPROVAL_STATUSES = frozenset({"pending_approval", "approved", "rejected", "expired"})
INITIAL_EXECUTION_APPROVAL_TTL = timedelta(minutes=30)
_SOURCE_FIELDS = (
    "candidate_id", "candidate_fingerprint", "accepted_candidate_review_id", "proposal_id",
    "proposal_fingerprint", "accepted_proposal_review_id", "plan_id", "plan_fingerprint",
    "accepted_plan_review_id",
)
_FIELDS = frozenset({
    "schema_version", "execution_approval_id", "execution_candidate_id",
    "execution_candidate_fingerprint", "article_id", *_SOURCE_FIELDS, "status",
    "approved_by", "approved_at", "expires_at", "single_use",
    "article_change_authorized", "publication_authorized", "execution_authorized",
})
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


class SeoImprovementExecutionApprovalError(ValueError):
    """Execution approval violates its fixed, non-executing boundary."""


def canonical_json(value: Mapping[str, Any]) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as error:
        raise SeoImprovementExecutionApprovalError("execution approval cannot be canonically encoded") from error


def _time(value: object, name: str) -> datetime:
    if not isinstance(value, str):
        raise SeoImprovementExecutionApprovalError(name + " is invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise SeoImprovementExecutionApprovalError(name + " is invalid") from error
    if parsed.tzinfo is None:
        raise SeoImprovementExecutionApprovalError(name + " must include UTC offset")
    return parsed.astimezone(timezone.utc)


def _source(candidate: Mapping[str, Any]) -> dict[str, Any]:
    return {field: candidate[field] for field in _SOURCE_FIELDS}


def _approval_id_source(approval: Mapping[str, Any]) -> dict[str, Any]:
    return {field: approval[field] for field in _FIELDS if field != "execution_approval_id"}


def deterministic_execution_approval_id(approval: Mapping[str, Any]) -> str:
    return "seo_execution_approval_" + sha256(canonical_json(_approval_id_source(approval)).encode("utf-8")).hexdigest()[:24]


def build_execution_approval(
    execution_candidate: Mapping[str, Any],
    execution_candidate_input: Mapping[str, Any],
    decision: Mapping[str, Any],
) -> dict[str, Any]:
    """Build an immutable approval record; it never authorizes execution."""
    try:
        validate_execution_candidate(execution_candidate, execution_candidate_input)
    except SeoImprovementExecutionCandidateError as error:
        raise SeoImprovementExecutionApprovalError("execution candidate is invalid") from error
    if not isinstance(decision, Mapping):
        raise SeoImprovementExecutionApprovalError("execution approval decision is invalid")
    for field, value in {
        "execution_candidate_id": execution_candidate["execution_candidate_id"],
        "execution_candidate_fingerprint": execution_candidate["execution_candidate_fingerprint"],
        "article_id": execution_candidate["article_id"],
        **_source(execution_candidate),
    }.items():
        if decision.get(field) != value:
            raise SeoImprovementExecutionApprovalError(f"execution approval {field} does not match candidate")
    status = decision.get("status")
    if status not in EXECUTION_APPROVAL_STATUSES:
        raise SeoImprovementExecutionApprovalError("execution approval status is invalid")
    approved_by = decision.get("approved_by")
    if not isinstance(approved_by, str) or not _SAFE_ID.fullmatch(approved_by):
        raise SeoImprovementExecutionApprovalError("execution approval reviewer is invalid")
    approved_at = _time(decision.get("approved_at"), "approved_at")
    expires_at = _time(decision.get("expires_at"), "expires_at")
    if expires_at <= approved_at or expires_at > approved_at + INITIAL_EXECUTION_APPROVAL_TTL:
        raise SeoImprovementExecutionApprovalError("execution approval TTL is invalid")
    if decision.get("single_use") is not True:
        raise SeoImprovementExecutionApprovalError("execution approval must be single use")
    approval = {
        "schema_version": EXECUTION_APPROVAL_SCHEMA_VERSION,
        "execution_candidate_id": execution_candidate["execution_candidate_id"],
        "execution_candidate_fingerprint": execution_candidate["execution_candidate_fingerprint"],
        "article_id": execution_candidate["article_id"],
        **_source(execution_candidate),
        "status": status,
        "approved_by": approved_by,
        "approved_at": decision["approved_at"],
        "expires_at": decision["expires_at"],
        "single_use": True,
        "article_change_authorized": False,
        "publication_authorized": False,
        "execution_authorized": False,
    }
    approval["execution_approval_id"] = deterministic_execution_approval_id(approval)
    return approval


def validate_execution_approval(
    approval: Mapping[str, Any],
    execution_candidate: Mapping[str, Any],
    execution_candidate_input: Mapping[str, Any],
    *,
    now: str,
    current_snapshot: Mapping[str, Any] | None = None,
    used_approval_ids: Sequence[str] = (),
) -> None:
    """Fail closed unless an unexpired, unused approved record matches exactly."""
    try:
        validate_execution_candidate(execution_candidate, execution_candidate_input, current_snapshot=current_snapshot)
    except SeoImprovementExecutionCandidateError as error:
        raise SeoImprovementExecutionApprovalError("execution candidate is invalid or stale") from error
    if not isinstance(approval, Mapping) or set(approval) != _FIELDS or approval.get("schema_version") != EXECUTION_APPROVAL_SCHEMA_VERSION:
        raise SeoImprovementExecutionApprovalError("execution approval schema is invalid")
    expected = {
        "execution_candidate_id": execution_candidate["execution_candidate_id"],
        "execution_candidate_fingerprint": execution_candidate["execution_candidate_fingerprint"],
        "article_id": execution_candidate["article_id"],
        **_source(execution_candidate),
    }
    if any(approval.get(field) != value for field, value in expected.items()):
        raise SeoImprovementExecutionApprovalError("execution approval source identity is invalid")
    if approval.get("status") != "approved":
        raise SeoImprovementExecutionApprovalError("execution approval is not approved")
    if not isinstance(approval.get("approved_by"), str) or not _SAFE_ID.fullmatch(approval["approved_by"]):
        raise SeoImprovementExecutionApprovalError("execution approval reviewer is invalid")
    approved_at = _time(approval.get("approved_at"), "approved_at")
    expires_at = _time(approval.get("expires_at"), "expires_at")
    current = _time(now, "now")
    if expires_at <= approved_at or expires_at > approved_at + INITIAL_EXECUTION_APPROVAL_TTL or current >= expires_at:
        raise SeoImprovementExecutionApprovalError("execution approval is expired")
    if approval.get("single_use") is not True:
        raise SeoImprovementExecutionApprovalError("execution approval must be single use")
    if not isinstance(used_approval_ids, Sequence) or isinstance(used_approval_ids, (str, bytes, bytearray)) or any(not isinstance(item, str) for item in used_approval_ids):
        raise SeoImprovementExecutionApprovalError("used execution approval IDs are invalid")
    if approval["execution_approval_id"] in used_approval_ids:
        raise SeoImprovementExecutionApprovalError("execution approval was already used")
    if any(approval.get(field) is not False for field in ("article_change_authorized", "publication_authorized", "execution_authorized")):
        raise SeoImprovementExecutionApprovalError("execution approval authorization boundary is invalid")
    if approval.get("execution_approval_id") != deterministic_execution_approval_id(approval):
        raise SeoImprovementExecutionApprovalError("execution approval identity is invalid")
