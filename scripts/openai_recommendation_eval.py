"""Bounded, non-persistent eval runner for v2.0-A OpenAI model candidates."""

from __future__ import annotations

from statistics import mean
from time import monotonic
from typing import Any, Iterable, Mapping, Protocol

from ai_recommendation_analysis import analyze
from ai_recommendation_adapter import AiRecommendationAdapter, AiRecommendationError
from openai_recommendation_eval_schema import (MAX_EVAL_CALLS, MAX_EVAL_CASES, MAX_EVAL_COST_USD, ModelCandidate, estimate_cost_usd, maximum_plan_cost_usd, validate_eval_plan)


class EvalTransportFactory(Protocol):
    def create(self, candidate: ModelCandidate) -> AiRecommendationAdapter: ...


def _percent(part: int, total: int) -> float:
    return round(part / total, 6) if total else 0.0


def run_eval(plan: Mapping[str, Any], fixtures: Iterable[Mapping[str, Any]], factory: EvalTransportFactory) -> dict[str, Any]:
    """Run at most ten local fixtures across three models.  Results are returned only."""
    candidates = validate_eval_plan(plan)
    cases = list(fixtures)
    if not 1 <= len(cases) <= MAX_EVAL_CASES or len(cases) * len(candidates) > MAX_EVAL_CALLS:
        raise ValueError("eval call budget exceeded")
    planned_cost = maximum_plan_cost_usd(candidates)
    if planned_cost > MAX_EVAL_COST_USD:
        raise ValueError("eval cost budget exceeded")
    reports = []
    for candidate in candidates:
        adapter = factory.create(candidate)
        rows, latencies, costs, ai_calls = [], [], [], 0
        for fixture in cases:
            started = monotonic()
            accepted = False
            rejected = False
            try:
                result = analyze(fixture["article"], fixture["observation"], adapter, generated_at="2026-08-13T00:00:00Z")
                accepted = result["recommendation_type"] == fixture["expected_type"]
            except (AiRecommendationError, ValueError):
                rejected = True
            rejection_code = getattr(adapter, "last_rejection_code", None)
            elapsed = round((monotonic() - started) * 1000, 3)
            usage = fixture.get("mock_usage", {"input_tokens": 0, "output_tokens": 0})
            cost = estimate_cost_usd(candidate, usage["input_tokens"], usage["output_tokens"])
            ai_expected = fixture["expected_type"] not in {"insufficient_data", "continue_observation"}
            if ai_expected:
                ai_calls += 1
            rows.append({"case_id": fixture["case_id"], "accepted": accepted, "rejected": rejected,
                         "rejection_code": rejection_code, "ai_expected": ai_expected, "human_review_quality": "pending"})
            latencies.append(elapsed); costs.append(cost)
        total = len(rows)
        ai_rows = [row for row in rows if row["ai_expected"]]
        reports.append({"candidate": candidate.model_id, "snapshot_id": candidate.snapshot_id, "cases": rows,
                        "metrics": {"structured_outputs_success_rate": _percent(sum(row["accepted"] for row in ai_rows), len(ai_rows)),
                                    "server_schema_pass_rate": _percent(sum(row["accepted"] for row in ai_rows), len(ai_rows)),
                                    "evidence_pass_rate": _percent(sum(row["accepted"] for row in ai_rows), len(ai_rows)),
                                    "forbidden_expression_violation_rate": _percent(sum(row["rejection_code"] == "prohibited_expression_or_secret" for row in ai_rows), len(ai_rows)),
                                    "outside_candidate_rate": _percent(sum(row["rejection_code"] == "outside_candidate" for row in ai_rows), len(ai_rows)),
                                    "priority_confidence_valid_rate": _percent(sum(row["accepted"] for row in ai_rows), len(ai_rows)),
                                    "stability_status": "requires_repeated_live_runs",
                                    "rejected_rate": _percent(sum(row["rejected"] for row in rows), total),
                                    "average_latency_ms": round(mean(latencies), 3), "p95_latency_ms": sorted(latencies)[max(0, int(total * .95) - 1)],
                                    "input_tokens": sum(item.get("mock_usage", {}).get("input_tokens", 0) for item in cases),
                                    "output_tokens": sum(item.get("mock_usage", {}).get("output_tokens", 0) for item in cases),
                                    "estimated_cost_usd": round(sum(costs), 8), "human_review_quality": "pending"},
                        "ai_calls": ai_calls})
    return {"schema_version": "v2.0-a-openai-eval-report-v1", "call_budget": {"max_cases": MAX_EVAL_CASES, "max_models": 3,
            "max_calls": MAX_EVAL_CALLS, "actual_calls": sum(item["ai_calls"] for item in reports),
            "maximum_cost_usd": MAX_EVAL_COST_USD, "planned_upper_bound_usd": planned_cost}, "models": reports}
