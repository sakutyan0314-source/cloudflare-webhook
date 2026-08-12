"""Read-only Google Search Console API client.

Credentials and property configuration are supplied only through environment
variables.  This module deliberately exposes no Search Console write API.
"""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional, Sequence


WEBMASTERS_READONLY_SCOPE = "https://www.googleapis.com/auth/webmasters.readonly"
ALLOWED_DIMENSIONS = frozenset(
    {"date", "query", "page", "country", "device", "searchAppearance"}
)
DEFAULT_SEARCH_TYPE = "web"
PROPERTY_PERMISSION_LEVELS = frozenset(
    {"siteOwner", "siteFullUser", "siteRestrictedUser"}
)


class SearchConsoleConfigurationError(ValueError):
    """Raised when the read-only client configuration is missing or invalid."""


def _require_environment(name: str, environment: Mapping[str, str]) -> str:
    value = environment.get(name, "").strip()
    if not value:
        raise SearchConsoleConfigurationError(f"{name} must be set")
    return value


def _validate_property_url(value: str) -> str:
    if not value.startswith(("https://", "http://")) or not value.endswith("/"):
        raise SearchConsoleConfigurationError(
            "SEARCH_CONSOLE_PROPERTY_URL must be an exact URL-prefix property ending in '/'")
    return value


def _iso_date(value: date | str, field_name: str) -> str:
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str):
        try:
            return date.fromisoformat(value).isoformat()
        except ValueError as error:
            raise ValueError(f"{field_name} must use YYYY-MM-DD") from error
    raise TypeError(f"{field_name} must be a date or YYYY-MM-DD string")


def _validate_dimensions(dimensions: Optional[Sequence[str]]) -> list[str]:
    values = list(dimensions or [])
    if len(values) != len(set(values)):
        raise ValueError("dimensions must not contain duplicates")
    invalid = [dimension for dimension in values if dimension not in ALLOWED_DIMENSIONS]
    if invalid:
        raise ValueError(f"unsupported Search Console dimensions: {', '.join(invalid)}")
    return values


class SearchConsoleClient:
    """A minimal client limited to Search Console read-only operations."""

    def __init__(self, service: Any, property_url: str):
        self._service = service
        self._property_url = _validate_property_url(property_url)

    @classmethod
    def from_environment(
        cls, environment: Optional[Mapping[str, str]] = None
    ) -> "SearchConsoleClient":
        """Build a client from an external service-account JSON key path.

        The key contents are never read into application configuration or logs.
        """
        environment = environment if environment is not None else os.environ
        property_url = _validate_property_url(
            _require_environment("SEARCH_CONSOLE_PROPERTY_URL", environment)
        )
        key_path = Path(_require_environment("GOOGLE_APPLICATION_CREDENTIALS", environment))
        if not key_path.is_file():
            raise SearchConsoleConfigurationError(
                "GOOGLE_APPLICATION_CREDENTIALS must reference a readable file"
            )

        # Imported lazily so local unit tests do not need Google SDK packages.
        from google.oauth2 import service_account
        from googleapiclient.discovery import build

        credentials = service_account.Credentials.from_service_account_file(
            str(key_path), scopes=[WEBMASTERS_READONLY_SCOPE]
        )
        service = build("searchconsole", "v1", credentials=credentials, cache_discovery=False)
        return cls(service=service, property_url=property_url)

    def list_sites(self) -> Mapping[str, Any]:
        """Return Search Console properties accessible to this identity."""
        return self._service.sites().list().execute()

    @property
    def property_url(self) -> str:
        """Configured exact URL-prefix property, without exposing credentials."""
        return self._property_url

    def property_permission_level(self) -> str:
        """Return the API-confirmed permission level for the configured property.

        Search Console Sites resources use ``permissionLevel`` (not
        ``permission``).  URL-prefix matching is intentionally exact because
        the configured URL is itself the canonical property identifier.
        """
        response = self.list_sites()
        entries = response.get("siteEntry", []) if isinstance(response, Mapping) else []
        matches = [
            entry for entry in entries
            if isinstance(entry, Mapping) and entry.get("siteUrl") == self._property_url
        ]
        if len(matches) != 1:
            raise SearchConsoleConfigurationError(
                "configured Search Console URL-prefix property is unavailable"
            )
        level = matches[0].get("permissionLevel")
        if level not in PROPERTY_PERMISSION_LEVELS:
            raise SearchConsoleConfigurationError(
                "configured Search Console property has no usable permissionLevel"
            )
        return str(level)

    def query_search_analytics(
        self,
        start_date: date | str,
        end_date: date | str,
        dimensions: Optional[Sequence[str]] = None,
        *,
        row_limit: int = 1_000,
        start_row: int = 0,
        search_type: str = DEFAULT_SEARCH_TYPE,
        dimension_filter_groups: Optional[Sequence[Mapping[str, Any]]] = None,
        aggregation_type: Optional[str] = None,
        data_state: Optional[str] = None,
    ) -> Mapping[str, Any]:
        """Read Search Analytics rows for the configured property.

        This uses only ``searchanalytics.query``; it neither stores nor modifies
        Search Console data.
        """
        normalized_start = _iso_date(start_date, "start_date")
        normalized_end = _iso_date(end_date, "end_date")
        if normalized_start > normalized_end:
            raise ValueError("start_date must be on or before end_date")
        if not isinstance(row_limit, int) or not 1 <= row_limit <= 25_000:
            raise ValueError("row_limit must be an integer between 1 and 25000")
        if not isinstance(start_row, int) or start_row < 0:
            raise ValueError("start_row must be a non-negative integer")
        if not isinstance(search_type, str) or not search_type:
            raise ValueError("search_type must be a non-empty string")

        body: dict[str, Any] = {
            "startDate": normalized_start,
            "endDate": normalized_end,
            "dimensions": _validate_dimensions(dimensions),
            "rowLimit": row_limit,
            "startRow": start_row,
            "type": search_type,
        }
        if dimension_filter_groups is not None:
            body["dimensionFilterGroups"] = list(dimension_filter_groups)
        if aggregation_type is not None:
            body["aggregationType"] = aggregation_type
        if data_state is not None:
            body["dataState"] = data_state

        return self._service.searchanalytics().query(
            siteUrl=self._property_url, body=body
        ).execute()
