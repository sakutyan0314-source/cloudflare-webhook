"""Pure append-only human-review records for validated SEO proposals."""

from __future__ import annotations

from datetime import datetime
from hashlib import sha256
import json
import re
from typing import Any, Mapping, Sequence

from seo_improvement_proposal import PROPOSAL_SCHEMA_VERSION, SeoImprovementProposalError, validate_proposal


REVIEW_RECORD_SCHEMA_VERSION = "seo-improvement-proposal-review-record-v1"
REVIEW_STATUSES = frozenset({"pending_review", "accepted", "rejected", "deferred"})
_REVIEW_REASONS = {
    "pending_review": frozenset({"proposal_created"}),
    "accepted": frozenset({"proposal_approved_for_change_plan"}),
    "rejected": frozenset({"proposal_not_selected"}),
    "deferred": frozenset({"proposal_deferred"}),
}
_REVIEWER_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_RECORD_FIELDS = frozenset({
    "schema_version", "proposal_review_id", "proposal_id", "proposal_fingerprint", "article_id",
    "candidate_fingerprint", "accepted_review_id", "status", "reviewer_id", "reviewed_at",
    "review_reason_code", "previous_review_id", "article_change_authorized",
    "publication_authorized", "execution_authorized",
})


class SeoImprovementProposalReviewError(ValueError):
    """Proposal review data violates its non-executable append-only contract."""


def _canonical_json(value: Mapping[str, Any]) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as error:
        raise SeoImprovementProposalReviewError("proposal cannot be canonically encoded") from error


def proposal_fingerprint(proposal: Mapping[str, Any], proposal_input: Mapping[str, Any]) -> str:
    """Return SHA-256 of the complete, already-validated canonical proposal."""
    try:
        validate_proposal(proposal, proposal_input)
    except SeoImprovementProposalError as error:
        raise SeoImprovementProposalReviewError("proposal is invalid") from error
    return sha256(_canonical_json(proposal).encode("utf-8")).hexdigest()


def validate_status(status: object) -> str:
    if not isinstance(status, str) or status not in REVIEW_STATUSES:
        raise SeoImprovementProposalReviewError("proposal review status is invalid")
    return status


def _timestamp(value: object) -> str:
    if not isinstance(value, str):
        raise SeoImprovementProposalReviewError("reviewed_at is invalid")
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise SeoImprovementProposalReviewError("reviewed_at is invalid") from error
    return value


def _review_id(record: Mapping[str, Any]) -> str:
    identity = {key: record[key] for key in ("schema_version", "proposal_id", "proposal_fingerprint", "article_id", "candidate_fingerprint", "accepted_review_id", "status", "reviewer_id", "reviewed_at", "previous_review_id")}
    return "seo_proposal_review_" + sha256(_canonical_json(identity).encode("utf-8")).hexdigest()[:24]


def build_review_record(proposal: Mapping[str, Any], proposal_input: Mapping[str, Any], decision: Mapping[str, Any]) -> dict[str, Any]:
    """Build one immutable review record; no persistence or change authority exists."""
    fingerprint = proposal_fingerprint(proposal, proposal_input)
    if not isinstance(decision, Mapping):
        raise SeoImprovementProposalReviewError("proposal review decision is invalid")
    status = validate_status(decision.get("status"))
    for key in ("proposal_id", "proposal_fingerprint", "article_id", "candidate_fingerprint", "accepted_review_id"):
        if decision.get(key) != (fingerprint if key == "proposal_fingerprint" else proposal[key]):
            raise SeoImprovementProposalReviewError(f"proposal review {key} does not match proposal")
    reviewer_id = decision.get("reviewer_id")
    if not isinstance(reviewer_id, str) or not _REVIEWER_ID.fullmatch(reviewer_id):
        raise SeoImprovementProposalReviewError("proposal reviewer ID is invalid")
    reason = decision.get("review_reason_code")
    if reason not in _REVIEW_REASONS[status]:
        raise SeoImprovementProposalReviewError("proposal review reason code is invalid")
    previous = decision.get("previous_review_id")
    if previous is not None and (not isinstance(previous, str) or not previous):
        raise SeoImprovementProposalReviewError("previous proposal review ID is invalid")
    record = {
        "schema_version": REVIEW_RECORD_SCHEMA_VERSION,
        "proposal_id": proposal["proposal_id"], "proposal_fingerprint": fingerprint,
        "article_id": proposal["article_id"], "candidate_fingerprint": proposal["candidate_fingerprint"],
        "accepted_review_id": proposal["accepted_review_id"], "status": status,
        "reviewer_id": reviewer_id, "reviewed_at": _timestamp(decision.get("reviewed_at")),
        "review_reason_code": reason, "previous_review_id": previous,
        "article_change_authorized": False, "publication_authorized": False, "execution_authorized": False,
    }
    record["proposal_review_id"] = _review_id(record)
    return record


def validate_review_record(record: Mapping[str, Any], proposal: Mapping[str, Any], proposal_input: Mapping[str, Any]) -> None:
    if not isinstance(record, Mapping) or set(record) != _RECORD_FIELDS or record.get("schema_version") != REVIEW_RECORD_SCHEMA_VERSION:
        raise SeoImprovementProposalReviewError("proposal review record schema is invalid")
    fingerprint = proposal_fingerprint(proposal, proposal_input)
    for key in ("proposal_id", "article_id", "candidate_fingerprint", "accepted_review_id"):
        if record.get(key) != proposal.get(key):
            raise SeoImprovementProposalReviewError(f"proposal review {key} is invalid")
    if record.get("proposal_fingerprint") != fingerprint:
        raise SeoImprovementProposalReviewError("proposal review fingerprint is invalid")
    status = validate_status(record.get("status"))
    if record.get("review_reason_code") not in _REVIEW_REASONS[status]:
        raise SeoImprovementProposalReviewError("proposal review reason code is invalid")
    if not isinstance(record.get("reviewer_id"), str) or not _REVIEWER_ID.fullmatch(record["reviewer_id"]):
        raise SeoImprovementProposalReviewError("proposal review reviewer ID is invalid")
    _timestamp(record.get("reviewed_at"))
    previous = record.get("previous_review_id")
    if previous is not None and (not isinstance(previous, str) or not previous):
        raise SeoImprovementProposalReviewError("proposal review previous ID is invalid")
    if record.get("proposal_review_id") != _review_id(record):
        raise SeoImprovementProposalReviewError("proposal review ID is invalid")
    if any(record.get(key) is not False for key in ("article_change_authorized", "publication_authorized", "execution_authorized")):
        raise SeoImprovementProposalReviewError("proposal review authorization boundary is invalid")


def append_review_record(records: Sequence[Mapping[str, Any]], record: Mapping[str, Any], proposal: Mapping[str, Any], proposal_input: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Validate and return a new append-only chain without modifying inputs."""
    if not isinstance(records, Sequence) or isinstance(records, (str, bytes, bytearray)):
        raise SeoImprovementProposalReviewError("proposal review records are invalid")
    copied = [dict(item) for item in records]
    for index, item in enumerate(copied):
        validate_review_record(item, proposal, proposal_input)
        if index == 0 and item["previous_review_id"] is not None:
            raise SeoImprovementProposalReviewError("initial proposal review cannot supersede another review")
        if index:
            previous = copied[index - 1]
            if item["previous_review_id"] != previous["proposal_review_id"]:
                raise SeoImprovementProposalReviewError("proposal review chain is invalid")
    validate_review_record(record, proposal, proposal_input)
    if copied:
        if record["previous_review_id"] != copied[-1]["proposal_review_id"]:
            raise SeoImprovementProposalReviewError("proposal review is not appended after latest")
    elif record["previous_review_id"] is not None:
        raise SeoImprovementProposalReviewError("initial proposal review cannot supersede another review")
    if any(item["proposal_review_id"] == record["proposal_review_id"] for item in copied):
        raise SeoImprovementProposalReviewError("duplicate proposal review record")
    return [*copied, dict(record)]


def latest_review_status(records: Sequence[Mapping[str, Any]], proposal: Mapping[str, Any], proposal_input: Mapping[str, Any]) -> str | None:
    if not records:
        return None
    return append_review_record(records[:-1], records[-1], proposal, proposal_input)[-1]["status"]
