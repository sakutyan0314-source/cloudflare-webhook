"""Read-only Phase 2A candidate listing through the local Wrangler login.

This command has no D1 write, migration, approval, execution, or article
mutation path.  It invokes only fixed SELECT statements from the existing
recommendation reader and emits a minimized JSON candidate list.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
from typing import Any, Mapping, Sequence

from ai_recommendation_d1_reader import AiRecommendationD1Reader
from search_console_d1_reader import D1ReadSafetyError, _validate_fixed_select
from search_console_improvement_candidate_review import build_review_envelopes
from search_console_improvement_candidates import build_improvement_candidate_report


DATABASE_NAME = "zero-capital-insight-db"
CLI_SCHEMA_VERSION = "phase-2a-production-candidate-list-v1"


class Phase2ACandidateReadError(RuntimeError):
    """Sanitized failure from the read-only candidate listing command."""


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _parse_wrangler_json(stdout: str) -> Mapping[str, Any]:
    try:
        value = json.loads(stdout)
    except json.JSONDecodeError as error:
        raise Phase2ACandidateReadError("wrangler_json_invalid") from error
    if isinstance(value, list):
        value = {"success": True, "result": value}
    if not isinstance(value, Mapping):
        raise Phase2ACandidateReadError("wrangler_response_invalid")
    return value


def _render_fixed_select(sql: str, params: Sequence[object]) -> str:
    """Bind fixed-reader parameters without exposing caller-controlled SQL."""
    if sql.count("?") != len(params):
        raise Phase2ACandidateReadError("fixed_select_parameter_mismatch")
    values = []
    for value in params:
        if isinstance(value, str):
            values.append("'" + value.replace("'", "''") + "'")
        elif isinstance(value, int) and not isinstance(value, bool):
            values.append(str(value))
        else:
            raise Phase2ACandidateReadError("fixed_select_parameter_invalid")
    for value in values:
        sql = sql.replace("?", value, 1)
    return sql


class WranglerFixedSelectTransport:
    """Adapter that exposes only the reader's prevalidated SELECT statements."""

    def __init__(self, runner: Any = subprocess.run, *, root: Path | None = None) -> None:
        self._runner, self._root = runner, root or _repo_root()

    def request(self, method: str, path: str, payload: object | None = None) -> Mapping[str, Any]:
        if method != "POST" or path != "/query" or not isinstance(payload, Mapping):
            raise Phase2ACandidateReadError("read_request_invalid")
        batch = payload.get("batch")
        if not isinstance(batch, list) or len(batch) != 3:
            raise Phase2ACandidateReadError("fixed_select_batch_invalid")
        results: list[Mapping[str, Any]] = []
        for item in batch:
            if not isinstance(item, Mapping) or not isinstance(item.get("sql"), str) or not isinstance(item.get("params"), list):
                raise Phase2ACandidateReadError("fixed_select_statement_invalid")
            try:
                _validate_fixed_select(type("Statement", (), {"sql": item["sql"]})())
            except D1ReadSafetyError as error:
                raise Phase2ACandidateReadError("fixed_select_rejected") from error
            command = [
                "node", "--no-warnings", "node_modules/wrangler/wrangler-dist/cli.js", "d1", "execute", DATABASE_NAME,
                "--remote", "--config", "./wrangler.toml", "--command", _render_fixed_select(item["sql"], item["params"]), "--json",
            ]
            try:
                completed = self._runner(command, cwd=self._root, capture_output=True, text=True, check=False)
            except OSError as error:
                raise Phase2ACandidateReadError("wrangler_start_failed") from error
            if completed.returncode != 0:
                raise Phase2ACandidateReadError("wrangler_read_failed")
            response = _parse_wrangler_json(completed.stdout)
            result = response.get("result")
            if not isinstance(result, list) or len(result) != 1 or not isinstance(result[0], Mapping):
                raise Phase2ACandidateReadError("wrangler_result_invalid")
            results.append(result[0])
        return {"success": True, "result": results}


def build_candidate_listing(reader: Any, property_uri: str, current_period_end: str) -> dict[str, Any]:
    """Build selection-safe Phase 2A candidate output without performing I/O here."""
    from datetime import date, timedelta
    try:
        end = date.fromisoformat(current_period_end)
    except (TypeError, ValueError) as error:
        raise Phase2ACandidateReadError("current_period_end_invalid") from error
    start = end - timedelta(days=6)
    page_rows, _affiliate_rows, article_rows = reader.fetch_source(property_uri, "web", start.isoformat(), end.isoformat())
    report = build_improvement_candidate_report(page_rows, article_rows, start.isoformat(), end.isoformat())
    # Phase 2A.5 owns the deterministic, content-free candidate fingerprint.
    envelopes = build_review_envelopes(report, article_rows)
    by_article = {item["article_id"]: item for item in envelopes}
    candidates = []
    for item in report["candidates"]:
        envelope = by_article.get(item["article_id"])
        if envelope is None:
            continue
        candidates.append({
            "article_id": item["article_id"], "title": envelope["title"], "category": envelope["category"],
            "recommendation_type": item["recommendation_type"], "reason_code": item["reason_code"],
            "current_metrics": {key: item[key] for key in ("current_clicks", "current_impressions", "current_ctr", "current_position")},
            "candidate_fingerprint": envelope["candidate_fingerprint"],
        })
    return {"schema_version": CLI_SCHEMA_VERSION, "current_period": report["current_period"], "previous_period": report["previous_period"], "candidate_count": len(candidates), "candidates": candidates}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="List Phase 2A SEO candidates using fixed D1 SELECTs only.")
    parser.add_argument("--property-uri", required=True)
    parser.add_argument("--current-period-end", required=True, help="Latest confirmed Search Console date (YYYY-MM-DD)")
    args = parser.parse_args(argv)
    try:
        listing = build_candidate_listing(AiRecommendationD1Reader(WranglerFixedSelectTransport()), args.property_uri, args.current_period_end)
    except (Phase2ACandidateReadError, D1ReadSafetyError, ValueError):
        print(json.dumps({"schema_version": CLI_SCHEMA_VERSION, "status": "fail", "error_class": "read_only_candidate_listing_failed"}))
        return 1
    print(json.dumps({"status": "pass", **listing}, ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
