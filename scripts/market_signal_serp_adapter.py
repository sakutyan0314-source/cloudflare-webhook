"""Pure, content-free normalization of a SERP provider response.

No provider connection is implemented here.  The adapter accepts an injected
response (fixtures in v1), keeps only result metadata, and never retains raw
provider payloads or competitor page bodies.
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence
from urllib.parse import urlsplit, urlunsplit

SERP_RESULT_SCHEMA_VERSION = "market-signal-serp-result-v1"
MAX_SERP_RESULTS = 10


class SerpNormalizationError(ValueError): pass


def canonical_result_url(value: object) -> str:
    if not isinstance(value, str): raise SerpNormalizationError("result_url_invalid")
    parts = urlsplit(value.strip())
    if parts.scheme not in {"https", "http"} or not parts.netloc: raise SerpNormalizationError("result_url_invalid")
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, parts.query, ""))


def normalize_serp_response(value: Mapping[str, Any], *, limit: int = MAX_SERP_RESULTS) -> list[dict[str, Any]]:
    if not isinstance(value, Mapping) or not isinstance(value.get("organic_results"), Sequence) or isinstance(value["organic_results"], (str, bytes)):
        raise SerpNormalizationError("serp_response_invalid")
    if not isinstance(limit, int) or not 1 <= limit <= MAX_SERP_RESULTS: raise SerpNormalizationError("result_limit_invalid")
    output, seen = [], set()
    for raw in value["organic_results"]:
        if not isinstance(raw, Mapping) or len(output) >= limit: continue
        try:
            position = raw.get("position")
            title = raw.get("title")
            url = canonical_result_url(raw.get("link", raw.get("url")))
            snippet = raw.get("snippet", raw.get("description", ""))
            if not isinstance(position, int) or position < 1 or not isinstance(title, str) or not title.strip() or not isinstance(snippet, str): raise SerpNormalizationError("result_invalid")
            if url in seen: continue
            published_at = raw.get("date")
            if published_at is not None and (not isinstance(published_at, str) or not published_at.strip()): published_at = None
            output.append({"schema_version": SERP_RESULT_SCHEMA_VERSION, "position": position, "title": title.strip(), "url": url, "domain": urlsplit(url).netloc, "snippet": snippet.strip(), "published_at": published_at})
            seen.add(url)
        except SerpNormalizationError:
            continue
    return output
