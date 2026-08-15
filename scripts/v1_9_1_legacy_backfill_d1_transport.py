"""Concrete, narrowly-scoped D1 transports for the six legacy SEO backfills.

This module performs no I/O at import time and contains no token source.  A
caller supplies the two in-memory tokens only through the role-specific
factories used by ``v1_9_1_legacy_backfill_runner``.  Read queries are fixed
SELECT statements; the Edit transport accepts only the approved one-row,
conditional metadata backfill shape.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Callable, Mapping, Protocol, Sequence
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from d1_read_only_session import (
    D1ReadOnlyRestTransport,
    D1ReadSafetyError,
    D1ReadTransportError,
    authorization_header,
    validate_read_only_result_sets,
)
from v1_9_1_legacy_backfill_runner import BackfillSafetyError, OutcomeUnknownError


ARTICLE_SELECT = """SELECT id, content, seo_status, category, title, description,
body_markdown, published_at, updated_at
FROM curation_logs WHERE id=?"""
FK_SELECT = "SELECT * FROM pragma_foreign_key_check"
BASELINE_SELECT = """SELECT
 (SELECT COUNT(*) FROM pipeline_runs WHERE status IN ('completed', 'sent')) AS pipeline_completed_sent,
 (SELECT COUNT(*) FROM pipeline_runs WHERE status='sending') AS sending,
 (SELECT COUNT(*) FROM reconciliation_events) AS reconciliation_events,
 (SELECT COUNT(*) FROM search_console_sync_runs) AS sync_runs,
 (SELECT COUNT(*) FROM search_console_page_daily_metrics) AS page_daily_metrics,
 (SELECT COUNT(*) FROM search_console_query_page_daily_metrics) AS query_page_daily_metrics,
 (SELECT COUNT(*) FROM affiliate_click_events) AS affiliate_click_events"""


class LegacyD1TransportError(BackfillSafetyError):
    """Safe, token-free transport classification for a known failed request."""


@dataclass(frozen=True)
class LegacyD1Target:
    account_id: str
    database_id: str
    database_name: str
    timeout_seconds: float = 20.0

    def __post_init__(self) -> None:
        if not all(isinstance(value, str) and value for value in (self.account_id, self.database_id, self.database_name)):
            raise BackfillSafetyError("D1 target configuration is incomplete")
        if not isinstance(self.timeout_seconds, (int, float)) or self.timeout_seconds <= 0:
            raise BackfillSafetyError("D1 timeout configuration is invalid")


class ReadClient(Protocol):
    def identity(self) -> Any: ...
    def fixed_select_batch(self, statements: Sequence[Mapping[str, object]]) -> Any: ...


class EditClient(Protocol):
    def query(self, sql: str, params: Sequence[object]) -> Mapping[str, Any]: ...


def _validate_identity(payload: Mapping[str, Any], target: LegacyD1Target) -> None:
    result = payload.get("result")
    if not isinstance(result, Mapping) or result.get("name") != target.database_name:
        raise BackfillSafetyError("d1_identity_name_mismatch")
    # Cloudflare returns the database UUID as ``uuid``.  Accepting a missing
    # UUID would make a same-name database unsafe.
    if result.get("uuid") != target.database_id:
        raise BackfillSafetyError("d1_identity_database_id_mismatch")


def _rows(item: Mapping[str, Any], required_count: int | None = None) -> list[Mapping[str, Any]]:
    rows = item.get("results")
    if not isinstance(rows, list) or not all(isinstance(row, Mapping) for row in rows):
        raise BackfillSafetyError("d1_read_rows_invalid")
    if required_count is not None and len(rows) != required_count:
        raise BackfillSafetyError("d1_read_row_count_invalid")
    return list(rows)


class LegacyReadD1Transport:
    """Read-role adapter exposing only the runner's three fixed SELECTs."""

    role = "read"

    def __init__(self, client: ReadClient) -> None:
        self._client = client

    def _select(self, sql: str, params: Sequence[object] = ()) -> list[Mapping[str, Any]]:
        response = self._client.fixed_select_batch(({"sql": sql, "params": list(params)},))
        payload = getattr(response, "payload", response)
        if not isinstance(payload, Mapping):
            raise BackfillSafetyError("d1_read_response_invalid")
        return _rows(validate_read_only_result_sets(payload, 1)[0])

    def read_article(self, article_id: int) -> Mapping[str, Any]:
        if not isinstance(article_id, int):
            raise BackfillSafetyError("article_id_invalid")
        return _rows({"results": self._select(ARTICLE_SELECT, (article_id,))}, 1)[0]

    def foreign_key_check(self) -> int:
        return len(self._select(FK_SELECT))

    def baseline(self) -> Mapping[str, int]:
        row = _rows({"results": self._select(BASELINE_SELECT)}, 1)[0]
        if not row or not all(isinstance(value, int) and not isinstance(value, bool) and value >= 0 for value in row.values()):
            raise BackfillSafetyError("baseline_read_invalid")
        return dict(row)


class ReadD1TransportFactory:
    """Identity-verifies a Read-only REST client before runner creation."""

    role = "read"

    def __init__(
        self,
        target: LegacyD1Target,
        client_factory: Callable[[LegacyD1Target, str], ReadClient] | None = None,
    ) -> None:
        self._target = target
        self._client_factory = client_factory or self._default_client

    @staticmethod
    def _default_client(target: LegacyD1Target, token: str) -> D1ReadOnlyRestTransport:
        return D1ReadOnlyRestTransport(target.account_id, target.database_id, token, target.timeout_seconds)

    def create_read_transport(self, token: str) -> LegacyReadD1Transport:
        client = self._client_factory(self._target, token)
        try:
            identity = client.identity()
        except (D1ReadTransportError, D1ReadSafetyError) as error:
            raise BackfillSafetyError("d1_read_identity_failed") from error
        payload = getattr(identity, "payload", identity)
        if not isinstance(payload, Mapping):
            raise BackfillSafetyError("d1_identity_response_invalid")
        _validate_identity(payload, self._target)
        return LegacyReadD1Transport(client)


class D1ConditionalEditClient:
    """Single-statement Query API client; no batch or arbitrary method boundary."""

    def __init__(self, target: LegacyD1Target, token: str, opener: Callable[..., Any] = urlopen) -> None:
        self._target, self._authorization, self._opener = target, authorization_header(token), opener

    def query(self, sql: str, params: Sequence[object]) -> Mapping[str, Any]:
        if not isinstance(sql, str) or not sql.startswith("UPDATE curation_logs SET ") or ";" in sql:
            raise BackfillSafetyError("conditional_update_sql_rejected")
        try:
            request = Request(
                f"https://api.cloudflare.com/client/v4/accounts/{self._target.account_id}/d1/database/{self._target.database_id}/query",
                data=json.dumps({"sql": sql, "params": list(params)}, separators=(",", ":")).encode("utf-8"),
                method="POST",
                headers={"Authorization": self._authorization, "Content-Type": "application/json"},
            )
        except (TypeError, ValueError) as error:
            raise BackfillSafetyError("conditional_update_request_invalid") from error
        try:
            response = self._opener(request, timeout=self._target.timeout_seconds)
            try:
                status, content_type, raw = int(response.status), str(response.headers.get("Content-Type", "")), response.read()
            finally:
                close = getattr(response, "close", None)
                if callable(close):
                    close()
        except HTTPError as error:
            raise LegacyD1TransportError(f"d1_edit_http_{error.code}") from None
        except (URLError, TimeoutError, OSError):
            raise OutcomeUnknownError("d1_edit_delivery_state_unknown") from None
        if not content_type.lower().startswith("application/json") or not raw:
            raise OutcomeUnknownError("d1_edit_response_unreadable")
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise OutcomeUnknownError("d1_edit_response_unparseable") from None
        if status < 200 or status >= 300 or not isinstance(payload, Mapping) or payload.get("success") is not True:
            raise LegacyD1TransportError("d1_edit_response_rejected")
        return payload


class LegacyEditD1Transport:
    """Edit-role adapter that constructs only the approved legacy backfill UPDATE."""

    role = "edit"

    def __init__(self, client: EditClient) -> None:
        self._client = client

    def conditional_update(self, plan: Mapping[str, Any], content: str) -> Mapping[str, Any]:
        expected, target = plan.get("expected"), plan.get("target")
        if not isinstance(expected, Mapping) or not isinstance(target, Mapping) or not isinstance(content, str):
            raise BackfillSafetyError("conditional_update_plan_invalid")
        required = ("title", "description", "category", "published_at", "updated_at", "seo_status")
        if any(field not in target for field in required):
            raise BackfillSafetyError("conditional_update_target_invalid")
        sql = """UPDATE curation_logs
SET title=?, description=?, body_markdown=?, category=?, published_at=?, updated_at=?, seo_status=?
WHERE id=? AND seo_status=? AND category=? AND title IS NULL AND description IS NULL
  AND body_markdown IS NULL AND published_at IS NULL AND updated_at IS NULL AND content=?
RETURNING id""".replace("\n", " ")
        params = (
            target["title"], target["description"], content, target["category"], target["published_at"], target["updated_at"], target["seo_status"],
            expected.get("id"), expected.get("seo_status"), expected.get("category"), content,
        )
        return self._client.query(sql, params)


class EditD1TransportFactory:
    """Creates the sole permitted edit-role transport from the Edit token."""

    role = "edit"

    def __init__(self, target: LegacyD1Target, client_factory: Callable[[LegacyD1Target, str], EditClient] | None = None) -> None:
        self._target = target
        self._client_factory = client_factory or (lambda target, token: D1ConditionalEditClient(target, token))

    def create_edit_transport(self, token: str) -> LegacyEditD1Transport:
        return LegacyEditD1Transport(self._client_factory(self._target, token))
