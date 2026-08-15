"""Safe, one-session D1 Read REST boundary.

This module is deliberately read-only: it validates a clipboard token in
memory, builds fixed REST requests, parses only JSON responses, and verifies
that every D1 result set reports no database change.  It never logs or writes
credentials, headers, response bodies, or D1 data.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Protocol, Sequence
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class D1ReadTokenError(ValueError):
    """The clipboard value cannot safely be used as a D1 Read token."""


class D1ReadTransportError(RuntimeError):
    """Safe transport classification; never carries response or token text."""

    def __init__(self, code: str, status: int | None = None, diagnostic: "D1HttpDiagnostic | None" = None):
        self.code = code
        self.status = status
        self.diagnostic = diagnostic
        super().__init__(f"D1 read transport failed: {code}")


class D1ReadSafetyError(RuntimeError):
    """A response violated the approved read-only contract."""


@dataclass(frozen=True)
class D1HttpDiagnostic:
    """Minimal, safe HTTP/API diagnostics; never includes body/header text."""

    http_status: int | None
    content_type: str | None
    response_size: int | None
    success_flag: bool | None
    error_count: int | None
    error_code: str | None
    error_message_class: str | None
    result_count: int | None
    request_stage: str


@dataclass(frozen=True)
class FixedSelectRequestDiagnostic:
    """Static request shape proof without exposing SQL or parameter values."""

    endpoint_path: str
    payload_shape: str
    statement_count: int
    sql_field_present: bool
    params_field_present: bool
    validator_passed: bool


_TOKEN_ALLOWED = re.compile(r"^[A-Za-z0-9._-]+$")


def normalize_d1_read_token(value: object) -> str:
    """Trim only outer ASCII whitespace; reject all token-altering input.

    A terminal newline or surrounding spaces from a clipboard copy are safe to
    remove.  Whitespace/control characters inside the token, multiple lines,
    and characters outside the documented opaque-token character set are
    rejected rather than rewritten.
    """
    if not isinstance(value, str):
        raise D1ReadTokenError("D1 Read token input is invalid")
    normalized = value.strip(" \t\r\n")
    if not normalized or any(character.isspace() or ord(character) < 32 for character in normalized):
        raise D1ReadTokenError("D1 Read token input is invalid")
    if not _TOKEN_ALLOWED.fullmatch(normalized):
        raise D1ReadTokenError("D1 Read token input is invalid")
    return normalized


def authorization_header(token: str) -> str:
    """Build an Authorization value only after token validation."""
    return f"Bearer {normalize_d1_read_token(token)}"


class Clipboard(Protocol):
    def __call__(self) -> str:
        """Return clipboard text without logging it."""


@dataclass
class D1ReadTokenSession:
    """Keeps one validated D1 Read token only for a single diagnostic session."""

    _token: str
    _clear_clipboard: Callable[[], None]
    _closed: bool = False

    @classmethod
    def from_clipboard(
        cls, read_clipboard: Clipboard, clear_clipboard: Callable[[], None]
    ) -> "D1ReadTokenSession":
        return cls(normalize_d1_read_token(read_clipboard()), clear_clipboard)

    @property
    def token(self) -> str:
        if self._closed:
            raise D1ReadTokenError("D1 Read token session is closed")
        return self._token

    def close(self) -> None:
        if not self._closed:
            self._token = ""
            self._closed = True
            self._clear_clipboard()

    def __enter__(self) -> "D1ReadTokenSession":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


@dataclass(frozen=True)
class D1JsonResponse:
    status: int
    content_type: str
    response_size: int
    payload: Mapping[str, Any]


class HttpOpener(Protocol):
    def __call__(self, request: Request, timeout: float) -> Any:
        """Issue one HTTP request and return a response-like object."""


class D1ReadOnlyRestTransport:
    """No-DML REST adapter with injectable HTTP for deterministic tests."""

    def __init__(self, account_id: str, database_id: str, token: str, timeout_seconds: float = 20.0, opener: HttpOpener = urlopen):
        if not account_id or not database_id:
            raise D1ReadSafetyError("D1 Read target configuration is incomplete")
        self._account_id = account_id
        self._database_id = database_id
        self._authorization = authorization_header(token)
        self._timeout_seconds = timeout_seconds
        self._opener = opener

    def _request(self, method: str, path: str, payload: object | None = None) -> D1JsonResponse:
        if (method, path) not in {("GET", ""), ("GET", "/time_travel/bookmark"), ("POST", "/query")}:
            raise D1ReadSafetyError("D1 Read transport rejects this request route")
        body = None if payload is None else json.dumps(payload, separators=(",", ":")).encode("utf-8")
        try:
            request = Request(
                f"https://api.cloudflare.com/client/v4/accounts/{self._account_id}/d1/database/{self._database_id}{path}",
                data=body, method=method,
                headers={"Authorization": self._authorization, "Content-Type": "application/json"},
            )
        except ValueError:
            raise D1ReadTransportError("request_construction_failed") from None
        try:
            response = self._opener(request, timeout=self._timeout_seconds)
            try:
                status = int(response.status)
                content_type = str(response.headers.get("Content-Type", ""))
                raw = response.read()
            finally:
                close = getattr(response, "close", None)
                if callable(close):
                    close()
        except HTTPError as error:
            status = error.code
            content_type = str(error.headers.get("Content-Type", "")) if error.headers else ""
            try:
                raw = error.read()
            except OSError:
                raw = b""
            diagnostic = _safe_http_diagnostic(status, content_type, raw, "response_received")
            raise D1ReadTransportError(_classify_http_error(diagnostic), status, diagnostic) from None
        except (URLError, TimeoutError, OSError):
            raise D1ReadTransportError("transport_exception") from None
        diagnostic = _safe_http_diagnostic(status, content_type, raw, "response_received")
        if not content_type.lower().startswith("application/json"):
            raise D1ReadTransportError("unexpected_content_type", status, diagnostic)
        if not raw:
            raise D1ReadTransportError("empty_response", status, diagnostic)
        try:
            decoded = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise D1ReadTransportError("json_parse_failed", status, diagnostic) from None
        if not isinstance(decoded, Mapping):
            raise D1ReadTransportError("invalid_json_shape", status, diagnostic)
        if status < 200 or status >= 300:
            raise D1ReadTransportError(_classify_http_error(diagnostic), status, diagnostic)
        if decoded.get("success") is not True:
            raise D1ReadTransportError("api_success_false", status, diagnostic)
        return D1JsonResponse(status, content_type.split(";", 1)[0], len(raw), decoded)

    def identity(self) -> D1JsonResponse:
        return self._request("GET", "")

    def current_bookmark(self) -> D1JsonResponse:
        """Retrieve the current Time Travel bookmark without changing D1."""
        return self._request("GET", "/time_travel/bookmark")

    def fixed_select_batch(self, statements: Sequence[Mapping[str, object]]) -> D1JsonResponse:
        validate_fixed_select_batch(statements)
        return self._request("POST", "/query", {"batch": list(statements)})


def _placeholder_count(sql: str) -> int:
    """Count positional placeholders outside SQLite string literals."""
    count, quote, index = 0, None, 0
    while index < len(sql):
        character = sql[index]
        if quote:
            if character == quote:
                if index + 1 < len(sql) and sql[index + 1] == quote:
                    index += 1
                else:
                    quote = None
        elif character in {"'", '"'}:
            quote = character
        elif character == "?":
            count += 1
        index += 1
    return count


def validate_fixed_select_batch(statements: Sequence[Mapping[str, object]]) -> FixedSelectRequestDiagnostic:
    """Prove request shape before HTTP; rejects DML, DDL, and multi-statements."""
    if not isinstance(statements, Sequence) or isinstance(statements, (str, bytes)) or not statements:
        raise D1ReadSafetyError("invalid_sql_shape")
    for item in statements:
        sql = item.get("sql") if isinstance(item, Mapping) else None
        params = item.get("params") if isinstance(item, Mapping) else None
        if not isinstance(sql, str) or not re.match(r"^SELECT\b", sql.lstrip(), re.IGNORECASE):
            raise D1ReadSafetyError("invalid_sql_shape")
        if ";" in sql.rstrip(";"):
            raise D1ReadSafetyError("invalid_sql_shape")
        if not isinstance(params, Sequence) or isinstance(params, (str, bytes)):
            raise D1ReadSafetyError("parameter_mismatch")
        if _placeholder_count(sql) != len(params):
            raise D1ReadSafetyError("parameter_mismatch")
    return FixedSelectRequestDiagnostic("/query", "batch", len(statements), True, True, True)


def _safe_http_diagnostic(status: int | None, content_type: str | None, raw: bytes, request_stage: str) -> D1HttpDiagnostic:
    """Parse only error metadata and classify message text without retaining it."""
    decoded: Mapping[str, Any] | None = None
    if content_type and content_type.lower().startswith("application/json") and raw:
        try:
            candidate = json.loads(raw.decode("utf-8"))
            if isinstance(candidate, Mapping):
                decoded = candidate
        except (UnicodeDecodeError, json.JSONDecodeError):
            pass
    success = decoded.get("success") if decoded else None
    success_flag = success if isinstance(success, bool) else None
    errors = decoded.get("errors") if decoded else None
    error_items = errors if isinstance(errors, list) and all(isinstance(item, Mapping) for item in errors) else []
    error_code = None
    if error_items and isinstance(error_items[0].get("code"), (str, int)):
        error_code = str(error_items[0]["code"])
    message = error_items[0].get("message") if error_items else None
    message_class = _classify_error_message(message) if isinstance(message, str) else None
    result = decoded.get("result") if decoded else None
    result_count = len(result) if isinstance(result, list) else (1 if isinstance(result, Mapping) else None)
    return D1HttpDiagnostic(status, content_type.split(";", 1)[0] if content_type else None, len(raw), success_flag, len(error_items) if decoded is not None else None, error_code, message_class, result_count, request_stage)


def _classify_error_message(message: str) -> str:
    lowered = message.lower()
    if "json" in lowered:
        return "invalid_json"
    if any(term in lowered for term in ("parameter", "bind", "placeholder")):
        return "parameter_mismatch"
    if any(term in lowered for term in ("syntax", "sql", "statement")):
        return "invalid_sql_shape"
    if any(term in lowered for term in ("unsupported", "not allowed", "not support")):
        return "unsupported_query"
    if "database" in lowered and any(term in lowered for term in ("not found", "does not exist", "unknown")):
        return "database_not_found"
    if any(term in lowered for term in ("account", "database id", "database_id")) and any(term in lowered for term in ("mismatch", "invalid", "not found")):
        return "account_or_database_mismatch"
    if any(term in lowered for term in ("malformed", "invalid request", "bad request")):
        return "malformed_request"
    return "cloudflare_api_validation_error"


def _classify_http_error(diagnostic: D1HttpDiagnostic) -> str:
    if diagnostic.http_status == 400:
        return diagnostic.error_message_class or "unknown_http_400"
    return "http_status"


def validate_read_only_result_sets(payload: Mapping[str, Any], expected_count: int) -> list[Mapping[str, Any]]:
    """Require a successful D1 batch and zero write metadata in every set."""
    result = payload.get("result")
    if not isinstance(result, list) or len(result) != expected_count or not all(isinstance(item, Mapping) for item in result):
        raise D1ReadSafetyError("D1 Read result-set shape is invalid")
    output: list[Mapping[str, Any]] = []
    for item in result:
        meta = item.get("meta")
        if item.get("success") is not True or not isinstance(meta, Mapping):
            raise D1ReadSafetyError("D1 Read result set is unsuccessful")
        if meta.get("changed_db") is not False or meta.get("rows_written") != 0:
            raise D1ReadSafetyError("D1 Read detected a possible database change")
        output.append(item)
    return output
