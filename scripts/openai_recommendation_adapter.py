"""OpenAI Responses API transport for v2.0-A, isolated from article generation.

No request is sent until a caller supplies an API key at runtime.  This module
does not persist requests, responses, secrets, or recommendations, and it
performs exactly one HTTP attempt per proposal.
"""

from __future__ import annotations

import json
import os
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from ai_recommendation_adapter import AiProposalTransport


class OpenAiRecommendationError(RuntimeError):
    """Safe provider failure without response, header, token, or key details."""


OPENAI_RESPONSE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["recommendation_type", "priority", "confidence", "evidence", "reasons", "suggested_action", "expected_effect", "risk_level"],
    "properties": {
        "recommendation_type": {"type": "string"}, "priority": {"type": "string"},
        "confidence": {"type": "string"}, "risk_level": {"type": "string"},
        "evidence": {"type": "array", "minItems": 1, "items": {"type": "object", "additionalProperties": False,
                     "required": ["field", "value"], "properties": {"field": {"type": "string"}, "value": {}}}},
        "reasons": {"type": "string"}, "suggested_action": {"type": "string"}, "expected_effect": {"type": "string"},
    },
}

SYSTEM_INSTRUCTIONS = """Return only the required JSON object. Use only values supplied in the input JSON as evidence.
Do not infer search queries, users, views, purchases, orders, revenue, commission, or conversion/CVR.
affiliate_click_rate is a reference ratio only, never a conversion rate. Select only an allowed recommendation type."""


def build_responses_payload(payload: Mapping[str, Any], model_id: str, max_output_tokens: int) -> dict[str, Any]:
    """Build a fixed Responses API Structured Outputs request without tools."""
    if not isinstance(model_id, str) or not model_id.startswith("gpt-5.6-"):
        raise ValueError("OpenAI model ID is not approved")
    return {
        "model": model_id, "store": False, "reasoning": {"effort": "low", "context": "current_turn"},
        "max_output_tokens": max_output_tokens,
        "input": [{"role": "system", "content": [{"type": "input_text", "text": SYSTEM_INSTRUCTIONS}]},
                  {"role": "user", "content": [{"type": "input_text", "text": json.dumps(payload, ensure_ascii=False, separators=(",", ":"))}]}],
        "text": {"format": {"type": "json_schema", "name": "v2a_recommendation", "strict": True, "schema": OPENAI_RESPONSE_SCHEMA}},
    }


def _output_text(response: Mapping[str, Any]) -> str:
    value = response.get("output_text")
    if isinstance(value, str) and value:
        return value
    raise OpenAiRecommendationError("OpenAI response did not contain structured output")


class OpenAiResponsesTransport(AiProposalTransport):
    """One-shot Responses API implementation; retries are intentionally absent."""

    def __init__(self, model_id: str, api_key: str | None = None):
        self._model_id = model_id
        self._api_key = (api_key if api_key is not None else os.environ.get("AI_RECOMMENDATION_OPENAI_API_KEY", "")).strip()
        if not self._api_key:
            raise OpenAiRecommendationError("OpenAI recommendation credential is unavailable")

    def propose(self, payload: Mapping[str, Any], *, max_input_tokens: int, max_output_tokens: int, timeout_seconds: int) -> Mapping[str, Any]:
        if max_input_tokens < 1 or max_output_tokens < 1 or timeout_seconds != 20:
            raise OpenAiRecommendationError("OpenAI recommendation limits are invalid")
        body = json.dumps(build_responses_payload(payload, self._model_id, max_output_tokens), separators=(",", ":")).encode("utf-8")
        request = Request("https://api.openai.com/v1/responses", data=body, method="POST", headers={
            "Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"})
        try:
            with urlopen(request, timeout=timeout_seconds) as response:  # nosec B310 fixed API URL
                parsed = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError):
            raise OpenAiRecommendationError("OpenAI recommendation request failed") from None
        try:
            return json.loads(_output_text(parsed))
        except (json.JSONDecodeError, OpenAiRecommendationError):
            raise OpenAiRecommendationError("OpenAI recommendation response was rejected") from None
