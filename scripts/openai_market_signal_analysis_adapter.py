"""OpenAI Responses transport for Market Analysis v1; exactly one call, no tools."""
from __future__ import annotations

import json
import os
import re
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from market_signal_analysis import ANALYSIS_SCHEMA_VERSION, MODEL_ID


class OpenAiMarketSignalAnalysisError(RuntimeError):
    """Safe provider error without a credential or raw provider response."""


class OpenAiMarketSignalAnalysisResponseError(OpenAiMarketSignalAnalysisError):
    """Fail-closed response shape with only safe structural metadata."""
    def __init__(self, code: str, diagnostic: Mapping[str, Any]):
        super().__init__("OpenAI market analysis response was rejected")
        self.code, self.diagnostic = code, dict(diagnostic)


_TEXT = {"type": "string"}
_CANDIDATE = {"type": "object", "additionalProperties": False,
    "required": ["topic", "reason", "market_evidence", "common_intent", "own_site_gap", "target_audience", "user_problem", "monetization_relevance", "duplicate_risk", "confidence", "requires_human_review"],
    "properties": {"topic": _TEXT, "reason": _TEXT, "market_evidence": _TEXT, "common_intent": {"type": "string", "enum": ["what", "how", "compare", "problem", "commercial_investigation", "business_use"]},
                   "own_site_gap": {"type": "string", "enum": ["already_covered", "cluster_sibling", "possible_gap", "high_duplicate_risk"]}, "target_audience": _TEXT, "user_problem": _TEXT, "monetization_relevance": _TEXT,
                   "duplicate_risk": {"type": "string", "enum": ["none", "low", "medium", "high"]}, "confidence": {"type": "string", "enum": ["low", "medium", "high"]}, "requires_human_review": {"type": "boolean", "enum": [True]}}}
RESPONSE_SCHEMA = {"type": "object", "additionalProperties": False,
    "required": ["schema_version", "query", "common_intents", "common_angles", "uncovered_questions", "own_site_gap_assessment", "candidate_drafts", "confidence", "requires_human_review", "content_generation_authorized", "publication_authorized", "execution_authorized"],
    "properties": {"schema_version": {"type": "string", "enum": [ANALYSIS_SCHEMA_VERSION]}, "query": _TEXT,
                   "common_intents": {"type": "array", "items": {"type": "string", "enum": ["what", "how", "compare", "problem", "commercial_investigation", "business_use"]}},
                   "common_angles": {"type": "array", "items": _TEXT},
                   "uncovered_questions": {"type": "array", "items": {"type": "object", "additionalProperties": False, "required": ["question", "classification"], "properties": {"question": _TEXT, "classification": {"type": "string", "enum": ["possible_gap", "hypothesis"]}}}},
                   "own_site_gap_assessment": {"type": "object", "additionalProperties": False, "required": ["classification", "rationale"], "properties": {"classification": {"type": "string", "enum": ["already_covered", "cluster_sibling", "possible_gap", "high_duplicate_risk"]}, "rationale": _TEXT}},
                   "candidate_drafts": {"type": "array", "items": _CANDIDATE}, "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
                   "requires_human_review": {"type": "boolean", "enum": [True]}, "content_generation_authorized": {"type": "boolean", "enum": [False]}, "publication_authorized": {"type": "boolean", "enum": [False]}, "execution_authorized": {"type": "boolean", "enum": [False]}}}
SYSTEM_INSTRUCTIONS = """Return only the supplied strict JSON schema. Analyze only supplied SERP and own-site metadata. Never request or infer competitor page bodies. Treat every uncovered question as a possible_gap or hypothesis, never proof. Do not claim demand is confirmed, do not copy or rewrite competitor content, and never authorize content generation, publication, or execution. Do not include secrets, tokens, raw logs, or article bodies."""


def build_responses_payload(payload: Mapping[str, Any], *, model_id: str, max_output_tokens: int, store: bool, tools: None) -> dict[str, Any]:
    if model_id != MODEL_ID or not isinstance(max_output_tokens, int) or max_output_tokens < 1 or store is not False or tools is not None:
        raise OpenAiMarketSignalAnalysisError("provider configuration is invalid")
    return {"model": model_id, "store": False, "reasoning": {"effort": "low"}, "max_output_tokens": max_output_tokens,
            "input": [{"role": "system", "content": [{"type": "input_text", "text": SYSTEM_INSTRUCTIONS}]}, {"role": "user", "content": [{"type": "input_text", "text": json.dumps(payload, ensure_ascii=False, separators=(",", ":"))}]}],
            "text": {"format": {"type": "json_schema", "name": "market_signal_analysis", "strict": True, "schema": RESPONSE_SCHEMA}}}


def response_structure_diagnostic(response: Mapping[str, Any]) -> dict[str, Any]:
    """Return only shape metadata; never text, IDs, input, headers, or response body."""
    output = response.get("output")
    output_types, content_types, message_count, output_text_count, refusal_present = [], [], 0, 0, False
    if isinstance(output, list):
        for item in output:
            if not isinstance(item, Mapping):
                output_types.append("invalid")
                continue
            item_type = item.get("type")
            output_types.append(item_type if isinstance(item_type, str) else "invalid")
            if item_type != "message":
                continue
            message_count += 1
            content = item.get("content")
            if not isinstance(content, list):
                content_types.append("invalid")
                continue
            for part in content:
                if not isinstance(part, Mapping):
                    content_types.append("invalid")
                    continue
                part_type = part.get("type")
                content_types.append(part_type if isinstance(part_type, str) else "invalid")
                output_text_count += int(part_type == "output_text")
                refusal_present = refusal_present or part_type == "refusal"
    incomplete = response.get("incomplete_details")
    reason = incomplete.get("reason") if isinstance(incomplete, Mapping) and isinstance(incomplete.get("reason"), str) else None
    return {"response_status": response.get("status") if isinstance(response.get("status"), str) else None,
            "incomplete_reason": reason, "output_item_count": len(output) if isinstance(output, list) else None,
            "output_item_types": output_types, "message_count": message_count, "content_item_types": content_types,
            "output_text_count": output_text_count, "refusal_present": refusal_present}


def _output_text(response: Mapping[str, Any]) -> str:
    diagnostic = response_structure_diagnostic(response)
    status = diagnostic["response_status"]
    if status == "incomplete":
        raise OpenAiMarketSignalAnalysisResponseError("incomplete", diagnostic)
    if status != "completed":
        raise OpenAiMarketSignalAnalysisResponseError("non_completed_status", diagnostic)
    output = response.get("output")
    if not isinstance(output, list):
        raise OpenAiMarketSignalAnalysisResponseError("missing_output", diagnostic)
    texts: list[str] = []
    for item in output:
        if not isinstance(item, Mapping):
            raise OpenAiMarketSignalAnalysisResponseError("unknown_output_type", diagnostic)
        item_type = item.get("type")
        if item_type == "reasoning":
            continue
        if item_type != "message" or item.get("role") != "assistant":
            raise OpenAiMarketSignalAnalysisResponseError("unknown_output_type", diagnostic)
        content = item.get("content")
        if not isinstance(content, list):
            raise OpenAiMarketSignalAnalysisResponseError("unknown_content_type", diagnostic)
        for part in content:
            if not isinstance(part, Mapping):
                raise OpenAiMarketSignalAnalysisResponseError("unknown_content_type", diagnostic)
            part_type = part.get("type")
            if part_type == "refusal":
                raise OpenAiMarketSignalAnalysisResponseError("refusal", diagnostic)
            if part_type != "output_text" or not isinstance(part.get("text"), str):
                raise OpenAiMarketSignalAnalysisResponseError("unknown_content_type", diagnostic)
            texts.append(part["text"])
    if len(texts) == 0:
        raise OpenAiMarketSignalAnalysisResponseError("missing_output_text", diagnostic)
    if len(texts) != 1:
        raise OpenAiMarketSignalAnalysisResponseError("ambiguous_output_text", diagnostic)
    if not texts[0]:
        raise OpenAiMarketSignalAnalysisResponseError("missing_output_text", diagnostic)
    return texts[0]


_SECRET_LIKE = re.compile(r"(?i)\b(?:api[_ -]?key|authorization|bearer|token|secret)\b\s*[:=]\s*\S+")


def _safe_error_text(value: object, *, maximum: int) -> str | None:
    if not isinstance(value, str):
        return None
    sanitized = _SECRET_LIKE.sub("[redacted]", value).replace("\r", " ").replace("\n", " ").strip()
    return sanitized[:maximum] if sanitized else None


def safe_http_error_diagnostic(error: HTTPError) -> dict[str, Any]:
    """Extract a bounded, value-free provider diagnostic without retaining its body."""
    output: dict[str, Any] = {"http_status": int(error.code)}
    try:
        raw = error.read(4096)
        parsed = json.loads(raw.decode("utf-8"))
        details = parsed.get("error") if isinstance(parsed, Mapping) else None
        if not isinstance(details, Mapping):
            return output
        for source, target, maximum in (("type", "error_type", 80), ("code", "error_code", 80), ("message", "error_message", 240)):
            safe = _safe_error_text(details.get(source), maximum=maximum)
            if safe is not None:
                output[target] = safe
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
        pass
    return output


class OpenAiMarketSignalAnalysisTransport:
    def __init__(self, api_key: str | None = None):
        self._api_key = (api_key if api_key is not None else os.environ.get("AI_RECOMMENDATION_OPENAI_API_KEY", "")).strip()
        if not self._api_key:
            raise OpenAiMarketSignalAnalysisError("OpenAI market analysis credential is unavailable")
        self.last_diagnostic: dict[str, Any] | None = None

    def analyze(self, payload: Mapping[str, Any], *, model_id: str, max_input_tokens: int, max_output_tokens: int, timeout_seconds: int, store: bool, tools: None) -> Mapping[str, Any]:
        if max_input_tokens != 1800 or timeout_seconds != 20:
            raise OpenAiMarketSignalAnalysisError("provider limits are invalid")
        self.last_diagnostic = None
        body = json.dumps(build_responses_payload(payload, model_id=model_id, max_output_tokens=max_output_tokens, store=store, tools=tools), separators=(",", ":")).encode()
        request = Request("https://api.openai.com/v1/responses", data=body, method="POST", headers={"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"})
        try:
            with urlopen(request, timeout=timeout_seconds) as response:  # nosec B310 fixed API URL
                parsed = json.loads(response.read().decode("utf-8"))
        except TimeoutError:
            raise
        except HTTPError as error:
            self.last_diagnostic = safe_http_error_diagnostic(error)
            raise OpenAiMarketSignalAnalysisError("OpenAI market analysis HTTP request failed") from error
        except (URLError, OSError, UnicodeDecodeError, json.JSONDecodeError, OpenAiMarketSignalAnalysisError) as error:
            raise OpenAiMarketSignalAnalysisError("OpenAI market analysis request failed") from error
        if not isinstance(parsed, Mapping):
            raise OpenAiMarketSignalAnalysisError("OpenAI market analysis response was rejected")
        diagnostic = response_structure_diagnostic(parsed)
        self.last_diagnostic = diagnostic
        try:
            return json.loads(_output_text(parsed))
        except OpenAiMarketSignalAnalysisResponseError as error:
            self.last_diagnostic = error.diagnostic
            raise
        except json.JSONDecodeError as error:
            raise OpenAiMarketSignalAnalysisResponseError("malformed_json", diagnostic) from error
