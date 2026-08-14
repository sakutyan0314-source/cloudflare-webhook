"""Human-review envelope and deterministic rubric for v2.0-A.

Only a validated, server-reconstructed recommendation can enter this module.
It has no model, D1, file, or persistence dependency.
"""

from __future__ import annotations

from typing import Any, Mapping


REVIEW_SCHEMA_VERSION = "v2.0-a-review-envelope-v1"
RUBRIC_FIELDS = (
    "evidence_accuracy",
    "type_priority_appropriateness",
    "hypothesis_actionability",
    "no_unobserved_claims",
    "japanese_clarity",
)


class ReviewValidationError(ValueError):
    """Review data is not safe or complete enough to be used."""


def build_review_envelope(recommendation: Mapping[str, Any]) -> dict[str, Any]:
    """Expose only the approved review fields; raw provider data is excluded."""
    article_id = recommendation.get("article_id")
    current_state = recommendation.get("current_state")
    if not isinstance(article_id, int) or article_id < 1 or not isinstance(current_state, Mapping):
        raise ReviewValidationError("validated recommendation is incomplete")
    required = (
        "recommendation_id", "recommendation_type", "priority", "confidence", "risk_level",
        "evidence", "reasons", "suggested_action", "expected_effect", "requires_human_review",
        "data_sufficiency", "generated_at",
    )
    if any(key not in recommendation for key in required) or recommendation["requires_human_review"] is not True:
        raise ReviewValidationError("recommendation is not review-only")
    return {
        "schema_version": REVIEW_SCHEMA_VERSION,
        "review_status": "pending",
        "article_id": article_id,
        "category": recommendation.get("category"),
        "title": recommendation.get("title"),
        "current_state": dict(current_state),
        "recommendation_id": recommendation["recommendation_id"],
        "recommendation_type": recommendation["recommendation_type"],
        "priority": recommendation["priority"],
        "confidence": recommendation["confidence"],
        "risk_level": recommendation["risk_level"],
        "evidence": recommendation["evidence"],
        "reasons": recommendation["reasons"],
        "suggested_action": recommendation["suggested_action"],
        "expected_effect": recommendation["expected_effect"],
        "requires_human_review": True,
        "data_sufficiency": recommendation["data_sufficiency"],
        "generated_at": recommendation["generated_at"],
    }


def score_review(envelope: Mapping[str, Any], scores: Mapping[str, Any]) -> dict[str, Any]:
    """Apply the fixed 0–2 rubric; adoption remains a human decision."""
    if envelope.get("schema_version") != REVIEW_SCHEMA_VERSION or envelope.get("review_status") != "pending":
        raise ReviewValidationError("review envelope is invalid")
    if set(scores) != set(RUBRIC_FIELDS):
        raise ReviewValidationError("review rubric fields are invalid")
    normalized: dict[str, int] = {}
    for field in RUBRIC_FIELDS:
        value = scores[field]
        if not isinstance(value, int) or isinstance(value, bool) or value not in (0, 1, 2):
            raise ReviewValidationError("review score must be between 0 and 2")
        normalized[field] = value
    total = sum(normalized.values())
    eligible = normalized["evidence_accuracy"] == 2 and total >= 8
    return {
        "schema_version": REVIEW_SCHEMA_VERSION,
        "recommendation_id": envelope["recommendation_id"],
        "rubric": normalized,
        "total_score": total,
        "eligible_for_v2_0_b_human_approval": eligible,
        "reason": "rubric_threshold_met" if eligible else "human_review_threshold_not_met",
    }
