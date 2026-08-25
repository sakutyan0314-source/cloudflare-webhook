"""Read-only KPI baseline report for the existing production D1 data.

The command exposes a deliberately closed set of SELECT statements.  It never
accepts SQL from the operator and has no migration, write, pipeline, or Worker
execution path.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence

from search_console_improvement_candidates import MIN_IMPRESSIONS, MIN_OBSERVATION_DAYS


DATABASE_NAME = "zero-capital-insight-db"
DEFAULT_PROPERTY_URI = "https://cloudflare-webhook.tyansaku3325.workers.dev/"
REPORT_SCHEMA_VERSION = "kpi-baseline-report-v1"


class KpiBaselineReadError(RuntimeError):
    """Sanitized failure from the fixed, read-only KPI report."""


class KpiReader(Protocol):
    def fetch(self, period_start: str, period_end: str, property_uri: str) -> Mapping[str, Sequence[Mapping[str, Any]]]: ...


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _iso_day(value: object, field: str) -> str:
    try:
        return date.fromisoformat(str(value)).isoformat()
    except (TypeError, ValueError) as error:
        raise KpiBaselineReadError(f"{field}_invalid") from error


def resolve_period(period_start: str | None, period_end: str | None, *, today: date | None = None) -> tuple[str, str]:
    end = _iso_day(period_end, "period_end") if period_end else (today or datetime.now(timezone.utc).date()).isoformat()
    start = _iso_day(period_start, "period_start") if period_start else (date.fromisoformat(end) - timedelta(days=13)).isoformat()
    if start > end or (date.fromisoformat(end) - date.fromisoformat(start)).days + 1 > 366:
        raise KpiBaselineReadError("period_invalid")
    return start, end


# The SQL is intentionally private to this module.  Operator arguments only
# bind dates/property URI; no command accepts caller-supplied SQL.
_FIXED_SELECTS: dict[str, str] = {
    "pipeline_runs": """SELECT id, trigger_type, status, stage, article_id, notification_status,
                                error_code, error_summary,
                                COALESCE(completed_at, failed_at, updated_at, started_at) AS event_at
                         FROM pipeline_runs
                         WHERE started_at >= ? AND started_at < ?
                         ORDER BY id ASC""",
    "canary_runs": """SELECT pipeline_run_id
                      FROM production_executions
                      WHERE pipeline_run_id IS NOT NULL AND started_at >= ? AND started_at < ?
                      ORDER BY pipeline_run_id ASC""",
    "quality_audits": """SELECT audit_id, pipeline_run_id, classification, evaluated_at
                          FROM quality_gate_audits
                          WHERE evaluated_at >= ? AND evaluated_at < ?
                          ORDER BY evaluated_at ASC, audit_id ASC""",
    "quality_reasons": """SELECT r.audit_id, r.reason_code
                           FROM quality_gate_audit_reasons AS r
                           JOIN quality_gate_audits AS a ON a.audit_id = r.audit_id
                           WHERE a.evaluated_at >= ? AND a.evaluated_at < ?
                           ORDER BY r.audit_id ASC, r.reason_order ASC""",
    "search_console": """SELECT metric_date, article_id, clicks, impressions, position
                           FROM search_console_page_daily_metrics
                           WHERE property_uri = ? AND search_type = 'web' AND metric_date BETWEEN ? AND ?
                           ORDER BY metric_date ASC, page_url ASC""",
    "affiliate_clicks": """SELECT article_id, placement, category, clicked_at
                             FROM affiliate_click_events
                             WHERE clicked_at >= ? AND clicked_at < ?
                             ORDER BY clicked_at ASC, id ASC""",
}


def _render_fixed_select(sql: str, params: Sequence[str]) -> str:
    if sql not in _FIXED_SELECTS.values() or sql.lstrip().upper().startswith("SELECT") is False or ";" in sql:
        raise KpiBaselineReadError("fixed_select_rejected")
    if sql.count("?") != len(params):
        raise KpiBaselineReadError("fixed_select_parameter_mismatch")
    for value in params:
        if not isinstance(value, str):
            raise KpiBaselineReadError("fixed_select_parameter_invalid")
        sql = sql.replace("?", "'" + value.replace("'", "''") + "'", 1)
    return sql


def _parse_wrangler_json(stdout: str) -> Mapping[str, Any]:
    try:
        value = json.loads(stdout)
    except json.JSONDecodeError as error:
        raise KpiBaselineReadError("wrangler_json_invalid") from error
    if isinstance(value, list):
        value = {"result": value}
    if not isinstance(value, Mapping):
        raise KpiBaselineReadError("wrangler_response_invalid")
    return value


class WranglerFixedKpiReader:
    """Production adapter limited to this module's six fixed SELECTs."""

    def __init__(self, runner: Any = subprocess.run, *, root: Path | None = None) -> None:
        self._runner, self._root = runner, root or _repo_root()

    def _select(self, name: str, params: Sequence[str]) -> list[Mapping[str, Any]]:
        sql = _FIXED_SELECTS.get(name)
        if sql is None:
            raise KpiBaselineReadError("fixed_select_name_invalid")
        command = [
            "node", "--no-warnings", "node_modules/wrangler/wrangler-dist/cli.js", "d1", "execute", DATABASE_NAME,
            "--remote", "--config", "./wrangler.toml", "--command", _render_fixed_select(sql, params), "--json",
        ]
        try:
            completed = self._runner(command, cwd=self._root, capture_output=True, text=True, check=False)
        except OSError as error:
            raise KpiBaselineReadError("wrangler_start_failed") from error
        if completed.returncode != 0:
            raise KpiBaselineReadError("wrangler_read_failed")
        result = _parse_wrangler_json(completed.stdout).get("result")
        if not isinstance(result, list) or len(result) != 1 or not isinstance(result[0], Mapping):
            raise KpiBaselineReadError("wrangler_result_invalid")
        meta, rows = result[0].get("meta"), result[0].get("results")
        if not isinstance(meta, Mapping) or meta.get("changed_db") is not False or meta.get("rows_written") != 0:
            raise KpiBaselineReadError("unexpected_d1_write")
        if not isinstance(rows, list) or not all(isinstance(row, Mapping) for row in rows):
            raise KpiBaselineReadError("wrangler_rows_invalid")
        return list(rows)

    def fetch(self, period_start: str, period_end: str, property_uri: str) -> Mapping[str, Sequence[Mapping[str, Any]]]:
        end_exclusive = (date.fromisoformat(period_end) + timedelta(days=1)).isoformat() + "T00:00:00Z"
        start_inclusive = period_start + "T00:00:00Z"
        return {
            "pipeline_runs": self._select("pipeline_runs", (start_inclusive, end_exclusive)),
            "canary_runs": self._select("canary_runs", (start_inclusive, end_exclusive)),
            "quality_audits": self._select("quality_audits", (start_inclusive, end_exclusive)),
            "quality_reasons": self._select("quality_reasons", (start_inclusive, end_exclusive)),
            "search_console": self._select("search_console", (property_uri, period_start, period_end)),
            "affiliate_clicks": self._select("affiliate_clicks", (start_inclusive, end_exclusive)),
        }


def _day_from_timestamp(value: object) -> str:
    if not isinstance(value, str) or len(value) < 10:
        raise KpiBaselineReadError("timestamp_invalid")
    return _iso_day(value[:10], "timestamp")


def _content_summary(rows: Sequence[Mapping[str, Any]], canary_rows: Sequence[Mapping[str, Any]], start: str, end: str) -> dict[str, Any]:
    canary_run_ids = {row.get("pipeline_run_id") for row in canary_rows if isinstance(row.get("pipeline_run_id"), int)}
    days = [(date.fromisoformat(start) + timedelta(days=offset)).isoformat() for offset in range((date.fromisoformat(end) - date.fromisoformat(start)).days + 1)]
    per_day_articles: Counter[str] = Counter()
    scheduled_no_article_days: set[str] = set()
    scheduled_runs = completed = failed = published = canary_runs = canary_articles = 0
    for row in rows:
        run_id, trigger, status, article_id = row.get("id"), row.get("trigger_type"), row.get("status"), row.get("article_id")
        day = _day_from_timestamp(row.get("event_at"))
        has_article = isinstance(article_id, int)
        if has_article:
            per_day_articles[day] += 1; published += 1
        if isinstance(run_id, int) and run_id in canary_run_ids:
            canary_runs += 1
            if has_article: canary_articles += 1
        if trigger == "cron":
            scheduled_runs += 1
            completed += int(status == "completed")
            failed += int(status == "failed")
            if not has_article: scheduled_no_article_days.add(day)
    return {
        "scheduled_pipeline_runs": scheduled_runs,
        "scheduled_completed_runs": completed,
        "scheduled_failed_runs": failed,
        "published_article_count": published,
        "calendar_no_update_days": [item for item in days if per_day_articles[item] == 0],
        "scheduled_no_update_days": sorted(scheduled_no_article_days),
        "normal_scheduled": {"runs": scheduled_runs, "published_articles": sum(1 for row in rows if row.get("trigger_type") == "cron" and isinstance(row.get("article_id"), int))},
        "topic_aware_canary": {"runs": canary_runs, "published_articles": canary_articles},
    }


def _quality_summary(audits: Sequence[Mapping[str, Any]], reasons: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    classifications = Counter(str(row.get("classification")) for row in audits)
    failed_audit_ids = {row.get("audit_id") for row in audits if row.get("classification") == "fail"}
    failures = Counter(str(row.get("reason_code")) for row in reasons if row.get("audit_id") in failed_audit_ids)
    passed, failed = classifications["pass"], classifications["fail"]
    return {"quality_gate_pass_count": passed, "quality_gate_fail_count": failed, "quality_gate_pass_rate": round(passed / (passed + failed), 6) if passed + failed else None, "fail_reasons": dict(sorted(failures.items()))}


def _search_summary(rows: Sequence[Mapping[str, Any]], start: str, end: str) -> dict[str, Any]:
    by_day: dict[str, dict[str, float]] = defaultdict(lambda: {"impressions": 0.0, "clicks": 0.0, "weighted_position": 0.0})
    observed_articles: set[int] = set()
    for row in rows:
        metric_day = _iso_day(row.get("metric_date"), "metric_date")
        impressions, clicks, position = row.get("impressions"), row.get("clicks"), row.get("position")
        if not all(isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0 for value in (impressions, clicks, position)):
            raise KpiBaselineReadError("search_metric_invalid")
        by_day[metric_day]["impressions"] += impressions; by_day[metric_day]["clicks"] += clicks; by_day[metric_day]["weighted_position"] += position * impressions
        if isinstance(row.get("article_id"), int): observed_articles.add(row["article_id"])
    total_impressions = sum(item["impressions"] for item in by_day.values())
    total_clicks = sum(item["clicks"] for item in by_day.values())
    weighted_position = sum(item["weighted_position"] for item in by_day.values())
    period_end = date.fromisoformat(end); current_start = period_end - timedelta(days=6); previous_start = current_start - timedelta(days=7)
    current = [item for day, item in by_day.items() if current_start.isoformat() <= day <= end]
    previous = [item for day, item in by_day.items() if previous_start.isoformat() <= day < current_start.isoformat()]
    current_impressions, previous_impressions = sum(item["impressions"] for item in current), sum(item["impressions"] for item in previous)
    sufficient = len(current) >= MIN_OBSERVATION_DAYS and len(previous) >= MIN_OBSERVATION_DAYS and current_impressions >= MIN_IMPRESSIONS and previous_impressions >= MIN_IMPRESSIONS
    return {"page_daily_row_count": len(rows), "observation_days": len(by_day), "observed_article_count": len(observed_articles), "impressions": int(total_impressions), "clicks": int(total_clicks), "ctr": round(total_clicks / total_impressions, 6) if total_impressions else None, "average_position": round(weighted_position / total_impressions, 6) if total_impressions else None, "evidence_sufficiency": {"status": "sufficient" if sufficient else "insufficient_data", "rule": "phase_2a_7_day_comparison", "current_observation_days": len(current), "previous_observation_days": len(previous), "current_impressions": int(current_impressions), "previous_impressions": int(previous_impressions), "min_observation_days": MIN_OBSERVATION_DAYS, "min_impressions": MIN_IMPRESSIONS}}


def _affiliate_summary(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    by_article: Counter[str] = Counter(); by_placement: Counter[str] = Counter(); by_category: Counter[str] = Counter()
    for row in rows:
        article_id, placement, category = row.get("article_id"), row.get("placement"), row.get("category")
        if not isinstance(article_id, int) or not isinstance(placement, str) or not isinstance(category, str):
            raise KpiBaselineReadError("affiliate_row_invalid")
        by_article[str(article_id)] += 1; by_placement[placement] += 1; by_category[category] += 1
    return {"affiliate_click_count": len(rows), "article_click_counts": dict(sorted(by_article.items(), key=lambda item: int(item[0]))), "placement_click_counts": dict(sorted(by_placement.items())), "category_click_counts": dict(sorted(by_category.items()))}


def build_kpi_baseline_report(reader: KpiReader, period_start: str | None = None, period_end: str | None = None, property_uri: str = DEFAULT_PROPERTY_URI, *, today: date | None = None) -> dict[str, Any]:
    start, end = resolve_period(period_start, period_end, today=today)
    source = reader.fetch(start, end, property_uri)
    required = {"pipeline_runs", "canary_runs", "quality_audits", "quality_reasons", "search_console", "affiliate_clicks"}
    if set(source) != required or not all(isinstance(source[key], Sequence) for key in required):
        raise KpiBaselineReadError("reader_result_invalid")
    return {"schema_version": REPORT_SCHEMA_VERSION, "period": {"start": start, "end": end, "days": (date.fromisoformat(end) - date.fromisoformat(start)).days + 1}, "property_uri": property_uri, "content_supply": _content_summary(source["pipeline_runs"], source["canary_runs"], start, end), "quality": _quality_summary(source["quality_audits"], source["quality_reasons"]), "search_console": _search_summary(source["search_console"], start, end), "affiliate": _affiliate_summary(source["affiliate_clicks"]), "read_only": {"fixed_select_only": True, "changed_db": False, "rows_written": 0}}


def render_summary(report: Mapping[str, Any]) -> str:
    period, content, quality, search, affiliate = report["period"], report["content_supply"], report["quality"], report["search_console"], report["affiliate"]
    return "\n".join((
        f"KPI BASELINE ({period['start']} to {period['end']}; {period['days']} days)",
        f"CONTENT scheduled={content['scheduled_pipeline_runs']} completed={content['scheduled_completed_runs']} failed={content['scheduled_failed_runs']} published={content['published_article_count']} no_update_days={len(content['calendar_no_update_days'])}",
        f"QUALITY pass={quality['quality_gate_pass_count']} fail={quality['quality_gate_fail_count']} pass_rate={quality['quality_gate_pass_rate']}",
        f"SEARCH rows={search['page_daily_row_count']} days={search['observation_days']} impressions={search['impressions']} clicks={search['clicks']} ctr={search['ctr']} position={search['average_position']} evidence={search['evidence_sufficiency']['status']}",
        f"AFFILIATE clicks={affiliate['affiliate_click_count']}",
        "READ_ONLY changed_db=false rows_written=0",
    ))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only KPI baseline report using fixed production D1 SELECTs.")
    parser.add_argument("--period-start")
    parser.add_argument("--period-end")
    parser.add_argument("--property-uri", default=DEFAULT_PROPERTY_URI)
    parser.add_argument("--format", choices=("summary", "json"), default="summary")
    args = parser.parse_args(argv)
    try:
        report = build_kpi_baseline_report(WranglerFixedKpiReader(), args.period_start, args.period_end, args.property_uri)
    except (KpiBaselineReadError, ValueError):
        print(json.dumps({"schema_version": REPORT_SCHEMA_VERSION, "status": "fail", "error_class": "kpi_baseline_read_failed"}))
        return 1
    if args.format == "json": print(json.dumps({"status": "pass", **report}, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    else: print(render_summary(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
