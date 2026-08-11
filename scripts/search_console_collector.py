"""Offline-safe transformation and persistence planning for Search Console data.

This module never creates a network client.  A future approved runtime may
provide a D1Writer implementation; tests use an isolated SQLite database.
"""

from __future__ import annotations

import hashlib
import json
from argparse import ArgumentParser
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Protocol, Sequence
from urllib.parse import parse_qsl, urlsplit, urlunsplit


PAGE_DAILY = "page_daily"
QUERY_PAGE_DAILY = "query_page_daily"
SYNC_FAMILIES = frozenset({PAGE_DAILY, QUERY_PAGE_DAILY})


@dataclass(frozen=True)
class SqlStatement:
    sql: str
    params: tuple[Any, ...]


class D1Writer(Protocol):
    """A transaction-capable writer supplied by a future approved runtime."""

    def execute_batch(self, statements: Sequence[SqlStatement]) -> Sequence[Mapping[str, Any]]:
        """Execute all statements atomically or raise without partial success."""


@dataclass(frozen=True)
class SyncRequest:
    property_uri: str
    search_type: str
    metric_family: str
    sync_kind: str
    metric_start_date: str
    metric_end_date: str
    dimensions: tuple[str, ...]
    row_limit: int


@dataclass(frozen=True)
class SyncRun:
    request: SyncRequest
    idempotency_key: str
    started_at: str


@dataclass(frozen=True)
class NormalizedUrl:
    page_url: str
    url_kind: str
    article_id: int | None


@dataclass(frozen=True)
class MetricRow:
    metric_date: str
    property_uri: str
    search_type: str
    page_url: str
    url_kind: str
    article_id: int | None
    clicks: int
    impressions: int
    ctr: float
    position: float
    observed_at: str
    query_text: str | None = None


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def canonical_json(value: Mapping[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def validate_request(request: SyncRequest) -> SyncRequest:
    if request.metric_family not in SYNC_FAMILIES:
        raise ValueError("metric_family is unsupported")
    if request.sync_kind not in {"scheduled", "refresh", "manual"}:
        raise ValueError("sync_kind is unsupported")
    if not request.property_uri.startswith(("https://", "http://")) or not request.property_uri.endswith("/"):
        raise ValueError("property_uri must be an exact URL-prefix property")
    if not request.search_type:
        raise ValueError("search_type is required")
    if not 1 <= request.row_limit <= 25_000:
        raise ValueError("row_limit must be between 1 and 25000")
    try:
        start = date.fromisoformat(request.metric_start_date)
        end = date.fromisoformat(request.metric_end_date)
    except ValueError as error:
        raise ValueError("metric dates must use YYYY-MM-DD") from error
    if start > end:
        raise ValueError("metric_start_date must be on or before metric_end_date")
    required = ("date", "page") if request.metric_family == PAGE_DAILY else ("date", "query", "page")
    if request.dimensions != required:
        raise ValueError(f"{request.metric_family} dimensions must be {required}")
    return request


def idempotency_key(request: SyncRequest) -> str:
    validate_request(request)
    material = {
        "dimensions": list(request.dimensions),
        "metric_end_date": request.metric_end_date,
        "metric_family": request.metric_family,
        "metric_start_date": request.metric_start_date,
        "property_uri": request.property_uri,
        "row_limit": request.row_limit,
        "search_type": request.search_type,
        "sync_kind": request.sync_kind,
    }
    return hashlib.sha256(canonical_json(material).encode("utf-8")).hexdigest()


def build_sync_run(request: SyncRequest, started_at: str | None = None) -> SyncRun:
    validate_request(request)
    return SyncRun(request=request, idempotency_key=idempotency_key(request), started_at=started_at or utc_now())


def build_sync_run_insert(run: SyncRun) -> SqlStatement:
    request = run.request
    return SqlStatement(
        """INSERT INTO search_console_sync_runs (
             idempotency_key, property_uri, search_type, metric_family, sync_kind,
             metric_start_date, metric_end_date, dimensions_json, row_limit, status, started_at
           ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'running', ?)
           ON CONFLICT(idempotency_key) DO NOTHING""",
        (
            run.idempotency_key, request.property_uri, request.search_type, request.metric_family,
            request.sync_kind, request.metric_start_date, request.metric_end_date,
            json.dumps(list(request.dimensions), separators=(",", ":")), request.row_limit,
            run.started_at,
        ),
    )


def normalize_page_url(raw_url: str, property_uri: str) -> NormalizedUrl:
    property_parts = urlsplit(property_uri)
    raw_parts = urlsplit(raw_url)
    if (raw_parts.scheme, raw_parts.netloc) != (property_parts.scheme, property_parts.netloc):
        raise ValueError("page URL does not belong to the configured property origin")
    path = raw_parts.path or "/"
    query = parse_qsl(raw_parts.query, keep_blank_values=True)
    page_values = [value for key, value in query if key == "page"]
    article_id: int | None = None
    url_kind = "unknown"
    if path.startswith("/article/") and path.count("/") == 2 and path[9:].isdigit():
        article_id = int(path[9:])
        url_kind = "article"
        normalized_query = ""
    elif path.startswith("/category/") and path.count("/") == 2 and len(path) > len("/category/"):
        url_kind = "category"
        normalized_query = ""
    elif path == "/" and len(query) == 1 and page_values and page_values[0].isdigit() and int(page_values[0]) >= 1:
        url_kind = "listing"
        normalized_query = f"page={int(page_values[0])}"
    elif path == "/" and not query:
        url_kind = "top"
        normalized_query = ""
    else:
        normalized_query = raw_parts.query
    return NormalizedUrl(
        page_url=urlunsplit((property_parts.scheme, property_parts.netloc, path, normalized_query, "")),
        url_kind=url_kind,
        article_id=article_id,
    )


def _number(row: Mapping[str, Any], key: str, integer: bool = False) -> int | float:
    value = row.get(key)
    if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0:
        raise ValueError(f"metric {key} must be a non-negative number")
    if integer:
        if int(value) != value:
            raise ValueError(f"metric {key} must be an integer")
        return int(value)
    return float(value)


def _metric_row(api_row: Mapping[str, Any], request: SyncRequest, observed_at: str) -> MetricRow:
    keys = api_row.get("keys")
    expected_keys = 2 if request.metric_family == PAGE_DAILY else 3
    if not isinstance(keys, list) or len(keys) != expected_keys:
        raise ValueError("Search Console row has an unexpected dimensions shape")
    metric_date = str(keys[0])
    date.fromisoformat(metric_date)
    if request.metric_family == PAGE_DAILY:
        page_url = str(keys[1])
        query_text = None
    else:
        query_text = str(keys[1])
        page_url = str(keys[2])
    normalized = normalize_page_url(page_url, request.property_uri)
    ctr = float(_number(api_row, "ctr"))
    if ctr > 1:
        raise ValueError("metric ctr must not exceed 1")
    return MetricRow(
        metric_date=metric_date,
        property_uri=request.property_uri,
        search_type=request.search_type,
        page_url=normalized.page_url,
        url_kind=normalized.url_kind,
        article_id=normalized.article_id,
        clicks=int(_number(api_row, "clicks", integer=True)),
        impressions=int(_number(api_row, "impressions", integer=True)),
        ctr=ctr,
        position=float(_number(api_row, "position")),
        observed_at=observed_at,
        query_text=query_text,
    )


def transform_metrics(response: Mapping[str, Any], request: SyncRequest, observed_at: str | None = None) -> list[MetricRow]:
    validate_request(request)
    rows = response.get("rows", [])
    if not isinstance(rows, list):
        raise ValueError("Search Console response rows must be a list")
    timestamp = observed_at or utc_now()
    return [_metric_row(row, request, timestamp) for row in rows]


def build_metric_upsert(run_id: int, metric: MetricRow) -> SqlStatement:
    if metric.query_text is None:
        return SqlStatement(
            """INSERT INTO search_console_page_daily_metrics (
                 sync_run_id, metric_date, property_uri, search_type, page_url, url_kind, article_id,
                 clicks, impressions, ctr, position, observed_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(property_uri, search_type, metric_date, page_url) DO UPDATE SET
                 sync_run_id=excluded.sync_run_id, url_kind=excluded.url_kind, article_id=excluded.article_id,
                 clicks=excluded.clicks, impressions=excluded.impressions, ctr=excluded.ctr,
                 position=excluded.position, observed_at=excluded.observed_at""",
            (run_id, metric.metric_date, metric.property_uri, metric.search_type, metric.page_url,
             metric.url_kind, metric.article_id, metric.clicks, metric.impressions, metric.ctr,
             metric.position, metric.observed_at),
        )
    return SqlStatement(
        """INSERT INTO search_console_query_page_daily_metrics (
             sync_run_id, metric_date, property_uri, search_type, query_text, page_url, url_kind, article_id,
             clicks, impressions, ctr, position, observed_at
           ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(property_uri, search_type, metric_date, query_text, page_url) DO UPDATE SET
             sync_run_id=excluded.sync_run_id, url_kind=excluded.url_kind, article_id=excluded.article_id,
             clicks=excluded.clicks, impressions=excluded.impressions, ctr=excluded.ctr,
             position=excluded.position, observed_at=excluded.observed_at""",
        (run_id, metric.metric_date, metric.property_uri, metric.search_type, metric.query_text,
         metric.page_url, metric.url_kind, metric.article_id, metric.clicks, metric.impressions,
         metric.ctr, metric.position, metric.observed_at),
    )


def build_success_batch(run_id: int, metrics: Iterable[MetricRow], completed_at: str | None = None) -> list[SqlStatement]:
    metric_list = list(metrics)
    statements = [build_metric_upsert(run_id, metric) for metric in metric_list]
    statements.append(SqlStatement(
        """UPDATE search_console_sync_runs
           SET status='succeeded', rows_received=?, rows_saved=?, completed_at=?, error_summary=NULL
           WHERE id=? AND status='running'""",
        (len(metric_list), len(metric_list), completed_at or utc_now(), run_id),
    ))
    return statements


def build_failure_update(run_id: int, summary: str, completed_at: str | None = None) -> SqlStatement:
    return SqlStatement(
        """UPDATE search_console_sync_runs
           SET status='failed', error_summary=?, completed_at=?
           WHERE id=? AND status='running'""",
        (summary, completed_at or utc_now(), run_id),
    )


def error_summary(stage: str, error: Exception, http_status: int | None = None, retryable: bool = False) -> str:
    if not stage or not stage.replace("_", "").isalnum():
        raise ValueError("stage must be a short identifier")
    error_type = type(error).__name__[:80]
    status = "none" if http_status is None else str(http_status)
    return f"stage={stage};error_type={error_type};http_status={status};retryable={str(retryable).lower()}"[:1000]


def dry_run_from_fixture(fixture_path: str | Path, property_uri: str, observed_at: str) -> Mapping[str, Any]:
    """Transform a fixture without API calls or D1 writes; never return raw queries."""
    fixture = json.loads(Path(fixture_path).read_text(encoding="utf-8"))
    reports = []
    for family in (PAGE_DAILY, QUERY_PAGE_DAILY):
        entry = fixture.get(family)
        if not isinstance(entry, Mapping):
            raise ValueError(f"fixture is missing {family}")
        request = SyncRequest(
            property_uri=property_uri,
            search_type="web",
            metric_family=family,
            sync_kind="manual",
            metric_start_date=str(entry["start_date"]),
            metric_end_date=str(entry["end_date"]),
            dimensions=("date", "page") if family == PAGE_DAILY else ("date", "query", "page"),
            row_limit=int(entry["row_limit"]),
        )
        metrics = transform_metrics(entry["response"], request, observed_at)
        kinds = {kind: sum(metric.url_kind == kind for metric in metrics) for kind in ("article", "category", "top", "listing", "unknown")}
        reports.append({
            "metric_family": family,
            "idempotency_key": idempotency_key(request),
            "rows_received": len(metrics),
            "url_kind_counts": kinds,
        })
    return {"mode": "dry-run", "changed_db": False, "rows_written": 0, "reports": reports}


def main(argv: Sequence[str] | None = None) -> int:
    """Run only the offline fixture dry-run; production collection is not implemented."""
    parser = ArgumentParser(description="Offline Search Console collector dry-run")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--fixture")
    parser.add_argument("--property-uri")
    parser.add_argument("--observed-at")
    options = parser.parse_args(argv)
    if not options.dry_run:
        parser.error("only --dry-run is supported; API and D1 execution are disabled")
    if not options.fixture or not options.property_uri or not options.observed_at:
        parser.error("--fixture, --property-uri, and --observed-at are required for --dry-run")
    print(json.dumps(dry_run_from_fixture(options.fixture, options.property_uri, options.observed_at), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
