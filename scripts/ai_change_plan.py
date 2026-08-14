"""Local-only v2.0-C change-plan construction and review.

The module accepts only a v2.0-B eligible human approval plus its verified
recommendation envelope.  It creates a deterministic, reviewable plan and
never writes D1, changes an article, calls a model, or authorizes execution.
"""

from __future__ import annotations

from hashlib import sha256
import json
import re
from typing import Any, Dict, Mapping, Sequence

from ai_recommendation_review_workflow import (
    REVIEW_DECISION_SCHEMA_VERSION,
    ReviewWorkflowError,
    canonical_review_envelope,
    recommendation_fingerprint,
)


PLAN_SCHEMA_VERSION = "v2.0-c-change-plan-v1"
PLAN_REVIEW_SCHEMA_VERSION = "v2.0-c-plan-review-v1"
PLAN_TYPES = frozenset({
    "improve_title", "improve_description", "improve_ctr", "improve_content",
    "refresh_content", "improve_internal_links", "improve_affiliate_category",
    "improve_affiliate_cta", "continue_observation", "insufficient_data",
})
PLAN_REVIEW_DECISIONS = frozenset({"approve", "reject", "hold"})
PLAN_RUBRIC_FIELDS = (
    "recommendation_alignment",
    "evidence_current_state_alignment",
    "scope_safety",
    "specificity_actionability",
    "rollback_stale_verifiability",
)
SNAPSHOT_FIELDS = (
    "article_id", "title", "description", "category", "content_sha256",
    "body_markdown_sha256", "published_at", "updated_at", "seo_status",
)
PROHIBITED_CHANGE_FIELDS = frozenset({
    "id", "article_id", "content", "body_markdown", "seo_status", "published_at",
    "updated_at", "public_state", "publication", "d1", "worker", "cron", "pipeline",
    "discord", "amazon_url", "amazon_tag", "deployment", "execution_authorized",
})
_SECRET_KEY = re.compile(r"(?:raw_?response|authorization|api[_ -]?key|private[_ -]?key|secret|token)", re.IGNORECASE)
_SECRET_VALUE = re.compile(r"(?:api[_ -]?key|authorization|bearer\s+|private[_ -]?key|token)\s*[:=]", re.IGNORECASE)
_SHA256 = re.compile(r"^[a-f0-9]{64}$")


class ChangePlanError(ValueError):
    """A change-plan input, plan, or local review violates a safety boundary."""


def _canonical_json(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as error:
        raise ChangePlanError("canonical JSON is invalid") from error


def _reject_sensitive(value: Any) -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if not isinstance(key, str) or _SECRET_KEY.search(key):
                raise ChangePlanError("plan contains prohibited sensitive data")
            _reject_sensitive(child)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for child in value:
            _reject_sensitive(child)
    elif isinstance(value, str) and _SECRET_VALUE.search(value):
        raise ChangePlanError("plan contains prohibited sensitive data")


def validate_article_snapshot(snapshot: Mapping[str, Any]) -> Dict[str, Any]:
    """Validate the exact stale-check snapshot; article bodies are never read."""
    if not isinstance(snapshot, Mapping) or set(snapshot) != set(SNAPSHOT_FIELDS):
        raise ChangePlanError("article snapshot fields are invalid")
    if not isinstance(snapshot["article_id"], int) or snapshot["article_id"] < 1:
        raise ChangePlanError("article snapshot ID is invalid")
    for key in ("title", "description", "category", "published_at", "updated_at", "seo_status"):
        if not isinstance(snapshot[key], str) or not snapshot[key].strip():
            raise ChangePlanError("article snapshot metadata is invalid")
    for key in ("content_sha256", "body_markdown_sha256"):
        if not isinstance(snapshot[key], str) or not _SHA256.fullmatch(snapshot[key]):
            raise ChangePlanError("article snapshot SHA-256 is invalid")
    _reject_sensitive(snapshot)
    return {key: snapshot[key] for key in SNAPSHOT_FIELDS}


def validate_review_decision(decision: Mapping[str, Any], envelope: Mapping[str, Any]) -> Dict[str, Any]:
    """Only an eligible v2.0-B approve can begin plan construction."""
    safe_envelope = canonical_review_envelope(envelope)
    required = {
        "schema_version", "recommendation_id", "recommendation_fingerprint", "review_id",
        "decision", "rubric", "total_score", "approval_eligible", "reviewed_at",
        "review_version", "handoff_scope", "execution_authorized",
    }
    if not isinstance(decision, Mapping) or set(decision) != required:
        raise ChangePlanError("review decision fields are invalid")
    if decision.get("schema_version") != REVIEW_DECISION_SCHEMA_VERSION:
        raise ChangePlanError("review decision schema is invalid")
    if decision.get("decision") != "approve" or decision.get("approval_eligible") is not True:
        raise ChangePlanError("review decision is not eligible for plan construction")
    if decision.get("handoff_scope") != "v2_0_c_change_plan_only" or decision.get("execution_authorized") is not False:
        raise ChangePlanError("review decision has an unsafe execution scope")
    if decision.get("recommendation_id") != safe_envelope["recommendation_id"]:
        raise ChangePlanError("review decision recommendation ID does not match")
    if decision.get("recommendation_fingerprint") != recommendation_fingerprint(safe_envelope):
        raise ChangePlanError("review decision recommendation fingerprint does not match")
    if not isinstance(decision.get("review_id"), str) or not decision["review_id"]:
        raise ChangePlanError("review decision review ID is invalid")
    if not isinstance(decision.get("review_version"), int) or decision["review_version"] < 1:
        raise ChangePlanError("review decision review version is invalid")
    _reject_sensitive(decision)
    return dict(decision)


def _valid_text(value: object, minimum: int, maximum: int) -> bool:
    return isinstance(value, str) and minimum <= len(value.strip()) <= maximum


def _validate_proposed_changes(plan_type: str, changes: Mapping[str, Any], snapshot: Mapping[str, Any], evidence_fields: set[str]) -> Dict[str, Any]:
    if plan_type not in PLAN_TYPES or not isinstance(changes, Mapping) or not changes:
        raise ChangePlanError("plan type or proposed changes are invalid")
    if set(changes) & PROHIBITED_CHANGE_FIELDS:
        raise ChangePlanError("plan changes contain a prohibited field")
    _reject_sensitive(changes)
    if plan_type == "improve_title":
        if set(changes) != {"title"} or not _valid_text(changes["title"], 12, 120):
            raise ChangePlanError("title plan is invalid")
    elif plan_type == "improve_description":
        if set(changes) != {"description"} or not _valid_text(changes["description"], 60, 160):
            raise ChangePlanError("description plan is invalid")
    elif plan_type == "improve_ctr":
        if not set(changes) <= {"title", "description"}:
            raise ChangePlanError("CTR plan scope is invalid")
        if "title" in changes and not _valid_text(changes["title"], 12, 120):
            raise ChangePlanError("CTR title is invalid")
        if "description" in changes and not _valid_text(changes["description"], 60, 160):
            raise ChangePlanError("CTR description is invalid")
    elif plan_type == "improve_internal_links":
        links = changes.get("internal_links")
        if set(changes) != {"internal_links"} or not isinstance(links, list) or not links:
            raise ChangePlanError("internal-link plan is invalid")
        for link in links:
            if not isinstance(link, Mapping) or set(link) != {"source_heading", "target_article_id", "anchor_text"}:
                raise ChangePlanError("internal-link change is invalid")
            if not _valid_text(link["source_heading"], 1, 160) or not _valid_text(link["anchor_text"], 2, 160):
                raise ChangePlanError("internal-link text is invalid")
            if not isinstance(link["target_article_id"], int) or link["target_article_id"] < 1:
                raise ChangePlanError("internal-link target is invalid")
    elif plan_type == "improve_affiliate_category":
        if set(changes) != {"affiliate_category"} or changes["affiliate_category"] not in {
            "ai-automation", "saas-cloud", "security-governance", "engineering-infrastructure", "dx-organization", "marketing-cx", "uncategorized",
        }:
            raise ChangePlanError("affiliate-category plan is invalid")
    elif plan_type == "improve_affiliate_cta":
        if set(changes) != {"affiliate_cta"} or not _valid_text(changes["affiliate_cta"], 2, 240):
            raise ChangePlanError("affiliate CTA plan is invalid")
    elif plan_type in {"improve_content", "refresh_content"}:
        scope = changes.get("content_revision_scope")
        if set(changes) != {"content_revision_scope"} or not isinstance(scope, Mapping) or set(scope) != {"target_h2", "revision_policy"}:
            raise ChangePlanError("content plan scope is invalid")
        if not _valid_text(scope["target_h2"], 1, 160) or not _valid_text(scope["revision_policy"], 8, 400):
            raise ChangePlanError("content plan details are invalid")
    else:  # observation-only plan types
        if set(changes) != {"observation_action"} or changes["observation_action"] != "continue_observation_no_change":
            raise ChangePlanError("observation plan must not propose a change")
    if not evidence_fields:
        raise ChangePlanError("plan requires verified evidence references")
    return {key: changes[key] for key in sorted(changes)}


def _current_values_for_changes(changes: Mapping[str, Any], snapshot: Mapping[str, Any]) -> Dict[str, Any]:
    values: Dict[str, Any] = {}
    for key in changes:
        if key in {"title", "description", "category"}:
            values[key] = snapshot[key]
        elif key == "affiliate_category":
            values[key] = None
        elif key == "affiliate_cta":
            values[key] = None
        elif key == "internal_links":
            values[key] = []
        elif key == "content_revision_scope":
            values[key] = {"content_sha256": snapshot["content_sha256"], "body_markdown_sha256": snapshot["body_markdown_sha256"]}
        elif key == "observation_action":
            values[key] = "no_change"
    return values


def _value_fingerprint(value: Any) -> str:
    return sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def build_change_plan(
    envelope: Mapping[str, Any], review_decision: Mapping[str, Any], article_snapshot: Mapping[str, Any],
    *, plan_type: str, proposed_changes: Mapping[str, Any], evidence_references: Sequence[str],
) -> Dict[str, Any]:
    """Build a deterministic pending plan; it is not an implementation command."""
    safe_envelope = canonical_review_envelope(envelope)
    decision = validate_review_decision(review_decision, safe_envelope)
    snapshot = validate_article_snapshot(article_snapshot)
    if snapshot["article_id"] != safe_envelope["article_id"]:
        raise ChangePlanError("article snapshot does not match recommendation")
    if plan_type != safe_envelope["recommendation_type"]:
        raise ChangePlanError("plan type does not match recommendation")
    allowed_evidence = {item["field"] for item in safe_envelope["evidence"] if isinstance(item, Mapping) and isinstance(item.get("field"), str)}
    references = list(evidence_references)
    if not references or any(not isinstance(field, str) or field not in allowed_evidence for field in references) or len(set(references)) != len(references):
        raise ChangePlanError("plan evidence references are invalid")
    changes = _validate_proposed_changes(plan_type, proposed_changes, snapshot, set(references))
    current_values = _current_values_for_changes(changes, snapshot)
    stale_check = {
        "snapshot": snapshot,
        "recommendation_fingerprint": decision["recommendation_fingerprint"],
        "target_current_value_fingerprints": {key: _value_fingerprint(value) for key, value in current_values.items()},
    }
    source = {
        "plan_schema_version": PLAN_SCHEMA_VERSION,
        "article_id": snapshot["article_id"], "recommendation_id": decision["recommendation_id"],
        "recommendation_fingerprint": decision["recommendation_fingerprint"], "review_id": decision["review_id"],
        "review_version": decision["review_version"], "plan_type": plan_type,
        "current_state_snapshot": snapshot, "proposed_changes": changes,
        "evidence_references": sorted(references),
        "prohibited_changes": sorted(PROHIBITED_CHANGE_FIELDS), "stale_check": stale_check,
    }
    plan_id = "plan_v2c_" + sha256(_canonical_json(source).encode("utf-8")).hexdigest()[:24]
    return {
        **source, "plan_id": plan_id, "plan_status": "pending_human_plan_review",
        "execution_authorized": False,
    }


def assert_plan_not_stale(plan: Mapping[str, Any], current_article_snapshot: Mapping[str, Any]) -> None:
    """Reject rather than regenerate if an important planned value changed."""
    if not isinstance(plan, Mapping) or plan.get("plan_schema_version") != PLAN_SCHEMA_VERSION:
        raise ChangePlanError("plan schema is invalid")
    current = validate_article_snapshot(current_article_snapshot)
    stale_check = plan.get("stale_check")
    if not isinstance(stale_check, Mapping) or stale_check.get("snapshot") != current:
        raise ChangePlanError("stale_plan_article_snapshot_changed")
    for key, expected in stale_check.get("target_current_value_fingerprints", {}).items():
        actual_values = _current_values_for_changes({key: plan["proposed_changes"][key]}, current)
        if _value_fingerprint(actual_values[key]) != expected:
            raise ChangePlanError("stale_plan_target_value_changed")


def assess_plan_rubric(rubric: Mapping[str, Any]) -> Dict[str, Any]:
    if not isinstance(rubric, Mapping) or set(rubric) != set(PLAN_RUBRIC_FIELDS):
        raise ChangePlanError("plan rubric fields are invalid")
    normalized: Dict[str, int] = {}
    for field in PLAN_RUBRIC_FIELDS:
        value = rubric[field]
        if not isinstance(value, int) or isinstance(value, bool) or value not in (0, 1, 2):
            raise ChangePlanError("plan rubric score is invalid")
        normalized[field] = value
    total = sum(normalized.values())
    eligible = normalized["evidence_current_state_alignment"] == 2 and normalized["scope_safety"] == 2 and total >= 8
    return {"rubric": normalized, "total_score": total, "approval_eligible": eligible}


def build_plan_review_decision(plan: Mapping[str, Any], *, decision: str, rubric: Mapping[str, Any]) -> Dict[str, Any]:
    """Local plan review only; approval submits to a future execution gate."""
    if not isinstance(plan, Mapping) or plan.get("plan_status") != "pending_human_plan_review" or plan.get("execution_authorized") is not False:
        raise ChangePlanError("plan is not pending review-only work")
    if decision not in PLAN_REVIEW_DECISIONS:
        raise ChangePlanError("plan review decision is invalid")
    result = assess_plan_rubric(rubric)
    if decision == "approve" and not result["approval_eligible"]:
        raise ChangePlanError("plan approve requires the fixed rubric threshold")
    return {
        "schema_version": PLAN_REVIEW_SCHEMA_VERSION, "plan_id": plan["plan_id"],
        "decision": decision, **result,
        "handoff_scope": "future_execution_approval_required",
        "execution_authorized": False,
    }
