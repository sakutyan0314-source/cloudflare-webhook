"""Single-attempt provider boundary for Phase 2B SEO improvement proposals."""

from __future__ import annotations

import json
from math import ceil
from typing import Any, Mapping, Protocol

from seo_improvement_proposal import (
    SeoImprovementProposalError,
    build_mock_proposal,
    build_proposal_input,
    validate_proposal,
)


PROVIDER = "openai"
MODEL_ID = "gpt-5.6-terra"
MAX_INPUT_TOKENS = 900
MAX_OUTPUT_TOKENS = 500
TIMEOUT_SECONDS = 20


class SeoImprovementProposalAdapterError(RuntimeError):
    """Safe, value-free provider or validation failure."""


class SeoImprovementProposalTransport(Protocol):
    def propose(self, payload: Mapping[str, Any], *, model_id: str, max_input_tokens: int,
                max_output_tokens: int, timeout_seconds: int, store: bool, tools: None) -> Mapping[str, Any]:
        """Perform exactly one provider request and return parsed JSON."""


def provider_config() -> dict[str, Any]:
    """Return the sole approved provider configuration; no fallback exists."""
    return {
        "provider": PROVIDER, "model_id": MODEL_ID, "max_input_tokens": MAX_INPUT_TOKENS,
        "max_output_tokens": MAX_OUTPUT_TOKENS, "timeout_seconds": TIMEOUT_SECONDS,
        "automatic_retry": False, "automatic_fallback": False, "store": False, "tools": None,
    }


def _estimated_input_tokens(payload: Mapping[str, Any]) -> int:
    try:
        return ceil(len(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")) / 4)
    except (TypeError, ValueError) as error:
        raise SeoImprovementProposalAdapterError("proposal input cannot be encoded") from error


class SeoImprovementProposalAdapter:
    """Builds server-owned input, makes one call, then validates one proposal."""

    def __init__(self, transport: SeoImprovementProposalTransport):
        self._transport = transport
        self.last_rejection_code: str | None = None
        self.limits = provider_config()

    def generate(self, envelope: Mapping[str, Any], accepted_review: Mapping[str, Any]) -> dict[str, Any]:
        self.last_rejection_code = None
        try:
            proposal_input = build_proposal_input(envelope, accepted_review, model_version=MODEL_ID)
            if _estimated_input_tokens(proposal_input) > MAX_INPUT_TOKENS:
                raise SeoImprovementProposalAdapterError("proposal input exceeds token limit")
            response = self._transport.propose(
                proposal_input, model_id=MODEL_ID, max_input_tokens=MAX_INPUT_TOKENS,
                max_output_tokens=MAX_OUTPUT_TOKENS, timeout_seconds=TIMEOUT_SECONDS,
                store=False, tools=None,
            )
            if not isinstance(response, Mapping):
                raise SeoImprovementProposalAdapterError("provider response is not a JSON object")
            proposal = build_mock_proposal(proposal_input, response)
            validate_proposal(proposal, proposal_input)
            return proposal
        except TimeoutError as error:
            self.last_rejection_code = "timeout"
            raise SeoImprovementProposalAdapterError("SEO proposal request timed out") from error
        except SeoImprovementProposalAdapterError:
            self.last_rejection_code = self.last_rejection_code or "provider_or_input_failure"
            raise
        except SeoImprovementProposalError as error:
            self.last_rejection_code = "proposal_validation_failed"
            raise SeoImprovementProposalAdapterError("SEO proposal response was rejected") from error
        except Exception as error:
            self.last_rejection_code = "provider_or_schema_failure"
            raise SeoImprovementProposalAdapterError("SEO proposal request failed") from error
