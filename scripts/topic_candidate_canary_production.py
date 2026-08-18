"""Local-only, single-use approved-canary production safety primitives.

No API, D1, Worker, publishing, or notification dependency exists here.  The
only transport boundary accepts a minimal ProductionBrief and is intended for
mock verification until a separately approved production integration exists.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Any, Mapping, Protocol, Sequence

from topic_candidate import canonical_json
from topic_candidate_production_input import (
    APPROVED_CONTENT_PRODUCTION_INPUT_SCHEMA_VERSION,
    TopicCandidateProductionInputSafetyError,
    validate_approved_content_production_input,
    validate_content_planning_handoff,
    validate_phase1c_source,
)
from topic_candidate_review import _parse_timestamp, _reject_forbidden


CONTENT_PRODUCTION_APPROVAL_SCHEMA_VERSION = "content-production-approval-v1"
PRODUCTION_EXECUTION_SCHEMA_VERSION = "approved-canary-production-execution-v1"
APPROVED_CANARY_TRIGGER_TYPE = "approved_canary"
CANARY_MAX_ATTEMPTS = 1
_FORBIDDEN_AUDIT_FIELDS = frozenset({"production_brief", "prompt", "raw_response", "raw_ai_response", "content", "body_markdown", "token", "secret", "authorization"})


class CanaryProductionSafetyError(ValueError):
    """The one-shot canary boundary was not safe to cross."""


class TransportTimeout(Exception): pass
class TransportConnectionFailure(Exception): pass
class TransportMalformedResponse(Exception): pass
class TransportProcessInterrupted(Exception): pass


def _safe(callable_, *args, **kwargs):
    try:
        return callable_(*args, **kwargs)
    except (TopicCandidateProductionInputSafetyError, ValueError) as error:
        raise CanaryProductionSafetyError("production_input_integrity_invalid") from error


def production_input_fingerprint(value: Mapping[str, Any]) -> str:
    _safe(validate_approved_content_production_input, value)
    return "production_input_" + sha256(canonical_json(dict(value)).encode("utf-8")).hexdigest()


def deterministic_approval_id(*, production_input_id: str, production_input_fingerprint_value: str, topic_candidate_id: str, human_review_id: str, approved_by: str, approved_at: str, expires_at: str) -> str:
    identity = {"schema_version": CONTENT_PRODUCTION_APPROVAL_SCHEMA_VERSION, "production_input_id": production_input_id, "production_input_fingerprint": production_input_fingerprint_value, "topic_candidate_id": topic_candidate_id, "human_review_id": human_review_id, "approved_by": approved_by, "approved_at": approved_at, "expires_at": expires_at, "single_use": True}
    return "production_approval_" + sha256(canonical_json(identity).encode("utf-8")).hexdigest()[:24]


def deterministic_production_execution_id(*, production_input_id: str, approval_id: str) -> str:
    identity = {"schema_version": PRODUCTION_EXECUTION_SCHEMA_VERSION, "production_input_id": production_input_id, "approval_id": approval_id, "trigger_type": APPROVED_CANARY_TRIGGER_TYPE}
    return "production_execution_" + sha256(canonical_json(identity).encode("utf-8")).hexdigest()[:24]


def build_content_production_approval(production_input: Mapping[str, Any], *, approved_by: str, approved_at: str, expires_at: str, max_ttl_seconds: int | None = None) -> dict[str, Any]:
    fingerprint = production_input_fingerprint(production_input)
    approved, expires = _safe(_parse_timestamp, approved_at), _safe(_parse_timestamp, expires_at)
    if not isinstance(approved_by, str) or not approved_by.strip() or expires <= approved:
        raise CanaryProductionSafetyError("approval_time_or_reviewer_invalid")
    duration = int((expires - approved).total_seconds())
    if max_ttl_seconds is not None and (not isinstance(max_ttl_seconds, int) or max_ttl_seconds < 1 or duration > max_ttl_seconds):
        raise CanaryProductionSafetyError("approval_ttl_invalid")
    approval = {
        "schema_version": CONTENT_PRODUCTION_APPROVAL_SCHEMA_VERSION,
        "approval_id": deterministic_approval_id(production_input_id=production_input["production_input_id"], production_input_fingerprint_value=fingerprint, topic_candidate_id=production_input["topic_candidate_id"], human_review_id=production_input["human_review_id"], approved_by=approved_by, approved_at=approved_at, expires_at=expires_at),
        "production_input_id": production_input["production_input_id"], "production_input_fingerprint": fingerprint,
        "topic_candidate_id": production_input["topic_candidate_id"], "human_review_id": production_input["human_review_id"],
        "approved_by": approved_by, "approved_at": approved_at, "expires_at": expires_at,
        "single_use": True, "ai_generation_authorized": True, "publication_authorized": False, "execution_authorized": True,
    }
    validate_content_production_approval(approval, production_input=production_input, now=approved_at, max_ttl_seconds=max_ttl_seconds)
    return approval


def validate_content_production_approval(approval: Mapping[str, Any], *, production_input: Mapping[str, Any], now: str, max_ttl_seconds: int | None = None) -> None:
    _safe(_reject_forbidden, approval); _safe(validate_approved_content_production_input, production_input)
    required = {"schema_version", "approval_id", "production_input_id", "production_input_fingerprint", "topic_candidate_id", "human_review_id", "approved_by", "approved_at", "expires_at", "single_use", "ai_generation_authorized", "publication_authorized", "execution_authorized"}
    if set(approval) != required or approval.get("schema_version") != CONTENT_PRODUCTION_APPROVAL_SCHEMA_VERSION:
        raise CanaryProductionSafetyError("approval_schema_invalid")
    approved, expires, current = _safe(_parse_timestamp, approval.get("approved_at")), _safe(_parse_timestamp, approval.get("expires_at")), _safe(_parse_timestamp, now)
    if expires <= approved or current > expires:
        raise CanaryProductionSafetyError("approval_expired_or_invalid")
    duration = int((expires - approved).total_seconds())
    if max_ttl_seconds is not None and (not isinstance(max_ttl_seconds, int) or max_ttl_seconds < 1 or duration > max_ttl_seconds):
        raise CanaryProductionSafetyError("approval_ttl_invalid")
    fingerprint = production_input_fingerprint(production_input)
    if any(approval.get(key) != production_input[key] for key in ("production_input_id", "topic_candidate_id", "human_review_id")) or approval.get("production_input_fingerprint") != fingerprint:
        raise CanaryProductionSafetyError("approval_input_mismatch")
    if not isinstance(approval.get("approved_by"), str) or not approval["approved_by"].strip() or approval.get("single_use") is not True or approval.get("ai_generation_authorized") is not True or approval.get("publication_authorized") is not False or approval.get("execution_authorized") is not True:
        raise CanaryProductionSafetyError("approval_authorization_boundary_invalid")
    expected = deterministic_approval_id(production_input_id=approval["production_input_id"], production_input_fingerprint_value=fingerprint, topic_candidate_id=approval["topic_candidate_id"], human_review_id=approval["human_review_id"], approved_by=approval["approved_by"], approved_at=approval["approved_at"], expires_at=approval["expires_at"])
    if approval.get("approval_id") != expected:
        raise CanaryProductionSafetyError("approval_id_invalid")


def build_production_brief(production_input: Mapping[str, Any]) -> dict[str, Any]:
    _safe(validate_approved_content_production_input, production_input)
    brief = {key: production_input[key] for key in ("production_input_id", "topic_candidate_id", "human_review_id", "topic", "title_hint", "primary_intent", "secondary_intents", "target_audience", "problem_to_solve", "related_article_ids", "internal_link_guidance", "quality_threshold_version")}
    brief["cluster_id"] = production_input["cluster"]
    # The brief carries no authority and is intentionally not a persisted audit payload.
    brief["ai_generation_authorized"] = False; brief["publication_authorized"] = False; brief["execution_authorized"] = False
    validate_production_brief(brief)
    return brief


def validate_production_brief(brief: Mapping[str, Any]) -> None:
    _safe(_reject_forbidden, brief)
    required = {"production_input_id", "topic_candidate_id", "human_review_id", "topic", "title_hint", "primary_intent", "secondary_intents", "target_audience", "problem_to_solve", "cluster_id", "related_article_ids", "internal_link_guidance", "quality_threshold_version", "ai_generation_authorized", "publication_authorized", "execution_authorized"}
    if set(brief) != required or any(brief.get(field) is not False for field in ("ai_generation_authorized", "publication_authorized", "execution_authorized")):
        raise CanaryProductionSafetyError("brief_schema_or_authorization_invalid")
    if not all(isinstance(brief.get(key), str) and brief[key] for key in ("production_input_id", "topic_candidate_id", "human_review_id", "topic", "title_hint", "primary_intent", "target_audience", "problem_to_solve", "cluster_id", "quality_threshold_version")):
        raise CanaryProductionSafetyError("brief_identity_invalid")
    if not isinstance(brief.get("secondary_intents"), list) or not isinstance(brief.get("related_article_ids"), list) or not isinstance(brief.get("internal_link_guidance"), Mapping):
        raise CanaryProductionSafetyError("brief_metadata_invalid")


@dataclass(frozen=True)
class ExecutionPolicy:
    trigger_type: str = APPROVED_CANARY_TRIGGER_TYPE
    max_attempts: int = CANARY_MAX_ATTEMPTS

    def __post_init__(self) -> None:
        if self.trigger_type != APPROVED_CANARY_TRIGGER_TYPE or self.max_attempts != CANARY_MAX_ATTEMPTS:
            raise CanaryProductionSafetyError("canary_execution_policy_invalid")


class BriefTransport(Protocol):
    def send(self, brief: Mapping[str, Any]) -> Mapping[str, Any]: ...


class MockBriefTransport:
    """Only accepts a ProductionBrief; injected modes model known outcomes safely."""
    def __init__(self, mode: str = "success") -> None:
        self.mode, self.calls = mode, []

    def send(self, brief: Mapping[str, Any]) -> Mapping[str, Any]:
        validate_production_brief(brief); self.calls.append(dict(brief))
        if self.mode == "success": return {"classification": "success"}
        if self.mode == "known_failure": return {"classification": "known_failure"}
        if self.mode == "timeout": raise TransportTimeout()
        if self.mode == "connection_failure": raise TransportConnectionFailure()
        if self.mode == "malformed_response": return {"unexpected": "value"}
        if self.mode == "process_interrupted": raise TransportProcessInterrupted()
        raise CanaryProductionSafetyError("mock_transport_mode_invalid")


class CanaryAllowlist:
    def __init__(self, production_input_id: str) -> None:
        if not isinstance(production_input_id, str) or not production_input_id:
            raise CanaryProductionSafetyError("canary_allowlist_invalid")
        self.production_input_id = production_input_id

    def require(self, production_input_id: str) -> None:
        if production_input_id != self.production_input_id:
            raise CanaryProductionSafetyError("canary_allowlist_rejected")


class LocalExecutionRegistry:
    """Injectable in-memory registry; production persistence is deliberately absent."""
    def __init__(self) -> None: self._by_execution: dict[str, dict[str, Any]] = {}; self._used_inputs: set[str] = set(); self._used_approvals: set[str] = set()

    def start(self, *, execution_id: str, production_input_id: str, approval_id: str, topic_candidate_id: str, started_at: str) -> None:
        if execution_id in self._by_execution or production_input_id in self._used_inputs or approval_id in self._used_approvals:
            raise CanaryProductionSafetyError("single_use_or_duplicate_execution_rejected")
        self._by_execution[execution_id] = {"production_execution_id": execution_id, "production_input_id": production_input_id, "approval_id": approval_id, "topic_candidate_id": topic_candidate_id, "trigger_type": APPROVED_CANARY_TRIGGER_TYPE, "state": "send_started", "started_at": started_at, "completed_at": None, "classification": "send_started", "pipeline_run_id": None, "final_article_id": None, "quality_gate_audit_id": None, "notification_classification": "not_started"}
        self._used_inputs.add(production_input_id); self._used_approvals.add(approval_id)

    def finish(self, execution_id: str, *, state: str, classification: str, completed_at: str) -> dict[str, Any]:
        record = self._by_execution.get(execution_id)
        if not record or record["state"] != "send_started": raise CanaryProductionSafetyError("execution_state_transition_invalid")
        if state not in {"outcome_known_success", "outcome_known_failed", "outcome_unknown"}: raise CanaryProductionSafetyError("execution_state_transition_invalid")
        record.update(state=state, classification=classification, completed_at=completed_at)
        return dict(record)

    def record(self, execution_id: str) -> Mapping[str, Any] | None:
        record = self._by_execution.get(execution_id); return dict(record) if record else None


def execute_approved_canary(*, candidate: Mapping[str, Any], reviews: Sequence[Mapping[str, Any]], approved_planning: Mapping[str, Any], content_handoff: Mapping[str, Any], production_input: Mapping[str, Any], approval: Mapping[str, Any], allowlist: CanaryAllowlist, registry: LocalExecutionRegistry, transport: BriefTransport, started_at: str, completed_at: str, max_ttl_seconds: int | None = None) -> dict[str, Any]:
    """Validate everything before send; after send_started all outcomes consume single use."""
    _safe(validate_phase1c_source, candidate, reviews, approved_planning)
    _safe(validate_content_planning_handoff, content_handoff)
    _safe(validate_approved_content_production_input, production_input)
    if content_handoff["handoff_id"] != production_input["source_handoff_id"] or content_handoff["topic_candidate_id"] != production_input["topic_candidate_id"] or content_handoff["human_review_id"] != production_input["human_review_id"]:
        raise CanaryProductionSafetyError("handoff_production_input_mismatch")
    _safe(validate_content_production_approval, approval, production_input=production_input, now=started_at, max_ttl_seconds=max_ttl_seconds)
    allowlist.require(production_input["production_input_id"])
    _safe(_parse_timestamp, started_at); _safe(_parse_timestamp, completed_at)
    execution_id = deterministic_production_execution_id(production_input_id=production_input["production_input_id"], approval_id=approval["approval_id"])
    brief = build_production_brief(production_input)
    registry.start(execution_id=execution_id, production_input_id=production_input["production_input_id"], approval_id=approval["approval_id"], topic_candidate_id=production_input["topic_candidate_id"], started_at=started_at)
    try:
        response = transport.send(brief)
        if not isinstance(response, Mapping) or response.get("classification") not in {"success", "known_failure"} or set(response) != {"classification"}:
            raise TransportMalformedResponse()
        if response["classification"] == "success":
            return registry.finish(execution_id, state="outcome_known_success", classification="success", completed_at=completed_at)
        return registry.finish(execution_id, state="outcome_known_failed", classification="known_failure", completed_at=completed_at)
    except (TransportTimeout, TransportConnectionFailure, TransportMalformedResponse, TransportProcessInterrupted):
        return registry.finish(execution_id, state="outcome_unknown", classification="outcome_unknown", completed_at=completed_at)


def validate_production_execution_audit(value: Mapping[str, Any]) -> None:
    _safe(_reject_forbidden, value)
    if any(key.casefold() in _FORBIDDEN_AUDIT_FIELDS for key in value): raise CanaryProductionSafetyError("audit_forbidden_field")
    required = {"production_execution_id", "production_input_id", "approval_id", "topic_candidate_id", "trigger_type", "state", "started_at", "completed_at", "classification", "pipeline_run_id", "final_article_id", "quality_gate_audit_id", "notification_classification"}
    if set(value) != required or value.get("trigger_type") != APPROVED_CANARY_TRIGGER_TYPE:
        raise CanaryProductionSafetyError("audit_schema_invalid")
