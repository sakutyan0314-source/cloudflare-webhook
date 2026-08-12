"""Independent, scheduled collection of one settled Search Console page-daily day.

This job is intentionally outside the Worker pipeline.  It obtains Search
Console data read-only and uses the approved D1 writer as its sole save path.
"""

from __future__ import annotations

import json
from argparse import ArgumentParser
from datetime import date, datetime, timedelta, timezone
from typing import Any, Mapping, Sequence

from search_console_client import SearchConsoleClient
from search_console_collector import PAGE_DAILY, SyncRequest, build_sync_run, transform_metrics, utc_now
from search_console_d1_writer import D1WriterSafetyError, SearchConsoleD1Writer


SETTLEMENT_LAG_DAYS = 3
PAGE_DAILY_ROW_LIMIT = 100
EXPECTED_DATABASE_NAME = "zero-capital-insight-db"


class ScheduledCollectionError(RuntimeError):
    """A safe scheduled-job failure; do not place response bodies in it."""


def settled_metric_date(as_of: date | str | None = None) -> str:
    """Return exactly one settled UTC metric date, three days behind execution."""
    if as_of is None:
        today = datetime.now(timezone.utc).date()
    elif isinstance(as_of, date):
        today = as_of
    elif isinstance(as_of, str):
        try:
            today = date.fromisoformat(as_of)
        except ValueError as error:
            raise ValueError("as_of must use YYYY-MM-DD") from error
    else:
        raise TypeError("as_of must be a date or YYYY-MM-DD string")
    return (today - timedelta(days=SETTLEMENT_LAG_DAYS)).isoformat()


def scheduled_request(property_uri: str, metric_date: str) -> SyncRequest:
    return SyncRequest(
        property_uri=property_uri, search_type="web", metric_family=PAGE_DAILY,
        sync_kind="scheduled", metric_start_date=metric_date, metric_end_date=metric_date,
        dimensions=("date", "page"), row_limit=PAGE_DAILY_ROW_LIMIT,
    )


def run_scheduled_page_daily(
    client: Any, writer: Any, property_uri: str, *, as_of: date | str | None = None,
    observed_at: str | None = None,
) -> Mapping[str, Any]:
    """Collect and save one day once; returns a secret-free fixed result object."""
    metric_date = settled_metric_date(as_of)
    permission = client.property_permission_level()
    if permission not in {"siteOwner", "siteFullUser", "siteRestrictedUser"}:
        raise ScheduledCollectionError("Search Console property permission is unavailable")
    writer.verify_database_identity(EXPECTED_DATABASE_NAME)
    request = scheduled_request(property_uri, metric_date)
    run = build_sync_run(request, observed_at or utc_now())
    record = writer.acquire_sync_run(run)
    if record.status == "succeeded":
        return {"status": "skipped", "reason": "idempotent_succeeded", "metric_date": metric_date,
                "metric_family": PAGE_DAILY, "rows_received": 0, "rows_saved": 0}
    if record.status != "running" or not record.inserted:
        raise ScheduledCollectionError("scheduled sync run is not eligible for automatic reuse")
    try:
        response = client.query_search_analytics(metric_date, metric_date, ["date", "page"], row_limit=PAGE_DAILY_ROW_LIMIT)
        rows = response.get("rows", []) if isinstance(response, Mapping) else []
        if not isinstance(rows, list) or len(rows) > PAGE_DAILY_ROW_LIMIT:
            raise ScheduledCollectionError("Search Console response exceeds scheduled bounds")
        metrics = transform_metrics({"rows": rows}, request, observed_at or utc_now())
        saved = writer.save_acquired_metrics(record, metrics, observed_at or utc_now())
    except Exception as error:
        try:
            writer.mark_failed(record.sync_run_id, error, observed_at or utc_now())
        except Exception:
            raise ScheduledCollectionError("scheduled collection failed and failure audit could not be recorded") from None
        raise ScheduledCollectionError("scheduled page_daily collection failed") from None
    return {"status": saved.status, "metric_date": metric_date, "metric_family": PAGE_DAILY,
            "rows_received": len(metrics), "rows_saved": saved.rows_saved}


def main(argv: Sequence[str] | None = None) -> int:
    parser = ArgumentParser(description="Collect one settled Search Console page_daily date")
    parser.add_argument("--as-of", help="UTC date used only to derive the three-day-lag metric date")
    options = parser.parse_args(argv)
    client = SearchConsoleClient.from_environment()
    writer = SearchConsoleD1Writer.from_environment()
    result = run_scheduled_page_daily(client, writer, client.property_url, as_of=options.as_of)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
