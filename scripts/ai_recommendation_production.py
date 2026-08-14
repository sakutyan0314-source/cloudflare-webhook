"""Read-only, review-only production execution path for v2.0-A.

This module coordinates existing v1.10-B/E analysis with v2.0-A rules and a
single Terra adapter.  It writes neither D1 nor recommendations and leaves
article, Worker, Cron, pipeline, and Discord behavior untouched.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Callable, Mapping, Sequence

from ai_recommendation_analysis import analyze, build_input
from ai_recommendation_review import build_review_envelope
from openai_recommendation_eval_runner import EvalExecutionError, SafeEvalExecutor
from openai_recommendation_run_audit import RunAuditLedger, build_request_plan
from search_console_affiliate_analysis import build_search_affiliate_report
from search_console_page_daily_analysis import build_page_daily_report


PRODUCTION_PROVIDER = "openai"
PRODUCTION_MODEL_ID = "gpt-5.6-terra"
SNAPSHOT_ID: None = None
SNAPSHOT_STATUS = "unfixed_requires_canary_eval_and_human_approval"
MAX_ARTICLES_PER_BATCH = 10
MAX_API_CALLS_PER_BATCH = 10
MAX_INPUT_TOKENS = 1800
MAX_OUTPUT_TOKENS = 500
TIMEOUT_SECONDS = 20
MAX_ESTIMATED_COST_USD = 0.12
TERRA_INPUT_USD_PER_MTOKEN = 2.50
TERRA_OUTPUT_USD_PER_MTOKEN = 15.00


class ProductionRecommendationSafetyError(RuntimeError):
    """A fail-closed boundary before article or provider side effects."""


def production_provider_config(*, model_id: str = PRODUCTION_MODEL_ID, snapshot_id: str | None = SNAPSHOT_ID) -> dict[str, Any]:
    """Terra is exact-only; aliases, Luna, Sol, and unapproved snapshots stop."""
    if model_id != PRODUCTION_MODEL_ID:
        raise ProductionRecommendationSafetyError("only the approved Terra model ID is allowed")
    if snapshot_id is not None:
        raise ProductionRecommendationSafetyError("snapshot is not approved for production")
    return {"provider": PRODUCTION_PROVIDER, "model_id": PRODUCTION_MODEL_ID, "snapshot_id": None,
            "snapshot_status": SNAPSHOT_STATUS, "automatic_fallback": False, "automatic_retry": False,
            "timeout_seconds": TIMEOUT_SECONDS, "max_input_tokens": MAX_INPUT_TOKENS,
            "max_output_tokens": MAX_OUTPUT_TOKENS, "store": False, "tools": "omitted"}


def estimate_batch_cost(article_count: int) -> float:
    """Conservative configured ceiling; actual billing is provider-side."""
    if not isinstance(article_count, int) or article_count < 0 or article_count > MAX_API_CALLS_PER_BATCH:
        raise ProductionRecommendationSafetyError("article batch limit is invalid")
    return round(article_count * ((MAX_INPUT_TOKENS * TERRA_INPUT_USD_PER_MTOKEN + MAX_OUTPUT_TOKENS * TERRA_OUTPUT_USD_PER_MTOKEN) / 1_000_000), 8)


def _age_days(published_at: object, current_end: str) -> int | None:
    if not isinstance(published_at, str):
        return None
    try:
        return max(0, (date.fromisoformat(current_end) - date.fromisoformat(published_at[:10])).days)
    except ValueError:
        return None


def build_production_inputs(
    page_rows: Sequence[Mapping[str, Any]], affiliate_rows: Sequence[Mapping[str, Any]], article_rows: Sequence[Mapping[str, Any]],
    start_date: str, end_date: str,
) -> list[dict[str, Any]]:
    """Reuse v1.10-B/E to construct validated AI inputs; no provider call occurs."""
    page_report = build_page_daily_report(page_rows, start_date, end_date)
    current_page_rows = [row for row in page_rows if row.get("metric_date") >= start_date]
    affiliate_report = build_search_affiliate_report(current_page_rows, affiliate_rows, start_date, end_date)
    metadata: dict[int, Mapping[str, Any]] = {}
    for row in article_rows:
        article_id = row.get("article_id")
        if not isinstance(article_id, int) or article_id < 1 or article_id in metadata:
            raise ProductionRecommendationSafetyError("article metadata is invalid")
        if not all(isinstance(row.get(key), str) and row[key].strip() for key in ("title", "description", "category")):
            raise ProductionRecommendationSafetyError("article metadata is incomplete")
        metadata[article_id] = row
    trend_by_article = {item["article_id"]: item for item in page_report["articles"]}
    affiliate_by_article = {item["article_id"]: item for item in affiliate_report["articles"]}
    metric_article_ids = set(trend_by_article) | set(affiliate_by_article)
    if not metric_article_ids <= set(metadata):
        raise ProductionRecommendationSafetyError("observability data does not map to a ready article")
    inputs = []
    for article_id in sorted(metric_article_ids):
        trend_item, affiliate_item, article = trend_by_article.get(article_id), affiliate_by_article.get(article_id), metadata[article_id]
        current = trend_item["current"] if trend_item else {"days_observed": 0, "clicks": 0, "impressions": 0, "ctr": None, "position": None}
        affiliate = affiliate_item or {"affiliate_click_count": 0, "affiliate_click_rate": None, "classification": "insufficient_data"}
        observation = {
            "period": {"start": start_date, "end": end_date}, "observation_days": current["days_observed"],
            "impressions": current["impressions"], "search_clicks": current["clicks"], "ctr": current["ctr"] or 0.0,
            "position": current["position"], "affiliate_click_count": affiliate["affiliate_click_count"],
            "affiliate_click_rate": affiliate["affiliate_click_rate"],
            "search_affiliate_classification": affiliate["classification"],
            "trend": trend_item["trend"]["classification"] if trend_item else "insufficient_data",
        }
        article_input = {"article_id": article_id, "title": article["title"], "description": article["description"],
                         "category": article["category"], "h2_headings": [], "published_at": article.get("published_at"),
                         "updated_at": article.get("updated_at"), "article_age_days": _age_days(article.get("published_at"), end_date)}
        inputs.append(build_input(article_input, observation))
    if len(inputs) > MAX_ARTICLES_PER_BATCH:
        raise ProductionRecommendationSafetyError("article batch exceeds the approved maximum")
    if estimate_batch_cost(sum(item["rule_assessment"]["ai_eligible"] for item in inputs)) > MAX_ESTIMATED_COST_USD:
        raise ProductionRecommendationSafetyError("estimated API cost exceeds the approved maximum")
    return inputs


def read_and_build_production_inputs(
    reader: Any, property_uri: str, search_type: str, start_date: str, end_date: str
) -> list[dict[str, Any]]:
    """Use the dedicated fixed-SELECT reader as the only production D1 input."""
    fetch_source = getattr(reader, "fetch_source", None)
    if not callable(fetch_source):
        raise ProductionRecommendationSafetyError("production source reader is invalid")
    page_rows, affiliate_rows, article_rows = fetch_source(property_uri, search_type, start_date, end_date)
    return build_production_inputs(page_rows, affiliate_rows, article_rows, start_date, end_date)


def prepare_terra_request_plan(run_id: str, inputs: Sequence[Mapping[str, Any]]) -> list[dict[str, str]]:
    """Plan only AI-eligible articles; observation-only proposals require no API call."""
    production_provider_config()
    ids = [f"article_{item['article']['article_id']}" for item in inputs if item["rule_assessment"]["ai_eligible"]]
    if len(ids) > MAX_API_CALLS_PER_BATCH:
        raise ProductionRecommendationSafetyError("API call limit is exceeded")
    return build_request_plan(run_id, PRODUCTION_MODEL_ID, ids) if ids else []


def run_review_only_batch(
    inputs: Sequence[Mapping[str, Any]], plan: Sequence[Mapping[str, str]], ledger: RunAuditLedger,
    transport_factory: Callable[[str, str], Any], *, generated_at: str,
) -> list[dict[str, Any]]:
    """Create in-memory review envelopes; stop on any provider safety outcome."""
    production_provider_config()
    requests = {request["fixture_id"]: request for request in plan}
    executor = SafeEvalExecutor(ledger, transport_factory)
    envelopes: list[dict[str, Any]] = []
    for payload in inputs:
        fixture_id = f"article_{payload['article']['article_id']}"
        if not payload["rule_assessment"]["ai_eligible"]:
            recommendation = analyze(payload["article"], payload["observation"], None, generated_at=generated_at)
            recommendation["category"], recommendation["title"] = payload["article"]["category"], payload["article"]["title"]
            envelopes.append(build_review_envelope(recommendation))
            continue
        request = requests.get(fixture_id)
        if request is None:
            raise ProductionRecommendationSafetyError("missing planned Terra request")
        envelope = executor.execute_one(request, payload, generated_at=generated_at, result_transform=lambda result: build_review_envelope({**result, "category": payload["article"]["category"], "title": payload["article"]["title"]}))
        envelopes.append(envelope)
    return envelopes
