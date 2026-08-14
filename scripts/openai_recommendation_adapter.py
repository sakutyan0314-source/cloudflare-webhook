"""OpenAI Responses API transport for v2.0-A, isolated from article generation.

No request is sent until a caller supplies an API key at runtime.  This module
does not persist requests, responses, secrets, or recommendations, and it
performs exactly one HTTP attempt per proposal.
"""

from __future__ import annotations

import json
import http.client
import os
import re
import socket
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from ai_recommendation_adapter import AiProposalTransport
from ai_recommendation_schema import EVIDENCE_FIELD_PATHS


class OpenAiRecommendationError(RuntimeError):
    """Safe provider failure without response, header, token, or key details."""


class OpenAiRecommendationHttpError(OpenAiRecommendationError):
    """Sanitized HTTP diagnostics, limited to the API's public error fields."""

    def __init__(self, status: int, error_type: str | None, error_code: str | None,
                 error_param: str | None, error_message: str):
        super().__init__("OpenAI recommendation request failed")
        self.status = status
        self.error_type = error_type
        self.error_code = error_code
        self.error_param = error_param
        self.error_message = error_message


class OpenAiRecommendationResponseError(OpenAiRecommendationError):
    """A fail-closed response-shape outcome with safe structural diagnostics."""

    def __init__(self, code: str, diagnostic: Mapping[str, Any]):
        super().__init__("OpenAI recommendation response was rejected")
        self.code = code
        self.diagnostic = dict(diagnostic)


class OpenAiRecommendationTransportError(OpenAiRecommendationError):
    """Value-free transport classification; delivery is never presumed."""

    def __init__(self, code: str):
        if code not in {"connection_reset", "connection_closed", "response_read_failed", "transport_exception", "delivery_state_unknown"}:
            code = "delivery_state_unknown"
        super().__init__("OpenAI recommendation transport failed")
        self.code = code


def _transport_error_code(error: BaseException) -> str:
    """Classify known local transport shapes without retaining error detail."""
    if isinstance(error, ConnectionResetError):
        return "connection_reset"
    if isinstance(error, (http.client.RemoteDisconnected, ConnectionAbortedError)):
        return "connection_closed"
    if isinstance(error, (UnicodeDecodeError, json.JSONDecodeError)):
        return "response_read_failed"
    if isinstance(error, (URLError, OSError, socket.error)):
        return "transport_exception"
    return "delivery_state_unknown"


def _redact_error_message(value: object) -> str:
    """Keep a short schema diagnostic without leaking credentials or input text."""
    message = str(value)[:500]
    message = re.sub(r"(?i)bearer\s+[^\s]+", "Bearer [REDACTED]", message)
    message = re.sub(r"\b(?:sk|sess|key)-[A-Za-z0-9_-]+", "[REDACTED]", message)
    return message


def _safe_http_error(error: HTTPError) -> OpenAiRecommendationHttpError:
    """Parse only permitted diagnostic fields from an error body held in memory."""
    try:
        body = json.loads(error.read().decode("utf-8"))
        detail = body.get("error", {}) if isinstance(body, Mapping) else {}
    except (UnicodeDecodeError, json.JSONDecodeError):
        detail = {}
    if not isinstance(detail, Mapping):
        detail = {}
    return OpenAiRecommendationHttpError(
        error.code,
        detail.get("type") if isinstance(detail.get("type"), str) else None,
        detail.get("code") if isinstance(detail.get("code"), str) else None,
        detail.get("param") if isinstance(detail.get("param"), str) else None,
        _redact_error_message(detail.get("message", "OpenAI API request failed")),
    )


OPENAI_RESPONSE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["recommendation_type", "priority", "confidence", "evidence", "reasons", "suggested_action", "expected_effect", "risk_level"],
    "properties": {
        "recommendation_type": {"type": "string"}, "priority": {"type": "string"},
        "confidence": {"type": "string"}, "risk_level": {"type": "string"},
        "evidence": {"type": "array", "minItems": 1, "items": {"type": "object", "additionalProperties": False,
                     "required": ["field", "value"], "properties": {
                         "field": {"type": "string", "enum": list(EVIDENCE_FIELD_PATHS)},
                         "value": {"anyOf": [{"type": "string"}, {"type": "number"}, {"type": "null"}]},
                     }}},
        "reasons": {"type": "string"}, "suggested_action": {"type": "string"}, "expected_effect": {"type": "string"},
    },
}

SYSTEM_INSTRUCTIONS = """Return only the required JSON object. Use only values supplied in the input JSON as evidence.
evidence.field must be one of the supplied complete JSON paths. Never use a shortened field name.
For example use observation.impressions or article.article_id, never impressions or article_id.
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


def response_structure_diagnostic(response: Mapping[str, Any]) -> dict[str, Any]:
    """Return only safe structural metadata; never response text or identifiers."""
    output = response.get("output")
    output_types = []
    content_types = []
    has_output_text = False
    has_refusal = False
    if isinstance(output, list):
        for item in output:
            if not isinstance(item, Mapping):
                output_types.append("invalid")
                continue
            item_type = item.get("type")
            output_types.append(item_type if isinstance(item_type, str) else "invalid")
            content = item.get("content")
            if isinstance(content, list):
                for part in content:
                    if not isinstance(part, Mapping):
                        content_types.append("invalid")
                        continue
                    part_type = part.get("type")
                    content_types.append(part_type if isinstance(part_type, str) else "invalid")
                    has_output_text = has_output_text or part_type == "output_text"
                    has_refusal = has_refusal or part_type == "refusal"
    usage = response.get("usage")
    safe_usage = {}
    if isinstance(usage, Mapping):
        for key in ("input_tokens", "output_tokens", "total_tokens"):
            if isinstance(usage.get(key), int):
                safe_usage[key] = usage[key]
    incomplete = response.get("incomplete_details")
    reason = incomplete.get("reason") if isinstance(incomplete, Mapping) and isinstance(incomplete.get("reason"), str) else None
    return {"http_status": 200, "response_status": response.get("status") if isinstance(response.get("status"), str) else None,
            "output_item_types": output_types, "content_item_types": content_types, "output_text_present": has_output_text,
            "refusal_present": has_refusal, "incomplete_reason": reason, "usage": safe_usage}


def _output_text(response: Mapping[str, Any]) -> str:
    """Extract exactly one text part from completed Responses API output items."""
    diagnostic = response_structure_diagnostic(response)
    status = diagnostic["response_status"]
    if status == "incomplete":
        raise OpenAiRecommendationResponseError("incomplete", diagnostic)
    if status != "completed":
        raise OpenAiRecommendationResponseError("unexpected_response_status", diagnostic)
    output = response.get("output")
    if not isinstance(output, list):
        raise OpenAiRecommendationResponseError("missing_output", diagnostic)
    texts = []
    for item in output:
        if not isinstance(item, Mapping):
            raise OpenAiRecommendationResponseError("unknown_output_item", diagnostic)
        item_type = item.get("type")
        if item_type == "reasoning":
            continue
        if item_type != "message" or item.get("role") != "assistant":
            raise OpenAiRecommendationResponseError("unknown_output_item", diagnostic)
        content = item.get("content")
        if not isinstance(content, list):
            raise OpenAiRecommendationResponseError("missing_message_content", diagnostic)
        for part in content:
            if not isinstance(part, Mapping):
                raise OpenAiRecommendationResponseError("unknown_content_item", diagnostic)
            part_type = part.get("type")
            if part_type == "refusal":
                raise OpenAiRecommendationResponseError("refusal", diagnostic)
            if part_type != "output_text" or not isinstance(part.get("text"), str):
                raise OpenAiRecommendationResponseError("unknown_content_item", diagnostic)
            texts.append(part["text"])
    if len(texts) != 1 or not texts[0]:
        raise OpenAiRecommendationResponseError("missing_or_ambiguous_output_text", diagnostic)
    return texts[0]


class OpenAiResponsesTransport(AiProposalTransport):
    """One-shot Responses API implementation; retries are intentionally absent."""

    def __init__(self, model_id: str, api_key: str | None = None, *, client_request_id: str | None = None):
        self._model_id = model_id
        self._api_key = (api_key if api_key is not None else os.environ.get("AI_RECOMMENDATION_OPENAI_API_KEY", "")).strip()
        if not self._api_key:
            raise OpenAiRecommendationError("OpenAI recommendation credential is unavailable")
        if client_request_id is not None and (not isinstance(client_request_id, str) or not client_request_id.isascii() or not 1 <= len(client_request_id) <= 512):
            raise OpenAiRecommendationError("OpenAI client request ID is invalid")
        self._client_request_id = client_request_id
        self.last_response_diagnostic: dict[str, Any] | None = None
        self.last_request_metadata: dict[str, Any] | None = None

    def propose(self, payload: Mapping[str, Any], *, max_input_tokens: int, max_output_tokens: int, timeout_seconds: int) -> Mapping[str, Any]:
        if max_input_tokens < 1 or max_output_tokens < 1 or timeout_seconds != 20:
            raise OpenAiRecommendationError("OpenAI recommendation limits are invalid")
        body = json.dumps(build_responses_payload(payload, self._model_id, max_output_tokens), separators=(",", ":")).encode("utf-8")
        headers = {"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"}
        if self._client_request_id is not None:
            headers["X-Client-Request-Id"] = self._client_request_id
        request = Request("https://api.openai.com/v1/responses", data=body, method="POST", headers=headers)
        try:
            with urlopen(request, timeout=timeout_seconds) as response:  # nosec B310 fixed API URL
                parsed = json.loads(response.read().decode("utf-8"))
                server_request_id = response.headers.get("x-request-id")
                self.last_request_metadata = {"client_request_id": self._client_request_id,
                                              "server_request_id": server_request_id if isinstance(server_request_id, str) else None}
        except HTTPError as error:
            raise _safe_http_error(error) from None
        except TimeoutError:
            raise
        except (URLError, OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise OpenAiRecommendationTransportError(_transport_error_code(error)) from None
        try:
            self.last_response_diagnostic = response_structure_diagnostic(parsed)
            return json.loads(_output_text(parsed))
        except OpenAiRecommendationResponseError:
            # The HTTP request completed and the response was understood well
            # enough to classify it.  Preserve that fact for the audit ledger;
            # it must not be treated as a delivery-unknown outcome.
            raise
        except (json.JSONDecodeError, OpenAiRecommendationError):
            raise OpenAiRecommendationError("OpenAI recommendation response was rejected") from None
