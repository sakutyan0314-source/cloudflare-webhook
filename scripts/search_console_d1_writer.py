"""D1 REST persistence adapter for approved Search Console collector runs.

This module does not create a collector, fetch Search Console data, or write
unless a caller explicitly supplies a REST transport.  It never logs tokens,
Authorization headers, response bodies, or query text.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Mapping, Protocol, Sequence
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from search_console_collector import (
    MetricRow,
    SqlStatement,
    SyncRun,
    build_failure_update,
    build_metric_upsert,
    build_sync_run_insert,
    error_summary,
    utc_now,
)


class D1WriterConfigurationError(ValueError):
    """Raised before any HTTP call when required runtime configuration is invalid."""


class D1WriterSafetyError(RuntimeError):
    """Raised when D1 identity, idempotency, or response guarantees are insufficient."""


class D1ApiError(RuntimeError):
    """A safe API error: it contains no response body, header, or credential."""

    def __init__(self, operation: str, status: int | None = None):
        self.operation = operation
        self.status = status
        super().__init__(f"D1 REST request failed during {operation}")


class RestTransport(Protocol):
    """Small injectable HTTP boundary; production uses UrllibRestTransport."""

    def request(self, method: str, path: str, payload: object | None = None) -> Mapping[str, Any]:
        """Return parsed JSON only or raise D1ApiError."""


@dataclass(frozen=True)
class D1RuntimeConfig:
    account_id: str
    database_id: str
    api_token: str

    @classmethod
    def from_environment(cls, environ: Mapping[str, str] | None = None) -> "D1RuntimeConfig":
        source = os.environ if environ is None else environ
        values = {name: source.get(name, "").strip() for name in (
            "CLOUDFLARE_ACCOUNT_ID", "CLOUDFLARE_D1_DATABASE_ID", "CLOUDFLARE_API_TOKEN"
        )}
        if not all(values.values()):
            raise D1WriterConfigurationError("Cloudflare D1 REST environment configuration is incomplete")
        return cls(values["CLOUDFLARE_ACCOUNT_ID"], values["CLOUDFLARE_D1_DATABASE_ID"], values["CLOUDFLARE_API_TOKEN"])


class UrllibRestTransport:
    """Direct REST transport.  Do not print or persist this object's configuration."""

    def __init__(self, config: D1RuntimeConfig, timeout_seconds: float = 20.0):
        self._config = config
        self._timeout_seconds = timeout_seconds
        self._base_path = f"https://api.cloudflare.com/client/v4/accounts/{config.account_id}/d1/database/{config.database_id}"

    def request(self, method: str, path: str, payload: object | None = None) -> Mapping[str, Any]:
        body = None if payload is None else json.dumps(payload, separators=(",", ":")).encode("utf-8")
        request = Request(
            f"{self._base_path}{path}", data=body, method=method,
            headers={"Authorization": f"Bearer {self._config.api_token}", "Content-Type": "application/json"},
        )
        try:
            with urlopen(request, timeout=self._timeout_seconds) as response:  # nosec B310: fixed API base
                parsed = json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            raise D1ApiError("http_request", error.code) from None
        except (URLError, TimeoutError, json.JSONDecodeError):
            raise D1ApiError("http_request") from None
        if not isinstance(parsed, Mapping) or parsed.get("success") is not True:
            raise D1ApiError("api_response")
        return parsed


@dataclass(frozen=True)
class SyncRunRecord:
    sync_run_id: int
    status: str
    inserted: bool


@dataclass(frozen=True)
class SaveResult:
    sync_run_id: int
    status: str
    rows_saved: int
    skipped: bool = False


def _statement_payload(statement: SqlStatement) -> dict[str, object]:
    return {"sql": statement.sql, "params": list(statement.params)}


def _result_sets(response: Mapping[str, Any]) -> Sequence[Mapping[str, Any]]:
    result = response.get("result")
    if not isinstance(result, list) or not all(isinstance(item, Mapping) for item in result):
        raise D1WriterSafetyError("D1 batch response did not contain expected result sets")
    return result


def _rows(result_set: Mapping[str, Any]) -> Sequence[Mapping[str, Any]]:
    rows = result_set.get("results", result_set.get("result"))
    if not isinstance(rows, list) or not all(isinstance(row, Mapping) for row in rows):
        raise D1WriterSafetyError("D1 query response did not contain expected rows")
    return rows


def _changes(result_set: Mapping[str, Any]) -> int:
    meta = result_set.get("meta")
    changes = meta.get("changes") if isinstance(meta, Mapping) else None
    if not isinstance(changes, int) or changes < 0:
        raise D1WriterSafetyError("D1 acquire response did not contain a valid change count")
    return changes


class SearchConsoleD1Writer:
    """Persistence-only writer using D1 REST Query batches.

    The caller must have already completed collection, normalization, and
    validation.  No retry loop is implemented.
    """

    def __init__(self, config: D1RuntimeConfig, transport: RestTransport):
        self._config = config
        self._transport = transport

    @classmethod
    def from_environment(cls, environ: Mapping[str, str] | None = None) -> "SearchConsoleD1Writer":
        config = D1RuntimeConfig.from_environment(environ)
        return cls(config, UrllibRestTransport(config))

    def verify_database_identity(self, expected_database_name: str) -> None:
        response = self._transport.request("GET", "")
        result = response.get("result")
        name = result.get("name") if isinstance(result, Mapping) else None
        if name != expected_database_name:
            raise D1WriterSafetyError("D1 database identity does not match the approved target")

    def _batch(self, statements: Sequence[SqlStatement]) -> Sequence[Mapping[str, Any]]:
        if not statements:
            raise D1WriterSafetyError("refusing to submit an empty D1 batch")
        response = self._transport.request(
            "POST", "/query", {"batch": [_statement_payload(item) for item in statements]}
        )
        return _result_sets(response)

    def acquire_sync_run(self, run: SyncRun) -> SyncRunRecord:
        """Insert-if-absent then read the D1-assigned id for the exact key."""
        select = SqlStatement(
            "SELECT id, status FROM search_console_sync_runs WHERE idempotency_key=?",
            (run.idempotency_key,),
        )
        results = self._batch((build_sync_run_insert(run), select))
        if len(results) != 2:
            raise D1WriterSafetyError("D1 acquire batch returned an unexpected result count")
        inserted = _changes(results[0]) == 1
        rows = _rows(results[1])
        if len(rows) != 1:
            raise D1WriterSafetyError("D1 did not return exactly one sync run for idempotency key")
        run_id, status = rows[0].get("id"), rows[0].get("status")
        if not isinstance(run_id, int) or status not in {"running", "succeeded", "failed", "partial"}:
            raise D1WriterSafetyError("D1 returned an invalid sync run record")
        return SyncRunRecord(run_id, status, inserted)

    def save_metrics(self, run: SyncRun, metrics: Sequence[MetricRow], completed_at: str | None = None) -> SaveResult:
        """Save validated metrics without retrying conflicts or transient failures."""
        record = self.acquire_sync_run(run)
        if record.status == "succeeded":
            return SaveResult(record.sync_run_id, record.status, 0, skipped=True)
        if record.status != "running" or not record.inserted:
            raise D1WriterSafetyError("sync run is not eligible for automatic reuse")
        return self.save_acquired_metrics(record, metrics, completed_at)

    def save_acquired_metrics(
        self, record: SyncRunRecord, metrics: Sequence[MetricRow], completed_at: str | None = None
    ) -> SaveResult:
        """Save after a newly inserted running record; no reacquisition or retry."""
        if record.status != "running" or not record.inserted:
            raise D1WriterSafetyError("sync run must be newly acquired before saving metrics")
        completed = completed_at or utc_now()
        success_batch = [build_metric_upsert(record.sync_run_id, metric) for metric in metrics]
        success_batch.append(SqlStatement(
            """UPDATE search_console_sync_runs
               SET status='succeeded', rows_received=?, rows_saved=?, completed_at=?, error_summary=NULL
               WHERE id=? AND status='running'""",
            (len(metrics), len(metrics), completed, record.sync_run_id),
        ))
        try:
            self._batch(success_batch)
        except (D1ApiError, D1WriterSafetyError) as error:
            self.mark_failed(record.sync_run_id, error)
            raise
        return SaveResult(record.sync_run_id, "succeeded", len(metrics))

    def mark_failed(self, sync_run_id: int, error: Exception, completed_at: str | None = None) -> None:
        """Record a bounded classification only; never retain response text or metrics."""
        status = error.status if isinstance(error, D1ApiError) else None
        summary = error_summary("d1_write", error, status, False)
        self._batch((build_failure_update(sync_run_id, summary, completed_at or utc_now()),))
