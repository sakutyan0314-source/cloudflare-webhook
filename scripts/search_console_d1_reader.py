"""Read-only D1 adapter for stored Search Console page-daily metrics.

The reader deliberately exposes no arbitrary SQL interface.  It accepts only
the fixed page-daily query below and fails closed if D1 reports a write.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Mapping, Protocol, Sequence

from search_console_collector import SqlStatement


class D1ReadSafetyError(RuntimeError):
    """Raised when a D1 read contract or response is unsafe."""


class ReadTransport(Protocol):
    def request(self, method: str, path: str, payload: object | None = None) -> Mapping[str, Any]:
        """Return parsed D1 REST JSON without logging credentials or bodies."""


def _validate_iso_date(value: str, name: str) -> str:
    try:
        return date.fromisoformat(value).isoformat()
    except (TypeError, ValueError) as error:
        raise ValueError(f"{name} must use YYYY-MM-DD") from error


def _validate_fixed_select(statement: SqlStatement) -> None:
    normalized = statement.sql.lstrip().upper()
    if not normalized.startswith("SELECT ") or ";" in normalized.rstrip(";"):
        raise D1ReadSafetyError("D1 reader accepts one SELECT statement only")


def build_page_daily_select(
    property_uri: str, search_type: str, start_date: str, end_date: str
) -> SqlStatement:
    """Build the only query exposed by this v1.10-B reader."""
    start, end = _validate_iso_date(start_date, "start_date"), _validate_iso_date(end_date, "end_date")
    if start > end:
        raise ValueError("start_date must be on or before end_date")
    if not property_uri.startswith(("https://", "http://")) or not property_uri.endswith("/"):
        raise ValueError("property_uri must be an exact URL-prefix property")
    if not search_type:
        raise ValueError("search_type is required")
    return SqlStatement(
        """SELECT metric_date, property_uri, search_type, page_url, url_kind, article_id,
                  clicks, impressions, ctr, position, observed_at
             FROM search_console_page_daily_metrics
             WHERE property_uri=? AND search_type=? AND metric_date BETWEEN ? AND ?
             ORDER BY metric_date ASC, page_url ASC""",
        (property_uri, search_type, start, end),
    )


class SearchConsoleD1Reader:
    """Fixed-query read adapter; it cannot construct DML or arbitrary SQL."""

    def __init__(self, transport: ReadTransport):
        self._transport = transport

    def fetch_page_daily(
        self, property_uri: str, search_type: str, start_date: str, end_date: str
    ) -> list[Mapping[str, Any]]:
        statement = build_page_daily_select(property_uri, search_type, start_date, end_date)
        _validate_fixed_select(statement)
        response = self._transport.request(
            "POST", "/query", {"sql": statement.sql, "params": list(statement.params)}
        )
        result = response.get("result")
        if not isinstance(result, list) or len(result) != 1 or not isinstance(result[0], Mapping):
            raise D1ReadSafetyError("D1 read response did not contain exactly one result set")
        item = result[0]
        meta = item.get("meta")
        if not isinstance(meta, Mapping) or meta.get("changed_db") is not False:
            raise D1ReadSafetyError("D1 reader detected an unexpected database change")
        rows_written = meta.get("rows_written")
        if not isinstance(rows_written, int) or rows_written != 0:
            raise D1ReadSafetyError("D1 reader detected unexpected written rows")
        rows = item.get("results")
        if not isinstance(rows, list) or not all(isinstance(row, Mapping) for row in rows):
            raise D1ReadSafetyError("D1 read response rows are invalid")
        return list(rows)
