"""One-request-at-a-time eval executor backed by the crash-safe audit ledger.

No request is made on import.  Callers must explicitly supply a transport
factory; production wiring remains a separately approved operation.
"""

from __future__ import annotations

from typing import Any, Callable, Mapping

from ai_recommendation_schema import EvidenceValidationError, RecommendationValidationError, UnsafeAiResponseError, build_recommendation, diagnose_evidence
from openai_recommendation_adapter import OpenAiRecommendationHttpError, OpenAiRecommendationResponseError, OpenAiRecommendationTransportError
from openai_recommendation_run_audit import RunAuditLedger


class EvalExecutionError(RuntimeError):
    """Safe, non-retryable eval execution outcome."""


TransportFactory = Callable[[str, str], Any]


class SafeEvalExecutor:
    """Executes one planned request only after durable `send_started` evidence."""

    def __init__(self, ledger: RunAuditLedger, transport_factory: TransportFactory):
        self._ledger = ledger
        self._transport_factory = transport_factory

    def execute_one(
        self,
        request: Mapping[str, str],
        payload: Mapping[str, Any],
        *,
        generated_at: str,
        result_transform: Callable[[Mapping[str, Any]], Mapping[str, Any]] | None = None,
    ) -> dict[str, Any]:
        model_id = request.get("model_id")
        client_request_id = request.get("client_request_id")
        if not isinstance(model_id, str) or not isinstance(client_request_id, str):
            raise EvalExecutionError("planned request is invalid")
        # This fsync-backed transition happens before the transport is created.
        self._ledger.begin_request(client_request_id)
        transport = self._transport_factory(model_id, client_request_id)
        try:
            response = transport.propose(payload, max_input_tokens=1800, max_output_tokens=500, timeout_seconds=20)
        except OpenAiRecommendationHttpError as error:
            self._ledger.finalize(client_request_id, "result_known", http_status=error.status, classification="http_error")
            raise EvalExecutionError("OpenAI returned an HTTP error") from None
        except OpenAiRecommendationResponseError as error:
            classification = "response_" + error.code
            self._ledger.finalize(client_request_id, "result_known", http_status=200, classification=classification)
            raise EvalExecutionError("OpenAI response failed closed") from None
        except TimeoutError:
            self._ledger.finalize(client_request_id, "outcome_unknown", http_status=None, classification="timeout")
            raise EvalExecutionError("OpenAI delivery outcome is unknown") from None
        except OpenAiRecommendationTransportError as error:
            self._ledger.finalize(client_request_id, "outcome_unknown", http_status=None, classification=error.code)
            raise EvalExecutionError("OpenAI delivery outcome is unknown") from None
        except KeyboardInterrupt:
            self._ledger.finalize(client_request_id, "outcome_unknown", http_status=None, classification="local_process_interrupted")
            raise EvalExecutionError("OpenAI delivery outcome is unknown") from None
        except Exception:
            # Do not retry: this covers connection loss after send_started.
            self._ledger.finalize(client_request_id, "outcome_unknown", http_status=None, classification="delivery_unknown")
            raise EvalExecutionError("OpenAI delivery outcome is unknown") from None

        usage = getattr(transport, "last_response_diagnostic", {}).get("usage", {})
        metadata = getattr(transport, "last_request_metadata", {}) or {}
        input_tokens = usage.get("input_tokens", 0) if isinstance(usage.get("input_tokens", 0), int) else 0
        output_tokens = usage.get("output_tokens", 0) if isinstance(usage.get("output_tokens", 0), int) else 0
        server_request_id = metadata.get("server_request_id") if isinstance(metadata.get("server_request_id"), str) else None
        try:
            evidence = diagnose_evidence(response.get("evidence"), payload) if isinstance(response, Mapping) else {"code": "response_not_object"}
            if evidence.get("code") is not None:
                raise EvidenceValidationError(evidence["code"], evidence)
            result = build_recommendation(payload, response, generated_at=generated_at)
        except EvidenceValidationError:
            classification = "evidence_invalid"
        except UnsafeAiResponseError as error:
            # The ledger stores only a predeclared category code, never model
            # text or a detected fragment.  The first code is deterministic.
            classification = error.diagnostic.get("codes", ["other_prohibited_expression"])[0]
        except RecommendationValidationError:
            classification = "schema_invalid"
        else:
            # Eval callers receive only aggregate-safe values.  The production
            # path may supply a local transform that creates the explicitly
            # approved human-review envelope from this already validated,
            # server-reconstructed recommendation.  Neither path persists the
            # model response or creates a database record.
            if result_transform is not None:
                try:
                    transformed = result_transform(result)
                except Exception:
                    self._ledger.finalize(client_request_id, "result_known", http_status=200, classification="review_transform_invalid",
                                          input_tokens=input_tokens, output_tokens=output_tokens, server_request_id=server_request_id)
                    raise EvalExecutionError("review transform is invalid") from None
                if not isinstance(transformed, Mapping):
                    self._ledger.finalize(client_request_id, "result_known", http_status=200, classification="review_transform_invalid",
                                          input_tokens=input_tokens, output_tokens=output_tokens, server_request_id=server_request_id)
                    raise EvalExecutionError("review transform is invalid")
                self._ledger.finalize(client_request_id, "result_known", http_status=200, classification="recommendation_generated",
                                      input_tokens=input_tokens, output_tokens=output_tokens, server_request_id=server_request_id)
                return dict(transformed)
            self._ledger.finalize(client_request_id, "result_known", http_status=200, classification="recommendation_generated",
                                  input_tokens=input_tokens, output_tokens=output_tokens, server_request_id=server_request_id)
            return {"state": "result_known", "classification": "recommendation_generated", "recommendation_generated": True,
                    "recommendation_type": result["recommendation_type"], "priority": result["priority"],
                    "confidence": result["confidence"], "requires_human_review": result["requires_human_review"]}
        self._ledger.finalize(client_request_id, "result_known", http_status=200, classification=classification,
                              input_tokens=input_tokens, output_tokens=output_tokens, server_request_id=server_request_id)
        raise EvalExecutionError("OpenAI response failed safety validation")
