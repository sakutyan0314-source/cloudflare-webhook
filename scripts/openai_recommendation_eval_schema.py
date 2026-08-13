"""Static, reviewable configuration schema for v2.0-A OpenAI evals."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


EVAL_SCHEMA_VERSION = "v2.0-a-openai-eval-v1"
MAX_EVAL_CASES = 10
MAX_EVAL_MODELS = 3
MAX_EVAL_CALLS = MAX_EVAL_CASES * MAX_EVAL_MODELS
MAX_INPUT_TOKENS = 1800
MAX_OUTPUT_TOKENS = 500
TIMEOUT_SECONDS = 20
MAX_EVAL_COST_USD = 0.45


class EvalConfigurationError(ValueError):
    """Raised before an eval makes any API call."""


@dataclass(frozen=True)
class ModelCandidate:
    key: str
    model_id: str
    snapshot_id: str | None
    input_usd_per_million: float
    output_usd_per_million: float


# Verified against official OpenAI Docs on 2026-08-13.  Snapshot values are
# intentionally null until the API's available snapshot identifiers are
# checked during the separately approved live eval.
DEFAULT_CANDIDATES = (
    ModelCandidate("luna", "gpt-5.6-luna", None, 1.00, 6.00),
    ModelCandidate("terra", "gpt-5.6-terra", None, 2.50, 15.00),
    ModelCandidate("sol", "gpt-5.6-sol", None, 5.00, 30.00),
)


def validate_eval_plan(plan: Mapping[str, Any]) -> tuple[ModelCandidate, ...]:
    if not isinstance(plan, Mapping) or plan.get("schema_version") != EVAL_SCHEMA_VERSION:
        raise EvalConfigurationError("eval plan schema is invalid")
    models = plan.get("models")
    if not isinstance(models, list) or not 1 <= len(models) <= MAX_EVAL_MODELS:
        raise EvalConfigurationError("eval model count is invalid")
    result = []
    for item in models:
        if not isinstance(item, Mapping):
            raise EvalConfigurationError("eval model is invalid")
        candidate = ModelCandidate(item.get("key"), item.get("model_id"), item.get("snapshot_id"),
                                   item.get("input_usd_per_million"), item.get("output_usd_per_million"))
        if candidate.key not in {"luna", "terra", "sol"} or candidate.model_id not in {c.model_id for c in DEFAULT_CANDIDATES}:
            raise EvalConfigurationError("unapproved model candidate")
        if candidate.snapshot_id is not None and (not isinstance(candidate.snapshot_id, str) or not candidate.snapshot_id):
            raise EvalConfigurationError("snapshot_id is invalid")
        if not all(isinstance(value, (int, float)) and value >= 0 for value in (candidate.input_usd_per_million, candidate.output_usd_per_million)):
            raise EvalConfigurationError("token pricing is invalid")
        result.append(candidate)
    if len({item.model_id for item in result}) != len(result):
        raise EvalConfigurationError("duplicate model candidate")
    return tuple(result)


def estimate_cost_usd(candidate: ModelCandidate, input_tokens: int, output_tokens: int) -> float:
    if not all(isinstance(value, int) and value >= 0 for value in (input_tokens, output_tokens)):
        raise EvalConfigurationError("usage tokens are invalid")
    return round((input_tokens * candidate.input_usd_per_million + output_tokens * candidate.output_usd_per_million) / 1_000_000, 8)


def maximum_plan_cost_usd(candidates: tuple[ModelCandidate, ...]) -> float:
    """Upper bound before any call, using every allowed case at configured limits."""
    return round(sum(estimate_cost_usd(item, MAX_INPUT_TOKENS * MAX_EVAL_CASES, MAX_OUTPUT_TOKENS * MAX_EVAL_CASES) for item in candidates), 8)
