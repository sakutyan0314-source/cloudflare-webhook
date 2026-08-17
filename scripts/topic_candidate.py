"""Phase 1A: local-only, non-executable topic-candidate planning primitives.

This module deliberately has no network, D1, AI-provider, publishing, or
content-generation dependency.  A TopicCandidate is planning metadata only;
all routes remain non-executable until a separate human-review phase exists.
"""

from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
import re
import unicodedata
from typing import Any, Mapping, Sequence


TOPIC_CANDIDATE_SCHEMA_VERSION = "topic-candidate-v1"
INTENTS = frozenset({"what", "how", "compare", "problem", "commercial_investigation", "business_use"})
OVERLAP_CLASSES = frozenset({"exact_duplicate", "semantic_near_duplicate", "same_intent_overlap", "partial_overlap", "cluster_sibling", "no_material_overlap"})
PRIORITIES = frozenset({"HIGH", "MEDIUM", "LOW", "HOLD"})
ROUTING_DECISIONS = frozenset({"new_content_planning", "existing_content_improvement", "human_review", "hold", "needs_more_evidence"})
SEARCH_CONSOLE_STATES = frozenset({"missing", "observed_zero", "insufficient_data", "sufficient_for_review"})
_SENSITIVE_FIELD_NAMES = frozenset({
    "token", "read_token", "edit_token", "export_token", "authorization", "api_key",
    "secret", "raw_response", "raw_external_response", "content", "body_markdown",
})


class TopicCandidateSafetyError(ValueError):
    """A candidate attempted to cross a Phase 1A safety boundary."""


DEFAULT_CLUSTER_MAP: dict[str, Mapping[str, Any]] = {
    "ai-agent-foundation": {
        "label": "AIエージェント基礎・導入",
        "nodes": {
            "concept": (17, 18, 19, 23, 28, 31),
            "adoption": (), "use_cases": (), "comparison": (), "problems": (),
            "security": (), "selection": (),
        },
    },
    "saas-post-saas": {
        "label": "SaaS / Post-SaaS",
        "nodes": {
            "saas_change": (20, 21, 29, 30, 32, 33),
            "ai_agent_role": (), "a2a": (), "agentic_mesh": (24, 25, 26, 27),
            "business_os": (), "autonomous_enterprise": (),
        },
    },
}
LEGACY_EXCLUDED_ARTICLE_IDS = frozenset({22})


def canonical_json(value: Mapping[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def normalize_topic(value: str) -> str:
    """Apply only mechanical normalization; never infer semantic aliases."""
    if not isinstance(value, str):
        raise TopicCandidateSafetyError("topic_invalid")
    normalized = unicodedata.normalize("NFKC", value).strip()
    normalized = re.sub(r"\s+", " ", normalized).casefold()
    if not normalized:
        raise TopicCandidateSafetyError("topic_invalid")
    return normalized


def normalize_topic_with_alias(value: str, alias_registry: Mapping[str, str] | None = None) -> str:
    key = normalize_topic(value)
    if not alias_registry:
        return key
    safe_registry = {normalize_topic(source): normalize_topic(target) for source, target in alias_registry.items()}
    return safe_registry.get(key, key)


def deterministic_topic_candidate_id(*, normalized_topic_key: str, primary_intent: str, target_audience_key: str, cluster_id: str, language: str, market: str) -> str:
    identity = {
        "schema_version": TOPIC_CANDIDATE_SCHEMA_VERSION,
        "normalized_topic_key": normalized_topic_key,
        "primary_intent": primary_intent,
        "target_audience_key": target_audience_key,
        "cluster_id": cluster_id,
        "language": language,
        "market": market,
    }
    return "topic_" + sha256(canonical_json(identity).encode("utf-8")).hexdigest()[:24]


def _reject_sensitive(value: Any) -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if not isinstance(key, str) or key.casefold() in _SENSITIVE_FIELD_NAMES:
                raise TopicCandidateSafetyError("sensitive_or_content_field_rejected")
            _reject_sensitive(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            _reject_sensitive(child)


def _validate_intents(primary: str, secondary: Sequence[str]) -> tuple[str, tuple[str, ...]]:
    if primary not in INTENTS:
        raise TopicCandidateSafetyError("primary_intent_invalid")
    if not isinstance(secondary, Sequence) or isinstance(secondary, (str, bytes)) or len(secondary) > 2:
        raise TopicCandidateSafetyError("secondary_intents_invalid")
    values = tuple(secondary)
    if any(item not in INTENTS or item == primary for item in values) or len(set(values)) != len(values):
        raise TopicCandidateSafetyError("secondary_intents_invalid")
    return primary, values


def validate_cluster_id(cluster_id: str, cluster_map: Mapping[str, Mapping[str, Any]] = DEFAULT_CLUSTER_MAP) -> str:
    if cluster_id not in cluster_map:
        raise TopicCandidateSafetyError("cluster_id_invalid")
    return cluster_id


def classify_overlap(*, normalized_topic_key: str, primary_intent: str, related_existing: Sequence[Mapping[str, Any]], cluster_id: str, injected_semantic_result: str | None = None) -> str:
    """Classify supplied metadata only; Phase 1A never performs AI semantics."""
    if injected_semantic_result is not None:
        if injected_semantic_result not in OVERLAP_CLASSES:
            raise TopicCandidateSafetyError("overlap_class_invalid")
        return injected_semantic_result
    for item in related_existing:
        if normalize_topic(str(item.get("topic_key", ""))) == normalized_topic_key:
            return "exact_duplicate"
    for item in related_existing:
        if item.get("primary_intent") == primary_intent and item.get("satisfies_same_intent") is True:
            return "same_intent_overlap"
    for item in related_existing:
        if item.get("cluster_id") == cluster_id:
            return "cluster_sibling"
    return "no_material_overlap"


def classify_search_console_state(*, data_present: bool, final_data_days: int, impressions: int, required_days: int = 7, required_impressions: int = 10) -> str:
    if not data_present:
        return "missing"
    if any(not isinstance(value, int) or isinstance(value, bool) or value < 0 for value in (final_data_days, impressions, required_days, required_impressions)):
        raise TopicCandidateSafetyError("search_console_state_invalid")
    if final_data_days == 0 and impressions == 0:
        return "observed_zero"
    if final_data_days < required_days or impressions < required_impressions:
        return "insufficient_data"
    return "sufficient_for_review"


def _priority_and_routing(*, demand_evidence: Sequence[Mapping[str, Any]], content_gap_type: str, overlap: str, duplicate_risk: str, cannibalization_risk: str, related_article_ids: Sequence[int], primary_intent: str) -> tuple[str, str, tuple[str, ...]]:
    reasons: list[str] = ["primary_intent_clear"]
    if any(article_id in LEGACY_EXCLUDED_ARTICLE_IDS for article_id in related_article_ids):
        return "HOLD", "hold", ("legacy_or_unsafe_article_dependency",)
    if not demand_evidence:
        # Unknown volume is acceptable; absence of *all* verifiable evidence is not HIGH-worthy.
        return "MEDIUM", "needs_more_evidence", ("demand_evidence_missing", "high_priority_blocked")
    reasons.append("demand_evidence_present")
    if overlap in {"exact_duplicate", "semantic_near_duplicate"}:
        return "LOW", "human_review", tuple(reasons + ["near_duplicate_detected"])
    if overlap == "same_intent_overlap":
        return "MEDIUM", "existing_content_improvement", tuple(reasons + ["same_intent_existing_article"])
    if overlap == "partial_overlap":
        return "MEDIUM", "human_review", tuple(reasons + ["partial_overlap_detected"])
    if content_gap_type in {"how_to_gap", "comparison_gap", "problem_gap", "business_use_gap", "concept_hub_gap"} and duplicate_risk in {"none", "low"} and cannibalization_risk in {"none", "low"}:
        return "HIGH", "new_content_planning", tuple(reasons + ["content_gap_confirmed", "overlap_acceptable", "cluster_priority_candidate"])
    return "MEDIUM", "human_review", tuple(reasons + ["human_judgment_required"])


def build_topic_candidate(data: Mapping[str, Any], *, alias_registry: Mapping[str, str] | None = None, cluster_map: Mapping[str, Mapping[str, Any]] = DEFAULT_CLUSTER_MAP, injected_overlap: str | None = None) -> dict[str, Any]:
    """Create a planning-only candidate with forced non-executable permissions."""
    _reject_sensitive(data)
    topic = data.get("topic")
    normalized_topic_key = normalize_topic_with_alias(topic, alias_registry)
    primary, secondary = _validate_intents(data.get("primary_intent"), data.get("secondary_intents", ()))
    cluster_id = validate_cluster_id(data.get("cluster_id"), cluster_map)
    target_audience_key = normalize_topic(data.get("target_audience_key", ""))
    language, market = data.get("language", "ja"), data.get("market", "JP")
    if not all(isinstance(value, str) and value for value in (language, market, data.get("target_audience"), data.get("problem_to_solve"), data.get("proposed_title_hint"))):
        raise TopicCandidateSafetyError("candidate_text_field_invalid")
    related = tuple(data.get("related_article_ids", ()))
    children = tuple(data.get("possible_child_article_ids", ()))
    parent = data.get("possible_parent_article_id")
    all_references = related + children + (() if parent is None else (parent,))
    if any(not isinstance(article_id, int) or article_id < 1 for article_id in all_references) or len(set(related)) != len(related):
        raise TopicCandidateSafetyError("article_reference_invalid")
    evidence = tuple(data.get("demand_evidence", ()))
    if not isinstance(data.get("demand_evidence", ()), Sequence) or isinstance(data.get("demand_evidence", ()), (str, bytes)):
        raise TopicCandidateSafetyError("demand_evidence_invalid")
    for item in evidence:
        if not isinstance(item, Mapping) or not all(isinstance(item.get(key), str) and item[key] for key in ("evidence_type", "evidence_source", "evidence_observed_at")):
            raise TopicCandidateSafetyError("demand_evidence_invalid")
        _reject_sensitive(item)
    overlap = injected_overlap or data.get("overlap_classification", "no_material_overlap")
    if overlap not in OVERLAP_CLASSES:
        raise TopicCandidateSafetyError("overlap_class_invalid")
    duplicate_risk = data.get("duplicate_risk", "low")
    cannibalization_risk = data.get("cannibalization_risk", "low")
    if duplicate_risk not in {"none", "low", "medium", "high"} or cannibalization_risk not in {"none", "low", "medium", "high"}:
        raise TopicCandidateSafetyError("risk_invalid")
    content_gap_type = data.get("content_gap_type")
    if content_gap_type not in {"concept_hub_gap", "how_to_gap", "comparison_gap", "problem_gap", "business_use_gap", "selection_gap", "no_confirmed_gap"}:
        raise TopicCandidateSafetyError("content_gap_invalid")
    priority, routing, reasons = _priority_and_routing(demand_evidence=evidence, content_gap_type=content_gap_type, overlap=overlap, duplicate_risk=duplicate_risk, cannibalization_risk=cannibalization_risk, related_article_ids=all_references, primary_intent=primary)
    if data.get("search_volume_known") not in {True, False} or data.get("trend_direction_known") not in {True, False}:
        raise TopicCandidateSafetyError("demand_known_flags_invalid")
    candidate = {
        "schema_version": TOPIC_CANDIDATE_SCHEMA_VERSION,
        "topic_candidate_id": deterministic_topic_candidate_id(normalized_topic_key=normalized_topic_key, primary_intent=primary, target_audience_key=target_audience_key, cluster_id=cluster_id, language=language, market=market),
        "created_at": data.get("created_at") or datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "candidate_status": "pending_human_review",
        "topic": topic, "normalized_topic_key": normalized_topic_key, "proposed_title_hint": data["proposed_title_hint"],
        "primary_intent": primary, "secondary_intents": list(secondary), "target_audience": data["target_audience"], "target_audience_key": target_audience_key, "problem_to_solve": data["problem_to_solve"],
        "demand_evidence": [dict(item) for item in evidence], "search_volume_known": data["search_volume_known"], "trend_direction_known": data["trend_direction_known"],
        "related_article_ids": list(related), "possible_parent_article_id": parent, "possible_child_article_ids": list(children),
        "duplicate_risk": duplicate_risk, "cannibalization_risk": cannibalization_risk, "overlap_classification": overlap, "content_gap_type": content_gap_type, "cluster_id": cluster_id,
        "commercial_intent": data.get("commercial_intent", "not_evaluated"), "affiliate_relevance": data.get("affiliate_relevance", "not_evaluated"),
        "priority": priority, "routing_decision": routing, "reason_codes": list(reasons),
        "requires_human_review": True, "content_generation_authorized": False, "publication_authorized": False, "execution_authorized": False,
    }
    validate_topic_candidate(candidate, cluster_map=cluster_map)
    return candidate


def validate_topic_candidate(candidate: Mapping[str, Any], *, cluster_map: Mapping[str, Mapping[str, Any]] = DEFAULT_CLUSTER_MAP) -> None:
    _reject_sensitive(candidate)
    required = {"schema_version", "topic_candidate_id", "created_at", "candidate_status", "topic", "normalized_topic_key", "proposed_title_hint", "primary_intent", "secondary_intents", "target_audience", "target_audience_key", "problem_to_solve", "demand_evidence", "search_volume_known", "trend_direction_known", "related_article_ids", "possible_parent_article_id", "possible_child_article_ids", "duplicate_risk", "cannibalization_risk", "overlap_classification", "content_gap_type", "cluster_id", "commercial_intent", "affiliate_relevance", "priority", "routing_decision", "reason_codes", "requires_human_review", "content_generation_authorized", "publication_authorized", "execution_authorized"}
    if set(candidate) != required or candidate.get("schema_version") != TOPIC_CANDIDATE_SCHEMA_VERSION:
        raise TopicCandidateSafetyError("candidate_schema_invalid")
    primary, secondary = _validate_intents(candidate["primary_intent"], candidate["secondary_intents"])
    validate_cluster_id(candidate["cluster_id"], cluster_map)
    expected_id = deterministic_topic_candidate_id(normalized_topic_key=candidate["normalized_topic_key"], primary_intent=primary, target_audience_key=candidate["target_audience_key"], cluster_id=candidate["cluster_id"], language="ja", market="JP")
    if candidate["topic_candidate_id"] != expected_id:
        raise TopicCandidateSafetyError("candidate_id_invalid")
    if candidate["priority"] not in PRIORITIES or candidate["routing_decision"] not in ROUTING_DECISIONS or candidate["overlap_classification"] not in OVERLAP_CLASSES:
        raise TopicCandidateSafetyError("candidate_enum_invalid")
    if candidate["priority"] == "HIGH" and not candidate["demand_evidence"]:
        raise TopicCandidateSafetyError("high_priority_requires_demand_evidence")
    if candidate["requires_human_review"] is not True or any(candidate[key] is not False for key in ("content_generation_authorized", "publication_authorized", "execution_authorized")):
        raise TopicCandidateSafetyError("candidate_authorization_boundary_invalid")
