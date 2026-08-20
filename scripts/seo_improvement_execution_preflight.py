"""Pure read-only preflight records for SEO execution candidates."""

from __future__ import annotations

from hashlib import sha256
import json
from typing import Any, Mapping, Sequence

from ai_change_plan import ChangePlanError, validate_article_snapshot
from seo_improvement_execution_approval import (
    SeoImprovementExecutionApprovalError,
    validate_execution_approval,
)
from seo_improvement_execution_candidate import (
    SeoImprovementExecutionCandidateError,
    canonical_json as candidate_canonical_json,
    validate_execution_candidate,
)


PREFLIGHT_SCHEMA_VERSION = "seo-improvement-execution-preflight-v1"
_SOURCE_FIELDS = (
    "execution_approval_id", "execution_candidate_id", "execution_candidate_fingerprint",
    "candidate_id", "candidate_fingerprint", "proposal_id", "proposal_fingerprint",
    "plan_id", "plan_fingerprint",
)
_FIELDS = frozenset({
    "schema_version", "preflight_id", *_SOURCE_FIELDS, "before_snapshot_fingerprint",
    "after_snapshot_fingerprint", "latest_snapshot_fingerprint", "expected_diff",
    "stale_check", "approval_check", "single_use_check", "final_diff_check",
    "changed_db", "rows_written", "execution_authorized",
})


class SeoImprovementExecutionPreflightError(ValueError):
    """Preflight input is not a safe, read-only execution boundary."""


def _snapshot(value: Mapping[str, Any]) -> dict[str, Any]:
    try:
        return validate_article_snapshot(value)
    except ChangePlanError as error:
        raise SeoImprovementExecutionPreflightError("preflight snapshot is invalid") from error


def snapshot_fingerprint(snapshot: Mapping[str, Any]) -> str:
    return sha256(candidate_canonical_json(_snapshot(snapshot)).encode("utf-8")).hexdigest()


def _source(approval: Mapping[str, Any], candidate: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "execution_approval_id": approval["execution_approval_id"],
        "execution_candidate_id": candidate["execution_candidate_id"],
        "execution_candidate_fingerprint": candidate["execution_candidate_fingerprint"],
        "candidate_id": candidate["candidate_id"],
        "candidate_fingerprint": candidate["candidate_fingerprint"],
        "proposal_id": candidate["proposal_id"],
        "proposal_fingerprint": candidate["proposal_fingerprint"],
        "plan_id": candidate["plan_id"],
        "plan_fingerprint": candidate["plan_fingerprint"],
    }


def _preflight_id_source(preflight: Mapping[str, Any]) -> dict[str, Any]:
    return {field: preflight[field] for field in _FIELDS if field != "preflight_id"}


def deterministic_preflight_id(preflight: Mapping[str, Any]) -> str:
    try:
        encoded = json.dumps(_preflight_id_source(preflight), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as error:
        raise SeoImprovementExecutionPreflightError("preflight cannot be canonically encoded") from error
    return "seo_execution_preflight_" + sha256(encoded.encode("utf-8")).hexdigest()[:24]


def build_execution_preflight(
    approval: Mapping[str, Any],
    execution_candidate: Mapping[str, Any],
    execution_candidate_input: Mapping[str, Any],
    latest_snapshot: Mapping[str, Any],
    *,
    now: str,
    used_approval_ids: Sequence[str] = (),
) -> dict[str, Any]:
    """Return a zero-write preflight record only after complete validation."""
    try:
        validate_execution_candidate(execution_candidate, execution_candidate_input, current_snapshot=latest_snapshot)
        validate_execution_approval(
            approval, execution_candidate, execution_candidate_input, now=now,
            current_snapshot=latest_snapshot, used_approval_ids=used_approval_ids,
        )
    except (SeoImprovementExecutionCandidateError, SeoImprovementExecutionApprovalError) as error:
        raise SeoImprovementExecutionPreflightError("preflight source is invalid") from error
    before = execution_candidate["before_snapshot"]
    after = execution_candidate["after_snapshot"]
    latest = _snapshot(latest_snapshot)
    preflight = {
        "schema_version": PREFLIGHT_SCHEMA_VERSION,
        **_source(approval, execution_candidate),
        "before_snapshot_fingerprint": snapshot_fingerprint(before),
        "after_snapshot_fingerprint": snapshot_fingerprint(after),
        "latest_snapshot_fingerprint": snapshot_fingerprint(latest),
        "expected_diff": execution_candidate["expected_diff"],
        "stale_check": True,
        "approval_check": True,
        "single_use_check": True,
        "final_diff_check": True,
        "changed_db": False,
        "rows_written": 0,
        "execution_authorized": False,
    }
    preflight["preflight_id"] = deterministic_preflight_id(preflight)
    return preflight


def validate_execution_preflight(
    preflight: Mapping[str, Any],
    approval: Mapping[str, Any],
    execution_candidate: Mapping[str, Any],
    execution_candidate_input: Mapping[str, Any],
    latest_snapshot: Mapping[str, Any],
    *,
    now: str,
    used_approval_ids: Sequence[str] = (),
) -> None:
    """Validate exactly one approved, unexpired, read-only preflight snapshot."""
    try:
        validate_execution_candidate(execution_candidate, execution_candidate_input, current_snapshot=latest_snapshot)
        validate_execution_approval(
            approval, execution_candidate, execution_candidate_input, now=now,
            current_snapshot=latest_snapshot, used_approval_ids=used_approval_ids,
        )
    except (SeoImprovementExecutionCandidateError, SeoImprovementExecutionApprovalError) as error:
        raise SeoImprovementExecutionPreflightError("preflight source is invalid") from error
    if not isinstance(preflight, Mapping) or set(preflight) != _FIELDS or preflight.get("schema_version") != PREFLIGHT_SCHEMA_VERSION:
        raise SeoImprovementExecutionPreflightError("preflight schema is invalid")
    expected_source = _source(approval, execution_candidate)
    if any(preflight.get(field) != value for field, value in expected_source.items()):
        raise SeoImprovementExecutionPreflightError("preflight source identity is invalid")
    before = execution_candidate["before_snapshot"]
    after = execution_candidate["after_snapshot"]
    latest = _snapshot(latest_snapshot)
    if (
        preflight.get("before_snapshot_fingerprint") != snapshot_fingerprint(before)
        or preflight.get("after_snapshot_fingerprint") != snapshot_fingerprint(after)
        or preflight.get("latest_snapshot_fingerprint") != snapshot_fingerprint(latest)
        or preflight.get("expected_diff") != execution_candidate["expected_diff"]
    ):
        raise SeoImprovementExecutionPreflightError("preflight snapshot or final diff is invalid")
    if any(preflight.get(field) is not True for field in ("stale_check", "approval_check", "single_use_check", "final_diff_check")):
        raise SeoImprovementExecutionPreflightError("preflight checks are invalid")
    if preflight.get("changed_db") is not False or preflight.get("rows_written") != 0 or preflight.get("execution_authorized") is not False:
        raise SeoImprovementExecutionPreflightError("preflight write or authorization boundary is invalid")
    if preflight.get("preflight_id") != deterministic_preflight_id(preflight):
        raise SeoImprovementExecutionPreflightError("preflight identity is invalid")
