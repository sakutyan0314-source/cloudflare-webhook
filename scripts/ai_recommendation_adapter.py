"""Model-neutral, single-attempt adapter for v2.0-A proposal text generation."""

from __future__ import annotations

from typing import Any, Mapping, Protocol

from ai_recommendation_schema import RecommendationValidationError, validate_ai_response


class AiRecommendationError(RuntimeError):
    """A safe failure category with no provider response or secret details."""


class AiProposalTransport(Protocol):
    def propose(self, payload: Mapping[str, Any], *, max_input_tokens: int, max_output_tokens: int, timeout_seconds: int) -> Mapping[str, Any]:
        """Return one parsed JSON object. Implementations must not retry."""


class AiRecommendationAdapter:
    """Validates a single model response; provider wiring remains outside v2.0-A."""

    def __init__(self, transport: AiProposalTransport, *, max_input_tokens: int = 1800, max_output_tokens: int = 500, timeout_seconds: int = 20):
        if min(max_input_tokens, max_output_tokens, timeout_seconds) < 1:
            raise ValueError("AI limits must be positive")
        self._transport = transport
        self.limits = {"max_input_tokens": max_input_tokens, "max_output_tokens": max_output_tokens, "timeout_seconds": timeout_seconds,
                       "automatic_retry": False, "max_recommendations_per_article": 1}

    def recommend(self, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        if not payload["rule_assessment"]["ai_eligible"]:
            raise AiRecommendationError("AI is not eligible for this observation")
        try:
            response = self._transport.propose(payload, **{key: self.limits[key] for key in ("max_input_tokens", "max_output_tokens", "timeout_seconds")})
            return validate_ai_response(response, payload)
        # Provider-specific 4xx/5xx and malformed transport failures are all
        # collapsed to the same safe outcome.  No response body is retained and
        # no retry is attempted here.
        except Exception as error:
            raise AiRecommendationError("AI recommendation was rejected") from error
