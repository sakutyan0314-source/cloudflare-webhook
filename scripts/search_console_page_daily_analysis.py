"""Pure, fixed-schema analysis for stored Search Console page-daily metrics."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from typing import Any, Iterable, Mapping


REPORT_SCHEMA_VERSION = "v1.10-b-page-daily-analysis-v1"
URL_KINDS = frozenset({"article", "category", "top", "listing", "unknown"})


def _date(value: str, name: str) -> date:
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{name} must use YYYY-MM-DD") from error


def _number(row: Mapping[str, Any], name: str, integer: bool = False) -> float | int:
    value = row.get(name)
    if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{name} must be a non-negative number")
    if integer:
        if int(value) != value:
            raise ValueError(f"{name} must be an integer")
        return int(value)
    return float(value)


def _period_bounds(start_date: str, end_date: str) -> tuple[date, date, date, date]:
    current_start, current_end = _date(start_date, "start_date"), _date(end_date, "end_date")
    if current_start > current_end:
        raise ValueError("start_date must be on or before end_date")
    days = (current_end - current_start).days + 1
    return current_start, current_end, current_start - timedelta(days=days), current_start - timedelta(days=1)


def _normalized_row(row: Mapping[str, Any]) -> dict[str, Any]:
    metric_date = _date(str(row.get("metric_date", "")), "metric_date")
    page_url = row.get("page_url")
    url_kind = row.get("url_kind")
    article_id = row.get("article_id")
    if not isinstance(page_url, str) or not page_url.startswith(("https://", "http://")):
        raise ValueError("page_url must be an absolute URL")
    if url_kind not in URL_KINDS:
        raise ValueError("url_kind is invalid")
    if article_id is not None and (not isinstance(article_id, int) or article_id < 1):
        raise ValueError("article_id is invalid")
    if url_kind == "article" and article_id is None:
        raise ValueError("article metrics require article_id")
    return {
        "metric_date": metric_date,
        "page_url": page_url,
        "url_kind": url_kind,
        "article_id": article_id,
        "clicks": _number(row, "clicks", integer=True),
        "impressions": _number(row, "impressions", integer=True),
        "position": _number(row, "position"),
    }


def _summary(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    values = list(rows)
    clicks = sum(int(row["clicks"]) for row in values)
    impressions = sum(int(row["impressions"]) for row in values)
    weighted_position = sum(float(row["position"]) * int(row["impressions"]) for row in values)
    return {
        "days_observed": len({row["metric_date"].isoformat() for row in values}),
        "clicks": clicks,
        "impressions": impressions,
        "ctr": round(clicks / impressions, 6) if impressions else None,
        "position": round(weighted_position / impressions, 6) if impressions else None,
    }


def _trend(current: dict[str, Any], previous: dict[str, Any], min_days: int, min_impressions: int) -> dict[str, Any]:
    adequate = (
        current["days_observed"] >= min_days
        and previous["days_observed"] >= min_days
        and current["impressions"] >= min_impressions
        and previous["impressions"] >= min_impressions
    )
    if not adequate:
        return {"classification": "insufficient_data", "clicks_delta": None, "impressions_delta": None,
                "ctr_delta": None, "position_delta": None}
    click_delta = current["clicks"] - previous["clicks"]
    impression_delta = current["impressions"] - previous["impressions"]
    ctr_delta = round((current["ctr"] or 0) - (previous["ctr"] or 0), 6)
    position_delta = round((current["position"] or 0) - (previous["position"] or 0), 6)
    if click_delta > 0 and impression_delta >= 0:
        classification = "growing"
    elif click_delta < 0 and impression_delta <= 0:
        classification = "declining"
    else:
        classification = "stable"
    return {"classification": classification, "clicks_delta": click_delta, "impressions_delta": impression_delta,
            "ctr_delta": ctr_delta, "position_delta": position_delta}


def _entity_report(key: tuple[Any, ...], current_rows: list[dict[str, Any]], previous_rows: list[dict[str, Any]],
                   min_days: int, min_impressions: int) -> dict[str, Any]:
    current, previous = _summary(current_rows), _summary(previous_rows)
    report = {"current": current, "previous": previous, "trend": _trend(current, previous, min_days, min_impressions)}
    if len(key) == 3:
        report.update({"page_url": key[0], "url_kind": key[1], "article_id": key[2]})
    else:
        report.update({"article_id": key[0]})
    return report


def build_page_daily_report(
    rows: Iterable[Mapping[str, Any]], start_date: str, end_date: str, *, min_comparison_days: int = 2,
    min_comparison_impressions: int = 1,
) -> dict[str, Any]:
    """Return a deterministic JSON-compatible report without query text or secrets."""
    if min_comparison_days < 1 or min_comparison_impressions < 1:
        raise ValueError("comparison minimums must be positive")
    current_start, current_end, previous_start, previous_end = _period_bounds(start_date, end_date)
    current_pages: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    previous_pages: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    current_articles: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    previous_articles: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    accepted = 0
    excluded = 0
    for source in rows:
        row = _normalized_row(source)
        page_key = (row["page_url"], row["url_kind"], row["article_id"])
        target_pages = target_articles = None
        if current_start <= row["metric_date"] <= current_end:
            target_pages, target_articles = current_pages, current_articles
        elif previous_start <= row["metric_date"] <= previous_end:
            target_pages, target_articles = previous_pages, previous_articles
        else:
            excluded += 1
            continue
        accepted += 1
        target_pages[page_key].append(row)
        if row["article_id"] is not None:
            target_articles[(row["article_id"],)].append(row)
    page_keys = sorted(set(current_pages) | set(previous_pages), key=lambda item: item[0])
    article_keys = sorted(set(current_articles) | set(previous_articles))
    page_reports = [_entity_report(key, current_pages[key], previous_pages[key], min_comparison_days, min_comparison_impressions) for key in page_keys]
    article_reports = [_entity_report(key, current_articles[key], previous_articles[key], min_comparison_days, min_comparison_impressions) for key in article_keys]
    all_current = [row for values in current_pages.values() for row in values]
    all_previous = [row for values in previous_pages.values() for row in values]
    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "metric_family": "page_daily",
        "current_period": {"start": current_start.isoformat(), "end": current_end.isoformat()},
        "comparison_period": {"start": previous_start.isoformat(), "end": previous_end.isoformat()},
        "overall": {"current": _summary(all_current), "previous": _summary(all_previous),
                    "trend": _trend(_summary(all_current), _summary(all_previous), min_comparison_days, min_comparison_impressions)},
        "pages": page_reports,
        "articles": article_reports,
        "diagnostics": {"input_rows": accepted + excluded, "accepted_rows": accepted, "excluded_outside_period_rows": excluded,
                        "insufficient_data_pages": sum(item["trend"]["classification"] == "insufficient_data" for item in page_reports),
                        "insufficient_data_articles": sum(item["trend"]["classification"] == "insufficient_data" for item in article_reports)},
    }
