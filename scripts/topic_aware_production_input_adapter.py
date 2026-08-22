"""Convert an already approved Topic Candidate chain into the existing safe Gemini brief.

This module is deliberately an adapter, not a new planning or approval system.
It reuses the established Phase 1A/1B/1C and approved-canary validators before
returning the content-free brief consumed by the Worker-side instruction builder.
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence

from topic_candidate_canary_production import (
    CanaryProductionSafetyError,
    build_production_brief,
    validate_content_production_approval,
)
from topic_candidate_production_input import (
    TopicCandidateProductionInputSafetyError,
    validate_approved_content_production_input,
    validate_content_planning_handoff,
    validate_phase1c_source,
)


class TopicAwareProductionInputAdapterError(ValueError):
    """The approved planning chain cannot be used to start Gemini."""


def build_topic_aware_gemini_brief(
    *,
    candidate: Mapping[str, Any],
    reviews: Sequence[Mapping[str, Any]],
    approved_planning: Mapping[str, Any],
    content_handoff: Mapping[str, Any],
    production_input: Mapping[str, Any],
    approval: Mapping[str, Any],
    now: str,
    max_ttl_seconds: int | None = None,
) -> dict[str, Any]:
    """Fail closed before returning a brief for the existing Gemini builder."""
    try:
        validate_phase1c_source(candidate, reviews, approved_planning)
        validate_content_planning_handoff(content_handoff)
        validate_approved_content_production_input(production_input)
        if (
            content_handoff["handoff_id"] != production_input["source_handoff_id"]
            or content_handoff["topic_candidate_id"] != production_input["topic_candidate_id"]
            or content_handoff["human_review_id"] != production_input["human_review_id"]
        ):
            raise TopicAwareProductionInputAdapterError("handoff_identity_mismatch")
        validate_content_production_approval(
            approval,
            production_input=production_input,
            now=now,
            max_ttl_seconds=max_ttl_seconds,
        )
        return build_production_brief(production_input)
    except (CanaryProductionSafetyError, TopicCandidateProductionInputSafetyError, ValueError, KeyError) as error:
        if isinstance(error, TopicAwareProductionInputAdapterError):
            raise
        raise TopicAwareProductionInputAdapterError("approved_topic_input_invalid") from error


def build_topic_aware_pipeline_specification(**kwargs: Any) -> dict[str, Any]:
    """Return the existing manual pipeline fields with a stable input-scoped key."""
    brief = build_topic_aware_gemini_brief(**kwargs)
    return {
        "triggerType": "manual",
        "idempotencyKey": f"manual:topic:{brief['production_input_id']}",
        "scheduledFor": None,
        "sourceType": "approved_topic_candidate",
        "discordHeader": None,
        "topicAwareBrief": brief,
    }
