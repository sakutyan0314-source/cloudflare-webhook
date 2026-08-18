"""Fixed-identity D1 backup/export boundary for approved production maintenance.

This adapter deliberately has no account discovery, no database selection, and
no query/update route.  A caller must provide the human-approved account,
database UUID, and database name.  The Database GET response is still checked
before the bookmark or export route is available.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Protocol
from urllib.parse import urlparse
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from d1_read_only_session import authorization_header


class D1BackupSafetyError(RuntimeError):
    """A token-free, response-body-free backup safety classification."""


class D1BackupTransportError(RuntimeError):
    """A token-free transport failure classification."""


_ACCOUNT_ID = re.compile(r"^[a-f0-9]{32}$")
_DATABASE_ID = re.compile(r"^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$")


@dataclass(frozen=True)
class ApprovedD1BackupIdentity:
    """The only identity that this backup session may address."""

    expected_account_id: str
    expected_database_id: str
    expected_database_name: str
    timeout_seconds: float = 30.0

    def __post_init__(self) -> None:
        if not _ACCOUNT_ID.fullmatch(self.expected_account_id):
            raise D1BackupSafetyError("approved_account_id_invalid")
        if not _DATABASE_ID.fullmatch(self.expected_database_id):
            raise D1BackupSafetyError("approved_database_id_invalid")
        if not isinstance(self.expected_database_name, str) or not self.expected_database_name:
            raise D1BackupSafetyError("approved_database_name_invalid")
        if not isinstance(self.timeout_seconds, (int, float)) or self.timeout_seconds <= 0:
            raise D1BackupSafetyError("backup_timeout_invalid")

    @property
    def base_url(self) -> str:
        return (
            "https://api.cloudflare.com/client/v4/accounts/"
            f"{self.expected_account_id}/d1/database/{self.expected_database_id}"
        )


@dataclass(frozen=True)
class D1BackupResponse:
    status: int
    content_type: str
    response_size: int
    payload: Mapping[str, Any]


@dataclass(frozen=True)
class D1ExportInProgress:
    """In-memory polling cursor; never persisted or logged."""

    at_bookmark: str


@dataclass(frozen=True)
class D1ExportComplete:
    """In-memory download capability returned only after a complete response."""

    at_bookmark: str
    signed_url: str


class HttpOpener(Protocol):
    def __call__(self, request: Request, timeout: float) -> Any: ...


class UrlOpener(Protocol):
    def __call__(self, url: str, timeout: float) -> Any: ...


class FixedIdentityD1BackupTransport:
    """Allows only identity, Time Travel bookmark, and polling export calls."""

    def __init__(self, identity: ApprovedD1BackupIdentity, token: str, opener: HttpOpener = urlopen) -> None:
        self._identity = identity
        self._authorization = authorization_header(token)
        self._opener = opener

    def _request(self, method: str, path: str, payload: Mapping[str, object] | None = None) -> D1BackupResponse:
        allowed = {
            ("GET", ""),
            ("GET", "/time_travel/bookmark"),
            ("POST", "/export"),
        }
        if (method, path) not in allowed:
            raise D1BackupSafetyError("backup_route_rejected")
        if method == "POST":
            if not isinstance(payload, Mapping) or payload.get("output_format") != "polling":
                raise D1BackupSafetyError("export_request_shape_invalid")
            if set(payload) - {"output_format", "current_bookmark", "dump_options"}:
                raise D1BackupSafetyError("export_request_shape_invalid")
        elif payload is not None:
            raise D1BackupSafetyError("backup_request_payload_rejected")
        body = None if payload is None else json.dumps(payload, separators=(",", ":")).encode("utf-8")
        try:
            request = Request(
                self._identity.base_url + path,
                data=body,
                method=method,
                headers={"Authorization": self._authorization, "Content-Type": "application/json"},
            )
        except (TypeError, ValueError):
            raise D1BackupTransportError("request_construction_failed") from None
        try:
            response = self._opener(request, timeout=self._identity.timeout_seconds)
            try:
                status = int(response.status)
                content_type = str(response.headers.get("Content-Type", ""))
                raw = response.read()
            finally:
                close = getattr(response, "close", None)
                if callable(close):
                    close()
        except HTTPError as error:
            raise D1BackupTransportError(f"http_{error.code}") from None
        except (URLError, TimeoutError, OSError):
            raise D1BackupTransportError("transport_exception") from None
        if not content_type.lower().startswith("application/json"):
            raise D1BackupTransportError("unexpected_content_type")
        if not raw:
            raise D1BackupTransportError("empty_response")
        try:
            parsed = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise D1BackupTransportError("json_parse_failed") from None
        if status < 200 or status >= 300:
            raise D1BackupTransportError(f"http_{status}")
        if not isinstance(parsed, Mapping) or parsed.get("success") is not True:
            raise D1BackupTransportError("api_success_false")
        return D1BackupResponse(status, content_type.split(";", 1)[0], len(raw), parsed)

    def verify_identity(self) -> D1BackupResponse:
        response = self._request("GET", "")
        result = response.payload.get("result")
        if not isinstance(result, Mapping):
            raise D1BackupSafetyError("identity_response_invalid")
        if result.get("uuid") != self._identity.expected_database_id:
            raise D1BackupSafetyError("database_id_mismatch")
        if result.get("name") != self._identity.expected_database_name:
            raise D1BackupSafetyError("database_name_mismatch")
        return response

    def current_bookmark(self) -> D1BackupResponse:
        response = self._request("GET", "/time_travel/bookmark")
        result = response.payload.get("result")
        if not isinstance(result, Mapping) or not isinstance(result.get("bookmark"), str) or not result["bookmark"]:
            raise D1BackupSafetyError("bookmark_response_invalid")
        return response

    def export_polling(self, current_bookmark: str | None = None) -> D1BackupResponse:
        payload: dict[str, object] = {"output_format": "polling"}
        if current_bookmark is not None:
            if not isinstance(current_bookmark, str) or not current_bookmark:
                raise D1BackupSafetyError("export_bookmark_invalid")
            payload["current_bookmark"] = current_bookmark
        return self._request("POST", "/export", payload)


def parse_export_polling_response(response: D1BackupResponse) -> D1ExportInProgress | D1ExportComplete:
    """Accept only documented polling cursors or completed signed URLs.

    Cloudflare documents ``status`` only for terminal ``complete`` and
    ``error`` responses.  An otherwise-valid response with ``at_bookmark`` and
    no terminal status remains in progress.  Unknown status values fail closed.
    """
    result = response.payload.get("result")
    if not isinstance(result, Mapping):
        raise D1BackupSafetyError("export_response_invalid")
    bookmark = result.get("at_bookmark")
    if not isinstance(bookmark, str) or not bookmark:
        raise D1BackupSafetyError("export_polling_bookmark_invalid")
    status = result.get("status")
    if status is None:
        return D1ExportInProgress(bookmark)
    if status == "error":
        raise D1BackupSafetyError("export_reported_error")
    if status != "complete":
        raise D1BackupSafetyError("export_status_unknown")
    completed = result.get("result")
    signed_url = completed.get("signed_url") if isinstance(completed, Mapping) else None
    parsed = urlparse(signed_url) if isinstance(signed_url, str) else None
    if not isinstance(signed_url, str) or not signed_url or parsed is None or parsed.scheme != "https" or not parsed.netloc:
        raise D1BackupSafetyError("export_signed_url_invalid")
    return D1ExportComplete(bookmark, signed_url)


class D1ExportPollingSession:
    """One export start followed only by bounded polls of the same bookmark."""

    def __init__(
        self,
        transport: FixedIdentityD1BackupTransport,
        *,
        max_polls: int = 5,
        timeout_seconds: float = 120.0,
        poll_interval_seconds: float = 1.0,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        download_opener: UrlOpener = urlopen,
    ) -> None:
        if not isinstance(max_polls, int) or max_polls < 1:
            raise D1BackupSafetyError("export_poll_limit_invalid")
        if not isinstance(timeout_seconds, (int, float)) or timeout_seconds <= 0:
            raise D1BackupSafetyError("export_timeout_invalid")
        if not isinstance(poll_interval_seconds, (int, float)) or poll_interval_seconds < 0:
            raise D1BackupSafetyError("export_poll_interval_invalid")
        self._transport, self._max_polls, self._timeout_seconds = transport, max_polls, float(timeout_seconds)
        self._poll_interval_seconds, self._clock, self._sleep, self._download_opener = float(poll_interval_seconds), clock, sleep, download_opener
        self._started = False

    def complete(self) -> D1ExportComplete:
        if self._started:
            raise D1BackupSafetyError("export_start_reuse_rejected")
        self._started = True
        started_at = self._clock()
        outcome = parse_export_polling_response(self._transport.export_polling())
        if isinstance(outcome, D1ExportComplete):
            return outcome
        bookmark = outcome.at_bookmark
        for _ in range(self._max_polls):
            if self._clock() - started_at >= self._timeout_seconds:
                raise D1BackupSafetyError("export_poll_timeout")
            if self._poll_interval_seconds:
                self._sleep(self._poll_interval_seconds)
            outcome = parse_export_polling_response(self._transport.export_polling(bookmark))
            if outcome.at_bookmark != bookmark:
                raise D1BackupSafetyError("export_polling_bookmark_changed")
            if isinstance(outcome, D1ExportComplete):
                return outcome
        raise D1BackupSafetyError("export_poll_limit_reached")

    def download(self, completed: D1ExportComplete) -> bytes:
        if not isinstance(completed, D1ExportComplete):
            raise D1BackupSafetyError("export_download_not_complete")
        try:
            response = self._download_opener(completed.signed_url, timeout=self._timeout_seconds)
            try:
                payload = response.read()
            finally:
                close = getattr(response, "close", None)
                if callable(close):
                    close()
        except (URLError, TimeoutError, OSError):
            raise D1BackupTransportError("export_download_transport_exception") from None
        if not isinstance(payload, bytes) or not payload:
            raise D1BackupSafetyError("export_download_invalid")
        return payload
