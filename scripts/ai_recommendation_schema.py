"""Strict schemas and deterministic identifiers for v2.0-A recommendations.

The module contains no I/O, no persistence, and no model SDK.  Values known
from the observation input are reconstructed locally rather than trusted from
an AI response.
"""

from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
import re
from typing import Any, Mapping


INPUT_SCHEMA_VERSION = "v2.0-a-input-v1"
OUTPUT_SCHEMA_VERSION = "v2.0-a-recommendation-v1"
RULE_VERSION = "v2.0-a-rules-v1"
RECOMMENDATION_TYPES = frozenset({
    "improve_title", "improve_description", "improve_ctr", "improve_content",
    "refresh_content", "improve_internal_links", "improve_affiliate_category",
    "improve_affiliate_cta", "continue_observation", "insufficient_data",
})
PRIORITIES = frozenset({"critical", "high", "medium", "low", "observe"})
CONFIDENCES = frozenset({"high", "medium", "low"})
DATA_SUFFICIENCY = frozenset({"sufficient", "insufficient_data"})
RISK_LEVELS = frozenset({"low", "medium", "high"})

# This is deliberately broad: neither direct claims nor common Japanese
# equivalents of conversion / purchase / revenue language are acceptable.
FORBIDDEN_AI_TERMS = re.compile(
    r"\b(cvr|conversion rate|conversion|purchase|order|revenue|sales|commission|earnings)\b|"
    r"購入|注文|売上|成果報酬|成約率|購入率|コンバージョン|CVR",
    re.IGNORECASE,
)
SECRET_MARKERS = re.compile(r"(?:api[_ -]?key|authorization|bearer\s+|private[_ -]?key|token)\s*[:=]", re.IGNORECASE)


class RecommendationValidationError(ValueError):
    """Raised when an input or AI response cannot safely become a proposal."""


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _positive_int(value: object, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise RecommendationValidationError(f"{name} must be a positive integer")
    return value


def _non_negative(value: object, name: str) -> int | float:
    if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0:
        raise RecommendationValidationError(f"{name} must be non-negative")
    return value


def validate_input(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Return a safe, normalized input subset.  Unknown fields are ignored."""
    if not isinstance(payload, Mapping) or payload.get("schema_version") != INPUT_SCHEMA_VERSION:
        raise RecommendationValidationError("input schema version is invalid")
    article, observation, rule_assessment = payload.get("article"), payload.get("observation"), payload.get("rule_assessment")
    if not all(isinstance(item, Mapping) for item in (article, observation, rule_assessment)):
        raise RecommendationValidationError("input sections are required")
    article_id = _positive_int(article.get("article_id"), "article_id")
    title, description, category = article.get("title"), article.get("description"), article.get("category")
    if not all(isinstance(value, str) and value.strip() for value in (title, description, category)):
        raise RecommendationValidationError("article metadata is invalid")
    headings = article.get("h2_headings", [])
    if not isinstance(headings, list) or not all(isinstance(item, str) for item in headings):
        raise RecommendationValidationError("h2_headings is invalid")
    period = observation.get("period")
    if not isinstance(period, Mapping) or not all(isinstance(period.get(key), str) for key in ("start", "end")):
        raise RecommendationValidationError("observation period is invalid")
    current = {
        "impressions": _non_negative(observation.get("impressions"), "impressions"),
        "search_clicks": _non_negative(observation.get("search_clicks"), "search_clicks"),
        "ctr": _non_negative(observation.get("ctr"), "ctr"),
        "position": observation.get("position"),
        "affiliate_click_count": _non_negative(observation.get("affiliate_click_count"), "affiliate_click_count"),
        "affiliate_click_rate": observation.get("affiliate_click_rate"),
        "search_affiliate_classification": observation.get("search_affiliate_classification", "insufficient_data"),
        "trend": observation.get("trend"),
        "observation_days": _positive_int(observation.get("observation_days"), "observation_days"),
    }
    if current["position"] is not None:
        _non_negative(current["position"], "position")
    if current["affiliate_click_rate"] is not None:
        _non_negative(current["affiliate_click_rate"], "affiliate_click_rate")
    if current["trend"] not in {"growing", "declining", "stable", "insufficient_data"}:
        raise RecommendationValidationError("trend is invalid")
    if current["search_affiliate_classification"] not in {"high_value", "traffic_only", "conversion_candidate", "insufficient_data"}:
        raise RecommendationValidationError("search affiliate classification is invalid")
    if rule_assessment.get("data_sufficiency") not in DATA_SUFFICIENCY or not isinstance(rule_assessment.get("ai_eligible"), bool):
        raise RecommendationValidationError("rule assessment is invalid")
    candidates = rule_assessment.get("candidate_types", [])
    if not isinstance(candidates, list) or not candidates or not set(candidates) <= RECOMMENDATION_TYPES:
        raise RecommendationValidationError("candidate types are invalid")
    return {
        "schema_version": INPUT_SCHEMA_VERSION,
        "article": {"article_id": article_id, "title": title.strip(), "description": description.strip(),
                    "category": category.strip(), "h2_headings": headings, "published_at": article.get("published_at"),
                    "updated_at": article.get("updated_at"), "article_age_days": article.get("article_age_days")},
        "observation": {"period": {"start": period["start"], "end": period["end"]}, **current},
        "rule_assessment": {"ai_eligible": rule_assessment["ai_eligible"],
                            "data_sufficiency": rule_assessment["data_sufficiency"],
                            "candidate_types": candidates, "reasons": list(rule_assessment.get("reasons", []))},
    }


def recommendation_id(input_payload: Mapping[str, Any], recommendation_type: str, evidence: list[Mapping[str, Any]]) -> str:
    stable = {"rule_version": RULE_VERSION, "article_id": input_payload["article"]["article_id"],
              "type": recommendation_type, "period": input_payload["observation"]["period"], "evidence": evidence}
    encoded = json.dumps(stable, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "rec_v2a_" + sha256(encoded).hexdigest()[:24]


def validate_ai_response(response: Mapping[str, Any], input_payload: Mapping[str, Any]) -> dict[str, Any]:
    """Validate only AI-owned free text; server-owned fields are reconstructed."""
    if not isinstance(response, Mapping):
        raise RecommendationValidationError("AI response must be an object")
    required = ("recommendation_type", "priority", "confidence", "evidence", "reasons", "suggested_action", "expected_effect", "risk_level")
    if any(key not in response for key in required):
        raise RecommendationValidationError("AI response fields are incomplete")
    recommendation_type = response["recommendation_type"]
    if recommendation_type not in input_payload["rule_assessment"]["candidate_types"]:
        raise RecommendationValidationError("AI recommendation type is not allowed")
    if response["priority"] not in PRIORITIES or response["confidence"] not in CONFIDENCES or response["risk_level"] not in RISK_LEVELS:
        raise RecommendationValidationError("AI enum is invalid")
    if not isinstance(response["evidence"], list) or not response["evidence"]:
        raise RecommendationValidationError("AI evidence is invalid")
    allowed_values = _evidence_values(input_payload)
    for item in response["evidence"]:
        if not isinstance(item, Mapping) or item.get("field") not in allowed_values or item.get("value") != allowed_values[item["field"]]:
            raise RecommendationValidationError("AI evidence does not match input")
    free_values = [response["reasons"], response["suggested_action"], response["expected_effect"]]
    if not all(isinstance(value, str) and value.strip() for value in free_values):
        raise RecommendationValidationError("AI free text is invalid")
    combined = "\n".join(free_values)
    if FORBIDDEN_AI_TERMS.search(combined) or SECRET_MARKERS.search(combined):
        raise RecommendationValidationError("AI response contains prohibited language")
    return {"recommendation_type": recommendation_type, "priority": response["priority"], "confidence": response["confidence"],
            "evidence": [{"field": item["field"], "value": item["value"]} for item in response["evidence"]],
            "reasons": response["reasons"].strip(), "suggested_action": response["suggested_action"].strip(),
            "expected_effect": response["expected_effect"].strip(), "risk_level": response["risk_level"]}


def _evidence_values(payload: Mapping[str, Any]) -> dict[str, Any]:
    obs = payload["observation"]
    return {f"observation.{key}": obs[key] for key in (
        "impressions", "search_clicks", "ctr", "position", "affiliate_click_count", "affiliate_click_rate", "search_affiliate_classification", "trend", "observation_days"
    )}


def build_recommendation(input_payload: Mapping[str, Any], ai: Mapping[str, Any] | None, generated_at: str | None = None) -> dict[str, Any]:
    """Create the final proposal.  All known state is reconstructed server-side."""
    safe_input = validate_input(input_payload)
    if ai is None:
        recommendation_type = safe_input["rule_assessment"]["candidate_types"][0]
        evidence = [{"field": "observation.impressions", "value": safe_input["observation"]["impressions"]}]
        priority, confidence, risk = "observe", "low", "low"
        reasons = "; ".join(safe_input["rule_assessment"]["reasons"])
        action, effect = "継続観測し、十分なデータが蓄積されるまで変更しない。", "判断に必要な観測量を増やす。"
    else:
        verified = validate_ai_response(ai, safe_input)
        recommendation_type, evidence = verified["recommendation_type"], verified["evidence"]
        priority, confidence, risk = verified["priority"], verified["confidence"], verified["risk_level"]
        reasons, action, effect = verified["reasons"], verified["suggested_action"], verified["expected_effect"]
    return {"schema_version": OUTPUT_SCHEMA_VERSION, "article_id": safe_input["article"]["article_id"],
            "recommendation_id": recommendation_id(safe_input, recommendation_type, evidence),
            "recommendation_type": recommendation_type, "priority": priority, "confidence": confidence,
            "current_state": safe_input["observation"], "evidence": evidence, "reasons": reasons,
            "suggested_action": action, "expected_effect": effect, "risk_level": risk,
            "requires_human_review": True, "data_sufficiency": safe_input["rule_assessment"]["data_sufficiency"],
            "generated_at": generated_at or utc_now()}
