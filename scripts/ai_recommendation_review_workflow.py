"""Local-only, append-only human-review decisions for v2.0-B.

This module deliberately has no D1, file, network, model, or article-change
dependency.  An ``approve`` decision only permits a later v2.0-C *planning*
step; it never authorizes or performs a content, publication, or affiliate
change.
"""

from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
import re
from typing import Any, Dict, Mapping, Optional, Sequence
from uuid import uuid4

from ai_recommendation_review import REVIEW_SCHEMA_VERSION


REVIEW_RECORD_SCHEMA_VERSION = "v2.0-b-review-record-v1"
REVIEW_DECISION_SCHEMA_VERSION = "v2.0-b-review-decision-envelope-v1"
DECISIONS = frozenset({"approve", "reject", "hold"})
RUBRIC_FIELDS = (
    "evidence_accuracy",
    "type_priority_validity",
    "actionability",
    "no_unobserved_claims",
    "japanese_clarity",
)
_REVIEWER_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_REASON_CODE = re.compile(r"^[a-z][a-z0-9_:-]{0,79}$")
_FORBIDDEN_RECORD_KEY = re.compile(r"(?:raw_?response|authorization|api[_ -]?key|private[_ -]?key|secret|token)", re.IGNORECASE)
_SECRET_LIKE_TEXT = re.compile(r"(?:api[_ -]?key|authorization|bearer\s+|private[_ -]?key|token)\s*[:=]", re.IGNORECASE)

_ENVELOPE_FIELDS = (
    "schema_version", "review_status", "article_id", "category", "title",
    "current_state", "recommendation_id", "recommendation_type", "priority",
    "confidence", "risk_level", "evidence", "reasons", "suggested_action",
    "expected_effect", "requires_human_review", "data_sufficiency", "generated_at",
)


class ReviewWorkflowError(ValueError):
    """A review record or its safe v2.0-C handoff is invalid."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _canonical_json(value: Mapping[str, Any]) -> str:
    """Fixed canonicalization: whitelisted fields, sorted keys, no whitespace.

    String bytes are UTF-8 with no Unicode normalization.  Numeric, boolean,
    null, list, and mapping values use standard JSON; unsupported values are
    rejected instead of coerced.
    """
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as error:
        raise ReviewWorkflowError("review envelope cannot be canonically encoded") from error


def _reject_forbidden_keys(value: Any) -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if not isinstance(key, str):
                raise ReviewWorkflowError("review data key is invalid")
            if _FORBIDDEN_RECORD_KEY.search(key):
                raise ReviewWorkflowError("review data contains a prohibited field")
            _reject_forbidden_keys(child)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for child in value:
            _reject_forbidden_keys(child)


def canonical_review_envelope(envelope: Mapping[str, Any]) -> Dict[str, Any]:
    """Return exactly the validated display envelope used for fingerprinting.

    Provider raw responses cannot enter because unknown fields, secret-like
    keys, and an invalid review-only marker all fail closed.
    """
    if not isinstance(envelope, Mapping) or set(envelope) != set(_ENVELOPE_FIELDS):
        raise ReviewWorkflowError("review envelope fields are invalid")
    if envelope.get("schema_version") != REVIEW_SCHEMA_VERSION or envelope.get("review_status") != "pending":
        raise ReviewWorkflowError("review envelope is not pending v2.0-A output")
    if not isinstance(envelope.get("article_id"), int) or envelope["article_id"] < 1:
        raise ReviewWorkflowError("review envelope article ID is invalid")
    if not isinstance(envelope.get("recommendation_id"), str) or not envelope["recommendation_id"]:
        raise ReviewWorkflowError("review envelope recommendation ID is invalid")
    if envelope.get("requires_human_review") is not True:
        raise ReviewWorkflowError("review envelope is not human-review-only")
    _reject_forbidden_keys(envelope)
    return {field: envelope[field] for field in _ENVELOPE_FIELDS}


def recommendation_fingerprint(envelope: Mapping[str, Any]) -> str:
    """SHA-256 of the fixed canonical RecommendationReviewEnvelope JSON."""
    canonical = _canonical_json(canonical_review_envelope(envelope))
    return sha256(canonical.encode("utf-8")).hexdigest()


def validate_rubric(rubric: Mapping[str, Any]) -> Dict[str, int]:
    if not isinstance(rubric, Mapping) or set(rubric) != set(RUBRIC_FIELDS):
        raise ReviewWorkflowError("review rubric fields are invalid")
    normalized: Dict[str, int] = {}
    for field in RUBRIC_FIELDS:
        value = rubric[field]
        if not isinstance(value, int) or isinstance(value, bool) or value not in (0, 1, 2):
            raise ReviewWorkflowError("review rubric score is invalid")
        normalized[field] = value
    return normalized


def rubric_summary(rubric: Mapping[str, Any]) -> Dict[str, Any]:
    normalized = validate_rubric(rubric)
    total = sum(normalized.values())
    return {
        "rubric": normalized,
        "total_score": total,
        "approval_eligible": normalized["evidence_accuracy"] == 2 and total >= 8,
    }


def _validate_timestamp(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise ReviewWorkflowError(field + " is invalid")
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ReviewWorkflowError(field + " is invalid") from error
    return value


def build_review_record(
    envelope: Mapping[str, Any], *, reviewer_id: str, decision: str,
    rubric: Mapping[str, Any], reason_code: str, human_note: Optional[str] = None,
    review_id: Optional[str] = None, reviewed_at: Optional[str] = None,
    review_version: int = 1, supersedes_review_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Build an unsaved record; only a registry may append it.

    The record stores the fingerprint, not recommendation prose/evidence.  An
    approval is a handoff permission for v2.0-C planning, never execution.
    """
    safe_envelope = canonical_review_envelope(envelope)
    if not isinstance(reviewer_id, str) or not _REVIEWER_ID.fullmatch(reviewer_id):
        raise ReviewWorkflowError("reviewer ID is invalid")
    if decision not in DECISIONS:
        raise ReviewWorkflowError("review decision is invalid")
    if not isinstance(reason_code, str) or not _REASON_CODE.fullmatch(reason_code):
        raise ReviewWorkflowError("review reason code is invalid")
    if human_note is not None:
        if not isinstance(human_note, str) or len(human_note) > 280 or _SECRET_LIKE_TEXT.search(human_note):
            raise ReviewWorkflowError("human note is invalid")
    if not isinstance(review_version, int) or isinstance(review_version, bool) or review_version < 1:
        raise ReviewWorkflowError("review version is invalid")
    if review_version == 1 and supersedes_review_id is not None:
        raise ReviewWorkflowError("first review cannot supersede another review")
    if review_version > 1 and (not isinstance(supersedes_review_id, str) or not supersedes_review_id):
        raise ReviewWorkflowError("re-review must name the superseded review")
    summary = rubric_summary(rubric)
    if decision == "approve" and not summary["approval_eligible"]:
        raise ReviewWorkflowError("approve requires the fixed rubric threshold")
    assigned_review_id = review_id or "review_" + uuid4().hex
    if not isinstance(assigned_review_id, str) or not assigned_review_id:
        raise ReviewWorkflowError("review ID is invalid")
    timestamp = _validate_timestamp(reviewed_at or _utc_now(), "reviewed_at")
    return {
        "schema_version": REVIEW_RECORD_SCHEMA_VERSION,
        "review_id": assigned_review_id,
        "recommendation_id": safe_envelope["recommendation_id"],
        "recommendation_fingerprint": recommendation_fingerprint(safe_envelope),
        "reviewer_id": reviewer_id,
        "reviewed_at": timestamp,
        "decision": decision,
        **summary,
        "reason_code": reason_code,
        "human_note": human_note,
        "review_version": review_version,
        "supersedes_review_id": supersedes_review_id,
        "created_at": _utc_now(),
    }


class InMemoryReviewRegistry:
    """Test/local append-only registry; production persistence is out of scope.

    A future store must enforce the same recommendation-ID approval reservation
    atomically.  This object demonstrates the contract without any D1 write.
    """

    def __init__(self) -> None:
        self._records: Dict[str, Dict[str, Any]] = {}

    def append(self, record: Mapping[str, Any]) -> Dict[str, Any]:
        value = dict(record)
        review_id = value.get("review_id")
        if not isinstance(review_id, str) or review_id in self._records:
            raise ReviewWorkflowError("review record already exists")
        recommendation_id = value.get("recommendation_id")
        fingerprint = value.get("recommendation_fingerprint")
        if not isinstance(recommendation_id, str) or not isinstance(fingerprint, str):
            raise ReviewWorkflowError("review record identity is invalid")
        previous = [item for item in self._records.values() if item["recommendation_id"] == recommendation_id]
        if value.get("review_version") == 1:
            if previous:
                raise ReviewWorkflowError("initial review already exists for recommendation")
        else:
            parent = self._records.get(value.get("supersedes_review_id"))
            if parent is None or parent["recommendation_id"] != recommendation_id or parent["recommendation_fingerprint"] != fingerprint:
                raise ReviewWorkflowError("superseded review does not match recommendation")
            if value["review_version"] != parent["review_version"] + 1:
                raise ReviewWorkflowError("re-review version is invalid")
        if value.get("decision") == "approve" and any(item["decision"] == "approve" for item in previous):
            raise ReviewWorkflowError("recommendation already has an approved review")
        self._records[review_id] = value
        return dict(value)

    def records(self) -> list[Dict[str, Any]]:
        return [dict(item) for item in self._records.values()]


def build_v2c_review_decision_envelope(record: Mapping[str, Any]) -> Dict[str, Any]:
    """Build the only v2.0-C handoff; it still cannot execute a change."""
    required = {
        "schema_version", "review_id", "recommendation_id", "recommendation_fingerprint",
        "decision", "rubric", "total_score", "approval_eligible", "reviewed_at", "review_version",
    }
    if not isinstance(record, Mapping) or not required <= set(record):
        raise ReviewWorkflowError("review record is incomplete")
    if record.get("schema_version") != REVIEW_RECORD_SCHEMA_VERSION:
        raise ReviewWorkflowError("review record schema is invalid")
    if record.get("decision") != "approve" or record.get("approval_eligible") is not True:
        raise ReviewWorkflowError("only eligible human approval can enter v2.0-C planning")
    return {
        "schema_version": REVIEW_DECISION_SCHEMA_VERSION,
        "recommendation_id": record["recommendation_id"],
        "recommendation_fingerprint": record["recommendation_fingerprint"],
        "review_id": record["review_id"],
        "decision": "approve",
        "rubric": dict(record["rubric"]),
        "total_score": record["total_score"],
        "approval_eligible": True,
        "reviewed_at": record["reviewed_at"],
        "review_version": record["review_version"],
        "handoff_scope": "v2_0_c_change_plan_only",
        "execution_authorized": False,
    }
