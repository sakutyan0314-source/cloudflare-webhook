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
EVIDENCE_FIELD_PATHS = (
    "article.article_id", "article.category", "article.title", "article.description",
    "observation.observation_days", "observation.impressions", "observation.search_clicks",
    "observation.ctr", "observation.position", "observation.affiliate_click_count",
    "observation.affiliate_click_rate", "observation.search_affiliate_classification",
    "observation.trend",
)

# This is deliberately broad: neither direct claims nor common Japanese
# equivalents of conversion / purchase / revenue language are acceptable.
# These patterns preserve the original rejection surface.  They only split its
# safe audit classification; no match has been removed or made optional.
FORBIDDEN_AI_TERMS = re.compile(
    r"\b(cvr|conversion rate|conversion|purchase|order|revenue|sales|commission|earnings)\b|"
    r"購入|注文|売上|成果報酬|成約率|購入率|コンバージョン|CVR",
    re.IGNORECASE,
)
SECRET_MARKERS = re.compile(r"(?:api[_ -]?key|authorization|bearer\s+|private[_ -]?key|token)\s*[:=]", re.IGNORECASE)
UNSAFE_AI_TEXT_PATTERNS = (
    ("prohibited_cvr_term", re.compile(r"\b(?:cvr|conversion rate)\b|CVR", re.IGNORECASE), "prohibited_expression"),
    ("prohibited_affiliate_conversion_term", re.compile(r"\bconversion\b|コンバージョン|成約率|購入率", re.IGNORECASE), "prohibited_expression"),
    ("prohibited_purchase_term", re.compile(r"\b(?:purchase|order)\b|購入|注文", re.IGNORECASE), "prohibited_expression"),
    ("prohibited_sales_term", re.compile(r"\bsales\b|売上", re.IGNORECASE), "prohibited_expression"),
    ("prohibited_revenue_term", re.compile(r"\b(?:revenue|commission|earnings)\b|成果報酬", re.IGNORECASE), "prohibited_expression"),
    ("suspected_api_key", re.compile(r"api[_ -]?key\s*[:=]", re.IGNORECASE), "secret"),
    ("suspected_authorization_header", re.compile(r"(?:authorization|bearer\s+)\s*[:=]", re.IGNORECASE), "secret"),
    ("suspected_secret", re.compile(r"private[_ -]?key\s*[:=]", re.IGNORECASE), "secret"),
    ("suspected_token", re.compile(r"token\s*[:=]", re.IGNORECASE), "secret"),
)


class RecommendationValidationError(ValueError):
    """Raised when an input or AI response cannot safely become a proposal."""


class EvidenceValidationError(RecommendationValidationError):
    """Safe, value-free evidence diagnostics for an otherwise rejected response."""

    def __init__(self, code: str, diagnostic: Mapping[str, Any]):
        super().__init__("AI evidence does not match input")
        self.code = code
        self.diagnostic = dict(diagnostic)


class UnsafeAiResponseError(RecommendationValidationError):
    """Fail-closed unsafe text with value-free diagnostic metadata only."""

    def __init__(self, diagnostic: Mapping[str, Any]):
        super().__init__("AI response contains prohibited or secret-like text")
        self.diagnostic = dict(diagnostic)


def diagnose_unsafe_ai_text(fields: Mapping[str, object]) -> dict[str, Any]:
    """Classify blocked text without returning the text or matched fragment."""
    matches = []
    for field_name, value in fields.items():
        if not isinstance(field_name, str) or not isinstance(value, str):
            continue
        for code, pattern, category in UNSAFE_AI_TEXT_PATTERNS:
            count = len(pattern.findall(value))
            if count:
                matches.append({"code": code, "category": category, "field": field_name, "count": count})
    # Preserve the broad legacy patterns as a final defensive check.  These
    # fallback codes cannot make an allowed response become accepted.
    combined = "\n".join(value for value in fields.values() if isinstance(value, str))
    if FORBIDDEN_AI_TERMS.search(combined) and not any(item["category"] == "prohibited_expression" for item in matches):
        matches.append({"code": "other_prohibited_expression", "category": "prohibited_expression", "field": "unknown", "count": 1})
    if SECRET_MARKERS.search(combined) and not any(item["category"] == "secret" for item in matches):
        matches.append({"code": "suspected_secret", "category": "secret", "field": "unknown", "count": 1})
    codes = []
    for item in matches:
        if item["code"] not in codes:
            codes.append(item["code"])
    return {"blocked": bool(matches), "categories": sorted({item["category"] for item in matches}),
            "codes": codes, "detection_count": sum(item["count"] for item in matches),
            "fields": sorted({item["field"] for item in matches})}


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
    evidence_diagnostic = diagnose_evidence(response["evidence"], input_payload)
    if evidence_diagnostic["code"] is not None:
        raise EvidenceValidationError(evidence_diagnostic["code"], evidence_diagnostic)
    free_values = [response["reasons"], response["suggested_action"], response["expected_effect"]]
    if not all(isinstance(value, str) and value.strip() for value in free_values):
        raise RecommendationValidationError("AI free text is invalid")
    unsafe_diagnostic = diagnose_unsafe_ai_text({
        "reasons": response["reasons"],
        "suggested_action": response["suggested_action"],
        "expected_effect": response["expected_effect"],
    })
    if unsafe_diagnostic["blocked"]:
        raise UnsafeAiResponseError(unsafe_diagnostic)
    return {"recommendation_type": recommendation_type, "priority": response["priority"], "confidence": response["confidence"],
            "evidence": [{"field": item["field"], "value": item["value"]} for item in response["evidence"]],
            "reasons": response["reasons"].strip(), "suggested_action": response["suggested_action"].strip(),
            "expected_effect": response["expected_effect"].strip(), "risk_level": response["risk_level"]}


def _evidence_values(payload: Mapping[str, Any]) -> dict[str, Any]:
    article = payload["article"]
    obs = payload["observation"]
    values = {f"article.{key}": article[key] for key in ("article_id", "category", "title", "description")}
    values.update({f"observation.{key}": obs[key] for key in (
        "impressions", "search_clicks", "ctr", "position", "affiliate_click_count", "affiliate_click_rate", "search_affiliate_classification", "trend", "observation_days"
    )})
    return values


def _evidence_type(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "string"
    return type(value).__name__


def diagnose_evidence(evidence: object, payload: Mapping[str, Any]) -> dict[str, Any]:
    """Classify evidence safety without retaining or exposing any evidence values."""
    if not isinstance(evidence, list) or not evidence:
        return {"code": "evidence_empty", "evidence_count": 0, "items": []}
    allowed = _evidence_values(payload)
    rows, seen, overall_code = [], set(), None
    for item in evidence:
        if not isinstance(item, Mapping):
            rows.append({"field": None, "field_exists": False, "expected_type": None, "actual_type": None,
                         "matches": False, "code": "missing_field"})
            overall_code = overall_code or "missing_field"
            continue
        field = item.get("field")
        field_name = field if isinstance(field, str) else None
        if "operator" in item:
            code, expected = "operator_invalid", None
        elif field_name is None:
            code, expected = "missing_field", None
        elif field_name not in allowed:
            code, expected = "unknown_field", None
        elif field_name in seen:
            code, expected = "duplicate_evidence", allowed[field_name]
        elif "value" not in item:
            code, expected = "missing_field", allowed[field_name]
        else:
            expected, actual = allowed[field_name], item["value"]
            if expected is None or actual is None:
                code = None if expected is actual else "null_mismatch"
            elif isinstance(expected, (int, float)) and not isinstance(expected, bool) and isinstance(actual, (int, float)) and not isinstance(actual, bool):
                code = None if expected == actual else "value_mismatch"
            elif _evidence_type(expected) != _evidence_type(actual):
                code = "type_mismatch"
            elif expected != actual:
                code = "value_mismatch"
            else:
                code = None
        if field_name is not None:
            seen.add(field_name)
        actual = item.get("value")
        field_exists = field_name in allowed if field_name is not None else False
        rows.append({"field": field_name, "field_exists": field_exists,
                     "expected_type": _evidence_type(expected) if field_exists else None,
                     "actual_type": _evidence_type(actual) if "value" in item else None, "matches": code is None, "code": code})
        overall_code = overall_code or code
    return {"code": overall_code, "evidence_count": len(evidence), "items": rows}


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
