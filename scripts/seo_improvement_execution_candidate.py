"""Pure, non-executable SEO execution-candidate snapshots.

This module deliberately stops before Execution Approval or any article/D1
operation.  It turns only the latest accepted Change Candidate review into an
immutable title/description snapshot that a later, separately approved stage
may inspect.
"""

from __future__ import annotations

from hashlib import sha256
import json
from typing import Any, Mapping, Sequence

from ai_change_plan import ChangePlanError, validate_article_snapshot
from seo_improvement_change_candidate import (
    SeoImprovementChangeCandidateError,
    validate_change_candidate,
)
from seo_improvement_change_candidate_review_workflow import (
    SeoImprovementChangeCandidateReviewError,
    latest_review_status,
    validate_review_record,
)


EXECUTION_CANDIDATE_INPUT_SCHEMA_VERSION = "seo-improvement-execution-candidate-input-v1"
EXECUTION_CANDIDATE_SCHEMA_VERSION = "seo-improvement-execution-candidate-v1"
_SOURCE_FIELDS = (
    "candidate_id", "candidate_fingerprint", "accepted_candidate_review_id",
    "article_id", "accepted_review_id", "proposal_id", "proposal_fingerprint",
    "accepted_proposal_review_id", "plan_id", "plan_fingerprint",
    "accepted_plan_review_id",
)
_INPUT_FIELDS = frozenset({"schema_version", *_SOURCE_FIELDS, "before_snapshot", "proposed_changes"})
_CANDIDATE_FIELDS = frozenset({
    "schema_version", "execution_candidate_id", "execution_candidate_fingerprint",
    *_SOURCE_FIELDS, "before_snapshot", "after_snapshot", "expected_diff",
    "article_change_authorized", "publication_authorized", "execution_authorized",
})
_ALLOWLIST = frozenset({"title", "description"})


class SeoImprovementExecutionCandidateError(ValueError):
    """Execution-candidate input or its immutable snapshot is invalid."""


def canonical_json(value: Mapping[str, Any]) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as error:
        raise SeoImprovementExecutionCandidateError("execution candidate cannot be canonically encoded") from error


def _snapshot(value: Mapping[str, Any]) -> dict[str, Any]:
    try:
        snapshot = validate_article_snapshot(value)
    except ChangePlanError as error:
        raise SeoImprovementExecutionCandidateError("execution candidate snapshot is invalid") from error
    if snapshot["seo_status"] != "ready":
        raise SeoImprovementExecutionCandidateError("execution candidate snapshot is not ready")
    return snapshot


def _changes(value: object, snapshot: Mapping[str, Any]) -> dict[str, str]:
    if not isinstance(value, Mapping) or not value or not set(value) <= _ALLOWLIST:
        raise SeoImprovementExecutionCandidateError("execution candidate changes are invalid")
    output: dict[str, str] = {}
    for field in sorted(_ALLOWLIST):
        if field in value:
            proposed = value[field]
            if not isinstance(proposed, str) or not proposed.strip() or proposed != proposed.strip() or proposed == snapshot[field]:
                raise SeoImprovementExecutionCandidateError("execution candidate proposed value is invalid")
            output[field] = proposed
    if not output:
        raise SeoImprovementExecutionCandidateError("execution candidate changes are invalid")
    return output


def build_execution_candidate_input(
    candidate: Mapping[str, Any],
    candidate_input: Mapping[str, Any],
    candidate_reviews: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Accept only a latest-accepted Candidate review and its exact snapshot."""
    try:
        validate_change_candidate(candidate, candidate_input)
        if not candidate_reviews or latest_review_status(candidate_reviews, candidate, candidate_input) != "accepted":
            raise SeoImprovementExecutionCandidateError("latest candidate review is not accepted")
        latest = candidate_reviews[-1]
        validate_review_record(latest, candidate, candidate_input)
    except (SeoImprovementChangeCandidateError, SeoImprovementChangeCandidateReviewError) as error:
        raise SeoImprovementExecutionCandidateError("change candidate review source is invalid") from error
    return {
        "schema_version": EXECUTION_CANDIDATE_INPUT_SCHEMA_VERSION,
        "candidate_id": candidate["candidate_id"],
        "candidate_fingerprint": candidate["candidate_fingerprint"],
        "accepted_candidate_review_id": latest["candidate_review_id"],
        "article_id": candidate["article_id"],
        "accepted_review_id": candidate["accepted_review_id"],
        "proposal_id": candidate["proposal_id"],
        "proposal_fingerprint": candidate["proposal_fingerprint"],
        "accepted_proposal_review_id": candidate["accepted_proposal_review_id"],
        "plan_id": candidate["plan_id"],
        "plan_fingerprint": candidate["plan_fingerprint"],
        "accepted_plan_review_id": candidate["accepted_plan_review_id"],
        "before_snapshot": _snapshot(candidate["before_snapshot"]),
        "proposed_changes": _changes(candidate["proposed_changes"], candidate["before_snapshot"]),
    }


def _validate_input(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != _INPUT_FIELDS or value.get("schema_version") != EXECUTION_CANDIDATE_INPUT_SCHEMA_VERSION:
        raise SeoImprovementExecutionCandidateError("execution candidate input schema is invalid")
    snapshot = _snapshot(value.get("before_snapshot"))
    if value.get("article_id") != snapshot["article_id"]:
        raise SeoImprovementExecutionCandidateError("execution candidate input article ID is invalid")
    for field in ("candidate_id", "accepted_candidate_review_id", "accepted_review_id", "proposal_id", "accepted_proposal_review_id", "plan_id", "accepted_plan_review_id"):
        if not isinstance(value.get(field), str) or not value[field]:
            raise SeoImprovementExecutionCandidateError("execution candidate source identity is invalid")
    for field in ("candidate_fingerprint", "proposal_fingerprint", "plan_fingerprint"):
        if not isinstance(value.get(field), str) or len(value[field]) != 64:
            raise SeoImprovementExecutionCandidateError("execution candidate source fingerprint is invalid")
    return {
        **{field: value[field] for field in _SOURCE_FIELDS},
        "before_snapshot": snapshot,
        "proposed_changes": _changes(value["proposed_changes"], snapshot),
    }


def _after_snapshot(before_snapshot: Mapping[str, Any], changes: Mapping[str, str]) -> dict[str, Any]:
    return {**before_snapshot, **changes}


def _expected_diff(before_snapshot: Mapping[str, Any], changes: Mapping[str, str]) -> dict[str, dict[str, str]]:
    return {field: {"current": before_snapshot[field], "proposed": changes[field]} for field in sorted(changes)}


def _fingerprint_source(candidate: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: candidate[key]
        for key in candidate
        if key not in {"execution_candidate_id", "execution_candidate_fingerprint"}
    }


def execution_candidate_fingerprint(candidate: Mapping[str, Any]) -> str:
    return sha256(canonical_json(_fingerprint_source(candidate)).encode("utf-8")).hexdigest()


def deterministic_execution_candidate_id(candidate: Mapping[str, Any]) -> str:
    return "seo_execution_candidate_" + execution_candidate_fingerprint(candidate)[:24]


def build_execution_candidate(candidate_input: Mapping[str, Any]) -> dict[str, Any]:
    """Build a fixed, non-authorizing execution snapshot from safe input."""
    safe = _validate_input(candidate_input)
    candidate = {
        "schema_version": EXECUTION_CANDIDATE_SCHEMA_VERSION,
        **{field: safe[field] for field in _SOURCE_FIELDS},
        "before_snapshot": safe["before_snapshot"],
        "after_snapshot": _after_snapshot(safe["before_snapshot"], safe["proposed_changes"]),
        "expected_diff": _expected_diff(safe["before_snapshot"], safe["proposed_changes"]),
        "article_change_authorized": False,
        "publication_authorized": False,
        "execution_authorized": False,
    }
    candidate["execution_candidate_fingerprint"] = execution_candidate_fingerprint(candidate)
    candidate["execution_candidate_id"] = deterministic_execution_candidate_id(candidate)
    return candidate


def validate_execution_candidate(
    candidate: Mapping[str, Any],
    candidate_input: Mapping[str, Any],
    *,
    current_snapshot: Mapping[str, Any] | None = None,
) -> None:
    """Validate identity, fixed scope, and optionally an exact stale check."""
    safe = _validate_input(candidate_input)
    if not isinstance(candidate, Mapping) or set(candidate) != _CANDIDATE_FIELDS or candidate.get("schema_version") != EXECUTION_CANDIDATE_SCHEMA_VERSION:
        raise SeoImprovementExecutionCandidateError("execution candidate schema is invalid")
    for field in _SOURCE_FIELDS:
        if candidate.get(field) != safe[field]:
            raise SeoImprovementExecutionCandidateError(f"execution candidate {field} does not match input")
    expected_after = _after_snapshot(safe["before_snapshot"], safe["proposed_changes"])
    expected_diff = _expected_diff(safe["before_snapshot"], safe["proposed_changes"])
    if candidate.get("before_snapshot") != safe["before_snapshot"] or candidate.get("after_snapshot") != expected_after or candidate.get("expected_diff") != expected_diff:
        raise SeoImprovementExecutionCandidateError("execution candidate snapshot or diff is invalid")
    if any(candidate.get(field) is not False for field in ("article_change_authorized", "publication_authorized", "execution_authorized")):
        raise SeoImprovementExecutionCandidateError("execution candidate authorization boundary is invalid")
    if candidate.get("execution_candidate_fingerprint") != execution_candidate_fingerprint(candidate) or candidate.get("execution_candidate_id") != deterministic_execution_candidate_id(candidate):
        raise SeoImprovementExecutionCandidateError("execution candidate identity is invalid")
    if current_snapshot is not None and _snapshot(current_snapshot) != safe["before_snapshot"]:
        raise SeoImprovementExecutionCandidateError("stale execution candidate snapshot")
