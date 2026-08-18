"""Local-only adapter from approved content planning to a non-public staging draft.

This module is an orchestration seam for the existing Worker production stages.
It has no HTTP route, D1 transport, AI client, Cron hook, publish call, or Discord
client.  Tests inject an in-memory stage runner and isolated SQLite repositories.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol, Sequence

from production_execution_repository import ProductionExecutionRepository
from publication_boundary_repository import PublicationBoundaryRepository, PublicationSafetyError
from topic_candidate_canary_production import (
    APPROVED_CANARY_TRIGGER_TYPE, CANARY_MAX_ATTEMPTS, CanaryAllowlist,
    CanaryProductionSafetyError, TransportConnectionFailure, TransportMalformedResponse,
    TransportProcessInterrupted, TransportTimeout, build_production_brief,
    deterministic_production_execution_id, production_input_fingerprint,
    validate_content_production_approval,
)
from topic_candidate_production_input import validate_approved_content_production_input, validate_content_planning_handoff, validate_phase1c_source


class ApprovedCanaryAdapterSafetyError(ValueError): pass


class ExistingPipelineStages(Protocol):
    def produce(self, brief: Mapping[str, Any], *, max_attempts: int) -> Mapping[str, Any]: ...


class QualityGateSink(Protocol):
    def evaluate(self, *, pipeline_run_id: int, article: Mapping[str, Any], now: str) -> Mapping[str, Any]: ...


@dataclass(frozen=True)
class ApprovedCanaryRequest:
    candidate: Mapping[str, Any]; reviews: Sequence[Mapping[str, Any]]; approved_planning: Mapping[str, Any]
    content_handoff: Mapping[str, Any]; production_input: Mapping[str, Any]; approval: Mapping[str, Any]
    production_execution_id: str; pipeline_run_id: int; started_at: str; completed_at: str


def _validate_request(request: ApprovedCanaryRequest, allowlist: CanaryAllowlist) -> None:
    try:
        validate_phase1c_source(request.candidate, request.reviews, request.approved_planning)
        validate_content_planning_handoff(request.content_handoff)
        validate_approved_content_production_input(request.production_input)
        validate_content_production_approval(request.approval, production_input=request.production_input, now=request.started_at)
    except (CanaryProductionSafetyError, ValueError) as error:
        raise ApprovedCanaryAdapterSafetyError("production_input_integrity_invalid") from error
    source = request.content_handoff
    item = request.production_input
    if source.get("handoff_id") != item.get("source_handoff_id") or source.get("topic_candidate_id") != item.get("topic_candidate_id") or source.get("human_review_id") != item.get("human_review_id"):
        raise ApprovedCanaryAdapterSafetyError("handoff_production_input_mismatch")
    allowlist.require(item["production_input_id"])
    expected = deterministic_production_execution_id(production_input_id=item["production_input_id"], approval_id=request.approval["approval_id"])
    if request.production_execution_id != expected or not isinstance(request.pipeline_run_id, int) or request.pipeline_run_id < 1:
        raise ApprovedCanaryAdapterSafetyError("approved_canary_identity_mismatch")


def _safe_outcome(row: Mapping[str, Any], *, draft_id: str | None = None) -> dict[str, Any]:
    output = {key: row.get(key) for key in ("production_execution_id", "production_input_id", "approval_id", "pipeline_run_id", "quality_gate_audit_id", "state", "classification", "publication_authorized")}
    output["trigger_type"] = APPROVED_CANARY_TRIGGER_TYPE
    output["staging_draft_id"] = draft_id
    return output


class ApprovedCanaryPipelineAdapter:
    """One-shot approved-canary flow; it stops at a non-public staging draft."""
    def __init__(self, execution_repository: ProductionExecutionRepository, publication_repository: PublicationBoundaryRepository, allowlist: CanaryAllowlist, stages: ExistingPipelineStages, quality_gate: QualityGateSink) -> None:
        self.execution_repository, self.publication_repository = execution_repository, publication_repository
        self.allowlist, self.stages, self.quality_gate = allowlist, stages, quality_gate

    def run(self, request: ApprovedCanaryRequest) -> dict[str, Any]:
        _validate_request(request, self.allowlist)
        item, approval = request.production_input, request.approval
        row = self.execution_repository.acquire(
            production_execution_id=request.production_execution_id, production_input_id=item["production_input_id"],
            production_input_fingerprint=production_input_fingerprint(item), approval_id=approval["approval_id"],
            topic_candidate_id=item["topic_candidate_id"], human_review_id=item["human_review_id"], created_at=request.started_at,
            publication_authorized=False,
        )
        row = self.execution_repository.transition(production_execution_id=row["production_execution_id"], expected_state=row["state"], expected_version=row["state_version"], to_state="preflight_verified", occurred_at=request.started_at)
        row = self.execution_repository.link_pipeline_run(production_execution_id=row["production_execution_id"], pipeline_run_id=request.pipeline_run_id, expected_state=row["state"], expected_version=row["state_version"])
        row = self.execution_repository.transition(production_execution_id=row["production_execution_id"], expected_state=row["state"], expected_version=row["state_version"], to_state="approval_verified", occurred_at=request.started_at)
        # This durable transition is the last operation before an injected AI transport.
        row = self.execution_repository.transition(production_execution_id=row["production_execution_id"], expected_state=row["state"], expected_version=row["state_version"], to_state="send_started", occurred_at=request.started_at)
        try:
            article = self.stages.produce(build_production_brief(item), max_attempts=CANARY_MAX_ATTEMPTS)
            if not isinstance(article, Mapping) or set(article) != {"content", "title", "description", "body_markdown", "category", "published_at", "updated_at"}:
                raise TransportMalformedResponse()
        except (TransportTimeout, TransportConnectionFailure, TransportMalformedResponse, TransportProcessInterrupted):
            row = self.execution_repository.transition(production_execution_id=row["production_execution_id"], expected_state="send_started", expected_version=row["state_version"], to_state="outcome_unknown", classification="outcome_unknown", reason_code="outcome_unknown_requires_review", occurred_at=request.completed_at)
            return _safe_outcome(row)
        except Exception:
            row = self.execution_repository.transition(production_execution_id=row["production_execution_id"], expected_state="send_started", expected_version=row["state_version"], to_state="outcome_known_failed", classification="known_failure", reason_code="transport_known_failure", occurred_at=request.completed_at)
            return _safe_outcome(row)
        quality = self.quality_gate.evaluate(pipeline_run_id=request.pipeline_run_id, article=article, now=request.completed_at)
        if not isinstance(quality, Mapping) or set(quality) != {"classification", "audit_id"} or quality.get("classification") != "pass" or not isinstance(quality.get("audit_id"), str):
            row = self.execution_repository.transition(production_execution_id=row["production_execution_id"], expected_state="send_started", expected_version=row["state_version"], to_state="outcome_known_failed", classification="known_failure", reason_code="transport_known_failure", occurred_at=request.completed_at)
            return _safe_outcome(row)
        row = self.execution_repository.link_quality_gate_audit(production_execution_id=row["production_execution_id"], quality_gate_audit_id=quality["audit_id"], expected_state="send_started", expected_version=row["state_version"])
        try:
            draft = self.publication_repository.create_staging_draft(staging_draft_id="staging_" + row["production_execution_id"], production_execution_id=row["production_execution_id"], production_input_id=item["production_input_id"], topic_candidate_id=item["topic_candidate_id"], quality_gate_audit_id=quality["audit_id"], content=article["content"], title=article["title"], description=article["description"], body_markdown=article["body_markdown"], category=article["category"], published_at_candidate=article["published_at"], updated_at_candidate=article["updated_at"], created_at=request.completed_at)
        except PublicationSafetyError as error:
            raise ApprovedCanaryAdapterSafetyError("staging_draft_write_failed") from error
        row = self.execution_repository.transition(production_execution_id=row["production_execution_id"], expected_state="send_started", expected_version=row["state_version"], to_state="outcome_known_success", classification="success", occurred_at=request.completed_at)
        return _safe_outcome(row, draft_id=draft["staging_draft_id"])
