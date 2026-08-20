"""Pure execution-attempt, post-verification, and rollback-candidate schemas."""

from __future__ import annotations

from datetime import datetime
from hashlib import sha256
import json
from typing import Any, Mapping, Sequence

from ai_change_plan import ChangePlanError, validate_article_snapshot
from seo_improvement_execution_approval import SeoImprovementExecutionApprovalError
from seo_improvement_execution_candidate import (
    SeoImprovementExecutionCandidateError,
    canonical_json as candidate_canonical_json,
)
from seo_improvement_execution_preflight import (
    SeoImprovementExecutionPreflightError,
    snapshot_fingerprint,
    validate_execution_preflight,
)


ATTEMPT_SCHEMA_VERSION = "seo-improvement-execution-attempt-v1"
POST_VERIFICATION_SCHEMA_VERSION = "seo-improvement-execution-post-verification-v1"
ROLLBACK_CANDIDATE_SCHEMA_VERSION = "seo-improvement-execution-rollback-candidate-v1"
ATTEMPT_STATES = frozenset({"planned", "preflight_verified", "approval_reserved", "update_started", "outcome_known_success", "outcome_known_failure", "outcome_unknown"})
_TRANSITIONS = {
    "planned": frozenset({"preflight_verified"}),
    "preflight_verified": frozenset({"approval_reserved"}),
    "approval_reserved": frozenset({"update_started"}),
    "update_started": frozenset({"outcome_known_success", "outcome_known_failure", "outcome_unknown"}),
    "outcome_known_success": frozenset(), "outcome_known_failure": frozenset(), "outcome_unknown": frozenset(),
}
_CLASSIFICATIONS = frozenset({"not_started", "preflight_verified", "approval_reserved", "update_started", "success", "known_failure", "outcome_unknown"})
_STATE_CLASSIFICATION = {
    "planned": "not_started", "preflight_verified": "preflight_verified",
    "approval_reserved": "approval_reserved", "update_started": "update_started",
    "outcome_known_success": "success", "outcome_known_failure": "known_failure",
    "outcome_unknown": "outcome_unknown",
}
_SOURCE_FIELDS = (
    "execution_approval_id", "preflight_id", "execution_candidate_id",
    "execution_candidate_fingerprint", "candidate_id", "candidate_fingerprint",
    "proposal_id", "proposal_fingerprint", "plan_id", "plan_fingerprint", "article_id",
)
_ATTEMPT_FIELDS = frozenset({
    "schema_version", "execution_attempt_id", *_SOURCE_FIELDS,
    "before_snapshot_fingerprint", "after_snapshot_fingerprint", "expected_diff",
    "state", "classification", "started_at", "completed_at", "changed_db", "changes",
    "returned_article_id", "execution_authorized", "publication_authorized",
})
_VERIFICATION_FIELDS = frozenset({
    "schema_version", "post_verification_id", "execution_attempt_id", "article_id",
    "after_snapshot_fingerprint", "observed_snapshot_fingerprint", "expected_diff",
    "title_description_match", "forbidden_fields_unchanged", "content_hash_unchanged",
    "body_markdown_hash_unchanged", "classification",
})
_ROLLBACK_FIELDS = frozenset({
    "schema_version", "rollback_candidate_id", "execution_attempt_id", "article_id",
    "before_snapshot_fingerprint", "after_snapshot_fingerprint", "rollback_expected_diff",
    "rollback_authorized", "requires_separate_human_approval",
})


class SeoImprovementExecutionAttemptError(ValueError):
    """Attempt, verification, or rollback data crossed an execution boundary."""


def _time(value: object, name: str, *, allow_none: bool = False) -> str | None:
    if value is None and allow_none:
        return None
    if not isinstance(value, str):
        raise SeoImprovementExecutionAttemptError(name + " is invalid")
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise SeoImprovementExecutionAttemptError(name + " is invalid") from error
    return value


def _snapshot(value: Mapping[str, Any]) -> dict[str, Any]:
    try:
        return validate_article_snapshot(value)
    except ChangePlanError as error:
        raise SeoImprovementExecutionAttemptError("execution snapshot is invalid") from error


def _source(preflight: Mapping[str, Any], execution_candidate: Mapping[str, Any]) -> dict[str, Any]:
    return {
        **{field: preflight[field] for field in _SOURCE_FIELDS if field != "article_id"},
        "article_id": execution_candidate["article_id"],
    }


def _attempt_id_source(attempt: Mapping[str, Any]) -> dict[str, Any]:
    return {field: attempt[field] for field in (*_SOURCE_FIELDS, "started_at")}


def deterministic_execution_attempt_id(attempt: Mapping[str, Any]) -> str:
    return "seo_execution_attempt_" + sha256(candidate_canonical_json(_attempt_id_source(attempt)).encode("utf-8")).hexdigest()[:24]


def validate_attempt_transition(current: object, target: object) -> None:
    if current not in ATTEMPT_STATES or target not in ATTEMPT_STATES or target not in _TRANSITIONS[current]:
        raise SeoImprovementExecutionAttemptError("execution attempt transition is invalid")


def _validate_result(state: str, facts: Mapping[str, Any], article_id: Any) -> dict[str, Any]:
    changed, changes, returned = facts.get("changed_db"), facts.get("changes"), facts.get("returned_article_id")
    if state == "outcome_known_success":
        if changed is not True or changes != 1 or returned != article_id:
            raise SeoImprovementExecutionAttemptError("successful execution result is invalid")
    elif state == "outcome_unknown":
        if changed is not None or changes is not None or returned is not None:
            raise SeoImprovementExecutionAttemptError("unknown execution result is invalid")
    elif changed is not False or changes != 0 or returned is not None:
        raise SeoImprovementExecutionAttemptError("non-successful execution result is invalid")
    return {"changed_db": changed, "changes": changes, "returned_article_id": returned}


def build_execution_attempt(
    preflight: Mapping[str, Any], approval: Mapping[str, Any], execution_candidate: Mapping[str, Any],
    execution_candidate_input: Mapping[str, Any], latest_snapshot: Mapping[str, Any], facts: Mapping[str, Any],
    *, now: str, used_approval_ids: Sequence[str] = (),
) -> dict[str, Any]:
    """Build an immutable attempt fact record; no transaction or update occurs."""
    try:
        validate_execution_preflight(preflight, approval, execution_candidate, execution_candidate_input, latest_snapshot, now=now, used_approval_ids=used_approval_ids)
    except (SeoImprovementExecutionPreflightError, SeoImprovementExecutionApprovalError, SeoImprovementExecutionCandidateError) as error:
        raise SeoImprovementExecutionAttemptError("execution preflight handoff is invalid") from error
    if not isinstance(facts, Mapping):
        raise SeoImprovementExecutionAttemptError("execution attempt facts are invalid")
    state = facts.get("state")
    if state not in ATTEMPT_STATES or facts.get("classification") != _STATE_CLASSIFICATION[state]:
        raise SeoImprovementExecutionAttemptError("execution attempt state or classification is invalid")
    started = _time(facts.get("started_at"), "started_at")
    completed = _time(facts.get("completed_at"), "completed_at", allow_none=True)
    if state.startswith("outcome_") != (completed is not None):
        raise SeoImprovementExecutionAttemptError("execution attempt completion time is invalid")
    result = _validate_result(state, facts, execution_candidate["article_id"])
    attempt = {
        "schema_version": ATTEMPT_SCHEMA_VERSION, **_source(preflight, execution_candidate),
        "before_snapshot_fingerprint": preflight["before_snapshot_fingerprint"],
        "after_snapshot_fingerprint": preflight["after_snapshot_fingerprint"],
        "expected_diff": preflight["expected_diff"], "state": state,
        "classification": facts["classification"], "started_at": started, "completed_at": completed,
        **result, "execution_authorized": False, "publication_authorized": False,
    }
    attempt["execution_attempt_id"] = deterministic_execution_attempt_id(attempt)
    return attempt


def validate_execution_attempt(
    attempt: Mapping[str, Any], preflight: Mapping[str, Any], approval: Mapping[str, Any],
    execution_candidate: Mapping[str, Any], execution_candidate_input: Mapping[str, Any],
    latest_snapshot: Mapping[str, Any], *, now: str, used_approval_ids: Sequence[str] = (),
) -> None:
    expected = build_execution_attempt(preflight, approval, execution_candidate, execution_candidate_input, latest_snapshot, {
        key: attempt.get(key) for key in ("state", "classification", "started_at", "completed_at", "changed_db", "changes", "returned_article_id")
    }, now=now, used_approval_ids=used_approval_ids)
    if not isinstance(attempt, Mapping) or set(attempt) != _ATTEMPT_FIELDS or attempt != expected:
        raise SeoImprovementExecutionAttemptError("execution attempt schema or identity is invalid")


def _verification_id(value: Mapping[str, Any]) -> str:
    source = {field: value[field] for field in _VERIFICATION_FIELDS if field != "post_verification_id"}
    return "seo_execution_post_verify_" + sha256(candidate_canonical_json(source).encode("utf-8")).hexdigest()[:24]


def build_post_verification(attempt: Mapping[str, Any], execution_candidate: Mapping[str, Any], observed_snapshot: Mapping[str, Any]) -> dict[str, Any]:
    """Build a read-only verification schema for a reported successful attempt."""
    if not isinstance(attempt, Mapping) or attempt.get("state") != "outcome_known_success":
        raise SeoImprovementExecutionAttemptError("post verification requires a successful attempt")
    observed, after, before = _snapshot(observed_snapshot), _snapshot(execution_candidate["after_snapshot"]), _snapshot(execution_candidate["before_snapshot"])
    if observed["article_id"] != attempt.get("article_id") or attempt.get("expected_diff") != execution_candidate.get("expected_diff"):
        raise SeoImprovementExecutionAttemptError("post verification source is invalid")
    fields = set(execution_candidate["expected_diff"])
    verification = {
        "schema_version": POST_VERIFICATION_SCHEMA_VERSION, "execution_attempt_id": attempt["execution_attempt_id"],
        "article_id": attempt["article_id"], "after_snapshot_fingerprint": snapshot_fingerprint(after),
        "observed_snapshot_fingerprint": snapshot_fingerprint(observed), "expected_diff": execution_candidate["expected_diff"],
        "title_description_match": all(observed[field] == after[field] for field in fields),
        "forbidden_fields_unchanged": all(observed[field] == before[field] for field in (set(before) - {"title", "description"})),
        "content_hash_unchanged": observed["content_sha256"] == before["content_sha256"],
        "body_markdown_hash_unchanged": observed["body_markdown_sha256"] == before["body_markdown_sha256"],
        "classification": "pass" if observed == after else "fail",
    }
    verification["post_verification_id"] = _verification_id(verification)
    return verification


def validate_post_verification(verification: Mapping[str, Any], attempt: Mapping[str, Any], execution_candidate: Mapping[str, Any], observed_snapshot: Mapping[str, Any]) -> None:
    expected = build_post_verification(attempt, execution_candidate, observed_snapshot)
    if not isinstance(verification, Mapping) or set(verification) != _VERIFICATION_FIELDS or verification != expected:
        raise SeoImprovementExecutionAttemptError("post verification schema is invalid")


def build_rollback_candidate(attempt: Mapping[str, Any], execution_candidate: Mapping[str, Any], verification: Mapping[str, Any]) -> dict[str, Any]:
    """Describe, but never perform, a separately-approved rollback."""
    validate_post_verification(verification, attempt, execution_candidate, execution_candidate["after_snapshot"])
    if verification["classification"] != "pass":
        raise SeoImprovementExecutionAttemptError("rollback requires verified after snapshot")
    rollback = {
        "schema_version": ROLLBACK_CANDIDATE_SCHEMA_VERSION, "execution_attempt_id": attempt["execution_attempt_id"],
        "article_id": attempt["article_id"], "before_snapshot_fingerprint": snapshot_fingerprint(execution_candidate["before_snapshot"]),
        "after_snapshot_fingerprint": snapshot_fingerprint(execution_candidate["after_snapshot"]),
        "rollback_expected_diff": {field: {"current": change["proposed"], "proposed": change["current"]} for field, change in execution_candidate["expected_diff"].items()},
        "rollback_authorized": False, "requires_separate_human_approval": True,
    }
    rollback["rollback_candidate_id"] = "seo_execution_rollback_" + sha256(candidate_canonical_json({field: rollback[field] for field in _ROLLBACK_FIELDS if field != "rollback_candidate_id"}).encode("utf-8")).hexdigest()[:24]
    return rollback
