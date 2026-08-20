"""Pure, append-only Phase 2A.6 human-review records for SEO candidates.

This is deliberately separate from the v2.0 AI recommendation workflow.  It
does not persist records, invoke AI, alter articles, or authorize publication
or execution.
"""

from __future__ import annotations

from datetime import datetime
from hashlib import sha256
import json
import re
from typing import Any, Mapping, Sequence

from search_console_improvement_candidate_review import (
    KNOWN_CANDIDATE_REASON_CODES,
    REVIEW_SCHEMA_VERSION,
    candidate_fingerprint,
)


REVIEW_RECORD_SCHEMA_VERSION = "seo-improvement-review-record-v1"
REVIEW_STATUSES = frozenset({"pending_review", "accepted", "rejected", "deferred"})
_REVIEW_REASONS = {
    "pending_review": frozenset({"candidate_created"}),
    "accepted": frozenset({"improvement_generation_candidate_approved"}),
    "rejected": frozenset({"not_selected_for_improvement"}),
    "deferred": frozenset({"deferred_for_later_review"}),
}
_REVIEWER_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_ENVELOPE_FIELDS = frozenset({
    "schema_version", "status", "article_id", "title", "category",
    "recommendation_type", "reason_code", "current_metrics", "previous_metrics",
    "evidence", "requires_human_review", "candidate_fingerprint",
})
_RECORD_FIELDS = frozenset({
    "schema_version", "review_id", "candidate_fingerprint", "article_id",
    "candidate_reason_code", "status", "reviewer_id", "reviewed_at",
    "review_reason_code", "previous_review_id", "ai_generation_authorized",
    "article_change_authorized", "publication_authorized", "execution_authorized",
})


class SeoImprovementReviewWorkflowError(ValueError):
    """SEO review status input violates the fixed, non-executable contract."""


def validate_status(status: object) -> str:
    if not isinstance(status, str) or status not in REVIEW_STATUSES:
        raise SeoImprovementReviewWorkflowError("review status is invalid")
    return status


def _timestamp(value: object) -> str:
    if not isinstance(value, str):
        raise SeoImprovementReviewWorkflowError("reviewed_at is invalid")
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise SeoImprovementReviewWorkflowError("reviewed_at is invalid") from error
    return value


def _canonical_json(value: Mapping[str, Any]) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as error:
        raise SeoImprovementReviewWorkflowError("review record cannot be canonically encoded") from error


def _validate_envelope(envelope: Mapping[str, Any]) -> None:
    if not isinstance(envelope, Mapping) or set(envelope) != _ENVELOPE_FIELDS:
        raise SeoImprovementReviewWorkflowError("review envelope fields are invalid")
    if envelope.get("schema_version") != REVIEW_SCHEMA_VERSION or envelope.get("status") != "pending_review":
        raise SeoImprovementReviewWorkflowError("review envelope is not pending Phase 2A.5 output")
    if not isinstance(envelope.get("article_id"), int) or envelope["article_id"] < 1:
        raise SeoImprovementReviewWorkflowError("review envelope article ID is invalid")
    if envelope.get("reason_code") not in KNOWN_CANDIDATE_REASON_CODES:
        raise SeoImprovementReviewWorkflowError("candidate reason code is invalid")
    if envelope.get("requires_human_review") is not True:
        raise SeoImprovementReviewWorkflowError("review envelope is not human-review-only")
    fingerprint = envelope.get("candidate_fingerprint")
    if not isinstance(fingerprint, str) or len(fingerprint) != 64 or fingerprint != candidate_fingerprint(envelope):
        raise SeoImprovementReviewWorkflowError("candidate fingerprint is invalid")


def _record_id(decision: Mapping[str, Any]) -> str:
    identity = {
        "schema_version": REVIEW_RECORD_SCHEMA_VERSION,
        "candidate_fingerprint": decision["candidate_fingerprint"],
        "article_id": decision["article_id"], "status": decision["status"],
        "reviewer_id": decision["reviewer_id"], "reviewed_at": decision["reviewed_at"],
        "previous_review_id": decision.get("previous_review_id"),
    }
    return "seo_review_" + sha256(_canonical_json(identity).encode("utf-8")).hexdigest()[:24]


def build_review_record(envelope: Mapping[str, Any], decision: Mapping[str, Any]) -> dict[str, Any]:
    """Build one immutable SEO review record; it performs no append or I/O."""
    _validate_envelope(envelope)
    if not isinstance(decision, Mapping):
        raise SeoImprovementReviewWorkflowError("review decision is invalid")
    status = validate_status(decision.get("status"))
    if decision.get("candidate_fingerprint") != envelope["candidate_fingerprint"]:
        raise SeoImprovementReviewWorkflowError("decision fingerprint does not match envelope")
    if decision.get("article_id") != envelope["article_id"]:
        raise SeoImprovementReviewWorkflowError("decision article ID does not match envelope")
    if decision.get("candidate_reason_code") != envelope["reason_code"]:
        raise SeoImprovementReviewWorkflowError("decision reason code does not match envelope")
    reviewer_id = decision.get("reviewer_id")
    if not isinstance(reviewer_id, str) or not _REVIEWER_ID.fullmatch(reviewer_id):
        raise SeoImprovementReviewWorkflowError("reviewer ID is invalid")
    review_reason = decision.get("review_reason_code")
    if review_reason not in _REVIEW_REASONS[status]:
        raise SeoImprovementReviewWorkflowError("review reason code is invalid")
    previous = decision.get("previous_review_id")
    if previous is not None and (not isinstance(previous, str) or not previous):
        raise SeoImprovementReviewWorkflowError("previous review ID is invalid")
    value = {
        "schema_version": REVIEW_RECORD_SCHEMA_VERSION,
        "candidate_fingerprint": envelope["candidate_fingerprint"],
        "article_id": envelope["article_id"],
        "candidate_reason_code": envelope["reason_code"],
        "status": status,
        "reviewer_id": reviewer_id,
        "reviewed_at": _timestamp(decision.get("reviewed_at")),
        "review_reason_code": review_reason,
        "previous_review_id": previous,
        # Accepted only makes this a future planning input candidate. None of
        # these flags permits AI execution, an article change, or publication.
        "ai_generation_authorized": False,
        "article_change_authorized": False,
        "publication_authorized": False,
        "execution_authorized": False,
    }
    value["review_id"] = _record_id(value)
    return value


def validate_review_record(record: Mapping[str, Any]) -> None:
    if not isinstance(record, Mapping) or set(record) != _RECORD_FIELDS:
        raise SeoImprovementReviewWorkflowError("review record fields are invalid")
    if record.get("schema_version") != REVIEW_RECORD_SCHEMA_VERSION:
        raise SeoImprovementReviewWorkflowError("review record schema is invalid")
    status = validate_status(record.get("status"))
    if not isinstance(record.get("candidate_fingerprint"), str) or len(record["candidate_fingerprint"]) != 64:
        raise SeoImprovementReviewWorkflowError("review record fingerprint is invalid")
    if not isinstance(record.get("article_id"), int) or record["article_id"] < 1:
        raise SeoImprovementReviewWorkflowError("review record article ID is invalid")
    if record.get("candidate_reason_code") not in KNOWN_CANDIDATE_REASON_CODES or record.get("review_reason_code") not in _REVIEW_REASONS[status]:
        raise SeoImprovementReviewWorkflowError("review record reason code is invalid")
    if not isinstance(record.get("reviewer_id"), str) or not _REVIEWER_ID.fullmatch(record["reviewer_id"]):
        raise SeoImprovementReviewWorkflowError("review record reviewer ID is invalid")
    _timestamp(record.get("reviewed_at"))
    previous = record.get("previous_review_id")
    if previous is not None and (not isinstance(previous, str) or not previous):
        raise SeoImprovementReviewWorkflowError("review record previous review ID is invalid")
    if record.get("review_id") != _record_id(record):
        raise SeoImprovementReviewWorkflowError("review record ID is invalid")
    if any(record[key] is not False for key in ("ai_generation_authorized", "article_change_authorized", "publication_authorized", "execution_authorized")):
        raise SeoImprovementReviewWorkflowError("review record authorization boundary is invalid")


def append_review_record(records: Sequence[Mapping[str, Any]], record: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Return a new, validated append-only review chain without persistence."""
    if not isinstance(records, Sequence) or isinstance(records, (str, bytes, bytearray)):
        raise SeoImprovementReviewWorkflowError("review records are invalid")
    copied = [dict(item) for item in records]
    for index, item in enumerate(copied):
        validate_review_record(item)
        if index == 0:
            if item["previous_review_id"] is not None:
                raise SeoImprovementReviewWorkflowError("initial review cannot supersede another review")
        else:
            previous = copied[index - 1]
            if item["candidate_fingerprint"] != previous["candidate_fingerprint"] or item["article_id"] != previous["article_id"] or item["previous_review_id"] != previous["review_id"]:
                raise SeoImprovementReviewWorkflowError("existing review chain is invalid")
    validate_review_record(record)
    if copied:
        latest = copied[-1]
        if record["candidate_fingerprint"] != latest["candidate_fingerprint"] or record["article_id"] != latest["article_id"]:
            raise SeoImprovementReviewWorkflowError("review record identity does not match chain")
        if record["previous_review_id"] != latest["review_id"]:
            raise SeoImprovementReviewWorkflowError("review record is not appended after latest")
    elif record["previous_review_id"] is not None:
        raise SeoImprovementReviewWorkflowError("initial review cannot supersede another review")
    if any(item["review_id"] == record["review_id"] for item in copied):
        raise SeoImprovementReviewWorkflowError("duplicate review record")
    return [*copied, dict(record)]


def latest_review_status(records: Sequence[Mapping[str, Any]]) -> str | None:
    """Return the newest validated status, or None when no review exists."""
    if not records:
        return None
    chain = append_review_record(records[:-1], records[-1])
    return chain[-1]["status"]
