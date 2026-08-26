"""One-call provider-neutral boundary for Market Analysis v1."""
from __future__ import annotations

from typing import Any, Mapping, Protocol

from market_signal_analysis import (MAX_INPUT_TOKENS, MAX_OUTPUT_TOKENS, TIMEOUT_SECONDS, MarketAnalysisError,
                                    build_market_analysis_input, provider_config, validate_market_analysis)


class MarketSignalAnalysisAdapterError(RuntimeError):
    """Sanitized analysis failure; never exposes provider response text."""
    def __init__(self, message: str, *, code: str | None = None, diagnostic: Mapping[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.diagnostic = dict(diagnostic) if isinstance(diagnostic, Mapping) else None


class MarketSignalAnalysisTransport(Protocol):
    def analyze(self, payload: Mapping[str, Any], *, model_id: str, max_input_tokens: int, max_output_tokens: int,
                timeout_seconds: int, store: bool, tools: None) -> Mapping[str, Any]: ...


class MarketSignalAnalysisAdapter:
    def __init__(self, transport: MarketSignalAnalysisTransport):
        self._transport = transport
        self.limits = provider_config()
        self.last_rejection_code: str | None = None

    def build_input(self, *, query: str, observed_at: str, serp_results: list[Mapping[str, Any]], own_site_signal: Mapping[str, Any]) -> dict[str, Any]:
        """The one input-builder contract shared by preflight and live analysis."""
        return build_market_analysis_input(query=query, observed_at=observed_at, serp_results=serp_results,
                                           own_site_signal=own_site_signal)

    def analyze_input(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        """Send an already-validated input exactly once; no retry or fallback."""
        self.last_rejection_code = None
        try:
            response = self._transport.analyze(payload, model_id=self.limits["model_id"], max_input_tokens=MAX_INPUT_TOKENS,
                                               max_output_tokens=MAX_OUTPUT_TOKENS, timeout_seconds=TIMEOUT_SECONDS, store=False, tools=None)
            if not isinstance(response, Mapping):
                raise MarketSignalAnalysisAdapterError("provider response is not a JSON object")
            return validate_market_analysis(response, payload)
        except TimeoutError as error:
            self.last_rejection_code = "timeout"
            raise MarketSignalAnalysisAdapterError("market analysis timed out", code=self.last_rejection_code,
                                                   diagnostic={"delivery_state": "unknown"}) from error
        except MarketAnalysisError as error:
            self.last_rejection_code = "schema_or_policy_failure"
            raise MarketSignalAnalysisAdapterError(
                "market analysis was rejected", code=self.last_rejection_code,
                diagnostic=getattr(error, "diagnostic", None)
            ) from error
        except MarketSignalAnalysisAdapterError:
            self.last_rejection_code = self.last_rejection_code or "provider_or_input_failure"
            raise
        except Exception as error:
            code = getattr(error, "code", None)
            diagnostic = getattr(error, "diagnostic", None)
            self.last_rejection_code = code if isinstance(code, str) else "provider_failure"
            raise MarketSignalAnalysisAdapterError("market analysis request failed", code=self.last_rejection_code, diagnostic=diagnostic) from error

    def analyze(self, *, query: str, observed_at: str, serp_results: list[Mapping[str, Any]], own_site_signal: Mapping[str, Any]) -> dict[str, Any]:
        try:
            payload = self.build_input(query=query, observed_at=observed_at, serp_results=serp_results,
                                       own_site_signal=own_site_signal)
        except MarketAnalysisError as error:
            self.last_rejection_code = "schema_or_policy_failure"
            raise MarketSignalAnalysisAdapterError("market analysis was rejected", code=self.last_rejection_code,
                                                   diagnostic=getattr(error, "diagnostic", None)) from error
        return self.analyze_input(payload)
