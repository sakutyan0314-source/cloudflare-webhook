"""Local-only v2.0-F improvement-cycle control.

This module consumes only human-accepted, threshold-approved v2.0-E
measurements.  It is deterministic and deliberately has no D1, network, AI,
article-change, rollback, or execution dependency.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import re
from typing import Any, Dict, Mapping, Sequence


CYCLE_SCHEMA_VERSION = "v2.0-f-improvement-cycle-v1"
V2A_REENTRY_SCHEMA_VERSION = "v2.0-f-v2a-reentry-v1"
ROLLBACK_CANDIDATE_SCHEMA_VERSION = "v2.0-f-rollback-candidate-v1"
COOLDOWN_DAYS = 14
MAX_CYCLES_PER_ARTICLE_90D = 3
MAX_NEW_CANDIDATES_PER_HOUR = 1
MAX_NEW_CANDIDATES_PER_DAY = 3
TERMINAL_STATES = frozenset({"measurement_result_known", "closed", "held", "rejected"})
VALID_CLASSIFICATIONS = frozenset({
    "improved", "neutral", "worsened", "mixed_signal",
    "classification_pending_threshold", "measurement_pending",
    "insufficient_data", "contaminated",
})
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_SECRET_KEY = re.compile(r"(?:raw_?response|authorization|api[_ -]?key|private[_ -]?key|secret|token)", re.IGNORECASE)
_SECRET_VALUE = re.compile(r"(?:api[_ -]?key|authorization|bearer\s+|private[_ -]?key|token)\s*[:=]", re.IGNORECASE)


class CycleSafetyError(ValueError):
    """A proposed next-improvement cycle violates a safety invariant."""


def _canonical_json(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as error:
        raise CycleSafetyError("cycle canonical JSON is invalid") from error


def _id(value: object, name: str) -> str:
    if not isinstance(value, str) or not _SAFE_ID.fullmatch(value):
        raise CycleSafetyError(name + " is invalid")
    return value


def _time(value: object, name: str) -> datetime:
    if not isinstance(value, str):
        raise CycleSafetyError(name + " is invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise CycleSafetyError(name + " is invalid") from error
    if parsed.tzinfo is None:
        raise CycleSafetyError(name + " must include an offset")
    return parsed.astimezone(timezone.utc)


def _reject_sensitive(value: Any) -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if not isinstance(key, str) or _SECRET_KEY.search(key):
                raise CycleSafetyError("sensitive data is prohibited")
            _reject_sensitive(child)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for child in value:
            _reject_sensitive(child)
    elif isinstance(value, str) and _SECRET_VALUE.search(value):
        raise CycleSafetyError("sensitive data is prohibited")


def _validate_measurement(measurement: Mapping[str, Any], review: Mapping[str, Any]) -> Dict[str, Any]:
    required = {
        "measurement_schema_version", "measurement_id", "execution_id", "article_id", "plan_id",
        "recommendation_id", "measurement_classification", "confidence", "threshold_status",
        "contamination_status", "requires_human_review", "execution_authorized",
    }
    if not isinstance(measurement, Mapping) or not required <= set(measurement):
        raise CycleSafetyError("measurement input is incomplete")
    if measurement.get("measurement_schema_version") != "v2.0-e-measurement-v1":
        raise CycleSafetyError("measurement schema is invalid")
    if measurement.get("execution_authorized") is not False or measurement.get("requires_human_review") is not True:
        raise CycleSafetyError("measurement has unsafe authorization")
    classification = measurement.get("measurement_classification")
    if classification not in VALID_CLASSIFICATIONS:
        raise CycleSafetyError("measurement classification is invalid")
    for field in ("measurement_id", "execution_id", "plan_id", "recommendation_id"):
        _id(measurement.get(field), field)
    if not isinstance(measurement.get("article_id"), int) or measurement["article_id"] < 1:
        raise CycleSafetyError("measurement article ID is invalid")
    if measurement.get("confidence") not in {"low", "medium", "high"}:
        raise CycleSafetyError("measurement confidence is invalid")
    if classification in {"improved", "neutral", "worsened", "mixed_signal"} and measurement.get("threshold_status") != "approved":
        raise CycleSafetyError("threshold classification is not approved")
    if not isinstance(review, Mapping) or review.get("measurement_id") != measurement["measurement_id"] or review.get("decision") != "accept_result":
        raise CycleSafetyError("measurement has not received human accept_result")
    if review.get("execution_authorized") is not False or not isinstance(review.get("reviewer_id"), str):
        raise CycleSafetyError("measurement review is unsafe")
    _reject_sensitive(measurement); _reject_sensitive(review)
    return dict(measurement)


def _safe_history(history: Sequence[Mapping[str, Any]]) -> list[Dict[str, Any]]:
    if not isinstance(history, Sequence) or isinstance(history, (str, bytes, bytearray)):
        raise CycleSafetyError("cycle history is invalid")
    normalized = []
    for item in history:
        if not isinstance(item, Mapping):
            raise CycleSafetyError("cycle history item is invalid")
        required = {"cycle_id", "article_id", "source_measurement_id", "prior_recommendation_type", "cause_code", "created_at", "state"}
        if not required <= set(item):
            raise CycleSafetyError("cycle history item is incomplete")
        _id(item["cycle_id"], "history cycle_id"); _id(item["source_measurement_id"], "history measurement_id")
        if not isinstance(item["article_id"], int) or item["article_id"] < 1 or not isinstance(item["prior_recommendation_type"], str) or not item["prior_recommendation_type"]:
            raise CycleSafetyError("cycle history identity is invalid")
        if not isinstance(item["cause_code"], str) or not item["cause_code"] or not isinstance(item["state"], str):
            raise CycleSafetyError("cycle history state is invalid")
        _time(item["created_at"], "history created_at")
        if item.get("measurement_started") is not None and not isinstance(item.get("measurement_started"), bool):
            raise CycleSafetyError("cycle history measurement state is invalid")
        _reject_sensitive(item)
        normalized.append(dict(item))
    return normalized


def _counts_and_guards(measurement: Mapping[str, Any], history: Sequence[Mapping[str, Any]], *, recommendation_type: str, cause_code: str, now: datetime) -> tuple[int, int, int]:
    article = measurement["article_id"]
    if any(item["source_measurement_id"] == measurement["measurement_id"] for item in history):
        raise CycleSafetyError("duplicate_measurement_cycle")
    if any(item["article_id"] == article and item["state"] not in TERMINAL_STATES for item in history):
        raise CycleSafetyError("unresolved_cycle_exists")
    recent_type = [item for item in history if item["article_id"] == article and item["prior_recommendation_type"] == recommendation_type and item["cause_code"] == cause_code]
    if any(_time(item["created_at"], "history created_at") > now - timedelta(days=COOLDOWN_DAYS) for item in recent_type):
        raise CycleSafetyError("cooldown_active")
    article_cycles = sum(1 for item in history if item["article_id"] == article and item.get("measurement_started") is True and _time(item["created_at"], "history created_at") > now - timedelta(days=90))
    hourly = sum(1 for item in history if item.get("decision") == "consider_new_recommendation" and _time(item["created_at"], "history created_at") > now - timedelta(hours=1))
    daily = sum(1 for item in history if item.get("decision") == "consider_new_recommendation" and _time(item["created_at"], "history created_at") > now - timedelta(days=1))
    return article_cycles, hourly, daily


def _rollback_eligible(measurement: Mapping[str, Any], rollback_context: Mapping[str, Any] | None) -> bool:
    if not isinstance(rollback_context, Mapping):
        return False
    required = {"execution_result_classification", "allowed_fields", "before_snapshot_fingerprint", "after_snapshot_fingerprint", "rollback_diff_deterministic"}
    return (required <= set(rollback_context) and rollback_context.get("execution_result_classification") == "result_known_applied"
            and set(rollback_context.get("allowed_fields", [])) <= {"title", "description"}
            and bool(rollback_context.get("allowed_fields")) and isinstance(rollback_context.get("before_snapshot_fingerprint"), str)
            and isinstance(rollback_context.get("after_snapshot_fingerprint"), str) and rollback_context.get("rollback_diff_deterministic") is True
            and measurement.get("contamination_status") == "clean" and measurement.get("confidence") in {"medium", "high"})


def build_next_improvement_candidate(
    measurement: Mapping[str, Any], review: Mapping[str, Any], *, prior_recommendation_type: str,
    cause_code: str, history: Sequence[Mapping[str, Any]], now: str, new_evidence: bool = False,
    rollback_context: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    """Build one non-executable v2.0-F candidate; never performs a retry or change."""
    safe = _validate_measurement(measurement, review)
    if not isinstance(prior_recommendation_type, str) or not prior_recommendation_type or not isinstance(cause_code, str) or not cause_code:
        raise CycleSafetyError("recommendation type or cause is invalid")
    current = _time(now, "now")
    past = _safe_history(history)
    cycles, hourly, daily = _counts_and_guards(safe, past, recommendation_type=prior_recommendation_type, cause_code=cause_code, now=current)
    classification = safe["measurement_classification"]
    decision, reasons, allowed = "hold", [], []
    if cycles >= MAX_CYCLES_PER_ARTICLE_90D:
        reasons = ["article_cycle_limit_reached"]
    elif classification == "improved":
        decision, reasons = "continue_observation", ["measurement_improved"]
    elif classification in {"measurement_pending", "insufficient_data"}:
        decision, reasons = "continue_observation", ["observation_not_sufficient"]
    elif classification in {"mixed_signal", "classification_pending_threshold", "contaminated"}:
        decision, reasons = "hold", ["mixed_signal" if classification == "mixed_signal" else classification]
    elif classification == "worsened":
        decision, reasons = ("consider_rollback_review", ["rollback_review_candidate"]) if _rollback_eligible(safe, rollback_context) else ("hold", ["rollback_conditions_not_met"])
    elif classification == "neutral":
        if not new_evidence:
            decision, reasons = "hold", ["new_evidence_required"]
        elif hourly >= MAX_NEW_CANDIDATES_PER_HOUR:
            decision, reasons = "hold", ["hourly_candidate_limit_reached"]
        elif daily >= MAX_NEW_CANDIDATES_PER_DAY:
            decision, reasons = "hold", ["daily_candidate_limit_reached"]
        else:
            decision, reasons, allowed = "consider_new_recommendation", ["neutral_with_new_evidence"], [prior_recommendation_type]
    else:
        raise CycleSafetyError("measurement classification is unsupported")
    source = {
        "cycle_schema_version": CYCLE_SCHEMA_VERSION, "article_id": safe["article_id"],
        "source_measurement_id": safe["measurement_id"], "source_execution_id": safe["execution_id"],
        "source_plan_id": safe["plan_id"], "source_recommendation_id": safe["recommendation_id"],
        "prior_recommendation_type": prior_recommendation_type, "measurement_classification": classification,
        "measurement_confidence": safe["confidence"], "threshold_config_version": safe.get("threshold_config_version", "unapproved"),
        "decision": decision, "reason_codes": reasons, "cooldown_until": (current + timedelta(days=COOLDOWN_DAYS)).isoformat().replace("+00:00", "Z"),
        "allowed_next_recommendation_types": allowed, "cycle_count_90d": cycles, "hourly_candidate_count": hourly,
        "daily_candidate_count": daily, "cause_code": cause_code,
    }
    fingerprint = sha256(_canonical_json(source).encode("utf-8")).hexdigest()
    return {**source, "cycle_id": "cycle_v2f_" + fingerprint[:24], "requires_human_review": True, "execution_authorized": False}


def build_rollback_candidate(candidate: Mapping[str, Any], rollback_context: Mapping[str, Any]) -> Dict[str, Any]:
    """Return a review-only rollback interface; it contains no execution authority."""
    if not isinstance(candidate, Mapping) or candidate.get("decision") != "consider_rollback_review" or candidate.get("execution_authorized") is not False:
        raise CycleSafetyError("rollback source candidate is invalid")
    if not _rollback_eligible({"measurement_classification": "worsened", "contamination_status": "clean", "confidence": candidate.get("measurement_confidence")}, rollback_context):
        raise CycleSafetyError("rollback conditions are invalid")
    return {"schema_version": ROLLBACK_CANDIDATE_SCHEMA_VERSION, "cycle_id": candidate["cycle_id"], "article_id": candidate["article_id"],
            "source_execution_id": candidate["source_execution_id"], "rollback_authorized": False,
            "requires_separate_candidate": True, "requires_separate_human_approval": True}


def build_v2a_reentry(candidate: Mapping[str, Any], human_review: Mapping[str, Any]) -> Dict[str, Any]:
    """Permit only a reviewed new candidate back to v2.0-A, never B/C/D directly."""
    if not isinstance(candidate, Mapping) or candidate.get("decision") != "consider_new_recommendation" or candidate.get("execution_authorized") is not False:
        raise CycleSafetyError("v2.0-A reentry candidate is invalid")
    if not isinstance(human_review, Mapping) or human_review.get("cycle_id") != candidate.get("cycle_id") or human_review.get("decision") != "approve" or human_review.get("execution_authorized") is not False:
        raise CycleSafetyError("v2.0-A reentry requires a distinct human review")
    return {"schema_version": V2A_REENTRY_SCHEMA_VERSION, "cycle_id": candidate["cycle_id"], "article_id": candidate["article_id"],
            "source_measurement_id": candidate["source_measurement_id"], "source_execution_id": candidate["source_execution_id"],
            "new_recommendation_input_required": True, "required_chain": ["v2.0-A", "v2.0-B", "v2.0-C", "v2.0-D", "v2.0-E"],
            "execution_authorized": False}


class AppendOnlyCycleLedger:
    """Git-external fsync ledger storing only safe cycle metadata."""
    ALLOWED = {"cycle_id", "article_id", "measurement_id", "execution_id", "classification", "decision", "reason_codes", "cooldown_until", "cycle_count", "hourly_count", "daily_count", "threshold_version", "reviewer_id", "review_decision", "at"}

    def __init__(self, directory: Path, filename: str = "improvement-cycle-audit.jsonl") -> None:
        directory.mkdir(mode=0o700, parents=True, exist_ok=True); os.chmod(directory, 0o700)
        self.path = directory / filename
        if not self.path.exists():
            fd = os.open(str(self.path), os.O_CREAT | os.O_WRONLY, 0o600); os.close(fd)
        os.chmod(self.path, 0o600)

    def append(self, event: Mapping[str, Any]) -> None:
        if not isinstance(event, Mapping) or set(event) - self.ALLOWED:
            raise CycleSafetyError("cycle audit fields are invalid")
        _reject_sensitive(event)
        fd = os.open(str(self.path), os.O_WRONLY | os.O_APPEND)
        try:
            os.write(fd, (_canonical_json({"schema_version": CYCLE_SCHEMA_VERSION, **dict(event)}) + "\n").encode("utf-8")); os.fsync(fd)
        finally:
            os.close(fd)
