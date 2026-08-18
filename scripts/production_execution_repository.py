"""Local SQLite repository for metadata-only approved-canary execution state.

It deliberately has no Worker, network, D1 transport, AI, article, or
notification operation.  The same SQL constraints and CAS behavior are tested
against an isolated SQLite database before any future D1 integration.
"""

from __future__ import annotations

from hashlib import sha256
import json
import sqlite3
from typing import Any, Mapping


EXECUTION_SCHEMA_VERSION = "approved-canary-production-execution-v1"
TRIGGER_TYPE = "approved_canary"
STATES = frozenset({"planned", "preflight_verified", "approval_verified", "send_started", "outcome_known_success", "outcome_known_failed", "outcome_unknown"})
TERMINAL_STATES = frozenset({"outcome_known_success", "outcome_known_failed", "outcome_unknown"})
CLASSIFICATIONS = frozenset({"success", "known_failure", "outcome_unknown", "pre_send_resume_candidate"})
REASON_CODES = frozenset({"approval_expired", "approval_mismatch", "production_input_mismatch", "candidate_fingerprint_mismatch", "review_chain_invalid", "superseded_review", "routing_invalid", "legacy_dependency", "duplicate_execution", "canary_not_allowed", "transport_known_failure", "transport_timeout", "transport_connection_failure", "response_malformed", "process_interrupted", "outcome_unknown_requires_review", "state_transition_conflict", "pipeline_run_link_failed", "publication_not_authorized"})
ALLOWED_TRANSITIONS = {
    "planned": frozenset({"preflight_verified"}),
    "preflight_verified": frozenset({"approval_verified"}),
    "approval_verified": frozenset({"send_started"}),
    "send_started": frozenset({"outcome_known_success", "outcome_known_failed", "outcome_unknown"}),
}
_FORBIDDEN_KEYS = frozenset({"prompt", "production_brief", "content", "body_markdown", "title_body", "description_body", "raw_response", "raw_ai_response", "token", "secret", "authorization", "api_key"})


class ProductionExecutionSafetyError(ValueError): pass
class ProductionExecutionDuplicateError(ProductionExecutionSafetyError): pass
class ProductionExecutionStateConflict(ProductionExecutionSafetyError): pass


def _reject_forbidden(value: Any) -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if not isinstance(key, str) or key.casefold() in _FORBIDDEN_KEYS:
                raise ProductionExecutionSafetyError("forbidden_execution_metadata")
            _reject_forbidden(child)
    elif isinstance(value, (list, tuple)):
        for child in value: _reject_forbidden(child)


def deterministic_event_id(*, production_execution_id: str, event_sequence: int, from_state: str | None, to_state: str, occurred_at: str) -> str:
    identity = {"production_execution_id": production_execution_id, "event_sequence": event_sequence, "from_state": from_state, "to_state": to_state, "occurred_at": occurred_at}
    return "production_event_" + sha256(json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()[:24]


def _row(cursor: sqlite3.Cursor) -> dict[str, Any] | None:
    item = cursor.fetchone(); return dict(item) if item is not None else None


class ProductionExecutionRepository:
    """Fixed-query, transactionally updated snapshot + append-only event store."""
    def __init__(self, connection: sqlite3.Connection, *, fail_event_insert: bool = False) -> None:
        self.connection, self.fail_event_insert = connection, fail_event_insert
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")

    def acquire(self, *, production_execution_id: str, production_input_id: str, production_input_fingerprint: str, approval_id: str, topic_candidate_id: str, human_review_id: str, created_at: str, publication_authorized: bool = False) -> dict[str, Any]:
        values = {"production_execution_id": production_execution_id, "production_input_id": production_input_id, "production_input_fingerprint": production_input_fingerprint, "approval_id": approval_id, "topic_candidate_id": topic_candidate_id, "human_review_id": human_review_id, "created_at": created_at}
        _reject_forbidden(values)
        if publication_authorized is not False or not all(isinstance(value, str) and value for value in values.values()):
            raise ProductionExecutionSafetyError("execution_acquire_input_invalid")
        event_id = deterministic_event_id(production_execution_id=production_execution_id, event_sequence=0, from_state=None, to_state="planned", occurred_at=created_at)
        try:
            with self.connection:
                self.connection.execute("INSERT INTO production_executions (production_execution_id, schema_version, production_input_id, production_input_fingerprint, approval_id, topic_candidate_id, human_review_id, trigger_type, state, classification, state_version, notification_classification, publication_authorized, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'planned', NULL, 0, 'not_applicable', 0, ?)", (production_execution_id, EXECUTION_SCHEMA_VERSION, production_input_id, production_input_fingerprint, approval_id, topic_candidate_id, human_review_id, TRIGGER_TYPE, created_at))
                if self.fail_event_insert: raise sqlite3.IntegrityError("injected_event_failure")
                self.connection.execute("INSERT INTO production_execution_events (event_id, production_execution_id, event_sequence, from_state, to_state, classification, reason_code, occurred_at) VALUES (?, ?, 0, NULL, 'planned', NULL, NULL, ?)", (event_id, production_execution_id, created_at))
        except sqlite3.IntegrityError as error:
            raise ProductionExecutionDuplicateError("execution_acquire_rejected") from error
        return self.by_execution_id(production_execution_id) or self._impossible()

    def transition(self, *, production_execution_id: str, expected_state: str, expected_version: int, to_state: str, occurred_at: str, classification: str | None = None, reason_code: str | None = None) -> dict[str, Any]:
        if expected_state not in STATES or to_state not in ALLOWED_TRANSITIONS.get(expected_state, ()) or not isinstance(expected_version, int) or expected_version < 0:
            raise ProductionExecutionStateConflict("state_transition_rejected")
        if classification is not None and classification not in CLASSIFICATIONS or reason_code is not None and reason_code not in REASON_CODES:
            raise ProductionExecutionSafetyError("event_classification_or_reason_invalid")
        if to_state == "outcome_known_success" and classification != "success": raise ProductionExecutionStateConflict("terminal_classification_invalid")
        if to_state == "outcome_known_failed" and classification != "known_failure": raise ProductionExecutionStateConflict("terminal_classification_invalid")
        if to_state == "outcome_unknown" and classification != "outcome_unknown": raise ProductionExecutionStateConflict("terminal_classification_invalid")
        next_version = expected_version + 1
        event_id = deterministic_event_id(production_execution_id=production_execution_id, event_sequence=next_version, from_state=expected_state, to_state=to_state, occurred_at=occurred_at)
        try:
            with self.connection:
                cursor = self.connection.execute("UPDATE production_executions SET state = ?, classification = ?, state_version = ?, started_at = CASE WHEN ? = 'preflight_verified' THEN ? ELSE started_at END, send_started_at = CASE WHEN ? = 'send_started' THEN ? ELSE send_started_at END, completed_at = CASE WHEN ? IN ('outcome_known_success', 'outcome_known_failed', 'outcome_unknown') THEN ? ELSE completed_at END WHERE production_execution_id = ? AND state = ? AND state_version = ?", (to_state, classification, next_version, to_state, occurred_at, to_state, occurred_at, to_state, occurred_at, production_execution_id, expected_state, expected_version))
                if cursor.rowcount != 1: raise ProductionExecutionStateConflict("cas_transition_conflict")
                if self.fail_event_insert: raise sqlite3.IntegrityError("injected_event_failure")
                event = self.connection.execute("INSERT INTO production_execution_events (event_id, production_execution_id, event_sequence, from_state, to_state, classification, reason_code, occurred_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (event_id, production_execution_id, next_version, expected_state, to_state, classification, reason_code, occurred_at))
                if event.rowcount != 1: raise ProductionExecutionStateConflict("event_insert_conflict")
        except sqlite3.IntegrityError as error:
            raise ProductionExecutionStateConflict("snapshot_event_atomicity_failed") from error
        return self.by_execution_id(production_execution_id) or self._impossible()

    def by_execution_id(self, production_execution_id: str) -> dict[str, Any] | None:
        return _row(self.connection.execute("SELECT * FROM production_executions WHERE production_execution_id = ?", (production_execution_id,)))
    def by_production_input_id(self, production_input_id: str) -> dict[str, Any] | None:
        return _row(self.connection.execute("SELECT * FROM production_executions WHERE production_input_id = ?", (production_input_id,)))
    def by_approval_id(self, approval_id: str) -> dict[str, Any] | None:
        return _row(self.connection.execute("SELECT * FROM production_executions WHERE approval_id = ?", (approval_id,)))
    def event_rows(self, production_execution_id: str) -> list[dict[str, Any]]:
        return [dict(row) for row in self.connection.execute("SELECT * FROM production_execution_events WHERE production_execution_id = ? ORDER BY event_sequence", (production_execution_id,))]
    def total_count(self) -> int: return int(self.connection.execute("SELECT COUNT(*) FROM production_executions").fetchone()[0])
    def state_counts(self) -> dict[str, int]: return {row["state"]: int(row["count"]) for row in self.connection.execute("SELECT state, COUNT(*) AS count FROM production_executions GROUP BY state")}
    def classification_counts(self) -> dict[str, int]: return {row["classification"]: int(row["count"]) for row in self.connection.execute("SELECT classification, COUNT(*) AS count FROM production_executions WHERE classification IS NOT NULL GROUP BY classification")}
    def outcome_unknown_count(self) -> int: return int(self.connection.execute("SELECT COUNT(*) FROM production_executions WHERE state = 'outcome_unknown'").fetchone()[0])
    def send_started(self, production_execution_id: str) -> bool:
        row = self.by_execution_id(production_execution_id); return bool(row and row["send_started_at"] is not None)
    def linked_rows(self) -> list[dict[str, Any]]:
        return [dict(row) for row in self.connection.execute("SELECT production_execution_id, pipeline_run_id, final_article_id, quality_gate_audit_id FROM production_executions WHERE pipeline_run_id IS NOT NULL OR final_article_id IS NOT NULL OR quality_gate_audit_id IS NOT NULL")]
    def unresolved_rows(self) -> list[dict[str, Any]]:
        return [dict(row) for row in self.connection.execute("SELECT * FROM production_executions WHERE state IN ('planned', 'preflight_verified', 'approval_verified', 'send_started') ORDER BY created_at")]
    def pre_send_resume_candidates(self) -> list[dict[str, Any]]:
        return [dict(row) for row in self.connection.execute("SELECT * FROM production_executions WHERE state = 'approval_verified' ORDER BY created_at")]
    def outcome_unknown_review_candidates(self) -> list[dict[str, Any]]:
        return [dict(row) for row in self.connection.execute("SELECT * FROM production_executions WHERE state IN ('send_started', 'outcome_unknown') ORDER BY created_at")]
    @staticmethod
    def _impossible() -> dict[str, Any]: raise ProductionExecutionSafetyError("execution_read_after_write_failed")
