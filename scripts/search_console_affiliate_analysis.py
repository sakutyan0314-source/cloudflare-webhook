"""Deterministic, read-only article-level search and affiliate analysis."""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import Any, Iterable, Mapping


REPORT_SCHEMA_VERSION = "v1.10-e-search-affiliate-analysis-v1"

# Fixed, versioned thresholds.  They are emitted in every report so a result
# remains reproducible even after a later analysis version adopts new rules.
MIN_IMPRESSIONS_FOR_CLASSIFICATION = 10
MIN_SEARCH_CLICKS_FOR_TRAFFIC = 1
MIN_AFFILIATE_CLICKS_FOR_VALUE = 1


def _iso_date(value: object, name: str) -> str:
    try:
        return date.fromisoformat(str(value)).isoformat()
    except (TypeError, ValueError) as error:
        raise ValueError(f"{name} must use YYYY-MM-DD") from error


def _article_id(value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError("article_id must be a positive integer")
    return value


def _non_negative_int(row: Mapping[str, Any], name: str) -> int:
    value = row.get(name)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")
    return value


def _non_negative_number(row: Mapping[str, Any], name: str) -> float:
    value = row.get(name)
    if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{name} must be a non-negative number")
    return float(value)


def _normalized_page(row: Mapping[str, Any], start: str, end: str) -> tuple[int, int, int, float]:
    metric_date = _iso_date(row.get("metric_date"), "metric_date")
    if not start <= metric_date <= end:
        raise ValueError("page metric_date is outside the requested period")
    return (_article_id(row.get("article_id")), _non_negative_int(row, "clicks"),
            _non_negative_int(row, "impressions"), _non_negative_number(row, "position"))


def _normalized_affiliate(row: Mapping[str, Any], start: str, end: str) -> int:
    clicked_at = row.get("clicked_at")
    if not isinstance(clicked_at, str) or len(clicked_at) < 10:
        raise ValueError("clicked_at must be an ISO timestamp")
    clicked_date = _iso_date(clicked_at[:10], "clicked_at")
    if not start <= clicked_date <= end:
        raise ValueError("affiliate clicked_at is outside the requested period")
    if row.get("link_type") != "amazon_search" or row.get("placement") not in {"article", "discord"}:
        raise ValueError("affiliate event type is invalid")
    return _article_id(row.get("article_id"))


def _classification(impressions: int, clicks: int, affiliate_clicks: int) -> tuple[str, list[str]]:
    if impressions < MIN_IMPRESSIONS_FOR_CLASSIFICATION:
        return "insufficient_data", ["impressions_below_minimum"]
    if clicks >= MIN_SEARCH_CLICKS_FOR_TRAFFIC and affiliate_clicks >= MIN_AFFILIATE_CLICKS_FOR_VALUE:
        return "high_value", ["search_click_and_affiliate_click_thresholds_met"]
    if clicks >= MIN_SEARCH_CLICKS_FOR_TRAFFIC:
        return "traffic_only", ["search_click_threshold_met", "no_affiliate_click"]
    return "conversion_candidate", ["impression_threshold_met", "no_search_click"]


def build_search_affiliate_report(
    page_rows: Iterable[Mapping[str, Any]], affiliate_rows: Iterable[Mapping[str, Any]], start_date: str, end_date: str
) -> dict[str, Any]:
    """Create a JSON-compatible, deterministic report without external calls."""
    start, end = _iso_date(start_date, "start_date"), _iso_date(end_date, "end_date")
    if start > end:
        raise ValueError("start_date must be on or before end_date")
    metrics: dict[int, dict[str, float | int]] = defaultdict(lambda: {"clicks": 0, "impressions": 0, "weighted_position": 0.0})
    page_input_rows = 0
    for source in page_rows:
        article_id, clicks, impressions, position = _normalized_page(source, start, end)
        entry = metrics[article_id]
        entry["clicks"] += clicks
        entry["impressions"] += impressions
        entry["weighted_position"] += position * impressions
        page_input_rows += 1
    affiliate_counts: dict[int, int] = defaultdict(int)
    affiliate_input_rows = 0
    for source in affiliate_rows:
        affiliate_counts[_normalized_affiliate(source, start, end)] += 1
        affiliate_input_rows += 1
    articles = []
    for article_id in sorted(set(metrics) | set(affiliate_counts)):
        values = metrics[article_id]
        clicks, impressions = int(values["clicks"]), int(values["impressions"])
        affiliate_clicks = affiliate_counts[article_id]
        classification, reasons = _classification(impressions, clicks, affiliate_clicks)
        articles.append({
            "article_id": article_id,
            "impressions": impressions,
            "clicks": clicks,
            "ctr": round(clicks / impressions, 6) if impressions else 0.0,
            "position": round(float(values["weighted_position"]) / impressions, 6) if impressions else None,
            "affiliate_click_count": affiliate_clicks,
            "affiliate_click_rate": round(affiliate_clicks / clicks, 6) if clicks else None,
            "classification": classification,
            "reasons": reasons,
        })
    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "metric_family": "search_affiliate_article_daily",
        "period": {"start": start, "end": end},
        "thresholds": {
            "min_impressions_for_classification": MIN_IMPRESSIONS_FOR_CLASSIFICATION,
            "min_search_clicks_for_traffic": MIN_SEARCH_CLICKS_FOR_TRAFFIC,
            "min_affiliate_clicks_for_value": MIN_AFFILIATE_CLICKS_FOR_VALUE,
        },
        "summary": {
            "article_count": len(articles),
            "impressions": sum(item["impressions"] for item in articles),
            "clicks": sum(item["clicks"] for item in articles),
            "affiliate_click_count": sum(item["affiliate_click_count"] for item in articles),
        },
        "articles": articles,
        "diagnostics": {"page_daily_input_rows": page_input_rows, "affiliate_input_rows": affiliate_input_rows},
    }
