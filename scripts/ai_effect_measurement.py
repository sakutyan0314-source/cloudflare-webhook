"""Local-only v2.0-E effect measurement foundation.

No D1, Search Console, affiliate, or AI client is present here.  Callers pass
already-read final data; this module only calculates reproducible windows,
aggregates, contamination, and human-review envelopes.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import re
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence
from zoneinfo import ZoneInfo


MEASUREMENT_SCHEMA_VERSION = "v2.0-e-measurement-v1"
MEASUREMENT_REVIEW_SCHEMA_VERSION = "v2.0-e-measurement-review-v1"
V2F_HANDOFF_SCHEMA_VERSION = "v2.0-f-measurement-handoff-v1"
MEASUREMENT_TIMEZONE = "America/Los_Angeles"
BEFORE_WINDOW_DAYS = 14
EXCLUSION_WINDOW_DAYS = 7
AFTER_WINDOW_DAYS = 14
MIN_FINAL_DAYS_PER_WINDOW = 7
MIN_IMPRESSIONS_PER_WINDOW = 10
THRESHOLD_STATUS = "unapproved"
MEASUREMENT_CLASSIFICATIONS = frozenset({"measurement_pending", "insufficient_data", "contaminated", "classification_pending_threshold", "improved", "neutral", "worsened"})
MEASUREMENT_REVIEW_DECISIONS = frozenset({"accept_result", "hold", "reject_measurement"})
METRIC_NAMES = ("impressions", "clicks", "ctr", "average_position", "affiliate_click_count")
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_SECRET_KEY = re.compile(r"(?:raw_?response|authorization|api[_ -]?key|private[_ -]?key|secret|token)", re.IGNORECASE)
_SECRET_VALUE = re.compile(r"(?:api[_ -]?key|authorization|bearer\s+|private[_ -]?key|token)\s*[:=]", re.IGNORECASE)


class MeasurementSafetyError(ValueError):
    """Measurement data is incomplete, unsafe, or not reproducible."""


def _canonical_json(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as error:
        raise MeasurementSafetyError("measurement canonical JSON is invalid") from error


def _id(value: object, name: str) -> str:
    if not isinstance(value, str) or not _SAFE_ID.fullmatch(value):
        raise MeasurementSafetyError(name + " is invalid")
    return value


def _date(value: object, name: str) -> date:
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError) as error:
        raise MeasurementSafetyError(name + " is invalid") from error


def _timestamp(value: object, name: str) -> datetime:
    if not isinstance(value, str):
        raise MeasurementSafetyError(name + " is invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise MeasurementSafetyError(name + " is invalid") from error
    if parsed.tzinfo is None:
        raise MeasurementSafetyError(name + " must include an offset")
    return parsed.astimezone(timezone.utc)


def _reject_sensitive(value: Any) -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if not isinstance(key, str) or _SECRET_KEY.search(key):
                raise MeasurementSafetyError("sensitive data is prohibited")
            _reject_sensitive(child)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for child in value:
            _reject_sensitive(child)
    elif isinstance(value, str) and _SECRET_VALUE.search(value):
        raise MeasurementSafetyError("sensitive data is prohibited")


def build_measurement_windows(applied_at: str) -> Dict[str, Dict[str, str]]:
    """Build calendar-day windows in the fixed Search Console reporting zone."""
    local_day = _timestamp(applied_at, "applied_at").astimezone(ZoneInfo(MEASUREMENT_TIMEZONE)).date()
    before_end = local_day - timedelta(days=1)
    before_start = before_end - timedelta(days=BEFORE_WINDOW_DAYS - 1)
    exclusion_start = local_day
    exclusion_end = exclusion_start + timedelta(days=EXCLUSION_WINDOW_DAYS - 1)
    after_start = exclusion_end + timedelta(days=1)
    after_end = after_start + timedelta(days=AFTER_WINDOW_DAYS - 1)
    def pack(start: date, end: date) -> Dict[str, str]: return {"start": start.isoformat(), "end": end.isoformat()}
    return {"before_window": pack(before_start, before_end), "exclusion_window": pack(exclusion_start, exclusion_end), "after_window": pack(after_start, after_end)}


def _in_window(day: date, window: Mapping[str, str]) -> bool:
    return _date(window["start"], "window start") <= day <= _date(window["end"], "window end")


def _normalized_page_rows(rows: Iterable[Mapping[str, Any]], article_id: int) -> list[Dict[str, Any]]:
    output = []
    for row in rows:
        if not isinstance(row, Mapping) or row.get("article_id") != article_id:
            raise MeasurementSafetyError("page metric article does not match")
        metric_day = _date(row.get("metric_date"), "metric_date")
        clicks, impressions, position = row.get("clicks"), row.get("impressions"), row.get("position")
        if not all(isinstance(value, int) and not isinstance(value, bool) and value >= 0 for value in (clicks, impressions)):
            raise MeasurementSafetyError("page metric count is invalid")
        if position is not None and (not isinstance(position, (int, float)) or isinstance(position, bool) or position < 0):
            raise MeasurementSafetyError("page metric position is invalid")
        output.append({"metric_date": metric_day, "clicks": clicks, "impressions": impressions, "position": position})
    return output


def _aggregate_page(rows: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    impressions = sum(row["impressions"] for row in rows)
    clicks = sum(row["clicks"] for row in rows)
    positioned = [row for row in rows if row["position"] is not None]
    weighted_position = sum(float(row["position"]) * row["impressions"] for row in positioned)
    position_impressions = sum(row["impressions"] for row in positioned)
    return {
        "final_days_observed": len({row["metric_date"].isoformat() for row in rows}),
        "impressions": impressions,
        "clicks": clicks,
        "ctr": round(clicks / impressions, 6) if impressions else None,
        "average_position": round(weighted_position / position_impressions, 6) if position_impressions else None,
    }


def _affiliate_count(events: Optional[Sequence[Mapping[str, Any]]], article_id: int, window: Mapping[str, str]) -> Optional[int]:
    if events is None:
        return None
    count = 0
    for event in events:
        if not isinstance(event, Mapping) or event.get("article_id") != article_id or event.get("link_type") != "amazon_search":
            raise MeasurementSafetyError("affiliate event is invalid")
        clicked_at = _timestamp(event.get("clicked_at"), "affiliate clicked_at").astimezone(ZoneInfo(MEASUREMENT_TIMEZONE)).date()
        if _in_window(clicked_at, window): count += 1
    return count


def _delta(before: Optional[float | int], after: Optional[float | int]) -> Dict[str, Any]:
    if before is None or after is None:
        return {"absolute_delta": None, "relative_delta": None, "direction": "unavailable"}
    absolute = round(after - before, 6)
    relative = None if before == 0 else round(absolute / before, 6)
    return {"absolute_delta": absolute, "relative_delta": relative, "direction": "increase" if absolute > 0 else "decrease" if absolute < 0 else "unchanged"}


def _validate_execution_input(execution: Mapping[str, Any]) -> Dict[str, Any]:
    required = {"execution_id", "article_id", "plan_id", "recommendation_id", "applied_at", "execution_result_classification", "execution_authorized"}
    if not isinstance(execution, Mapping) or not required <= set(execution):
        raise MeasurementSafetyError("execution measurement input is incomplete")
    if execution.get("execution_result_classification") != "result_known_applied" or execution.get("execution_authorized") is not False:
        raise MeasurementSafetyError("execution is not a confirmed safe measurement subject")
    for key in ("execution_id", "plan_id", "recommendation_id"):
        _id(execution.get(key), key)
    if not isinstance(execution.get("article_id"), int) or execution["article_id"] < 1:
        raise MeasurementSafetyError("execution article ID is invalid")
    _timestamp(execution.get("applied_at"), "applied_at")
    _reject_sensitive(execution)
    return dict(execution)


def _contamination(events: Sequence[Mapping[str, Any]], anomalies: Sequence[Mapping[str, Any]], execution: Mapping[str, Any], windows: Mapping[str, Mapping[str, str]], snapshot_mismatch: bool) -> list[str]:
    reasons = ["snapshot_fingerprint_mismatch"] if snapshot_mismatch else []
    observed_windows = (windows["before_window"], windows["exclusion_window"], windows["after_window"])
    protected = {"title", "description", "category", "content_sha256", "body_markdown_sha256", "seo_status", "public_state"}
    for event in events:
        if not isinstance(event, Mapping): raise MeasurementSafetyError("change event is invalid")
        at = _timestamp(event.get("at"), "change event timestamp").astimezone(ZoneInfo(MEASUREMENT_TIMEZONE)).date()
        fields = event.get("fields")
        if not isinstance(fields, list) or not all(isinstance(field, str) for field in fields): raise MeasurementSafetyError("change event fields are invalid")
        if not any(_in_window(at, window) for window in observed_windows): continue
        expected_initial = event.get("execution_id") == execution["execution_id"] and event.get("plan_id") == execution["plan_id"] and set(fields) <= set(execution.get("applied_fields", []))
        if not expected_initial and (set(fields) & protected or event.get("plan_outside_change") is True or event.get("execution_id") != execution["execution_id"]):
            reasons.append("article_change_within_measurement_windows")
    for anomaly in anomalies:
        if not isinstance(anomaly, Mapping) or not isinstance(anomaly.get("code"), str): raise MeasurementSafetyError("data anomaly is invalid")
        start, end = _date(anomaly.get("start_date"), "anomaly start"), _date(anomaly.get("end_date"), "anomaly end")
        if any(start <= _date(window["end"], "window end") and end >= _date(window["start"], "window start") for window in observed_windows):
            reasons.append("search_console_data_anomaly")
    return sorted(set(reasons))


def build_measurement(
    execution: Mapping[str, Any], *, page_rows: Iterable[Mapping[str, Any]], affiliate_events: Optional[Sequence[Mapping[str, Any]]],
    latest_final_date: str, change_events: Sequence[Mapping[str, Any]] = (), anomalies: Sequence[Mapping[str, Any]] = (), snapshot_mismatch: bool = False,
) -> Dict[str, Any]:
    """Build a deterministic envelope; no effect-size threshold is applied."""
    safe_execution = _validate_execution_input(execution)
    windows = build_measurement_windows(safe_execution["applied_at"])
    latest = _date(latest_final_date, "latest_final_date")
    pages = _normalized_page_rows(page_rows, safe_execution["article_id"])
    before_rows = [row for row in pages if _in_window(row["metric_date"], windows["before_window"])]
    after_rows = [row for row in pages if _in_window(row["metric_date"], windows["after_window"])]
    before, after = _aggregate_page(before_rows), _aggregate_page(after_rows)
    before["affiliate_click_count"] = _affiliate_count(affiliate_events, safe_execution["article_id"], windows["before_window"])
    after["affiliate_click_count"] = _affiliate_count(affiliate_events, safe_execution["article_id"], windows["after_window"])
    deltas = {metric: _delta(before.get(metric), after.get(metric)) for metric in METRIC_NAMES}
    contamination_reasons = _contamination(change_events, anomalies, safe_execution, windows, snapshot_mismatch)
    if contamination_reasons:
        classification, sufficiency, confidence = "contaminated", "not_evaluated", "low"
    elif latest < _date(windows["after_window"]["end"], "after end"):
        classification, sufficiency, confidence = "measurement_pending", "not_evaluated", "low"
    elif before["final_days_observed"] < MIN_FINAL_DAYS_PER_WINDOW or after["final_days_observed"] < MIN_FINAL_DAYS_PER_WINDOW or before["impressions"] < MIN_IMPRESSIONS_PER_WINDOW or after["impressions"] < MIN_IMPRESSIONS_PER_WINDOW:
        classification, sufficiency, confidence = "insufficient_data", "insufficient_data", "low"
    else:
        classification, sufficiency, confidence = "classification_pending_threshold", "sufficient", "medium"
    source = {
        "measurement_schema_version": MEASUREMENT_SCHEMA_VERSION,
        "execution_id": safe_execution["execution_id"], "article_id": safe_execution["article_id"], "plan_id": safe_execution["plan_id"],
        "recommendation_id": safe_execution["recommendation_id"], "applied_at": safe_execution["applied_at"], "timezone": MEASUREMENT_TIMEZONE,
        **windows, "data_finality": {"source": "search_console_final_only", "latest_final_date": latest.isoformat()},
        "before_metrics": before, "after_metrics": after, "metric_deltas": deltas,
        "data_sufficiency": sufficiency, "contamination_status": "contaminated" if contamination_reasons else "clean",
        "contamination_reason_codes": contamination_reasons, "measurement_classification": classification,
        "confidence": confidence, "threshold_status": THRESHOLD_STATUS,
    }
    measurement_id = "measurement_v2e_" + sha256(_canonical_json(source).encode("utf-8")).hexdigest()[:24]
    return {**source, "measurement_id": measurement_id, "requires_human_review": True, "execution_authorized": False}


def build_measurement_review(measurement: Mapping[str, Any], *, decision: str, reviewer_id: str) -> Dict[str, Any]:
    """Human review has no path to an article change, retry, or rollback."""
    if not isinstance(measurement, Mapping) or measurement.get("measurement_schema_version") != MEASUREMENT_SCHEMA_VERSION or measurement.get("execution_authorized") is not False:
        raise MeasurementSafetyError("measurement review input is invalid")
    if decision not in MEASUREMENT_REVIEW_DECISIONS: raise MeasurementSafetyError("measurement review decision is invalid")
    _id(reviewer_id, "reviewer_id")
    if decision == "accept_result" and (measurement.get("threshold_status") != "approved" or measurement.get("measurement_classification") not in {"improved", "neutral", "worsened"}):
        raise MeasurementSafetyError("measurement result cannot be accepted before thresholds are approved")
    return {"schema_version": MEASUREMENT_REVIEW_SCHEMA_VERSION, "measurement_id": measurement["measurement_id"], "decision": decision,
            "reviewer_id": reviewer_id, "execution_authorized": False}


class AppendOnlyMeasurementLedger:
    """Git-external canary audit ledger; only safe measurement metadata is accepted."""
    ALLOWED = {"measurement_id", "execution_id", "article_id", "state", "at", "classification", "contamination_codes", "reviewer_id", "review_decision"}
    def __init__(self, directory: Path, filename: str = "measurement-audit.jsonl") -> None:
        directory.mkdir(mode=0o700, parents=True, exist_ok=True); os.chmod(directory, 0o700); self.path = directory / filename
        if not self.path.exists(): fd = os.open(str(self.path), os.O_CREAT | os.O_WRONLY, 0o600); os.close(fd)
        os.chmod(self.path, 0o600)
    def append(self, event: Mapping[str, Any]) -> None:
        if not isinstance(event, Mapping) or set(event) - self.ALLOWED: raise MeasurementSafetyError("measurement audit fields are invalid")
        _reject_sensitive(event)
        fd = os.open(str(self.path), os.O_WRONLY | os.O_APPEND)
        try: os.write(fd, (_canonical_json({"schema_version": MEASUREMENT_SCHEMA_VERSION, **dict(event)}) + "\n").encode("utf-8")); os.fsync(fd)
        finally: os.close(fd)


def build_v2f_handoff(measurement: Mapping[str, Any], review: Mapping[str, Any]) -> Dict[str, Any]:
    """Only a human-accepted, threshold-approved result can be handed off."""
    if not isinstance(measurement, Mapping) or not isinstance(review, Mapping) or review.get("measurement_id") != measurement.get("measurement_id") or review.get("decision") != "accept_result":
        raise MeasurementSafetyError("v2.0-F handoff review is invalid")
    if measurement.get("threshold_status") != "approved" or measurement.get("measurement_classification") not in {"improved", "neutral", "worsened"}:
        raise MeasurementSafetyError("v2.0-F handoff threshold status is invalid")
    return {"schema_version": V2F_HANDOFF_SCHEMA_VERSION, "measurement_id": measurement["measurement_id"], "execution_id": measurement["execution_id"], "article_id": measurement["article_id"], "plan_id": measurement["plan_id"], "recommendation_id": measurement["recommendation_id"], "measurement_classification": measurement["measurement_classification"], "confidence": measurement["confidence"], "execution_authorized": False}
