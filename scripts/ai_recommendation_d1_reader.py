"""Fixed-SELECT source reader for v2.0-A production recommendations.

The reader returns only article metadata and observability rows.  It never
selects article bodies, accepts caller SQL, or permits a D1 write response.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Mapping, Protocol

from search_console_collector import SqlStatement
from search_console_d1_reader import D1ReadSafetyError, _validate_fixed_select


class RecommendationReadTransport(Protocol):
    def request(self, method: str, path: str, payload: object | None = None) -> Mapping[str, Any]:
        """Return parsed D1 REST JSON without logging credentials or row data."""


def build_recommendation_source_selects(
    property_uri: str, search_type: str, start_date: str, end_date: str
) -> tuple[SqlStatement, SqlStatement, SqlStatement]:
    """Return the complete, non-configurable SELECT set for this feature."""
    if not isinstance(property_uri, str) or not property_uri.startswith(("https://", "http://")) or not property_uri.endswith("/"):
        raise ValueError("property_uri must be an exact URL-prefix property")
    if not isinstance(search_type, str) or not search_type:
        raise ValueError("search_type is required")
    try:
        current_start, current_end = date.fromisoformat(start_date), date.fromisoformat(end_date)
    except (TypeError, ValueError) as error:
        raise ValueError("dates must use YYYY-MM-DD") from error
    if current_start > current_end:
        raise ValueError("start_date must be on or before end_date")
    previous_start = current_start - timedelta(days=(current_end - current_start).days + 1)
    end_exclusive = current_end + timedelta(days=1)
    return (
        SqlStatement(
            """SELECT metric_date, property_uri, search_type, page_url, url_kind, article_id,
                      clicks, impressions, ctr, position, observed_at
                 FROM search_console_page_daily_metrics
                 WHERE property_uri=? AND search_type=? AND metric_date BETWEEN ? AND ?
                   AND url_kind='article' AND article_id IS NOT NULL
                 ORDER BY metric_date ASC, page_url ASC""",
            (property_uri, search_type, previous_start.isoformat(), current_end.isoformat()),
        ),
        SqlStatement(
            """SELECT article_id, link_type, placement, category, clicked_at
                 FROM affiliate_click_events
                 WHERE clicked_at >= ? AND clicked_at < ?
                 ORDER BY clicked_at ASC, id ASC""",
            (f"{current_start.isoformat()}T00:00:00.000Z", f"{end_exclusive.isoformat()}T00:00:00.000Z"),
        ),
        SqlStatement(
            """SELECT id AS article_id, title, description, category, published_at, updated_at, seo_status
                 FROM curation_logs
                 WHERE seo_status='ready'
                 ORDER BY id ASC""",
            (),
        ),
    )


class AiRecommendationD1Reader:
    """Read exactly three fixed result sets and fail closed on write metadata."""

    def __init__(self, transport: RecommendationReadTransport):
        self._transport = transport

    def fetch_source(
        self, property_uri: str, search_type: str, start_date: str, end_date: str
    ) -> tuple[list[Mapping[str, Any]], list[Mapping[str, Any]], list[Mapping[str, Any]]]:
        statements = build_recommendation_source_selects(property_uri, search_type, start_date, end_date)
        for statement in statements:
            _validate_fixed_select(statement)
        response = self._transport.request("POST", "/query", {
            "batch": [{"sql": statement.sql, "params": list(statement.params)} for statement in statements]
        })
        result = response.get("result")
        if not isinstance(result, list) or len(result) != 3 or not all(isinstance(item, Mapping) for item in result):
            raise D1ReadSafetyError("D1 recommendation read response is invalid")
        output: list[list[Mapping[str, Any]]] = []
        for item in result:
            meta, rows = item.get("meta"), item.get("results")
            if not isinstance(meta, Mapping) or meta.get("changed_db") is not False or meta.get("rows_written") != 0:
                raise D1ReadSafetyError("D1 recommendation read detected a database change")
            if not isinstance(rows, list) or not all(isinstance(row, Mapping) for row in rows):
                raise D1ReadSafetyError("D1 recommendation rows are invalid")
            output.append(list(rows))
        return output[0], output[1], output[2]
