"""Read-only D1 adapter for article-level Search Console and affiliate metrics.

This module deliberately accepts no caller-supplied SQL.  It queries only the
two fixed, article-scoped SELECT statements below and fails closed when D1
reports any write metadata.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Mapping, Protocol

from search_console_collector import SqlStatement
from search_console_d1_reader import D1ReadSafetyError, _validate_fixed_select


class AffiliateReadTransport(Protocol):
    def request(self, method: str, path: str, payload: object | None = None) -> Mapping[str, Any]:
        """Return a parsed D1 REST response without logging credentials or rows."""


def _iso_date(value: str, name: str) -> str:
    try:
        return date.fromisoformat(value).isoformat()
    except (TypeError, ValueError) as error:
        raise ValueError(f"{name} must use YYYY-MM-DD") from error


def _validate_request(property_uri: str, search_type: str, start_date: str, end_date: str) -> tuple[str, str, str, str, str]:
    start, end = _iso_date(start_date, "start_date"), _iso_date(end_date, "end_date")
    if start > end:
        raise ValueError("start_date must be on or before end_date")
    if not isinstance(property_uri, str) or not property_uri.startswith(("https://", "http://")) or not property_uri.endswith("/"):
        raise ValueError("property_uri must be an exact URL-prefix property")
    if not isinstance(search_type, str) or not search_type:
        raise ValueError("search_type is required")
    end_exclusive = (date.fromisoformat(end) + timedelta(days=1)).isoformat()
    return property_uri, search_type, start, end, end_exclusive


def build_article_metric_selects(
    property_uri: str, search_type: str, start_date: str, end_date: str
) -> tuple[SqlStatement, SqlStatement]:
    """Build the only D1 queries exposed by the v1.10-E reader."""
    property_uri, search_type, start, end, end_exclusive = _validate_request(
        property_uri, search_type, start_date, end_date
    )
    page_daily = SqlStatement(
        """SELECT metric_date, article_id, clicks, impressions, position
             FROM search_console_page_daily_metrics
             WHERE property_uri=? AND search_type=? AND metric_date BETWEEN ? AND ?
               AND url_kind='article' AND article_id IS NOT NULL
             ORDER BY metric_date ASC, article_id ASC""",
        (property_uri, search_type, start, end),
    )
    affiliate = SqlStatement(
        """SELECT article_id, link_type, placement, category, clicked_at
             FROM affiliate_click_events
             WHERE clicked_at >= ? AND clicked_at < ?
             ORDER BY clicked_at ASC, id ASC""",
        (f"{start}T00:00:00.000Z", f"{end_exclusive}T00:00:00.000Z"),
    )
    return page_daily, affiliate


class SearchConsoleAffiliateReader:
    """Fixed-query reader for v1.10-E; no DML or arbitrary SQL boundary exists."""

    def __init__(self, transport: AffiliateReadTransport):
        self._transport = transport

    def fetch_article_metrics(
        self, property_uri: str, search_type: str, start_date: str, end_date: str
    ) -> tuple[list[Mapping[str, Any]], list[Mapping[str, Any]]]:
        statements = build_article_metric_selects(property_uri, search_type, start_date, end_date)
        for statement in statements:
            _validate_fixed_select(statement)
        response = self._transport.request(
            "POST", "/query", {"batch": [{"sql": item.sql, "params": list(item.params)} for item in statements]}
        )
        result = response.get("result")
        if not isinstance(result, list) or len(result) != 2 or not all(isinstance(item, Mapping) for item in result):
            raise D1ReadSafetyError("D1 affiliate read response did not contain two result sets")
        rows: list[list[Mapping[str, Any]]] = []
        for item in result:
            meta = item.get("meta")
            if not isinstance(meta, Mapping) or meta.get("changed_db") is not False:
                raise D1ReadSafetyError("D1 reader detected an unexpected database change")
            if meta.get("rows_written") != 0:
                raise D1ReadSafetyError("D1 reader detected unexpected written rows")
            result_rows = item.get("results")
            if not isinstance(result_rows, list) or not all(isinstance(row, Mapping) for row in result_rows):
                raise D1ReadSafetyError("D1 affiliate read response rows are invalid")
            rows.append(list(result_rows))
        return rows[0], rows[1]
