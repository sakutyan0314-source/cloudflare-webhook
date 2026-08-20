"""Pure, non-executable SEO change candidates derived from accepted plans."""

from __future__ import annotations

from hashlib import sha256
import json
import re
from typing import Any, Mapping, Sequence

from ai_change_plan import ChangePlanError, validate_article_snapshot
from seo_improvement_change_plan import SeoImprovementChangePlanError, validate_change_plan
from seo_improvement_change_plan_review_workflow import (
    SeoImprovementChangePlanReviewError,
    latest_review_status,
    validate_review_record,
)


CANDIDATE_INPUT_SCHEMA_VERSION = "seo-improvement-change-candidate-input-v1"
CANDIDATE_SCHEMA_VERSION = "seo-improvement-change-candidate-v1"
_INPUT_FIELDS = frozenset({"schema_version", "article_id", "accepted_review_id", "proposal_id", "proposal_fingerprint", "accepted_proposal_review_id", "plan_id", "plan_fingerprint", "accepted_plan_review_id", "before_snapshot", "proposed_changes"})
_CANDIDATE_FIELDS = frozenset({"schema_version", "candidate_id", "candidate_fingerprint", "article_id", "accepted_review_id", "proposal_id", "proposal_fingerprint", "accepted_proposal_review_id", "plan_id", "plan_fingerprint", "accepted_plan_review_id", "before_snapshot", "proposed_changes", "expected_diff", "requires_human_review", "article_change_authorized", "publication_authorized", "execution_authorized"})
_TITLE = re.compile(r"^.{12,120}$", re.DOTALL)
_DESCRIPTION = re.compile(r"^.{60,160}$", re.DOTALL)
_FORBIDDEN = re.compile(r"(?:body|content|sql|d1|publication|execution|worker|deploy|token|secret|authorization|api[_ -]?key)", re.IGNORECASE)


class SeoImprovementChangeCandidateError(ValueError):
    """Candidate source, snapshot, or proposed values are invalid."""


def canonical_json(value: Mapping[str, Any]) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as error:
        raise SeoImprovementChangeCandidateError("candidate cannot be canonically encoded") from error


def _snapshot(value: Mapping[str, Any]) -> dict[str, Any]:
    try:
        output = validate_article_snapshot(value)
    except ChangePlanError as error:
        raise SeoImprovementChangeCandidateError("article snapshot is invalid") from error
    if output["seo_status"] != "ready":
        raise SeoImprovementChangeCandidateError("article snapshot is not ready")
    return output


def _changes(value: object, snapshot: Mapping[str, Any]) -> dict[str, str]:
    if not isinstance(value, Mapping) or not value or not set(value) <= {"title", "description"}:
        raise SeoImprovementChangeCandidateError("candidate proposed changes are invalid")
    output: dict[str, str] = {}
    for field, pattern in (("title", _TITLE), ("description", _DESCRIPTION)):
        if field in value:
            item = value[field]
            if not isinstance(item, str) or not item.strip() or not pattern.fullmatch(item.strip()) or item == snapshot[field]:
                raise SeoImprovementChangeCandidateError("candidate proposed value is invalid")
            output[field] = item.strip()
    if not output:
        raise SeoImprovementChangeCandidateError("candidate proposed changes are invalid")
    return output


def build_change_candidate_input(plan: Mapping[str, Any], plan_input: Mapping[str, Any], plan_reviews: Sequence[Mapping[str, Any],], before_snapshot: Mapping[str, Any], proposed_changes: Mapping[str, Any]) -> dict[str, Any]:
    """Accept only the latest accepted snippet plan and a read-only snapshot."""
    try:
        validate_change_plan(plan, plan_input)
        if not plan_reviews or latest_review_status(plan_reviews, plan, plan_input) != "accepted":
            raise SeoImprovementChangeCandidateError("latest plan review is not accepted")
        latest = plan_reviews[-1]
        validate_review_record(latest, plan, plan_input)
    except (SeoImprovementChangePlanError, SeoImprovementChangePlanReviewError) as error:
        raise SeoImprovementChangeCandidateError("change plan review source is invalid") from error
    if {unit["scope"] for unit in plan["change_units"]} != {"snippet"}:
        raise SeoImprovementChangeCandidateError("only snippet plans can create initial candidates")
    snapshot = _snapshot(before_snapshot)
    if snapshot["article_id"] != plan["article_id"]:
        raise SeoImprovementChangeCandidateError("article snapshot does not match plan")
    return {
        "schema_version": CANDIDATE_INPUT_SCHEMA_VERSION,
        "article_id": plan["article_id"], "accepted_review_id": plan["accepted_review_id"],
        "proposal_id": plan["proposal_id"], "proposal_fingerprint": plan["proposal_fingerprint"],
        "accepted_proposal_review_id": plan["accepted_proposal_review_id"], "plan_id": plan["plan_id"],
        "plan_fingerprint": plan["plan_fingerprint"], "accepted_plan_review_id": latest["plan_review_id"],
        "before_snapshot": snapshot, "proposed_changes": _changes(proposed_changes, snapshot),
    }


def _validate_input(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != _INPUT_FIELDS or value.get("schema_version") != CANDIDATE_INPUT_SCHEMA_VERSION:
        raise SeoImprovementChangeCandidateError("candidate input schema is invalid")
    snapshot = _snapshot(value["before_snapshot"])
    if value.get("article_id") != snapshot["article_id"]:
        raise SeoImprovementChangeCandidateError("candidate input article ID is invalid")
    for field in ("accepted_review_id", "proposal_id", "accepted_proposal_review_id", "plan_id", "accepted_plan_review_id"):
        if not isinstance(value.get(field), str) or not value[field]:
            raise SeoImprovementChangeCandidateError("candidate input source identity is invalid")
    for field in ("proposal_fingerprint", "plan_fingerprint"):
        if not isinstance(value.get(field), str) or len(value[field]) != 64:
            raise SeoImprovementChangeCandidateError("candidate input fingerprint is invalid")
    return {**{key: value[key] for key in _INPUT_FIELDS if key not in {"schema_version", "before_snapshot", "proposed_changes"}}, "before_snapshot": snapshot, "proposed_changes": _changes(value["proposed_changes"], snapshot)}


def _fingerprint_source(candidate: Mapping[str, Any]) -> dict[str, Any]:
    return {key: candidate[key] for key in candidate if key not in {"candidate_id", "candidate_fingerprint"}}


def candidate_fingerprint(candidate: Mapping[str, Any]) -> str:
    return sha256(canonical_json(_fingerprint_source(candidate)).encode("utf-8")).hexdigest()


def deterministic_candidate_id(candidate: Mapping[str, Any]) -> str:
    return "seo_change_candidate_" + candidate_fingerprint(candidate)[:24]


def build_change_candidate(candidate_input: Mapping[str, Any]) -> dict[str, Any]:
    safe = _validate_input(candidate_input)
    expected = {field: {"current": safe["before_snapshot"][field], "proposed": value} for field, value in sorted(safe["proposed_changes"].items())}
    candidate = {"schema_version": CANDIDATE_SCHEMA_VERSION, **safe, "expected_diff": expected,
                 "requires_human_review": True, "article_change_authorized": False,
                 "publication_authorized": False, "execution_authorized": False}
    candidate["candidate_fingerprint"] = candidate_fingerprint(candidate)
    candidate["candidate_id"] = deterministic_candidate_id(candidate)
    return candidate


def validate_change_candidate(candidate: Mapping[str, Any], candidate_input: Mapping[str, Any], *, current_snapshot: Mapping[str, Any] | None = None) -> None:
    safe = _validate_input(candidate_input)
    if not isinstance(candidate, Mapping) or set(candidate) != _CANDIDATE_FIELDS or candidate.get("schema_version") != CANDIDATE_SCHEMA_VERSION:
        raise SeoImprovementChangeCandidateError("candidate schema is invalid")
    for key in ("article_id", "accepted_review_id", "proposal_id", "proposal_fingerprint", "accepted_proposal_review_id", "plan_id", "plan_fingerprint", "accepted_plan_review_id", "before_snapshot", "proposed_changes"):
        if candidate.get(key) != safe[key]:
            raise SeoImprovementChangeCandidateError(f"candidate {key} does not match input")
    expected = {field: {"current": safe["before_snapshot"][field], "proposed": value} for field, value in sorted(safe["proposed_changes"].items())}
    if candidate.get("expected_diff") != expected or candidate.get("requires_human_review") is not True or any(candidate.get(key) is not False for key in ("article_change_authorized", "publication_authorized", "execution_authorized")):
        raise SeoImprovementChangeCandidateError("candidate review or authorization boundary is invalid")
    if candidate.get("candidate_fingerprint") != candidate_fingerprint(candidate) or candidate.get("candidate_id") != deterministic_candidate_id(candidate):
        raise SeoImprovementChangeCandidateError("candidate identity is invalid")
    if current_snapshot is not None and _snapshot(current_snapshot) != safe["before_snapshot"]:
        raise SeoImprovementChangeCandidateError("stale candidate snapshot")
