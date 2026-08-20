"""Pure Phase 2C SEO change-plan snapshots, without execution authority."""

from __future__ import annotations

from hashlib import sha256
import json
import re
from typing import Any, Mapping, Sequence

from seo_improvement_proposal import SeoImprovementProposalError, validate_proposal
from seo_improvement_proposal_review_workflow import (
    SeoImprovementProposalReviewError,
    latest_review_status,
    proposal_fingerprint,
    validate_review_record,
)


PLAN_INPUT_SCHEMA_VERSION = "seo-improvement-change-plan-input-v1"
PLAN_SCHEMA_VERSION = "seo-improvement-change-plan-v1"
PLAN_STATUS = "pending_review"
CHANGE_SCOPES = frozenset({"snippet", "content_refresh", "internal_link_direction"})
VERIFICATION_METRICS = ("clicks", "impressions", "ctr", "position")
_INPUT_FIELDS = frozenset({
    "schema_version", "article_id", "candidate_fingerprint", "accepted_review_id", "proposal_id",
    "proposal_fingerprint", "accepted_proposal_review_id", "change_units", "verification_plan",
})
_PLAN_FIELDS = frozenset({
    "schema_version", "plan_id", "plan_fingerprint", "article_id", "candidate_fingerprint",
    "accepted_review_id", "proposal_id", "proposal_fingerprint", "accepted_proposal_review_id",
    "plan_status", "change_units", "verification_plan", "requires_human_review",
    "article_change_authorized", "publication_authorized", "execution_authorized",
})
_SECRET_KEY = re.compile(r"(?:raw_?response|authorization|api[_ -]?key|private[_ -]?key|secret|token|binding|body|content|title|description|d1|sql)", re.IGNORECASE)
_SECRET_VALUE = re.compile(r"(?:api[_ -]?key|authorization|bearer\s+|private[_ -]?key|token)\s*[:=]", re.IGNORECASE)


class SeoImprovementChangePlanError(ValueError):
    """A SEO change-plan input or snapshot is unsafe or inconsistent."""


def canonical_json(value: Mapping[str, Any]) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as error:
        raise SeoImprovementChangePlanError("change plan cannot be canonically encoded") from error


def _reject_forbidden(value: Any) -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if not isinstance(key, str) or _SECRET_KEY.search(key):
                raise SeoImprovementChangePlanError("change plan contains prohibited data")
            _reject_forbidden(child)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for child in value:
            _reject_forbidden(child)
    elif isinstance(value, str) and _SECRET_VALUE.search(value):
        raise SeoImprovementChangePlanError("change plan contains prohibited data")


def _text(value: object, minimum: int, maximum: int) -> str:
    if not isinstance(value, str) or not minimum <= len(value.strip()) <= maximum:
        raise SeoImprovementChangePlanError("change plan text is invalid")
    return value.strip()


def _change_units(value: object) -> list[dict[str, str]]:
    if not isinstance(value, list) or not 1 <= len(value) <= 3:
        raise SeoImprovementChangePlanError("change units are invalid")
    output = []
    for item in value:
        if not isinstance(item, Mapping) or set(item) != {"scope", "rationale", "suggested_direction"} or item.get("scope") not in CHANGE_SCOPES:
            raise SeoImprovementChangePlanError("change unit is invalid")
        output.append({"scope": item["scope"], "rationale": _text(item.get("rationale"), 4, 400), "suggested_direction": _text(item.get("suggested_direction"), 4, 400)})
    _reject_forbidden(output)
    return output


def _verification_plan(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != {"metrics", "comparison"} or value.get("metrics") != list(VERIFICATION_METRICS) or value.get("comparison") != "future_fixed_period_comparison":
        raise SeoImprovementChangePlanError("verification plan is invalid")
    return {"metrics": list(VERIFICATION_METRICS), "comparison": "future_fixed_period_comparison"}


def build_change_plan_input(proposal: Mapping[str, Any], proposal_input: Mapping[str, Any], review_records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Build an input only when the latest proposal review is accepted."""
    try:
        validate_proposal(proposal, proposal_input)
        if not review_records or latest_review_status(review_records, proposal, proposal_input) != "accepted":
            raise SeoImprovementChangePlanError("latest proposal review is not accepted")
        latest = review_records[-1]
        validate_review_record(latest, proposal, proposal_input)
        fingerprint = proposal_fingerprint(proposal, proposal_input)
    except (SeoImprovementProposalError, SeoImprovementProposalReviewError) as error:
        raise SeoImprovementChangePlanError("proposal review source is invalid") from error
    return {
        "schema_version": PLAN_INPUT_SCHEMA_VERSION,
        "article_id": proposal["article_id"], "candidate_fingerprint": proposal["candidate_fingerprint"],
        "accepted_review_id": proposal["accepted_review_id"], "proposal_id": proposal["proposal_id"],
        "proposal_fingerprint": fingerprint, "accepted_proposal_review_id": latest["proposal_review_id"],
        "change_units": _change_units(proposal["proposed_changes"]),
        "verification_plan": {"metrics": list(VERIFICATION_METRICS), "comparison": "future_fixed_period_comparison"},
    }


def _validate_input(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != _INPUT_FIELDS or value.get("schema_version") != PLAN_INPUT_SCHEMA_VERSION:
        raise SeoImprovementChangePlanError("change plan input schema is invalid")
    if not isinstance(value.get("article_id"), int) or value["article_id"] < 1:
        raise SeoImprovementChangePlanError("change plan article ID is invalid")
    for field in ("candidate_fingerprint", "proposal_fingerprint"):
        if not isinstance(value.get(field), str) or len(value[field]) != 64:
            raise SeoImprovementChangePlanError("change plan fingerprint is invalid")
    for field in ("accepted_review_id", "proposal_id", "accepted_proposal_review_id"):
        _text(value.get(field), 1, 200)
    output = {key: value[key] for key in ("schema_version", "article_id", "candidate_fingerprint", "accepted_review_id", "proposal_id", "proposal_fingerprint", "accepted_proposal_review_id")}
    output["change_units"] = _change_units(value["change_units"])
    output["verification_plan"] = _verification_plan(value["verification_plan"])
    _reject_forbidden(output)
    return output


def _fingerprint_source(plan: Mapping[str, Any]) -> dict[str, Any]:
    return {key: plan[key] for key in plan if key not in {"plan_id", "plan_fingerprint"}}


def plan_fingerprint(plan: Mapping[str, Any]) -> str:
    """Return SHA-256 of the canonical plan snapshot excluding derived IDs."""
    return sha256(canonical_json(_fingerprint_source(plan)).encode("utf-8")).hexdigest()


def deterministic_plan_id(plan: Mapping[str, Any]) -> str:
    return "seo_change_plan_" + plan_fingerprint(plan)[:24]


def build_pending_change_plan(change_plan_input: Mapping[str, Any]) -> dict[str, Any]:
    safe = _validate_input(change_plan_input)
    plan = {
        "schema_version": PLAN_SCHEMA_VERSION,
        **{key: safe[key] for key in ("article_id", "candidate_fingerprint", "accepted_review_id", "proposal_id", "proposal_fingerprint", "accepted_proposal_review_id", "change_units", "verification_plan")},
        "plan_status": PLAN_STATUS, "requires_human_review": True,
        "article_change_authorized": False, "publication_authorized": False, "execution_authorized": False,
    }
    plan["plan_fingerprint"] = plan_fingerprint(plan)
    plan["plan_id"] = deterministic_plan_id(plan)
    return plan


def validate_change_plan(plan: Mapping[str, Any], change_plan_input: Mapping[str, Any]) -> None:
    safe = _validate_input(change_plan_input)
    if not isinstance(plan, Mapping) or set(plan) != _PLAN_FIELDS or plan.get("schema_version") != PLAN_SCHEMA_VERSION:
        raise SeoImprovementChangePlanError("change plan schema is invalid")
    for key in ("article_id", "candidate_fingerprint", "accepted_review_id", "proposal_id", "proposal_fingerprint", "accepted_proposal_review_id", "change_units", "verification_plan"):
        if plan.get(key) != safe[key]:
            raise SeoImprovementChangePlanError(f"change plan {key} does not match input")
    if plan.get("plan_status") != PLAN_STATUS or plan.get("requires_human_review") is not True:
        raise SeoImprovementChangePlanError("change plan review boundary is invalid")
    if any(plan.get(key) is not False for key in ("article_change_authorized", "publication_authorized", "execution_authorized")):
        raise SeoImprovementChangePlanError("change plan authorization boundary is invalid")
    _change_units(plan.get("change_units")); _verification_plan(plan.get("verification_plan")); _reject_forbidden(plan)
    if plan.get("plan_fingerprint") != plan_fingerprint(plan) or plan.get("plan_id") != deterministic_plan_id(plan):
        raise SeoImprovementChangePlanError("change plan identity is invalid")
