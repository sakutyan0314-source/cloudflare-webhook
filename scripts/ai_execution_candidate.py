"""Local-only v2.0-D execution-candidate safety foundation.

No function in this module contacts D1 or an AI provider.  It constructs
conditional UPDATE input only after all human approvals and preflight facts
are supplied by a future caller.  Execution remains explicitly unauthorized.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import re
from typing import Any, Dict, Mapping, Optional, Sequence

from ai_change_plan import PLAN_REVIEW_SCHEMA_VERSION, PLAN_SCHEMA_VERSION, ChangePlanError, validate_article_snapshot


EXECUTION_CANDIDATE_SCHEMA_VERSION = "v2.0-d-execution-candidate-v1"
EXECUTION_APPROVAL_SCHEMA_VERSION = "v2.0-d-execution-approval-v1"
EXECUTION_AUDIT_SCHEMA_VERSION = "v2.0-d-execution-audit-v1"
ROLLBACK_CANDIDATE_SCHEMA_VERSION = "v2.0-d-rollback-candidate-v1"
EFFECT_HANDOFF_SCHEMA_VERSION = "v2.0-e-execution-handoff-v1"
INITIAL_EXECUTION_ALLOWLIST = frozenset({"title", "description"})
INITIAL_EXECUTION_APPROVAL_TTL = timedelta(minutes=30)
EXECUTION_STATES = {
    "planned": {"preflight_verified"},
    "preflight_verified": {"approval_verified"},
    "approval_verified": {"send_started"},
    "send_started": {"result_known", "outcome_unknown"},
    "result_known": set(),
    "outcome_unknown": set(),
}
_SHA256 = re.compile(r"^[a-f0-9]{64}$")
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_SENSITIVE_KEY = re.compile(r"(?:raw_?response|authorization|api[_ -]?key|private[_ -]?key|secret|token)", re.IGNORECASE)
_SENSITIVE_VALUE = re.compile(r"(?:api[_ -]?key|authorization|bearer\s+|private[_ -]?key|token)\s*[:=]", re.IGNORECASE)


class ExecutionSafetyError(ValueError):
    """Candidate, approval, update, or audit input failed closed."""


def _canonical_json(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as error:
        raise ExecutionSafetyError("canonical JSON is invalid") from error


def _digest(value: Any) -> str:
    return sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _require_id(value: object, name: str) -> str:
    if not isinstance(value, str) or not _SAFE_ID.fullmatch(value):
        raise ExecutionSafetyError(name + " is invalid")
    return value


def _parse_time(value: object, name: str) -> datetime:
    if not isinstance(value, str):
        raise ExecutionSafetyError(name + " is invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ExecutionSafetyError(name + " is invalid") from error
    if parsed.tzinfo is None:
        raise ExecutionSafetyError(name + " must include UTC offset")
    return parsed.astimezone(timezone.utc)


def _reject_sensitive(value: Any) -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if not isinstance(key, str) or _SENSITIVE_KEY.search(key):
                raise ExecutionSafetyError("sensitive data is prohibited")
            _reject_sensitive(child)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for child in value:
            _reject_sensitive(child)
    elif isinstance(value, str) and _SENSITIVE_VALUE.search(value):
        raise ExecutionSafetyError("sensitive data is prohibited")


def plan_fingerprint(plan: Mapping[str, Any]) -> str:
    """Fingerprint the immutable plan representation; no execution fields."""
    if not isinstance(plan, Mapping) or plan.get("plan_schema_version") != PLAN_SCHEMA_VERSION:
        raise ExecutionSafetyError("change plan schema is invalid")
    if plan.get("execution_authorized") is not False or plan.get("plan_status") != "pending_human_plan_review":
        raise ExecutionSafetyError("change plan execution state is invalid")
    _reject_sensitive(plan)
    return _digest(dict(plan))


def validate_plan_review_approval(plan: Mapping[str, Any], approval: Mapping[str, Any]) -> Dict[str, Any]:
    """Validate a distinct v2.0-C plan-review approval, never an execution approval."""
    required = {
        "schema_version", "plan_id", "plan_fingerprint", "plan_review_id", "plan_review_version",
        "reviewer_id", "reviewed_at", "decision", "approval_eligible", "execution_authorized",
    }
    if not isinstance(approval, Mapping) or set(approval) != required:
        raise ExecutionSafetyError("plan review approval fields are invalid")
    if approval.get("schema_version") != PLAN_REVIEW_SCHEMA_VERSION:
        raise ExecutionSafetyError("plan review approval schema is invalid")
    if approval.get("decision") != "approve" or approval.get("approval_eligible") is not True or approval.get("execution_authorized") is not False:
        raise ExecutionSafetyError("plan review approval is not an eligible planning approval")
    if approval.get("plan_id") != plan.get("plan_id") or approval.get("plan_fingerprint") != plan_fingerprint(plan):
        raise ExecutionSafetyError("plan review approval does not match change plan")
    for key in ("plan_review_id", "reviewer_id"):
        _require_id(approval.get(key), key)
    if not isinstance(approval.get("plan_review_version"), int) or approval["plan_review_version"] < 1:
        raise ExecutionSafetyError("plan review version is invalid")
    _parse_time(approval.get("reviewed_at"), "reviewed_at")
    _reject_sensitive(approval)
    return dict(approval)


def build_execution_candidate(plan: Mapping[str, Any], plan_review_approval: Mapping[str, Any]) -> Dict[str, Any]:
    """Create a deterministic candidate limited to title/description updates."""
    review = validate_plan_review_approval(plan, plan_review_approval)
    snapshot = validate_article_snapshot(plan.get("current_state_snapshot"))
    changes = plan.get("proposed_changes")
    if not isinstance(changes, Mapping) or not changes or not set(changes) <= INITIAL_EXECUTION_ALLOWLIST:
        raise ExecutionSafetyError("initial execution allowlist permits title and description only")
    if set(changes) - {"title", "description"}:
        raise ExecutionSafetyError("execution change contains prohibited field")
    for field, value in changes.items():
        if not isinstance(value, str) or not value.strip():
            raise ExecutionSafetyError("execution proposed value is invalid")
    source = {
        "candidate_schema_version": EXECUTION_CANDIDATE_SCHEMA_VERSION,
        "article_id": snapshot["article_id"], "recommendation_id": plan["recommendation_id"],
        "recommendation_fingerprint": plan["recommendation_fingerprint"], "review_id": plan["review_id"],
        "review_version": plan["review_version"], "plan_id": plan["plan_id"], "plan_fingerprint": plan_fingerprint(plan),
        "plan_review_id": review["plan_review_id"], "plan_review_version": review["plan_review_version"],
        "current_state_snapshot": snapshot, "allowed_changes": {key: changes[key] for key in sorted(changes)},
        "expected_diff": {key: {"current": snapshot[key], "proposed": changes[key]} for key in sorted(changes)},
        "stale_check": {"snapshot": snapshot, "recommendation_fingerprint": plan["recommendation_fingerprint"]},
    }
    fingerprint = _digest(source)
    return {**source, "candidate_fingerprint": fingerprint, "candidate_id": "candidate_v2d_" + fingerprint[:24],
            "execution_authorized": False}


def validate_execution_approval(candidate: Mapping[str, Any], approval: Mapping[str, Any], *, now: str) -> Dict[str, Any]:
    """Require a separate, unexpired human execution approval."""
    required = {"schema_version", "approval_id", "candidate_id", "candidate_fingerprint", "plan_id", "article_id", "reviewer_id", "approved_at", "expires_at"}
    if not isinstance(candidate, Mapping) or candidate.get("candidate_schema_version") != EXECUTION_CANDIDATE_SCHEMA_VERSION:
        raise ExecutionSafetyError("execution candidate schema is invalid")
    if not isinstance(approval, Mapping) or set(approval) != required or approval.get("schema_version") != EXECUTION_APPROVAL_SCHEMA_VERSION:
        raise ExecutionSafetyError("execution approval schema is invalid")
    for key in ("approval_id", "candidate_id", "plan_id", "reviewer_id"):
        _require_id(approval.get(key), key)
    if approval.get("candidate_id") != candidate.get("candidate_id") or approval.get("candidate_fingerprint") != candidate.get("candidate_fingerprint"):
        raise ExecutionSafetyError("execution approval candidate does not match")
    if approval.get("plan_id") != candidate.get("plan_id") or approval.get("article_id") != candidate.get("article_id"):
        raise ExecutionSafetyError("execution approval plan or article does not match")
    approved_at = _parse_time(approval.get("approved_at"), "approved_at")
    expires_at = _parse_time(approval.get("expires_at"), "expires_at")
    current = _parse_time(now, "now")
    if expires_at <= approved_at or expires_at > approved_at + INITIAL_EXECUTION_APPROVAL_TTL or current >= expires_at:
        raise ExecutionSafetyError("execution approval is expired or invalid")
    _reject_sensitive(approval)
    return dict(approval)


def validate_current_state(candidate: Mapping[str, Any], current_snapshot: Mapping[str, Any]) -> None:
    current = validate_article_snapshot(current_snapshot)
    if not isinstance(candidate, Mapping) or candidate.get("current_state_snapshot") != current:
        raise ExecutionSafetyError("stale_execution_candidate")


def validate_final_diff(candidate: Mapping[str, Any], final_diff: Mapping[str, Any]) -> Dict[str, Any]:
    """Require the displayed execution diff to equal the immutable candidate."""
    if not isinstance(candidate, Mapping) or not isinstance(final_diff, Mapping):
        raise ExecutionSafetyError("final diff is invalid")
    if final_diff.get("article_id") != candidate.get("article_id") or final_diff.get("candidate_fingerprint") != candidate.get("candidate_fingerprint"):
        raise ExecutionSafetyError("final diff identity does not match candidate")
    if final_diff.get("changes") != candidate.get("expected_diff"):
        raise ExecutionSafetyError("final diff does not match candidate")
    return {"article_id": final_diff["article_id"], "candidate_fingerprint": final_diff["candidate_fingerprint"], "changes": final_diff["changes"]}


def validate_dry_run(candidate: Mapping[str, Any], dry_run: Mapping[str, Any]) -> Dict[str, Any]:
    """Validate a read-only zero-write simulation for exactly this candidate."""
    if not isinstance(dry_run, Mapping) or dry_run.get("article_id") != candidate.get("article_id") or dry_run.get("candidate_fingerprint") != candidate.get("candidate_fingerprint"):
        raise ExecutionSafetyError("dry-run identity does not match candidate")
    if dry_run.get("changed_db") is not False or dry_run.get("rows_written") != 0 or dry_run.get("expected_diff") != candidate.get("expected_diff"):
        raise ExecutionSafetyError("dry-run does not satisfy read-only candidate conditions")
    return {"article_id": dry_run["article_id"], "candidate_fingerprint": dry_run["candidate_fingerprint"], "changed_db": False, "rows_written": 0}


def build_preflight_record(candidate: Mapping[str, Any], facts: Mapping[str, Any]) -> Dict[str, Any]:
    """Model required backup, restore, dry-run and final-diff facts without I/O."""
    required = {"identity_verified", "bookmark", "export_sha256", "restore_verified", "dry_run", "final_diff"}
    if not isinstance(facts, Mapping) or set(facts) != required or not all(facts.get(key) is True for key in ("identity_verified", "restore_verified")):
        raise ExecutionSafetyError("execution preflight is incomplete")
    if not isinstance(facts.get("bookmark"), str) or not facts["bookmark"] or not isinstance(facts.get("export_sha256"), str) or not _SHA256.fullmatch(facts["export_sha256"]):
        raise ExecutionSafetyError("execution backup facts are invalid")
    return {"candidate_id": candidate.get("candidate_id"), "identity_verified": True, "bookmark": facts["bookmark"],
            "export_sha256": facts["export_sha256"], "restore_verified": True,
            "dry_run": validate_dry_run(candidate, facts["dry_run"]),
            "final_diff": validate_final_diff(candidate, facts["final_diff"])}


def build_conditional_update(candidate: Mapping[str, Any], current_row: Mapping[str, Any]) -> Dict[str, Any]:
    """Build but never send an exact title/description conditional UPDATE.

    ``content`` and ``body_markdown`` may exist only in caller memory to bind
    the WHERE precondition.  They are omitted from the returned audit view.
    """
    snapshot = validate_article_snapshot(candidate.get("current_state_snapshot"))
    required = {"id", "title", "description", "category", "content", "body_markdown", "published_at", "updated_at", "seo_status"}
    if not isinstance(current_row, Mapping) or set(current_row) != required or current_row.get("id") != snapshot["article_id"]:
        raise ExecutionSafetyError("conditional update current row is invalid")
    content, body = current_row["content"], current_row["body_markdown"]
    if not isinstance(content, str) or not isinstance(body, str) or sha256(content.encode("utf-8")).hexdigest() != snapshot["content_sha256"] or sha256(body.encode("utf-8")).hexdigest() != snapshot["body_markdown_sha256"]:
        raise ExecutionSafetyError("conditional update SHA precondition failed")
    for key in ("title", "description", "category", "published_at", "updated_at", "seo_status"):
        if current_row[key] != snapshot[key]:
            raise ExecutionSafetyError("conditional update snapshot precondition failed")
    changes = candidate.get("allowed_changes")
    if not isinstance(changes, Mapping) or not changes or not set(changes) <= INITIAL_EXECUTION_ALLOWLIST:
        raise ExecutionSafetyError("conditional update allowlist is invalid")
    set_parts, params = [], []
    for field in ("title", "description"):
        if field in changes:
            set_parts.append(field + "=?")
            params.append(changes[field])
    sql = "UPDATE curation_logs SET " + ", ".join(set_parts) + " WHERE id=? AND title=? AND description=? AND category=? AND content=? AND body_markdown=? AND published_at=? AND updated_at=? AND seo_status=? RETURNING id"
    params.extend([snapshot["article_id"], snapshot["title"], snapshot["description"], snapshot["category"], content, body, snapshot["published_at"], snapshot["updated_at"], snapshot["seo_status"]])
    return {"sql": sql, "params": params, "audit": {"article_id": snapshot["article_id"], "set_fields": sorted(changes), "content_sha256": snapshot["content_sha256"], "body_markdown_sha256": snapshot["body_markdown_sha256"]}}


def validate_update_response(candidate: Mapping[str, Any], meta: Mapping[str, Any], returned_rows: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """Success requires changes=1 and one expected RETURNING row; rows_written is reference-only."""
    expected_id = candidate.get("article_id")
    if not isinstance(meta, Mapping) or meta.get("changed_db") is not True or meta.get("changes") != 1:
        raise ExecutionSafetyError("conditional update metadata is invalid")
    if not isinstance(returned_rows, Sequence) or len(returned_rows) != 1 or returned_rows[0].get("id") != expected_id:
        raise ExecutionSafetyError("conditional update RETURNING row is invalid")
    rows_written = meta.get("rows_written")
    if rows_written is not None and (not isinstance(rows_written, int) or isinstance(rows_written, bool) or rows_written < 0):
        raise ExecutionSafetyError("conditional update rows_written reference is invalid")
    return {"changed_db": True, "changes": 1, "returning_article_id": expected_id, "rows_written_reference": rows_written}


class ExecutionStateMachine:
    """In-memory duplicate/retry barrier; a future DB adapter can replace it."""
    def __init__(self) -> None:
        self._states: Dict[str, str] = {}

    def begin(self, execution_id: str) -> str:
        _require_id(execution_id, "execution_id")
        if execution_id in self._states:
            raise ExecutionSafetyError("execution ID cannot be reused")
        self._states[execution_id] = "planned"
        return "planned"

    def transition(self, execution_id: str, target: str) -> str:
        state = self._states.get(execution_id)
        if state is None or target not in EXECUTION_STATES.get(state, set()):
            raise ExecutionSafetyError("execution state transition is invalid")
        self._states[execution_id] = target
        return target


class AppendOnlyExecutionLedger:
    """Git-external fsync ledger for initial canaries; no plan/recommendation prose."""
    ALLOWED = {"execution_id", "candidate_id", "candidate_fingerprint", "plan_id", "article_id", "approval_id", "state", "at", "result_code", "http_status", "changed_db", "changes", "returning_article_id", "rows_written_reference"}

    def __init__(self, directory: Path, filename: str = "execution-audit.jsonl") -> None:
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(directory, 0o700)
        self.path = directory / filename
        if not self.path.exists():
            fd = os.open(str(self.path), os.O_CREAT | os.O_WRONLY, 0o600); os.close(fd)
        os.chmod(self.path, 0o600)

    def append(self, event: Mapping[str, Any]) -> None:
        if not isinstance(event, Mapping) or set(event) - self.ALLOWED:
            raise ExecutionSafetyError("execution audit event fields are invalid")
        _reject_sensitive(event)
        payload = {"schema_version": EXECUTION_AUDIT_SCHEMA_VERSION, **dict(event)}
        encoded = (_canonical_json(payload) + "\n").encode("utf-8")
        fd = os.open(str(self.path), os.O_WRONLY | os.O_APPEND)
        try:
            os.write(fd, encoded); os.fsync(fd)
        finally:
            os.close(fd)


def build_rollback_candidate(execution_result: Mapping[str, Any]) -> Dict[str, Any]:
    """Interface only; cannot rollback and has no approval path in this module."""
    required = {"execution_id", "candidate_id", "article_id", "before_snapshot_fingerprint", "after_snapshot_fingerprint"}
    if not isinstance(execution_result, Mapping) or not required <= set(execution_result):
        raise ExecutionSafetyError("rollback source is incomplete")
    return {"schema_version": ROLLBACK_CANDIDATE_SCHEMA_VERSION, "execution_id": execution_result["execution_id"],
            "candidate_id": execution_result["candidate_id"], "article_id": execution_result["article_id"],
            "before_snapshot_fingerprint": execution_result["before_snapshot_fingerprint"],
            "after_snapshot_fingerprint": execution_result["after_snapshot_fingerprint"],
            "rollback_authorized": False, "requires_separate_human_approval": True}


def build_v2e_execution_handoff(execution_result: Mapping[str, Any]) -> Dict[str, Any]:
    """Minimal post-application effect-measurement interface only."""
    required = {"execution_id", "article_id", "plan_id", "recommendation_id", "before_snapshot_fingerprint", "after_snapshot_fingerprint", "applied_at", "applied_fields"}
    if not isinstance(execution_result, Mapping) or not required <= set(execution_result):
        raise ExecutionSafetyError("effect handoff source is incomplete")
    return {"schema_version": EFFECT_HANDOFF_SCHEMA_VERSION, **{key: execution_result[key] for key in required},
            "execution_authorized": False}
