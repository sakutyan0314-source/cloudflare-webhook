"""Phase 1B: local-only human review and non-executable planning handoff.

This module has no network, D1, AI, publishing, Worker, or scheduler path.
Its ledger is deliberately supplied by the operator and must live outside the
repository.  It records safe candidate snapshots and immutable review metadata
only; article prose, credentials, and raw external responses are rejected.
"""

from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import fcntl
import json
import os
from pathlib import Path
from typing import Any, Mapping, Sequence

from topic_candidate import (
    LEGACY_EXCLUDED_ARTICLE_IDS,
    TOPIC_CANDIDATE_SCHEMA_VERSION,
    TopicCandidateSafetyError,
    canonical_json,
    validate_topic_candidate,
)


HUMAN_REVIEW_SCHEMA_VERSION = "topic-candidate-human-review-v1"
APPROVED_TOPIC_PLANNING_SCHEMA_VERSION = "approved-topic-planning-v1"
REVIEW_DECISIONS = frozenset({
    "approve_for_content_planning", "hold", "reject", "strengthen_existing", "needs_more_evidence",
})
REASON_CODES_BY_DECISION = {
    "approve_for_content_planning": frozenset({"demand_evidence_sufficient", "priority_confirmed", "cluster_fit_confirmed", "content_gap_confirmed"}),
    "hold": frozenset({"timing_not_ready", "capacity_limited", "strategic_deprioritized"}),
    "reject": frozenset({"duplicate_or_overlap", "out_of_scope", "insufficient_quality"}),
    "strengthen_existing": frozenset({"existing_content_more_appropriate", "cannibalization_risk"}),
    "needs_more_evidence": frozenset({"demand_evidence_insufficient", "search_console_insufficient", "competitive_context_missing"}),
}
_FORBIDDEN_FIELD_NAMES = frozenset({
    "token", "read_token", "edit_token", "export_token", "authorization", "api_key", "secret",
    "raw_response", "raw_external_response", "content", "body_markdown", "article_body", "title_body", "description_body",
})


class TopicCandidateReviewSafetyError(ValueError):
    """A Phase 1B record attempted to cross a human-review safety boundary."""


def _reject_forbidden(value: Any) -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if not isinstance(key, str) or key.casefold() in _FORBIDDEN_FIELD_NAMES:
                raise TopicCandidateReviewSafetyError("forbidden_field_rejected")
            _reject_forbidden(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            _reject_forbidden(child)


def _parse_timestamp(value: object) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise TopicCandidateReviewSafetyError("timestamp_invalid")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise TopicCandidateReviewSafetyError("timestamp_invalid") from error


def candidate_identity_fingerprint(candidate: Mapping[str, Any]) -> str:
    """Fingerprint the full validated candidate so non-ID edits cannot be hidden."""
    validate_topic_candidate(candidate)
    return "candidate_" + sha256(canonical_json(dict(candidate)).encode("utf-8")).hexdigest()


def deterministic_review_id(*, topic_candidate_id: str, candidate_fingerprint: str, decision: str, reason_codes: Sequence[str], reviewed_at: str, previous_review_id: str | None) -> str:
    identity = {
        "schema_version": HUMAN_REVIEW_SCHEMA_VERSION,
        "topic_candidate_id": topic_candidate_id,
        "candidate_identity_fingerprint": candidate_fingerprint,
        "decision": decision,
        "reason_codes": list(reason_codes),
        "reviewed_at": reviewed_at,
        "previous_review_id": previous_review_id,
    }
    return "topic_review_" + sha256(canonical_json(identity).encode("utf-8")).hexdigest()[:24]


def validate_candidate_for_review(candidate: Mapping[str, Any], *, approval_decision: bool = False) -> str:
    """Revalidate every Phase 1A boundary before a human decision is accepted."""
    try:
        validate_topic_candidate(candidate)
    except TopicCandidateSafetyError as error:
        raise TopicCandidateReviewSafetyError("candidate_invalid") from error
    _reject_forbidden(candidate)
    if candidate.get("candidate_status") != "pending_human_review":
        raise TopicCandidateReviewSafetyError("candidate_not_pending_human_review")
    references = tuple(candidate["related_article_ids"]) + tuple(candidate["possible_child_article_ids"]) + (() if candidate["possible_parent_article_id"] is None else (candidate["possible_parent_article_id"],))
    if approval_decision and any(article_id in LEGACY_EXCLUDED_ARTICLE_IDS for article_id in references):
        raise TopicCandidateReviewSafetyError("legacy_candidate_cannot_be_approved")
    return candidate_identity_fingerprint(candidate)


def build_human_review(candidate: Mapping[str, Any], *, decision: str, reason_codes: Sequence[str], reviewed_at: str, previous_review: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Build fixed, content-free human review metadata; no free-text field exists."""
    if decision not in REVIEW_DECISIONS:
        raise TopicCandidateReviewSafetyError("review_decision_invalid")
    fingerprint = validate_candidate_for_review(candidate, approval_decision=decision == "approve_for_content_planning")
    if not isinstance(reason_codes, Sequence) or isinstance(reason_codes, (str, bytes)) or not 1 <= len(reason_codes) <= 3:
        raise TopicCandidateReviewSafetyError("review_reason_codes_invalid")
    reasons = tuple(reason_codes)
    if len(set(reasons)) != len(reasons) or any(reason not in REASON_CODES_BY_DECISION[decision] for reason in reasons):
        raise TopicCandidateReviewSafetyError("review_reason_codes_invalid")
    reviewed = _parse_timestamp(reviewed_at)
    if reviewed < _parse_timestamp(candidate["created_at"]):
        raise TopicCandidateReviewSafetyError("review_precedes_candidate")
    previous_review_id: str | None = None
    if previous_review is not None:
        validate_human_review(previous_review)
        if previous_review["topic_candidate_id"] != candidate["topic_candidate_id"] or previous_review["candidate_identity_fingerprint"] != fingerprint:
            raise TopicCandidateReviewSafetyError("previous_review_candidate_mismatch")
        previous_review_id = previous_review["review_id"]
    review = {
        "schema_version": HUMAN_REVIEW_SCHEMA_VERSION,
        "review_id": deterministic_review_id(topic_candidate_id=candidate["topic_candidate_id"], candidate_fingerprint=fingerprint, decision=decision, reason_codes=reasons, reviewed_at=reviewed_at, previous_review_id=previous_review_id),
        "topic_candidate_id": candidate["topic_candidate_id"],
        "candidate_schema_version": candidate["schema_version"],
        "candidate_identity_fingerprint": fingerprint,
        "decision": decision,
        "reason_codes": list(reasons),
        "reviewed_at": reviewed_at,
        "reviewer_type": "human",
        "previous_review_id": previous_review_id,
        "supersedes_review_id": previous_review_id,
        "content_generation_authorized": False,
        "publication_authorized": False,
        "execution_authorized": False,
    }
    validate_human_review(review)
    return review


def validate_human_review(review: Mapping[str, Any]) -> None:
    _reject_forbidden(review)
    required = {
        "schema_version", "review_id", "topic_candidate_id", "candidate_schema_version", "candidate_identity_fingerprint",
        "decision", "reason_codes", "reviewed_at", "reviewer_type", "previous_review_id", "supersedes_review_id",
        "content_generation_authorized", "publication_authorized", "execution_authorized",
    }
    if set(review) != required or review.get("schema_version") != HUMAN_REVIEW_SCHEMA_VERSION:
        raise TopicCandidateReviewSafetyError("review_schema_invalid")
    if review.get("candidate_schema_version") != TOPIC_CANDIDATE_SCHEMA_VERSION or review.get("decision") not in REVIEW_DECISIONS:
        raise TopicCandidateReviewSafetyError("review_enum_invalid")
    if review.get("reviewer_type") != "human" or not isinstance(review.get("topic_candidate_id"), str) or not isinstance(review.get("candidate_identity_fingerprint"), str):
        raise TopicCandidateReviewSafetyError("review_identity_invalid")
    reasons = review.get("reason_codes")
    if not isinstance(reasons, list) or not 1 <= len(reasons) <= 3 or len(set(reasons)) != len(reasons) or any(reason not in REASON_CODES_BY_DECISION[review["decision"]] for reason in reasons):
        raise TopicCandidateReviewSafetyError("review_reason_codes_invalid")
    _parse_timestamp(review.get("reviewed_at"))
    previous = review.get("previous_review_id")
    if previous is not None and (not isinstance(previous, str) or review.get("supersedes_review_id") != previous):
        raise TopicCandidateReviewSafetyError("review_supersede_invalid")
    if previous is None and review.get("supersedes_review_id") is not None:
        raise TopicCandidateReviewSafetyError("review_supersede_invalid")
    expected = deterministic_review_id(topic_candidate_id=review["topic_candidate_id"], candidate_fingerprint=review["candidate_identity_fingerprint"], decision=review["decision"], reason_codes=reasons, reviewed_at=review["reviewed_at"], previous_review_id=previous)
    if review.get("review_id") != expected:
        raise TopicCandidateReviewSafetyError("review_id_invalid")
    if any(review[key] is not False for key in ("content_generation_authorized", "publication_authorized", "execution_authorized")):
        raise TopicCandidateReviewSafetyError("review_authorization_boundary_invalid")


class TopicCandidateReviewLedger:
    """Git-external, locked JSONL ledger with append + fsync and fail-closed reads."""

    def __init__(self, path: Path, *, repository_root: Path) -> None:
        self.path, self.repository_root = path.resolve(), repository_root.resolve()
        try:
            self.path.relative_to(self.repository_root)
        except ValueError:
            pass
        else:
            raise TopicCandidateReviewSafetyError("ledger_path_must_be_outside_repository")
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(self.path.parent, 0o700)
        if not self.path.exists():
            descriptor = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            os.close(descriptor)
        os.chmod(self.path, 0o600)

    def _records(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        data = self.path.read_bytes()
        if data and not data.endswith(b"\n"):
            raise TopicCandidateReviewSafetyError("ledger_partial_record_detected")
        for line in data.splitlines():
            try:
                item = json.loads(line.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise TopicCandidateReviewSafetyError("ledger_record_invalid") from error
            if not isinstance(item, dict):
                raise TopicCandidateReviewSafetyError("ledger_record_invalid")
            _reject_forbidden(item)
            rows.append(item)
        return rows

    def _append(self, record: Mapping[str, Any]) -> None:
        _reject_forbidden(record)
        encoded = (canonical_json(dict(record)) + "\n").encode("utf-8")
        descriptor = os.open(self.path, os.O_WRONLY | os.O_APPEND)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            written = os.write(descriptor, encoded)
            if written != len(encoded):
                raise TopicCandidateReviewSafetyError("ledger_append_incomplete")
            os.fsync(descriptor)
        finally:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            finally:
                os.close(descriptor)

    def append_candidate(self, candidate: Mapping[str, Any]) -> str:
        fingerprint = validate_candidate_for_review(candidate)
        for record in self._records():
            if record.get("record_type") == "candidate_snapshot" and record.get("topic_candidate_id") == candidate["topic_candidate_id"]:
                if record.get("candidate_identity_fingerprint") == fingerprint:
                    raise TopicCandidateReviewSafetyError("duplicate_candidate_snapshot")
                raise TopicCandidateReviewSafetyError("candidate_identity_collision")
        self._append({"record_type": "candidate_snapshot", "topic_candidate_id": candidate["topic_candidate_id"], "candidate_identity_fingerprint": fingerprint, "candidate": dict(candidate)})
        return fingerprint

    def reviews_for(self, topic_candidate_id: str) -> list[dict[str, Any]]:
        reviews: list[dict[str, Any]] = []
        for record in self._records():
            if record.get("record_type") == "human_review":
                review = record.get("review")
                if isinstance(review, dict) and review.get("topic_candidate_id") == topic_candidate_id:
                    validate_human_review(review)
                    reviews.append(review)
        return reviews

    def append_review(self, candidate: Mapping[str, Any], review: Mapping[str, Any]) -> None:
        fingerprint = validate_candidate_for_review(candidate, approval_decision=review.get("decision") == "approve_for_content_planning")
        validate_human_review(review)
        snapshots = [record for record in self._records() if record.get("record_type") == "candidate_snapshot" and record.get("topic_candidate_id") == candidate["topic_candidate_id"]]
        if len(snapshots) != 1 or snapshots[0].get("candidate_identity_fingerprint") != fingerprint:
            raise TopicCandidateReviewSafetyError("candidate_snapshot_missing_or_mismatched")
        if review["candidate_identity_fingerprint"] != fingerprint or review["candidate_schema_version"] != candidate["schema_version"]:
            raise TopicCandidateReviewSafetyError("review_candidate_mismatch")
        prior = self.reviews_for(candidate["topic_candidate_id"])
        if any(item["review_id"] == review["review_id"] for item in prior):
            raise TopicCandidateReviewSafetyError("duplicate_review_rejected")
        expected_previous = prior[-1]["review_id"] if prior else None
        if review["previous_review_id"] != expected_previous or review["supersedes_review_id"] != expected_previous:
            raise TopicCandidateReviewSafetyError("review_chain_invalid")
        self._append({"record_type": "human_review", "review_id": review["review_id"], "topic_candidate_id": review["topic_candidate_id"], "candidate_identity_fingerprint": fingerprint, "review": dict(review)})


def deterministic_handoff_id(*, topic_candidate_id: str, candidate_fingerprint: str, human_review_id: str) -> str:
    return "topic_handoff_" + sha256(canonical_json({"schema_version": APPROVED_TOPIC_PLANNING_SCHEMA_VERSION, "topic_candidate_id": topic_candidate_id, "candidate_identity_fingerprint": candidate_fingerprint, "human_review_id": human_review_id}).encode("utf-8")).hexdigest()[:24]


def _validate_review_chain(candidate: Mapping[str, Any], reviews: Sequence[Mapping[str, Any]], fingerprint: str) -> None:
    previous: str | None = None
    for review in reviews:
        validate_human_review(review)
        if review["topic_candidate_id"] != candidate["topic_candidate_id"] or review["candidate_identity_fingerprint"] != fingerprint:
            raise TopicCandidateReviewSafetyError("review_candidate_mismatch")
        if review["previous_review_id"] != previous or review["supersedes_review_id"] != previous:
            raise TopicCandidateReviewSafetyError("review_chain_invalid")
        previous = review["review_id"]


def build_approved_topic_planning_handoff(candidate: Mapping[str, Any], reviews: Sequence[Mapping[str, Any]], *, created_at: str) -> dict[str, Any]:
    fingerprint = validate_candidate_for_review(candidate, approval_decision=True)
    if candidate["routing_decision"] != "new_content_planning":
        raise TopicCandidateReviewSafetyError("routing_auto_handoff_forbidden")
    if not reviews:
        raise TopicCandidateReviewSafetyError("approved_review_missing")
    _validate_review_chain(candidate, reviews, fingerprint)
    latest = reviews[-1]
    if latest["topic_candidate_id"] != candidate["topic_candidate_id"] or latest["candidate_identity_fingerprint"] != fingerprint or latest["decision"] != "approve_for_content_planning":
        raise TopicCandidateReviewSafetyError("approved_review_missing")
    _parse_timestamp(created_at)
    evidence_summary = [{"evidence_type": item["evidence_type"], "evidence_source": item["evidence_source"], "evidence_observed_at": item["evidence_observed_at"]} for item in candidate["demand_evidence"]]
    handoff = {
        "schema_version": APPROVED_TOPIC_PLANNING_SCHEMA_VERSION,
        "handoff_id": deterministic_handoff_id(topic_candidate_id=candidate["topic_candidate_id"], candidate_fingerprint=fingerprint, human_review_id=latest["review_id"]),
        "topic_candidate_id": candidate["topic_candidate_id"], "candidate_identity_fingerprint": fingerprint,
        "human_review_id": latest["review_id"], "decision": latest["decision"], "topic": candidate["topic"],
        "primary_intent": candidate["primary_intent"], "target_audience": candidate["target_audience"], "cluster_id": candidate["cluster_id"],
        "routing": candidate["routing_decision"], "priority": candidate["priority"],
        "demand_evidence_summary": evidence_summary, "related_article_ids": list(candidate["related_article_ids"]), "created_at": created_at,
        "content_generation_authorized": False, "publication_authorized": False, "execution_authorized": False,
    }
    validate_approved_topic_planning_handoff(handoff)
    return handoff


def validate_approved_topic_planning_handoff(handoff: Mapping[str, Any]) -> None:
    """Verify that a handoff is planning metadata, never execution authority."""
    _reject_forbidden(handoff)
    required = {
        "schema_version", "handoff_id", "topic_candidate_id", "candidate_identity_fingerprint", "human_review_id", "decision",
        "topic", "primary_intent", "target_audience", "cluster_id", "routing", "priority", "demand_evidence_summary",
        "related_article_ids", "created_at", "content_generation_authorized", "publication_authorized", "execution_authorized",
    }
    if set(handoff) != required or handoff.get("schema_version") != APPROVED_TOPIC_PLANNING_SCHEMA_VERSION:
        raise TopicCandidateReviewSafetyError("handoff_schema_invalid")
    if handoff.get("decision") != "approve_for_content_planning" or handoff.get("routing") != "new_content_planning":
        raise TopicCandidateReviewSafetyError("handoff_decision_or_routing_invalid")
    if not all(isinstance(handoff.get(key), str) and handoff[key] for key in ("handoff_id", "topic_candidate_id", "candidate_identity_fingerprint", "human_review_id", "topic", "primary_intent", "target_audience", "cluster_id")):
        raise TopicCandidateReviewSafetyError("handoff_identity_invalid")
    if not isinstance(handoff.get("related_article_ids"), list) or any(not isinstance(item, int) or item < 1 for item in handoff["related_article_ids"]):
        raise TopicCandidateReviewSafetyError("handoff_article_reference_invalid")
    evidence = handoff.get("demand_evidence_summary")
    if not isinstance(evidence, list) or not evidence:
        raise TopicCandidateReviewSafetyError("handoff_evidence_invalid")
    for item in evidence:
        if not isinstance(item, Mapping) or set(item) != {"evidence_type", "evidence_source", "evidence_observed_at"} or not all(isinstance(item.get(key), str) and item[key] for key in item):
            raise TopicCandidateReviewSafetyError("handoff_evidence_invalid")
    _parse_timestamp(handoff.get("created_at"))
    if any(handoff[key] is not False for key in ("content_generation_authorized", "publication_authorized", "execution_authorized")):
        raise TopicCandidateReviewSafetyError("handoff_authorization_boundary_invalid")
