"""OpenAI Responses transport for Market Analysis v1; exactly one call, no tools."""
from __future__ import annotations

import json
import os
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from market_signal_analysis import ANALYSIS_SCHEMA_VERSION, MODEL_ID


class OpenAiMarketSignalAnalysisError(RuntimeError):
    """Safe provider error without a credential or raw provider response."""


_TEXT = {"type": "string", "minLength": 1, "maxLength": 500}
_CANDIDATE = {"type": "object", "additionalProperties": False,
    "required": ["topic", "reason", "market_evidence", "common_intent", "own_site_gap", "target_audience", "user_problem", "monetization_relevance", "duplicate_risk", "confidence", "requires_human_review"],
    "properties": {"topic": _TEXT, "reason": _TEXT, "market_evidence": _TEXT, "common_intent": {"type": "string", "enum": ["what", "how", "compare", "problem", "commercial_investigation", "business_use"]},
                   "own_site_gap": {"type": "string", "enum": ["already_covered", "cluster_sibling", "possible_gap", "high_duplicate_risk"]}, "target_audience": _TEXT, "user_problem": _TEXT, "monetization_relevance": _TEXT,
                   "duplicate_risk": {"type": "string", "enum": ["none", "low", "medium", "high"]}, "confidence": {"type": "string", "enum": ["low", "medium", "high"]}, "requires_human_review": {"const": True}}}
RESPONSE_SCHEMA = {"type": "object", "additionalProperties": False,
    "required": ["schema_version", "query", "common_intents", "common_angles", "uncovered_questions", "own_site_gap_assessment", "candidate_drafts", "confidence", "requires_human_review", "content_generation_authorized", "publication_authorized", "execution_authorized"],
    "properties": {"schema_version": {"const": ANALYSIS_SCHEMA_VERSION}, "query": _TEXT,
                   "common_intents": {"type": "array", "minItems": 1, "maxItems": 6, "items": {"type": "string", "enum": ["what", "how", "compare", "problem", "commercial_investigation", "business_use"]}},
                   "common_angles": {"type": "array", "minItems": 1, "maxItems": 10, "items": _TEXT},
                   "uncovered_questions": {"type": "array", "maxItems": 10, "items": {"type": "object", "additionalProperties": False, "required": ["question", "classification"], "properties": {"question": _TEXT, "classification": {"type": "string", "enum": ["possible_gap", "hypothesis"]}}}},
                   "own_site_gap_assessment": {"type": "object", "additionalProperties": False, "required": ["classification", "rationale"], "properties": {"classification": {"type": "string", "enum": ["already_covered", "cluster_sibling", "possible_gap", "high_duplicate_risk"]}, "rationale": _TEXT}},
                   "candidate_drafts": {"type": "array", "maxItems": 3, "items": _CANDIDATE}, "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
                   "requires_human_review": {"const": True}, "content_generation_authorized": {"const": False}, "publication_authorized": {"const": False}, "execution_authorized": {"const": False}}}
SYSTEM_INSTRUCTIONS = """Return only the supplied strict JSON schema. Analyze only supplied SERP and own-site metadata. Never request or infer competitor page bodies. Treat every uncovered question as a possible_gap or hypothesis, never proof. Do not claim demand is confirmed, do not copy or rewrite competitor content, and never authorize content generation, publication, or execution. Do not include secrets, tokens, raw logs, or article bodies."""


def build_responses_payload(payload: Mapping[str, Any], *, model_id: str, max_output_tokens: int, store: bool, tools: None) -> dict[str, Any]:
    if model_id != MODEL_ID or not isinstance(max_output_tokens, int) or max_output_tokens < 1 or store is not False or tools is not None:
        raise OpenAiMarketSignalAnalysisError("provider configuration is invalid")
    return {"model": model_id, "store": False, "reasoning": {"effort": "low", "context": "current_turn"}, "max_output_tokens": max_output_tokens,
            "input": [{"role": "system", "content": [{"type": "input_text", "text": SYSTEM_INSTRUCTIONS}]}, {"role": "user", "content": [{"type": "input_text", "text": json.dumps(payload, ensure_ascii=False, separators=(",", ":"))}]}],
            "text": {"format": {"type": "json_schema", "name": "market_signal_analysis", "strict": True, "schema": RESPONSE_SCHEMA}}}


def _output_text(response: Mapping[str, Any]) -> str:
    if response.get("status") != "completed" or not isinstance(response.get("output"), list):
        raise OpenAiMarketSignalAnalysisError("provider response structure is invalid")
    texts = [part["text"] for item in response["output"] if isinstance(item, Mapping) and item.get("type") == "message" and item.get("role") == "assistant" and isinstance(item.get("content"), list) for part in item["content"] if isinstance(part, Mapping) and part.get("type") == "output_text" and isinstance(part.get("text"), str)]
    if len(texts) != 1 or not texts[0]:
        raise OpenAiMarketSignalAnalysisError("provider response structure is invalid")
    return texts[0]


class OpenAiMarketSignalAnalysisTransport:
    def __init__(self, api_key: str | None = None):
        self._api_key = (api_key if api_key is not None else os.environ.get("AI_RECOMMENDATION_OPENAI_API_KEY", "")).strip()
        if not self._api_key:
            raise OpenAiMarketSignalAnalysisError("OpenAI market analysis credential is unavailable")

    def analyze(self, payload: Mapping[str, Any], *, model_id: str, max_input_tokens: int, max_output_tokens: int, timeout_seconds: int, store: bool, tools: None) -> Mapping[str, Any]:
        if max_input_tokens != 1800 or timeout_seconds != 20:
            raise OpenAiMarketSignalAnalysisError("provider limits are invalid")
        body = json.dumps(build_responses_payload(payload, model_id=model_id, max_output_tokens=max_output_tokens, store=store, tools=tools), separators=(",", ":")).encode()
        request = Request("https://api.openai.com/v1/responses", data=body, method="POST", headers={"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"})
        try:
            with urlopen(request, timeout=timeout_seconds) as response:  # nosec B310 fixed API URL
                return json.loads(_output_text(json.loads(response.read().decode("utf-8"))))
        except TimeoutError:
            raise
        except (HTTPError, URLError, OSError, UnicodeDecodeError, json.JSONDecodeError, OpenAiMarketSignalAnalysisError) as error:
            raise OpenAiMarketSignalAnalysisError("OpenAI market analysis request failed") from error
