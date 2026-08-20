"""Read-only, deterministic Phase 2A article-improvement candidate extraction.

This module does not call D1, Search Console, or an AI provider. Its optional
reader adapter accepts the existing fixed-SELECT reader only and returns a
human-review list; it never persists recommendations or changes articles.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from typing import Any, Mapping, Sequence
from urllib.parse import urlsplit


REPORT_SCHEMA_VERSION = "phase-2a-improvement-candidates-v1"
PERIOD_DAYS = 7
MIN_OBSERVATION_DAYS = 7
MIN_IMPRESSIONS = 10
CTR_LOW_THRESHOLD = 0.02
POSITION_MIN = 4.0
POSITION_MAX = 20.0

# Page-daily has no query or snippet-rendering data from which to distinguish
# title from description. A zero-click candidate therefore remains neutral.
RECOMMENDATION_IMPROVE_SNIPPET = "improve_snippet"

# No CTR baseline exists in the prior rules. This explicit initial policy is a
# conservative, review-only cutoff: at least 10 impressions and <=2% CTR.
# It is versioned here so a future threshold change is reviewable and tested.


class CandidateExtractionError(ValueError):
    """Input did not satisfy the fixed, read-only candidate contract."""


def _date(value: object, field: str) -> date:
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError) as error:
        raise CandidateExtractionError(f"{field} must use YYYY-MM-DD") from error


def _periods(current_start: str, current_end: str) -> tuple[date, date, date, date]:
    start, end = _date(current_start, "current_period_start"), _date(current_end, "current_period_end")
    if start > end or (end - start).days + 1 != PERIOD_DAYS:
        raise CandidateExtractionError("current period must contain exactly seven days")
    return start, end, start - timedelta(days=PERIOD_DAYS), start - timedelta(days=1)


def _number(row: Mapping[str, Any], field: str, *, integer: bool = False) -> int | float:
    value = row.get(field)
    if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0:
        raise CandidateExtractionError(f"{field} is invalid")
    if integer:
        if int(value) != value:
            raise CandidateExtractionError(f"{field} must be an integer")
        return int(value)
    return float(value)


def _valid_article_url(row: Mapping[str, Any], article_id: int) -> bool:
    if row.get("url_kind") != "article" or row.get("article_id") != article_id:
        return False
    page_url, property_uri = row.get("page_url"), row.get("property_uri")
    if not isinstance(page_url, str) or not isinstance(property_uri, str):
        return False
    page, property_url = urlsplit(page_url), urlsplit(property_uri)
    return (
        property_url.scheme in {"https", "http"}
        and property_url.netloc
        and property_url.path == "/"
        and property_url.query == property_url.fragment == ""
        and (page.scheme, page.netloc, page.path, page.query, page.fragment)
        == (property_url.scheme, property_url.netloc, f"/article/{article_id}", "", "")
    )


def _empty_summary() -> dict[str, Any]:
    return {"days": set(), "clicks": 0, "impressions": 0, "weighted_position": 0.0}


def _summary(value: Mapping[str, Any]) -> dict[str, Any]:
    impressions = int(value["impressions"])
    clicks = int(value["clicks"])
    return {
        "days": len(value["days"]), "clicks": clicks, "impressions": impressions,
        "ctr": round(clicks / impressions, 6) if impressions else None,
        "position": round(float(value["weighted_position"]) / impressions, 6) if impressions else None,
    }


def _assessment(article: Mapping[str, Any], current: Mapping[str, Any], previous: Mapping[str, Any], periods: tuple[date, date, date, date]) -> dict[str, Any]:
    current_start, current_end, previous_start, previous_end = periods
    current_days, previous_days = current["days"], previous["days"]
    common = {
        "article_id": article["article_id"], "title": article["title"],
        "current_period_start": current_start.isoformat(), "current_period_end": current_end.isoformat(),
        "previous_period_start": previous_start.isoformat(), "previous_period_end": previous_end.isoformat(),
        "current_clicks": current["clicks"], "previous_clicks": previous["clicks"],
        "clicks_delta": current["clicks"] - previous["clicks"],
        "current_impressions": current["impressions"], "previous_impressions": previous["impressions"],
        "impressions_delta": current["impressions"] - previous["impressions"],
        "current_ctr": current["ctr"], "previous_ctr": previous["ctr"],
        "ctr_delta": None if current["ctr"] is None or previous["ctr"] is None else round(current["ctr"] - previous["ctr"], 6),
        "current_position": current["position"], "previous_position": previous["position"],
        "position_delta": None if current["position"] is None or previous["position"] is None else round(current["position"] - previous["position"], 6),
    }
    if current_days < MIN_OBSERVATION_DAYS or previous_days < MIN_OBSERVATION_DAYS:
        return {**common, "recommendation_type": "insufficient_data", "reason_code": "observation_days_below_minimum", "data_status": "insufficient_data", "is_candidate": False}
    if current["impressions"] < MIN_IMPRESSIONS or previous["impressions"] < MIN_IMPRESSIONS:
        return {**common, "recommendation_type": "insufficient_data", "reason_code": "impressions_below_minimum", "data_status": "insufficient_data", "is_candidate": False}
    clicks_delta, impressions_delta = common["clicks_delta"], common["impressions_delta"]
    if clicks_delta > 0 and impressions_delta >= 0:
        return {**common, "recommendation_type": "continue_observation", "reason_code": "growing_trend", "data_status": "sufficient", "is_candidate": False}
    if clicks_delta < 0 and impressions_delta < 0:
        return {**common, "recommendation_type": "refresh_content", "reason_code": "clicks_and_impressions_declined", "data_status": "sufficient", "is_candidate": True}
    if current["clicks"] == 0:
        return {**common, "recommendation_type": RECOMMENDATION_IMPROVE_SNIPPET, "reason_code": "impressions_with_zero_clicks", "data_status": "sufficient", "is_candidate": True}
    if current["position"] is not None and POSITION_MIN <= current["position"] <= POSITION_MAX and current["ctr"] is not None and current["ctr"] <= CTR_LOW_THRESHOLD:
        return {**common, "recommendation_type": "improve_ctr", "reason_code": "position_opportunity_with_low_ctr", "data_status": "sufficient", "is_candidate": True}
    return {**common, "recommendation_type": "continue_observation", "reason_code": "stable_or_non_actionable_trend", "data_status": "sufficient", "is_candidate": False}


def build_improvement_candidate_report(page_rows: Sequence[Mapping[str, Any]], article_rows: Sequence[Mapping[str, Any]], current_period_start: str, current_period_end: str) -> dict[str, Any]:
    """Create one fixed assessment per eligible article, without I/O or writes."""
    periods = _periods(current_period_start, current_period_end)
    current_start, current_end, previous_start, previous_end = periods
    articles: dict[int, Mapping[str, Any]] = {}
    excluded_articles = 0
    for row in article_rows:
        article_id = row.get("article_id")
        if not isinstance(article_id, int) or article_id < 1 or article_id in articles or row.get("seo_status") != "ready" or not isinstance(row.get("title"), str) or not row["title"].strip():
            excluded_articles += 1
            continue
        articles[article_id] = row
    buckets: dict[int, dict[str, dict[str, Any]]] = defaultdict(lambda: {"current": _empty_summary(), "previous": _empty_summary()})
    excluded_metrics = 0
    for row in page_rows:
        article_id = row.get("article_id")
        if not isinstance(article_id, int) or article_id not in articles or not _valid_article_url(row, article_id):
            excluded_metrics += 1
            continue
        metric_date = _date(row.get("metric_date"), "metric_date")
        bucket = "current" if current_start <= metric_date <= current_end else "previous" if previous_start <= metric_date <= previous_end else None
        if bucket is None:
            excluded_metrics += 1
            continue
        clicks, impressions, position = _number(row, "clicks", integer=True), _number(row, "impressions", integer=True), _number(row, "position")
        target = buckets[article_id][bucket]
        target["days"].add(metric_date)
        target["clicks"] += clicks
        target["impressions"] += impressions
        target["weighted_position"] += position * impressions
    assessments = [_assessment(articles[article_id], _summary(buckets[article_id]["current"]), _summary(buckets[article_id]["previous"]), periods) for article_id in sorted(buckets)]
    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "current_period": {"start": current_start.isoformat(), "end": current_end.isoformat()},
        "previous_period": {"start": previous_start.isoformat(), "end": previous_end.isoformat()},
        "thresholds": {"min_observation_days": MIN_OBSERVATION_DAYS, "min_impressions": MIN_IMPRESSIONS, "low_ctr_threshold": CTR_LOW_THRESHOLD, "position_min": POSITION_MIN, "position_max": POSITION_MAX},
        "assessments": assessments,
        "candidates": [item for item in assessments if item["is_candidate"]],
        "diagnostics": {"excluded_article_metadata_rows": excluded_articles, "excluded_metric_rows": excluded_metrics},
    }


def read_and_build_improvement_candidate_report(reader: Any, property_uri: str, search_type: str, current_period_start: str, current_period_end: str) -> dict[str, Any]:
    """Use only the existing fixed-SELECT recommendation source reader."""
    fetch_source = getattr(reader, "fetch_source", None)
    if not callable(fetch_source):
        raise CandidateExtractionError("candidate source reader is invalid")
    page_rows, _affiliate_rows, article_rows = fetch_source(property_uri, search_type, current_period_start, current_period_end)
    return build_improvement_candidate_report(page_rows, article_rows, current_period_start, current_period_end)
