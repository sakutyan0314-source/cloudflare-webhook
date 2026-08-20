"""Pure append-only human-review records for SEO change-plan snapshots."""

from __future__ import annotations

from datetime import datetime
from hashlib import sha256
import json
import re
from typing import Any, Mapping, Sequence

from seo_improvement_change_plan import SeoImprovementChangePlanError, validate_change_plan


REVIEW_RECORD_SCHEMA_VERSION = "seo-improvement-change-plan-review-record-v1"
REVIEW_STATUSES = frozenset({"pending_review", "accepted", "rejected", "deferred"})
_REVIEW_REASONS = {
    "pending_review": frozenset({"plan_created"}),
    "accepted": frozenset({"change_candidate_creation_approved"}),
    "rejected": frozenset({"plan_not_selected"}),
    "deferred": frozenset({"plan_deferred"}),
}
_REVIEWER_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_SOURCE_FIELDS = ("plan_id", "plan_fingerprint", "article_id", "candidate_fingerprint", "accepted_review_id", "proposal_id", "proposal_fingerprint", "accepted_proposal_review_id")
_RECORD_FIELDS = frozenset({"schema_version", "plan_review_id", *_SOURCE_FIELDS, "status", "reviewer_id", "reviewed_at", "review_reason_code", "previous_review_id", "article_change_authorized", "publication_authorized", "execution_authorized"})


class SeoImprovementChangePlanReviewError(ValueError):
    """Change-plan review data violates its non-executable append-only contract."""


def _canonical_json(value: Mapping[str, Any]) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as error:
        raise SeoImprovementChangePlanReviewError("change plan review cannot be canonically encoded") from error


def validate_status(status: object) -> str:
    if not isinstance(status, str) or status not in REVIEW_STATUSES:
        raise SeoImprovementChangePlanReviewError("change plan review status is invalid")
    return status


def _timestamp(value: object) -> str:
    if not isinstance(value, str):
        raise SeoImprovementChangePlanReviewError("reviewed_at is invalid")
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise SeoImprovementChangePlanReviewError("reviewed_at is invalid") from error
    return value


def _plan_source(plan: Mapping[str, Any]) -> dict[str, Any]:
    return {field: plan[field] for field in _SOURCE_FIELDS}


def _review_id(record: Mapping[str, Any]) -> str:
    identity = {key: record[key] for key in ("schema_version", *_SOURCE_FIELDS, "status", "reviewer_id", "reviewed_at", "previous_review_id")}
    return "seo_change_plan_review_" + sha256(_canonical_json(identity).encode("utf-8")).hexdigest()[:24]


def build_review_record(plan: Mapping[str, Any], plan_input: Mapping[str, Any], decision: Mapping[str, Any]) -> dict[str, Any]:
    """Build one immutable review record without persistence or authorization."""
    try:
        validate_change_plan(plan, plan_input)
    except SeoImprovementChangePlanError as error:
        raise SeoImprovementChangePlanReviewError("change plan is invalid") from error
    if not isinstance(decision, Mapping):
        raise SeoImprovementChangePlanReviewError("change plan review decision is invalid")
    for key, value in _plan_source(plan).items():
        if decision.get(key) != value:
            raise SeoImprovementChangePlanReviewError(f"change plan review {key} does not match plan")
    status = validate_status(decision.get("status"))
    reviewer_id = decision.get("reviewer_id")
    if not isinstance(reviewer_id, str) or not _REVIEWER_ID.fullmatch(reviewer_id):
        raise SeoImprovementChangePlanReviewError("change plan reviewer ID is invalid")
    if decision.get("review_reason_code") not in _REVIEW_REASONS[status]:
        raise SeoImprovementChangePlanReviewError("change plan review reason code is invalid")
    previous = decision.get("previous_review_id")
    if previous is not None and (not isinstance(previous, str) or not previous):
        raise SeoImprovementChangePlanReviewError("previous change plan review ID is invalid")
    record = {
        "schema_version": REVIEW_RECORD_SCHEMA_VERSION, **_plan_source(plan), "status": status,
        "reviewer_id": reviewer_id, "reviewed_at": _timestamp(decision.get("reviewed_at")),
        "review_reason_code": decision["review_reason_code"], "previous_review_id": previous,
        "article_change_authorized": False, "publication_authorized": False, "execution_authorized": False,
    }
    record["plan_review_id"] = _review_id(record)
    return record


def validate_review_record(record: Mapping[str, Any], plan: Mapping[str, Any], plan_input: Mapping[str, Any]) -> None:
    if not isinstance(record, Mapping) or set(record) != _RECORD_FIELDS or record.get("schema_version") != REVIEW_RECORD_SCHEMA_VERSION:
        raise SeoImprovementChangePlanReviewError("change plan review record schema is invalid")
    try:
        validate_change_plan(plan, plan_input)
    except SeoImprovementChangePlanError as error:
        raise SeoImprovementChangePlanReviewError("change plan is invalid") from error
    for key, value in _plan_source(plan).items():
        if record.get(key) != value:
            raise SeoImprovementChangePlanReviewError(f"change plan review {key} is invalid")
    status = validate_status(record.get("status"))
    if record.get("review_reason_code") not in _REVIEW_REASONS[status]:
        raise SeoImprovementChangePlanReviewError("change plan review reason code is invalid")
    if not isinstance(record.get("reviewer_id"), str) or not _REVIEWER_ID.fullmatch(record["reviewer_id"]):
        raise SeoImprovementChangePlanReviewError("change plan reviewer ID is invalid")
    _timestamp(record.get("reviewed_at"))
    previous = record.get("previous_review_id")
    if previous is not None and (not isinstance(previous, str) or not previous):
        raise SeoImprovementChangePlanReviewError("previous change plan review ID is invalid")
    if record.get("plan_review_id") != _review_id(record):
        raise SeoImprovementChangePlanReviewError("change plan review ID is invalid")
    if any(record.get(key) is not False for key in ("article_change_authorized", "publication_authorized", "execution_authorized")):
        raise SeoImprovementChangePlanReviewError("change plan review authorization boundary is invalid")


def append_review_record(records: Sequence[Mapping[str, Any]], record: Mapping[str, Any], plan: Mapping[str, Any], plan_input: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Return a new validated chain; neither source records nor plan are changed."""
    if not isinstance(records, Sequence) or isinstance(records, (str, bytes, bytearray)):
        raise SeoImprovementChangePlanReviewError("change plan review records are invalid")
    copied = [dict(item) for item in records]
    for index, item in enumerate(copied):
        validate_review_record(item, plan, plan_input)
        if index == 0 and item["previous_review_id"] is not None:
            raise SeoImprovementChangePlanReviewError("initial change plan review cannot supersede another review")
        if index and item["previous_review_id"] != copied[index - 1]["plan_review_id"]:
            raise SeoImprovementChangePlanReviewError("change plan review chain is invalid")
    validate_review_record(record, plan, plan_input)
    if copied:
        if record["previous_review_id"] != copied[-1]["plan_review_id"]:
            raise SeoImprovementChangePlanReviewError("change plan review is not appended after latest")
    elif record["previous_review_id"] is not None:
        raise SeoImprovementChangePlanReviewError("initial change plan review cannot supersede another review")
    if any(item["plan_review_id"] == record["plan_review_id"] for item in copied):
        raise SeoImprovementChangePlanReviewError("duplicate change plan review record")
    return [*copied, dict(record)]


def latest_review_status(records: Sequence[Mapping[str, Any]], plan: Mapping[str, Any], plan_input: Mapping[str, Any]) -> str | None:
    if not records:
        return None
    return append_review_record(records[:-1], records[-1], plan, plan_input)[-1]["status"]
