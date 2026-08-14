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

    def __init__(self, code: str, status: int | None = None):
        self.code = code
        self.status = status
        super().__init__(f"D1 read transport failed: {code}")


class D1ReadSafetyError(RuntimeError):
    """A response violated the approved read-only contract."""


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
            raise D1ReadTransportError("http_status", error.code) from None
        except (URLError, TimeoutError, OSError):
            raise D1ReadTransportError("transport_exception") from None
        if not content_type.lower().startswith("application/json"):
            raise D1ReadTransportError("unexpected_content_type", status)
        if not raw:
            raise D1ReadTransportError("empty_response", status)
        try:
            decoded = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise D1ReadTransportError("json_parse_failed", status) from None
        if not isinstance(decoded, Mapping):
            raise D1ReadTransportError("invalid_json_shape", status)
        if status < 200 or status >= 300:
            raise D1ReadTransportError("http_status", status)
        if decoded.get("success") is not True:
            raise D1ReadTransportError("api_success_false", status)
        return D1JsonResponse(status, content_type.split(";", 1)[0], len(raw), decoded)

    def identity(self) -> D1JsonResponse:
        return self._request("GET", "")

    def current_bookmark(self) -> D1JsonResponse:
        """Retrieve the current Time Travel bookmark without changing D1."""
        return self._request("GET", "/time_travel/bookmark")

    def fixed_select_batch(self, statements: Sequence[Mapping[str, object]]) -> D1JsonResponse:
        if not statements or any(not isinstance(item.get("sql"), str) or not item["sql"].lstrip().upper().startswith("SELECT ") or ";" in item["sql"].rstrip(";") for item in statements):
            raise D1ReadSafetyError("D1 Read transport accepts fixed single SELECT statements only")
        return self._request("POST", "/query", {"batch": list(statements)})


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
