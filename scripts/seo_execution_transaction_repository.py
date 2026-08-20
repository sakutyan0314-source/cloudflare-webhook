"""Local SQLite transaction model for SEO execution metadata only.

It stores reservations and audit facts in an isolated SQLite database for
testing.  It has no Worker/D1 transport and never executes an article UPDATE.
"""

from __future__ import annotations

from hashlib import sha256
import json
import sqlite3
from typing import Any, Mapping

from d1_conditional_update_audit import ConditionalUpdateAudit, ConditionalUpdateAuditError, validate_exact_conditional_update
from seo_improvement_execution_attempt import ATTEMPT_SCHEMA_VERSION, ATTEMPT_STATES


_STATES = frozenset({"planned", "approval_reserved", "update_started", "outcome_known_success", "outcome_known_failure", "outcome_unknown"})
_TRANSITIONS = {
    "planned": frozenset({"approval_reserved"}), "approval_reserved": frozenset({"update_started"}),
    "update_started": frozenset({"outcome_known_success", "outcome_known_failure", "outcome_unknown"}),
}
_CLASSIFICATIONS = frozenset({"not_started", "approval_reserved", "update_started", "success", "known_failure", "outcome_unknown"})
_REASONS = frozenset({"approval_expired", "approval_already_reserved", "preflight_identity_mismatch", "stale_snapshot", "conditional_update_no_match", "conditional_update_returning_mismatch", "transaction_failed", "outcome_unknown"})
_FORBIDDEN = frozenset({"content", "body_markdown", "sql", "params", "token", "secret", "authorization", "api_key", "execution_authorized", "publication_authorized"})


class SeoExecutionTransactionError(ValueError): pass
class SeoExecutionDuplicateError(SeoExecutionTransactionError): pass
class SeoExecutionStateConflict(SeoExecutionTransactionError): pass


def _canonical(value: Mapping[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def deterministic_event_id(*, execution_attempt_id: str, event_sequence: int, from_state: str | None, to_state: str, occurred_at: str) -> str:
    return "seo_execution_event_" + sha256(_canonical({"execution_attempt_id": execution_attempt_id, "event_sequence": event_sequence, "from_state": from_state, "to_state": to_state, "occurred_at": occurred_at}).encode()).hexdigest()[:24]


def _row(cursor: sqlite3.Cursor) -> dict[str, Any] | None:
    value = cursor.fetchone()
    return dict(value) if value is not None else None


def _attempt_values(attempt: Mapping[str, Any]) -> tuple[Any, ...]:
    required = {"schema_version", "execution_attempt_id", "execution_approval_id", "preflight_id", "execution_candidate_id", "execution_candidate_fingerprint", "candidate_id", "candidate_fingerprint", "proposal_id", "proposal_fingerprint", "plan_id", "plan_fingerprint", "article_id", "before_snapshot_fingerprint", "after_snapshot_fingerprint", "expected_diff", "state", "classification", "started_at", "completed_at", "changed_db", "changes", "returned_article_id", "execution_authorized", "publication_authorized"}
    if not isinstance(attempt, Mapping) or set(attempt) != required or attempt.get("schema_version") != ATTEMPT_SCHEMA_VERSION:
        raise SeoExecutionTransactionError("attempt_schema_invalid")
    if attempt["state"] != "planned" or attempt["classification"] != "not_started" or attempt["completed_at"] is not None or attempt["changed_db"] is not False or attempt["changes"] != 0 or attempt["returned_article_id"] is not None or attempt["execution_authorized"] is not False or attempt["publication_authorized"] is not False:
        raise SeoExecutionTransactionError("attempt_reservation_input_invalid")
    if any(not isinstance(attempt[key], str) or not attempt[key] for key in ("execution_attempt_id", "execution_approval_id", "preflight_id", "execution_candidate_id", "execution_candidate_fingerprint", "candidate_id", "candidate_fingerprint", "proposal_id", "proposal_fingerprint", "plan_id", "plan_fingerprint", "before_snapshot_fingerprint", "after_snapshot_fingerprint", "started_at")) or not isinstance(attempt["article_id"], int):
        raise SeoExecutionTransactionError("attempt_identity_invalid")
    return tuple(attempt[key] if key != "expected_diff" else _canonical(attempt[key]) for key in ("execution_attempt_id", "schema_version", "execution_approval_id", "preflight_id", "execution_candidate_id", "execution_candidate_fingerprint", "candidate_id", "candidate_fingerprint", "proposal_id", "proposal_fingerprint", "plan_id", "plan_fingerprint", "article_id", "before_snapshot_fingerprint", "after_snapshot_fingerprint", "expected_diff"))


class SeoExecutionTransactionRepository:
    """SQLite-only reservation, CAS transition, and append-only event model."""
    def __init__(self, connection: sqlite3.Connection, *, fail_event_insert: bool = False) -> None:
        self.connection, self.fail_event_insert = connection, fail_event_insert
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")

    def reserve_approval(self, attempt: Mapping[str, Any], *, created_at: str) -> dict[str, Any]:
        values = _attempt_values(attempt)
        event_id = deterministic_event_id(execution_attempt_id=attempt["execution_attempt_id"], event_sequence=0, from_state=None, to_state="planned", occurred_at=created_at)
        try:
            with self.connection:
                self.connection.execute("INSERT INTO seo_execution_attempts (execution_attempt_id,schema_version,execution_approval_id,preflight_id,execution_candidate_id,execution_candidate_fingerprint,candidate_id,candidate_fingerprint,proposal_id,proposal_fingerprint,plan_id,plan_fingerprint,article_id,before_snapshot_fingerprint,after_snapshot_fingerprint,expected_diff_json,state,classification,state_version,started_at,changed_db,changes,execution_authorized,publication_authorized,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'planned','not_started',0,?,0,0,0,0,?)", (*values, attempt["started_at"], created_at))
                if self.fail_event_insert: raise sqlite3.IntegrityError("injected_event_failure")
                self.connection.execute("INSERT INTO seo_execution_attempt_events (event_id,execution_attempt_id,event_sequence,from_state,to_state,classification,reason_code,occurred_at) VALUES (?,?,0,NULL,'planned','not_started',NULL,?)", (event_id, attempt["execution_attempt_id"], created_at))
        except sqlite3.IntegrityError as error:
            raise SeoExecutionDuplicateError("approval_or_preflight_already_reserved") from error
        return self.by_attempt_id(attempt["execution_attempt_id"]) or self._impossible()

    def transition(self, *, execution_attempt_id: str, expected_state: str, expected_version: int, to_state: str, classification: str, occurred_at: str, reason_code: str | None = None) -> dict[str, Any]:
        if expected_state not in _STATES or to_state not in _TRANSITIONS.get(expected_state, ()) or classification not in _CLASSIFICATIONS or reason_code is not None and reason_code not in _REASONS:
            raise SeoExecutionStateConflict("state_transition_rejected")
        required_classification = {"approval_reserved": "approval_reserved", "update_started": "update_started", "outcome_known_success": "success", "outcome_known_failure": "known_failure", "outcome_unknown": "outcome_unknown"}[to_state]
        if classification != required_classification:
            raise SeoExecutionStateConflict("state_classification_invalid")
        next_version = expected_version + 1
        event_id = deterministic_event_id(execution_attempt_id=execution_attempt_id, event_sequence=next_version, from_state=expected_state, to_state=to_state, occurred_at=occurred_at)
        try:
            with self.connection:
                cursor = self.connection.execute("UPDATE seo_execution_attempts SET state=?,classification=?,state_version=?,update_started_at=CASE WHEN ?='update_started' THEN ? ELSE update_started_at END,completed_at=CASE WHEN ? IN ('outcome_known_success','outcome_known_failure','outcome_unknown') THEN ? ELSE completed_at END WHERE execution_attempt_id=? AND state=? AND state_version=?", (to_state, classification, next_version, to_state, occurred_at, to_state, occurred_at, execution_attempt_id, expected_state, expected_version))
                if cursor.rowcount != 1: raise SeoExecutionStateConflict("cas_transition_conflict")
                if self.fail_event_insert: raise sqlite3.IntegrityError("injected_event_failure")
                self.connection.execute("INSERT INTO seo_execution_attempt_events (event_id,execution_attempt_id,event_sequence,from_state,to_state,classification,reason_code,occurred_at) VALUES (?,?,?,?,?,?,?,?)", (event_id, execution_attempt_id, next_version, expected_state, to_state, classification, reason_code, occurred_at))
        except sqlite3.IntegrityError as error:
            raise SeoExecutionStateConflict("attempt_event_atomicity_failed") from error
        return self.by_attempt_id(execution_attempt_id) or self._impossible()

    def save_post_verification(self, verification: Mapping[str, Any], *, created_at: str) -> dict[str, Any]:
        fields = {"schema_version", "post_verification_id", "execution_attempt_id", "article_id", "after_snapshot_fingerprint", "observed_snapshot_fingerprint", "expected_diff", "title_description_match", "forbidden_fields_unchanged", "content_hash_unchanged", "body_markdown_hash_unchanged", "classification"}
        if not isinstance(verification, Mapping) or set(verification) != fields or verification.get("schema_version") != "seo-improvement-execution-post-verification-v1" or verification.get("classification") not in {"pass", "fail"} or not all(verification.get(key) in {True, False} for key in ("title_description_match", "forbidden_fields_unchanged", "content_hash_unchanged", "body_markdown_hash_unchanged")):
            raise SeoExecutionTransactionError("post_verification_schema_invalid")
        try:
            with self.connection:
                self.connection.execute("INSERT INTO seo_execution_post_verifications (post_verification_id,schema_version,execution_attempt_id,article_id,after_snapshot_fingerprint,observed_snapshot_fingerprint,expected_diff_json,title_description_match,forbidden_fields_unchanged,content_hash_unchanged,body_markdown_hash_unchanged,classification,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", (verification["post_verification_id"], verification["schema_version"], verification["execution_attempt_id"], verification["article_id"], verification["after_snapshot_fingerprint"], verification["observed_snapshot_fingerprint"], _canonical(verification["expected_diff"]), int(verification["title_description_match"]), int(verification["forbidden_fields_unchanged"]), int(verification["content_hash_unchanged"]), int(verification["body_markdown_hash_unchanged"]), verification["classification"], created_at))
        except sqlite3.IntegrityError as error:
            raise SeoExecutionDuplicateError("post_verification_duplicate_or_attempt_missing") from error
        return _row(self.connection.execute("SELECT * FROM seo_execution_post_verifications WHERE post_verification_id=?", (verification["post_verification_id"],))) or self._impossible()

    def by_attempt_id(self, execution_attempt_id: str) -> dict[str, Any] | None: return _row(self.connection.execute("SELECT * FROM seo_execution_attempts WHERE execution_attempt_id=?", (execution_attempt_id,)))
    def events(self, execution_attempt_id: str) -> list[dict[str, Any]]: return [dict(row) for row in self.connection.execute("SELECT * FROM seo_execution_attempt_events WHERE execution_attempt_id=? ORDER BY event_sequence", (execution_attempt_id,))]
    @staticmethod
    def _impossible() -> dict[str, Any]: raise SeoExecutionTransactionError("read_after_write_failed")


def build_conditional_snippet_update(execution_candidate: Mapping[str, Any], current_row: Mapping[str, Any]) -> dict[str, Any]:
    """Build, but never execute, the exact allowlisted conditional UPDATE."""
    required = {"id", "title", "description", "category", "content", "body_markdown", "published_at", "updated_at", "seo_status"}
    if not isinstance(current_row, Mapping) or set(current_row) != required or not isinstance(execution_candidate, Mapping):
        raise SeoExecutionTransactionError("conditional_update_input_invalid")
    before, changes = execution_candidate.get("before_snapshot"), execution_candidate.get("expected_diff")
    if not isinstance(before, Mapping) or not isinstance(changes, Mapping) or not changes or not set(changes) <= {"title", "description"}:
        raise SeoExecutionTransactionError("conditional_update_scope_invalid")
    import hashlib
    if current_row["id"] != before.get("article_id") or hashlib.sha256(current_row["content"].encode()).hexdigest() != before.get("content_sha256") or hashlib.sha256(current_row["body_markdown"].encode()).hexdigest() != before.get("body_markdown_sha256"):
        raise SeoExecutionTransactionError("conditional_update_stale_snapshot")
    for field in ("title", "description", "category", "published_at", "updated_at", "seo_status"):
        if current_row[field] != before.get(field): raise SeoExecutionTransactionError("conditional_update_stale_snapshot")
    if any(value != {"current": before[field], "proposed": execution_candidate["after_snapshot"][field]} for field, value in changes.items()):
        raise SeoExecutionTransactionError("conditional_update_diff_invalid")
    fields = [field for field in ("title", "description") if field in changes]
    sql = "UPDATE curation_logs SET " + ", ".join(field + "=?" for field in fields) + " WHERE id=? AND title=? AND description=? AND category=? AND content=? AND body_markdown=? AND published_at=? AND updated_at=? AND seo_status=? RETURNING id"
    params = [changes[field]["proposed"] for field in fields] + [current_row[key] for key in ("id", "title", "description", "category", "content", "body_markdown", "published_at", "updated_at", "seo_status")]
    return {"sql": sql, "params": params, "expected_article_id": current_row["id"], "set_fields": fields}


def validate_conditional_returning(response: Mapping[str, Any], expected_article_id: int) -> ConditionalUpdateAudit:
    try: return validate_exact_conditional_update(response, expected_article_id)
    except ConditionalUpdateAuditError as error: raise SeoExecutionTransactionError("conditional_update_returning_invalid") from error
