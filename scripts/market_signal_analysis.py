"""Single-call, planning-only Market Analysis v1 primitives.

This module accepts metadata that was already normalized by the Market Signal
layer.  It cannot fetch competitor pages, persist data, approve a candidate,
or authorize content generation.
"""
from __future__ import annotations

import json
import re
from math import ceil
from typing import Any, Mapping, Sequence

from topic_candidate import INTENTS


INPUT_SCHEMA_VERSION = "market-signal-analysis-input-v1"
ANALYSIS_SCHEMA_VERSION = "market-signal-analysis-v1"
MODEL_ID = "gpt-5.6-terra"
MAX_INPUT_TOKENS = 1800
# Responses API counts low-effort reasoning together with visible structured
# output. Local validation, rather than this provider budget, keeps JSON brief.
MAX_OUTPUT_TOKENS = 2400
TIMEOUT_SECONDS = 20
MAX_CANDIDATES = 3
_GAPS = frozenset({"already_covered", "cluster_sibling", "possible_gap", "high_duplicate_risk"})
_RISKS = frozenset({"none", "low", "medium", "high"})
_CONFIDENCE = frozenset({"low", "medium", "high"})
_SECRET_LIKE = re.compile(r"(?:api[_ -]?key|authorization|bearer\s+\S+|secret|token)\s*[:=]", re.I)


class MarketAnalysisError(ValueError):
    """A provider response crossed the planning-only analysis boundary."""


def _text(value: object, name: str, *, maximum: int = 500) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum:
        raise MarketAnalysisError(f"{name}_invalid")
    result = value.strip()
    if _SECRET_LIKE.search(result) or result.startswith("# ") or "\n\n" in result:
        raise MarketAnalysisError("secret_or_article_like_text_rejected")
    return result


def _timestamp(value: object) -> str:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise MarketAnalysisError("observed_at_invalid")
    return value


def _canonical(value: Mapping[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def estimated_input_tokens(value: Mapping[str, Any]) -> int:
    return ceil(len(_canonical(value).encode("utf-8")) / 4)


def provider_config() -> dict[str, Any]:
    return {"provider": "openai", "model_id": MODEL_ID, "max_input_tokens": MAX_INPUT_TOKENS,
            "max_output_tokens": MAX_OUTPUT_TOKENS, "timeout_seconds": TIMEOUT_SECONDS,
            "automatic_retry": False, "automatic_fallback": False, "store": False, "tools": None,
            "max_calls_per_market_query": 1}


def build_market_analysis_input(*, query: str, observed_at: str, serp_results: Sequence[Mapping[str, Any]], own_site_signal: Mapping[str, Any]) -> dict[str, Any]:
    clean_query = _text(query, "query", maximum=200)
    if not isinstance(serp_results, Sequence) or isinstance(serp_results, (str, bytes)) or len(serp_results) > 10:
        raise MarketAnalysisError("serp_results_invalid")
    safe_results = []
    for result in serp_results:
        if not isinstance(result, Mapping) or set(result) != {"schema_version", "position", "title", "url", "domain", "snippet", "published_at"}:
            raise MarketAnalysisError("serp_result_invalid")
        if not isinstance(result["position"], int) or result["position"] < 1:
            raise MarketAnalysisError("serp_result_invalid")
        # URLs are deliberately not provided to the LLM: domain plus snippet is
        # sufficient for market analysis and avoids unnecessary parameters.
        safe_results.append({"position": result["position"], "title": _text(result["title"], "serp_title", maximum=300),
                             "domain": _text(result["domain"], "serp_domain", maximum=200),
                             "snippet": _text(result["snippet"] or "(snippet unavailable)", "serp_snippet", maximum=600),
                             "published_at": result["published_at"] if isinstance(result["published_at"], str) else None})
    if not isinstance(own_site_signal, Mapping):
        raise MarketAnalysisError("own_site_signal_invalid")
    overlap = own_site_signal.get("overlap", {})
    matches = overlap.get("matched_articles", []) if isinstance(overlap, Mapping) else []
    safe_matches = []
    if not isinstance(matches, list):
        raise MarketAnalysisError("own_site_overlap_invalid")
    for item in matches:
        if not isinstance(item, Mapping) or not isinstance(item.get("article_id"), int):
            raise MarketAnalysisError("own_site_overlap_invalid")
        safe_matches.append({"article_id": item["article_id"], "title": _text(item.get("title"), "own_site_title", maximum=300),
                             "category": _text(item.get("category"), "own_site_category", maximum=100),
                             "overlap_classification": _text(overlap.get("classification"), "overlap_classification", maximum=100)})
    search_console = own_site_signal.get("search_console_signal")
    affiliate = own_site_signal.get("affiliate_signal")
    if not isinstance(search_console, Mapping) or not isinstance(affiliate, Mapping):
        raise MarketAnalysisError("own_site_signal_invalid")
    output = {"schema_version": INPUT_SCHEMA_VERSION, "query": clean_query, "observed_at": _timestamp(observed_at),
              "serp_results": safe_results, "own_site_overlap": safe_matches,
              "search_console_signal": {key: search_console.get(key) for key in ("status", "observation_days", "impressions", "clicks", "ctr")},
              "affiliate_signal": {key: affiliate.get(key) for key in ("article_click_count", "discord_click_count", "usable_click_count", "reliability_status", "conversion_or_revenue")},
              "intent_taxonomy": sorted(INTENTS),
              "analysis_instructions": "Use metadata only. Treat gaps as possible_gap or hypothesis, never as proof. Do not authorize or generate content."}
    if estimated_input_tokens(output) > MAX_INPUT_TOKENS:
        raise MarketAnalysisError("analysis_input_exceeds_token_limit")
    return output


def _candidate(value: Mapping[str, Any]) -> dict[str, Any]:
    required = {"topic", "reason", "market_evidence", "common_intent", "own_site_gap", "target_audience", "user_problem", "monetization_relevance", "duplicate_risk", "confidence", "requires_human_review"}
    if not isinstance(value, Mapping) or set(value) != required:
        raise MarketAnalysisError("candidate_schema_invalid")
    candidate = {key: _text(value[key], key) for key in required - {"requires_human_review"}}
    if candidate["common_intent"] not in INTENTS or candidate["own_site_gap"] not in _GAPS or candidate["duplicate_risk"] not in _RISKS or candidate["confidence"] not in _CONFIDENCE:
        raise MarketAnalysisError("candidate_enum_invalid")
    if value["requires_human_review"] is not True:
        raise MarketAnalysisError("candidate_human_review_required")
    if candidate["own_site_gap"] in {"already_covered", "high_duplicate_risk"} or candidate["duplicate_risk"] == "high":
        raise MarketAnalysisError("unsafe_candidate_rejected")
    return {**candidate, "requires_human_review": True}


def validate_market_analysis(value: Mapping[str, Any], analysis_input: Mapping[str, Any]) -> dict[str, Any]:
    required = {"schema_version", "query", "common_intents", "common_angles", "uncovered_questions", "own_site_gap_assessment", "candidate_drafts", "confidence", "requires_human_review", "content_generation_authorized", "publication_authorized", "execution_authorized"}
    if not isinstance(value, Mapping) or set(value) != required or value.get("schema_version") != ANALYSIS_SCHEMA_VERSION:
        raise MarketAnalysisError("analysis_schema_invalid")
    if value.get("query") != analysis_input.get("query"):
        raise MarketAnalysisError("query_identity_mismatch")
    intents = value.get("common_intents")
    if not isinstance(intents, list) or not intents or len(set(intents)) != len(intents) or any(item not in INTENTS for item in intents):
        raise MarketAnalysisError("intent_enum_invalid")
    angles = value.get("common_angles")
    if not isinstance(angles, list) or not angles or len(angles) > 10:
        raise MarketAnalysisError("common_angles_invalid")
    clean_angles = [_text(item, "common_angle", maximum=250) for item in angles]
    questions = value.get("uncovered_questions")
    if not isinstance(questions, list) or len(questions) > 10:
        raise MarketAnalysisError("uncovered_questions_invalid")
    clean_questions = []
    for item in questions:
        if not isinstance(item, Mapping) or set(item) != {"question", "classification"} or item.get("classification") not in {"possible_gap", "hypothesis"}:
            raise MarketAnalysisError("uncovered_question_invalid")
        clean_questions.append({"question": _text(item.get("question"), "uncovered_question", maximum=300), "classification": item["classification"]})
    assessment = value.get("own_site_gap_assessment")
    if not isinstance(assessment, Mapping) or set(assessment) != {"classification", "rationale"} or assessment.get("classification") not in _GAPS:
        raise MarketAnalysisError("own_site_gap_invalid")
    drafts = value.get("candidate_drafts")
    if not isinstance(drafts, list) or len(drafts) > MAX_CANDIDATES:
        raise MarketAnalysisError("candidate_count_invalid")
    clean_drafts = [_candidate(item) for item in drafts]
    if value.get("confidence") not in _CONFIDENCE or value.get("requires_human_review") is not True or any(value.get(key) is not False for key in ("content_generation_authorized", "publication_authorized", "execution_authorized")):
        raise MarketAnalysisError("analysis_authorization_boundary_invalid")
    return {"schema_version": ANALYSIS_SCHEMA_VERSION, "query": analysis_input["query"], "common_intents": list(intents), "common_angles": clean_angles,
            "uncovered_questions": clean_questions, "own_site_gap_assessment": {"classification": assessment["classification"], "rationale": _text(assessment.get("rationale"), "gap_rationale")},
            "candidate_drafts": clean_drafts, "confidence": value["confidence"], "requires_human_review": True,
            "content_generation_authorized": False, "publication_authorized": False, "execution_authorized": False}
