"""SerpApi Google adapter with a one-request, metadata-only boundary."""
from __future__ import annotations
import json, os
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence
from urllib.parse import urlencode, urlsplit, urlunsplit
from urllib.request import urlopen

SERP_RESULT_SCHEMA_VERSION = "market-signal-serp-result-v1"
MAX_SERP_RESULTS = 10


class SerpNormalizationError(ValueError): pass
class SerpApiSafetyError(RuntimeError): pass


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


def validate_normalized_results(value: object) -> list[dict[str, Any]]:
    """Validate the only cache payload consumed by the live SERP path."""
    if not isinstance(value, list) or len(value) > MAX_SERP_RESULTS:
        raise SerpApiSafetyError("normalized_cache_results_invalid")
    output, urls = [], set()
    for item in value:
        if not isinstance(item, Mapping) or set(item) != {"schema_version", "position", "title", "url", "domain", "snippet", "published_at"}:
            raise SerpApiSafetyError("normalized_cache_results_invalid")
        url = canonical_result_url(item.get("url"))
        if item.get("schema_version") != SERP_RESULT_SCHEMA_VERSION or not isinstance(item.get("position"), int) or item["position"] < 1 or not isinstance(item.get("title"), str) or not item["title"].strip() or not isinstance(item.get("domain"), str) or item["domain"] != urlsplit(url).netloc or not isinstance(item.get("snippet"), str) or not isinstance(item.get("published_at"), (str, type(None))) or url in urls:
            raise SerpApiSafetyError("normalized_cache_results_invalid")
        output.append(dict(item)); urls.add(url)
    return output


def normalized_query(value: object) -> str:
    if not isinstance(value, str) or not value.strip(): raise SerpApiSafetyError("query_invalid")
    return " ".join(value.split()).casefold()

def serp_cache_key(*, query: str, locale: str, region: str, result_count: int) -> str:
    if not all(isinstance(item, str) and item for item in (locale, region)) or result_count != MAX_SERP_RESULTS: raise SerpApiSafetyError("cache_key_invalid")
    return sha256(json.dumps({"query": normalized_query(query), "locale": locale, "region": region, "result_count": result_count}, sort_keys=True).encode()).hexdigest()

class LocalNormalizedSerpCache:
    """Local, gitignored cache containing only normalized result metadata."""
    def __init__(self, directory: Path, *, ttl_seconds: int = 7 * 24 * 60 * 60) -> None:
        if not isinstance(ttl_seconds, int) or ttl_seconds <= 0: raise SerpApiSafetyError("cache_ttl_invalid")
        self.directory, self.ttl_seconds = directory, ttl_seconds
    def get(self, key: str, *, now: datetime) -> list[dict[str, Any]] | None:
        path = self.directory / f"{key}.json"
        try: value=json.loads(path.read_text())
        except FileNotFoundError: return None
        except (OSError, json.JSONDecodeError): raise SerpApiSafetyError("cache_invalid")
        if not isinstance(value, Mapping) or value.get("schema_version") != "normalized-serp-cache-v1" or not isinstance(value.get("cached_at"), str) or not isinstance(value.get("results"), list): raise SerpApiSafetyError("cache_invalid")
        try: cached=datetime.fromisoformat(value["cached_at"].replace("Z","+00:00"))
        except ValueError as error: raise SerpApiSafetyError("cache_invalid") from error
        if now - cached > timedelta(seconds=self.ttl_seconds): return None
        return validate_normalized_results(value["results"])
    def put(self, key: str, results: Sequence[Mapping[str, Any]], *, now: datetime) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        payload={"schema_version":"normalized-serp-cache-v1","cached_at":now.isoformat(timespec="seconds").replace("+00:00","Z"),"results":validate_normalized_results(list(results))}
        (self.directory / f"{key}.json").write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True))

def _http_get(url: str, timeout: float) -> tuple[int, bytes]:
    with urlopen(url, timeout=timeout) as response: return int(response.status), response.read()

class SerpApiGoogleSearchAdapter:
    """A single Google organic search; no retry, batch, or provider switching."""
    def __init__(self, *, api_key: str | None = None, transport: Callable[[str, float], tuple[int, bytes]] = _http_get, timeout_seconds: float = 20.0, cache: LocalNormalizedSerpCache | None = None) -> None:
        self._api_key = (api_key if api_key is not None else os.environ.get("SERPAPI_API_KEY", "")).strip()
        self._transport, self._timeout, self._cache, self.request_count = transport, timeout_seconds, cache, 0
    def search(self, *, query: str, locale: str = "ja", region: str = "jp", result_count: int = MAX_SERP_RESULTS, now: datetime | None = None) -> tuple[list[dict[str, Any]], str]:
        if result_count != MAX_SERP_RESULTS: raise SerpApiSafetyError("result_count_invalid")
        current=now or datetime.now(timezone.utc); key=serp_cache_key(query=query,locale=locale,region=region,result_count=result_count)
        if self._cache:
            cached=self._cache.get(key,now=current)
            if cached is not None: return cached, "cache_hit"
        if not self._api_key: raise SerpApiSafetyError("api_key_missing")
        if self.request_count != 0: raise SerpApiSafetyError("request_limit_exceeded")
        self.request_count=1
        url="https://serpapi.com/search.json?"+urlencode({"engine":"google","q":query,"hl":locale,"gl":region,"num":result_count,"api_key":self._api_key})
        try: status, body=self._transport(url,self._timeout)
        except Exception as error: raise SerpApiSafetyError("transport_failure") from error
        if status < 200 or status >= 300: raise SerpApiSafetyError("http_failure")
        try: response=json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError,json.JSONDecodeError) as error: raise SerpApiSafetyError("response_malformed") from error
        if not isinstance(response, Mapping): raise SerpApiSafetyError("response_malformed")
        if response.get("error"): raise SerpApiSafetyError("provider_error")
        try: results=normalize_serp_response(response,limit=result_count)
        except SerpNormalizationError as error: raise SerpApiSafetyError("response_malformed") from error
        if response.get("organic_results") and not results:
            raise SerpApiSafetyError("response_malformed")
        if self._cache: self._cache.put(key,results,now=current)
        return results, "live_request"
