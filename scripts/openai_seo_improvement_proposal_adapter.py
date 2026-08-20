"""OpenAI Responses transport for Phase 2B proposals, with no retry or tools."""

from __future__ import annotations

import json
import os
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from seo_improvement_proposal_adapter import MODEL_ID, SeoImprovementProposalTransport


class OpenAiSeoImprovementProposalError(RuntimeError):
    """Safe provider failure that never includes credential or response text."""


RESPONSE_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["improvement_hypothesis", "proposed_changes", "expected_impact", "risk"],
    "properties": {
        "improvement_hypothesis": {"type": "string"}, "expected_impact": {"type": "string"},
        "risk": {"type": "string", "enum": ["low", "medium", "high"]},
        "proposed_changes": {"type": "array", "minItems": 1, "maxItems": 3, "items": {
            "type": "object", "additionalProperties": False,
            "required": ["scope", "rationale", "suggested_direction"],
            "properties": {"scope": {"type": "string", "enum": ["snippet", "content_refresh", "internal_link_direction"]},
                           "rationale": {"type": "string"}, "suggested_direction": {"type": "string"}},
        }},
    },
}
SYSTEM_INSTRUCTIONS = """Return only the required JSON object. Treat supplied evidence as read-only.
Propose directions only; do not claim an article was changed, authorize any action, or include secrets, tokens, raw logs, article body text, or query text."""


def build_responses_payload(payload: Mapping[str, Any], *, model_id: str, max_output_tokens: int, store: bool, tools: None) -> dict[str, Any]:
    if model_id != MODEL_ID or not isinstance(max_output_tokens, int) or max_output_tokens < 1 or store is not False or tools is not None:
        raise OpenAiSeoImprovementProposalError("provider configuration is invalid")
    return {
        "model": model_id, "store": False, "reasoning": {"effort": "low", "context": "current_turn"},
        "max_output_tokens": max_output_tokens,
        "input": [{"role": "system", "content": [{"type": "input_text", "text": SYSTEM_INSTRUCTIONS}]},
                  {"role": "user", "content": [{"type": "input_text", "text": json.dumps(payload, ensure_ascii=False, separators=(",", ":"))}]}],
        "text": {"format": {"type": "json_schema", "name": "seo_improvement_proposal", "strict": True, "schema": RESPONSE_SCHEMA}},
    }


def _output_text(response: Mapping[str, Any]) -> str:
    if response.get("status") != "completed" or not isinstance(response.get("output"), list):
        raise OpenAiSeoImprovementProposalError("provider response structure is invalid")
    texts = []
    for item in response["output"]:
        if not isinstance(item, Mapping) or item.get("type") == "reasoning":
            continue
        if item.get("type") != "message" or item.get("role") != "assistant" or not isinstance(item.get("content"), list):
            raise OpenAiSeoImprovementProposalError("provider response structure is invalid")
        for part in item["content"]:
            if not isinstance(part, Mapping) or part.get("type") != "output_text" or not isinstance(part.get("text"), str):
                raise OpenAiSeoImprovementProposalError("provider response structure is invalid")
            texts.append(part["text"])
    if len(texts) != 1 or not texts[0]:
        raise OpenAiSeoImprovementProposalError("provider response structure is invalid")
    return texts[0]


class OpenAiSeoImprovementProposalTransport(SeoImprovementProposalTransport):
    """One-shot runtime transport; credentials are never added to payloads or logs."""

    def __init__(self, api_key: str | None = None):
        self._api_key = (api_key if api_key is not None else os.environ.get("AI_RECOMMENDATION_OPENAI_API_KEY", "")).strip()
        if not self._api_key:
            raise OpenAiSeoImprovementProposalError("OpenAI proposal credential is unavailable")

    def propose(self, payload: Mapping[str, Any], *, model_id: str, max_input_tokens: int, max_output_tokens: int, timeout_seconds: int, store: bool, tools: None) -> Mapping[str, Any]:
        if max_input_tokens < 1 or timeout_seconds != 20:
            raise OpenAiSeoImprovementProposalError("provider limits are invalid")
        body = json.dumps(build_responses_payload(payload, model_id=model_id, max_output_tokens=max_output_tokens, store=store, tools=tools), separators=(",", ":")).encode("utf-8")
        request = Request("https://api.openai.com/v1/responses", data=body, method="POST", headers={"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"})
        try:
            with urlopen(request, timeout=timeout_seconds) as response:  # nosec B310 fixed API URL
                parsed = json.loads(response.read().decode("utf-8"))
            return json.loads(_output_text(parsed))
        except TimeoutError:
            raise
        except (HTTPError, URLError, OSError, UnicodeDecodeError, json.JSONDecodeError, OpenAiSeoImprovementProposalError) as error:
            raise OpenAiSeoImprovementProposalError("OpenAI proposal request failed") from error
