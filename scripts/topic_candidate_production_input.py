"""Phase 1C: local-only conversion from an approved topic to production input.

This module intentionally has no network, D1, Worker, AI, or publishing
dependency.  It creates non-executable planning metadata only; a later,
separate human authorization is required before any production pipeline use.
"""

from __future__ import annotations

from hashlib import sha256
from typing import Any, Mapping, Sequence

from topic_candidate import LEGACY_EXCLUDED_ARTICLE_IDS, canonical_json
from topic_candidate_review import (
    APPROVED_TOPIC_PLANNING_SCHEMA_VERSION,
    TopicCandidateReviewSafetyError,
    _parse_timestamp,
    _reject_forbidden,
    _validate_review_chain,
    candidate_identity_fingerprint,
    validate_approved_topic_planning_handoff,
    validate_candidate_for_review,
)


CONTENT_PLANNING_HANDOFF_SCHEMA_VERSION = "content-planning-handoff-v1"
APPROVED_CONTENT_PRODUCTION_INPUT_SCHEMA_VERSION = "approved-content-production-input-v1"
_AUTHORIZATION_FIELDS = ("ai_generation_authorized", "publication_authorized", "execution_authorized")
_SOURCE_AUTHORIZATION_FIELDS = ("content_generation_authorized", "publication_authorized", "execution_authorized")


class TopicCandidateProductionInputSafetyError(ValueError):
    """A Phase 1C input attempted to cross its non-executable boundary."""


def _fail_closed(callback, *args, **kwargs):
    try:
        return callback(*args, **kwargs)
    except (TopicCandidateReviewSafetyError, ValueError) as error:
        raise TopicCandidateProductionInputSafetyError("source_integrity_invalid") from error


def _require_false_authorizations(value: Mapping[str, Any]) -> None:
    if any(value.get(field) is not False for field in _AUTHORIZATION_FIELDS):
        raise TopicCandidateProductionInputSafetyError("authorization_boundary_invalid")


def _require_false_source_authorizations(value: Mapping[str, Any]) -> None:
    if any(value.get(field) is not False for field in _SOURCE_AUTHORIZATION_FIELDS):
        raise TopicCandidateProductionInputSafetyError("authorization_boundary_invalid")


def _safe_article_ids(value: object) -> list[int]:
    if not isinstance(value, list) or len(set(value)) != len(value) or any(not isinstance(item, int) or item < 1 for item in value):
        raise TopicCandidateProductionInputSafetyError("article_reference_invalid")
    if any(item in LEGACY_EXCLUDED_ARTICLE_IDS for item in value):
        raise TopicCandidateProductionInputSafetyError("legacy_or_unsafe_dependency")
    return list(value)


def _safe_evidence_summary(candidate: Mapping[str, Any]) -> list[dict[str, Any]]:
    # Deliberately retain only provenance metadata.  Unknown search volume stays unknown.
    output: list[dict[str, Any]] = []
    for item in candidate["demand_evidence"]:
        output.append({
            "evidence_type": item["evidence_type"],
            "evidence_source": item["evidence_source"],
            "evidence_observed_at": item["evidence_observed_at"],
        })
    return output


def validate_phase1c_source(candidate: Mapping[str, Any], reviews: Sequence[Mapping[str, Any]], approved: Mapping[str, Any]) -> str:
    """Revalidate Phase 1A/1B identities, chain, decision, and routing."""
    _fail_closed(_reject_forbidden, candidate)
    _fail_closed(_reject_forbidden, reviews)
    _fail_closed(_reject_forbidden, approved)
    fingerprint = _fail_closed(validate_candidate_for_review, candidate, approval_decision=True)
    _fail_closed(validate_approved_topic_planning_handoff, approved)
    _require_false_source_authorizations(candidate)
    _require_false_source_authorizations(approved)
    if not reviews:
        raise TopicCandidateProductionInputSafetyError("review_missing")
    _fail_closed(_validate_review_chain, candidate, reviews, fingerprint)
    latest = reviews[-1]
    _require_false_source_authorizations(latest)
    if latest["decision"] != "approve_for_content_planning":
        raise TopicCandidateProductionInputSafetyError("latest_review_not_approved")
    if candidate["routing_decision"] != "new_content_planning" or approved["routing"] != "new_content_planning":
        raise TopicCandidateProductionInputSafetyError("v2_routing_or_non_new_content_rejected")
    expected = {
        "topic_candidate_id": candidate["topic_candidate_id"],
        "candidate_identity_fingerprint": fingerprint,
        "human_review_id": latest["review_id"],
        "decision": "approve_for_content_planning",
    }
    if any(approved.get(key) != value for key, value in expected.items()):
        raise TopicCandidateProductionInputSafetyError("approved_planning_identity_mismatch")
    if approved.get("schema_version") != APPROVED_TOPIC_PLANNING_SCHEMA_VERSION:
        raise TopicCandidateProductionInputSafetyError("approved_planning_schema_invalid")
    return fingerprint


def deterministic_content_planning_handoff_id(*, approved_handoff_id: str, topic_candidate_id: str, candidate_fingerprint: str, human_review_id: str) -> str:
    identity = {"schema_version": CONTENT_PLANNING_HANDOFF_SCHEMA_VERSION, "approved_handoff_id": approved_handoff_id, "topic_candidate_id": topic_candidate_id, "candidate_identity_fingerprint": candidate_fingerprint, "human_review_id": human_review_id}
    return "content_plan_" + sha256(canonical_json(identity).encode("utf-8")).hexdigest()[:24]


def deterministic_production_input_id(*, handoff_id: str, topic_candidate_id: str, human_review_id: str) -> str:
    identity = {"schema_version": APPROVED_CONTENT_PRODUCTION_INPUT_SCHEMA_VERSION, "handoff_id": handoff_id, "topic_candidate_id": topic_candidate_id, "human_review_id": human_review_id}
    return "production_input_" + sha256(canonical_json(identity).encode("utf-8")).hexdigest()[:24]


def build_content_planning_handoff(candidate: Mapping[str, Any], reviews: Sequence[Mapping[str, Any]], approved: Mapping[str, Any], *, created_at: str) -> dict[str, Any]:
    fingerprint = validate_phase1c_source(candidate, reviews, approved)
    _fail_closed(_parse_timestamp, created_at)
    related = _safe_article_ids(candidate["related_article_ids"])
    parent = candidate["possible_parent_article_id"]
    children = _safe_article_ids(candidate["possible_child_article_ids"])
    if parent is not None and (not isinstance(parent, int) or parent < 1 or parent in LEGACY_EXCLUDED_ARTICLE_IDS):
        raise TopicCandidateProductionInputSafetyError("legacy_or_unsafe_dependency")
    handoff = {
        "schema_version": CONTENT_PLANNING_HANDOFF_SCHEMA_VERSION,
        "handoff_id": deterministic_content_planning_handoff_id(approved_handoff_id=approved["handoff_id"], topic_candidate_id=candidate["topic_candidate_id"], candidate_fingerprint=fingerprint, human_review_id=approved["human_review_id"]),
        "source_approved_topic_planning_handoff_id": approved["handoff_id"],
        "topic_candidate_id": candidate["topic_candidate_id"], "topic_candidate_fingerprint": fingerprint,
        "human_review_id": approved["human_review_id"], "planning_approval_fingerprint": sha256(canonical_json(dict(approved)).encode("utf-8")).hexdigest(),
        "topic": candidate["topic"], "proposed_title_hint": candidate["proposed_title_hint"],
        "primary_intent": candidate["primary_intent"], "secondary_intents": list(candidate["secondary_intents"]),
        "target_audience": candidate["target_audience"], "problem_to_solve": candidate["problem_to_solve"],
        "cluster_id": candidate["cluster_id"], "priority": candidate["priority"],
        "demand_evidence_summary": _safe_evidence_summary(candidate),
        "search_volume_known": candidate["search_volume_known"], "trend_direction_known": candidate["trend_direction_known"],
        "related_article_ids": related,
        "internal_link_candidates": {"suggested_parent_article_id": parent, "suggested_sibling_article_ids": related, "suggested_child_article_ids": children},
        "content_constraints": {"article_body_generation": "not_authorized", "publication": "not_authorized", "raw_external_data": "forbidden", "article_body_storage": "forbidden"},
        "created_at": created_at,
        "ai_generation_authorized": False, "publication_authorized": False, "execution_authorized": False,
    }
    validate_content_planning_handoff(handoff)
    return handoff


def validate_content_planning_handoff(handoff: Mapping[str, Any]) -> None:
    _fail_closed(_reject_forbidden, handoff)
    required = {"schema_version", "handoff_id", "source_approved_topic_planning_handoff_id", "topic_candidate_id", "topic_candidate_fingerprint", "human_review_id", "planning_approval_fingerprint", "topic", "proposed_title_hint", "primary_intent", "secondary_intents", "target_audience", "problem_to_solve", "cluster_id", "priority", "demand_evidence_summary", "search_volume_known", "trend_direction_known", "related_article_ids", "internal_link_candidates", "content_constraints", "created_at", "ai_generation_authorized", "publication_authorized", "execution_authorized"}
    if set(handoff) != required or handoff.get("schema_version") != CONTENT_PLANNING_HANDOFF_SCHEMA_VERSION:
        raise TopicCandidateProductionInputSafetyError("content_planning_schema_invalid")
    _require_false_authorizations(handoff); _fail_closed(_parse_timestamp, handoff.get("created_at"))
    if not all(isinstance(handoff.get(key), str) and handoff[key] for key in ("handoff_id", "source_approved_topic_planning_handoff_id", "topic_candidate_id", "topic_candidate_fingerprint", "human_review_id", "planning_approval_fingerprint", "topic", "proposed_title_hint", "primary_intent", "target_audience", "problem_to_solve", "cluster_id", "priority")):
        raise TopicCandidateProductionInputSafetyError("content_planning_identity_invalid")
    _safe_article_ids(handoff["related_article_ids"])
    if not isinstance(handoff.get("secondary_intents"), list) or not isinstance(handoff.get("demand_evidence_summary"), list) or not handoff["demand_evidence_summary"]:
        raise TopicCandidateProductionInputSafetyError("content_planning_metadata_invalid")
    if handoff.get("search_volume_known") not in {True, False} or handoff.get("trend_direction_known") not in {True, False}:
        raise TopicCandidateProductionInputSafetyError("demand_known_flags_invalid")
    links = handoff.get("internal_link_candidates")
    if not isinstance(links, Mapping) or set(links) != {"suggested_parent_article_id", "suggested_sibling_article_ids", "suggested_child_article_ids"}:
        raise TopicCandidateProductionInputSafetyError("internal_link_guidance_invalid")
    for key in ("suggested_sibling_article_ids", "suggested_child_article_ids"):
        _safe_article_ids(links[key])
    parent = links["suggested_parent_article_id"]
    if parent is not None and (not isinstance(parent, int) or parent < 1 or parent in LEGACY_EXCLUDED_ARTICLE_IDS):
        raise TopicCandidateProductionInputSafetyError("internal_link_guidance_invalid")


def build_approved_content_production_input(handoff: Mapping[str, Any], *, created_at: str, quality_threshold_version: str = "seo_quality_threshold_v1") -> dict[str, Any]:
    validate_content_planning_handoff(handoff); _fail_closed(_parse_timestamp, created_at)
    if not isinstance(quality_threshold_version, str) or not quality_threshold_version:
        raise TopicCandidateProductionInputSafetyError("quality_threshold_version_invalid")
    output = {
        "schema_version": APPROVED_CONTENT_PRODUCTION_INPUT_SCHEMA_VERSION,
        "production_input_id": deterministic_production_input_id(handoff_id=handoff["handoff_id"], topic_candidate_id=handoff["topic_candidate_id"], human_review_id=handoff["human_review_id"]),
        "source_handoff_id": handoff["handoff_id"], "topic_candidate_id": handoff["topic_candidate_id"], "human_review_id": handoff["human_review_id"],
        "topic": handoff["topic"], "title_hint": handoff["proposed_title_hint"], "primary_intent": handoff["primary_intent"], "secondary_intents": handoff["secondary_intents"],
        "target_audience": handoff["target_audience"], "problem_to_solve": handoff["problem_to_solve"], "cluster": handoff["cluster_id"],
        "related_article_ids": handoff["related_article_ids"], "internal_link_guidance": handoff["internal_link_candidates"],
        "demand_evidence_summary": handoff["demand_evidence_summary"], "search_volume_known": handoff["search_volume_known"], "trend_direction_known": handoff["trend_direction_known"],
        "quality_threshold_version": quality_threshold_version, "created_at": created_at,
        "ai_generation_authorized": False, "publication_authorized": False, "execution_authorized": False,
    }
    validate_approved_content_production_input(output)
    return output


def validate_approved_content_production_input(value: Mapping[str, Any]) -> None:
    _fail_closed(_reject_forbidden, value)
    required = {"schema_version", "production_input_id", "source_handoff_id", "topic_candidate_id", "human_review_id", "topic", "title_hint", "primary_intent", "secondary_intents", "target_audience", "problem_to_solve", "cluster", "related_article_ids", "internal_link_guidance", "demand_evidence_summary", "search_volume_known", "trend_direction_known", "quality_threshold_version", "created_at", "ai_generation_authorized", "publication_authorized", "execution_authorized"}
    if set(value) != required or value.get("schema_version") != APPROVED_CONTENT_PRODUCTION_INPUT_SCHEMA_VERSION:
        raise TopicCandidateProductionInputSafetyError("production_input_schema_invalid")
    _require_false_authorizations(value); _fail_closed(_parse_timestamp, value.get("created_at"))
    if not all(isinstance(value.get(key), str) and value[key] for key in ("production_input_id", "source_handoff_id", "topic_candidate_id", "human_review_id", "topic", "title_hint", "primary_intent", "target_audience", "problem_to_solve", "cluster", "quality_threshold_version")):
        raise TopicCandidateProductionInputSafetyError("production_input_identity_invalid")
    _safe_article_ids(value["related_article_ids"])
    if not isinstance(value.get("secondary_intents"), list) or not isinstance(value.get("demand_evidence_summary"), list) or not isinstance(value.get("internal_link_guidance"), Mapping):
        raise TopicCandidateProductionInputSafetyError("production_input_metadata_invalid")
    if value.get("search_volume_known") not in {True, False} or value.get("trend_direction_known") not in {True, False}:
        raise TopicCandidateProductionInputSafetyError("demand_known_flags_invalid")
