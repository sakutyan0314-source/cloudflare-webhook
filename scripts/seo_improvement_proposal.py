"""Provider-free Phase 2B proposal input and output safety boundary.

No API, D1, file, article, publication, or execution operation is available
here.  The only AI-shaped input is a supplied mock response, validated into a
non-executable improvement proposal.
"""

from __future__ import annotations

from hashlib import sha256
import json
import re
from typing import Any, Mapping, Sequence

from search_console_improvement_candidate_review import REVIEW_SCHEMA_VERSION, candidate_fingerprint
from search_console_improvement_candidate_review_workflow import (
    REVIEW_RECORD_SCHEMA_VERSION,
    SeoImprovementReviewWorkflowError,
    validate_review_record,
)


PROPOSAL_INPUT_SCHEMA_VERSION = "seo-improvement-proposal-input-v1"
PROPOSAL_SCHEMA_VERSION = "seo-improvement-proposal-v1"
UNBOUND_MODEL_VERSION = "unbound"
RISK_LEVELS = frozenset({"low", "medium", "high"})
CHANGE_SCOPES = frozenset({"snippet", "content_refresh", "internal_link_direction"})
_SECRET_KEY = re.compile(r"(?:raw_?response|authorization|api[_ -]?key|private[_ -]?key|secret|token|binding)", re.IGNORECASE)
_SECRET_VALUE = re.compile(r"(?:api[_ -]?key|authorization|bearer\s+|private[_ -]?key|token)\s*[:=]", re.IGNORECASE)
_ENVELOPE_FIELDS = frozenset({
    "schema_version", "status", "article_id", "title", "category",
    "recommendation_type", "reason_code", "current_metrics", "previous_metrics",
    "evidence", "requires_human_review", "candidate_fingerprint",
})
_INPUT_FIELDS = frozenset({
    "schema_version", "article_id", "candidate_fingerprint", "accepted_review_id",
    "reason_code", "article_context", "evidence_summary", "proposal_version", "model_version",
})
_PROPOSAL_FIELDS = frozenset({
    "schema_version", "proposal_id", "article_id", "candidate_fingerprint", "accepted_review_id",
    "evidence_summary", "improvement_hypothesis", "proposed_changes", "expected_impact", "risk",
    "requires_human_review", "article_change_authorized", "publication_authorized",
    "execution_authorized", "proposal_version", "model_version",
})


class SeoImprovementProposalError(ValueError):
    """A proposal input or output is unsafe, stale, or malformed."""


def _canonical_json(value: Mapping[str, Any]) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as error:
        raise SeoImprovementProposalError("proposal cannot be canonically encoded") from error


def _reject_sensitive(value: Any) -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if not isinstance(key, str) or _SECRET_KEY.search(key):
                raise SeoImprovementProposalError("proposal contains prohibited sensitive data")
            _reject_sensitive(child)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for child in value:
            _reject_sensitive(child)
    elif isinstance(value, str) and _SECRET_VALUE.search(value):
        raise SeoImprovementProposalError("proposal contains prohibited sensitive data")


def _valid_text(value: object, minimum: int, maximum: int) -> bool:
    return isinstance(value, str) and minimum <= len(value.strip()) <= maximum


def _validate_envelope(envelope: Mapping[str, Any]) -> None:
    if not isinstance(envelope, Mapping) or set(envelope) != _ENVELOPE_FIELDS:
        raise SeoImprovementProposalError("review envelope fields are invalid")
    if envelope.get("schema_version") != REVIEW_SCHEMA_VERSION or envelope.get("status") != "pending_review":
        raise SeoImprovementProposalError("review envelope is not Phase 2A.5 pending output")
    if not isinstance(envelope.get("article_id"), int) or envelope["article_id"] < 1:
        raise SeoImprovementProposalError("review envelope article ID is invalid")
    if not isinstance(envelope.get("candidate_fingerprint"), str) or len(envelope["candidate_fingerprint"]) != 64 or envelope["candidate_fingerprint"] != candidate_fingerprint(envelope):
        raise SeoImprovementProposalError("review envelope fingerprint is invalid")
    if not _valid_text(envelope.get("title"), 1, 300) or not _valid_text(envelope.get("category"), 1, 100):
        raise SeoImprovementProposalError("review envelope metadata is invalid")
    if envelope.get("requires_human_review") is not True:
        raise SeoImprovementProposalError("review envelope is not human-review-only")
    _reject_sensitive(envelope)


def build_proposal_input(envelope: Mapping[str, Any], accepted_review: Mapping[str, Any], *, model_version: str = UNBOUND_MODEL_VERSION) -> dict[str, Any]:
    """Build the exact, content-free input allowed for a future proposal model."""
    _validate_envelope(envelope)
    try:
        validate_review_record(accepted_review)
    except SeoImprovementReviewWorkflowError as error:
        raise SeoImprovementProposalError("accepted review record is invalid") from error
    if accepted_review.get("schema_version") != REVIEW_RECORD_SCHEMA_VERSION or accepted_review.get("status") != "accepted":
        raise SeoImprovementProposalError("only accepted review records can build a proposal input")
    for field, envelope_value, review_value in (
        ("article_id", envelope["article_id"], accepted_review["article_id"]),
        ("candidate_fingerprint", envelope["candidate_fingerprint"], accepted_review["candidate_fingerprint"]),
        ("reason_code", envelope["reason_code"], accepted_review["candidate_reason_code"]),
    ):
        if envelope_value != review_value:
            raise SeoImprovementProposalError(f"accepted review {field} does not match envelope")
    if not isinstance(model_version, str) or not model_version or len(model_version) > 160:
        raise SeoImprovementProposalError("model version is invalid")
    evidence = envelope.get("evidence")
    if not isinstance(evidence, Mapping) or set(evidence) != {"current_period", "previous_period", "delta", "data_status"}:
        raise SeoImprovementProposalError("review envelope evidence is invalid")
    output = {
        "schema_version": PROPOSAL_INPUT_SCHEMA_VERSION,
        "article_id": envelope["article_id"],
        "candidate_fingerprint": envelope["candidate_fingerprint"],
        "accepted_review_id": accepted_review["review_id"],
        "reason_code": envelope["reason_code"],
        "article_context": {"title": envelope["title"], "category": envelope["category"]},
        "evidence_summary": {"reason_code": envelope["reason_code"], **{key: evidence[key] for key in ("current_period", "previous_period", "delta", "data_status")}},
        "proposal_version": PROPOSAL_SCHEMA_VERSION,
        "model_version": model_version,
    }
    _reject_sensitive(output)
    return output


def _validate_input(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != _INPUT_FIELDS or value.get("schema_version") != PROPOSAL_INPUT_SCHEMA_VERSION:
        raise SeoImprovementProposalError("proposal input schema is invalid")
    if not isinstance(value.get("article_id"), int) or value["article_id"] < 1 or not isinstance(value.get("candidate_fingerprint"), str) or len(value["candidate_fingerprint"]) != 64:
        raise SeoImprovementProposalError("proposal input identity is invalid")
    if not _valid_text(value.get("accepted_review_id"), 1, 200) or not _valid_text(value.get("reason_code"), 1, 100):
        raise SeoImprovementProposalError("proposal input review identity is invalid")
    if value.get("proposal_version") != PROPOSAL_SCHEMA_VERSION or not _valid_text(value.get("model_version"), 1, 160):
        raise SeoImprovementProposalError("proposal input version is invalid")
    _reject_sensitive(value)
    return dict(value)


def _validate_mock_response(response: Mapping[str, Any]) -> dict[str, Any]:
    required = {"improvement_hypothesis", "proposed_changes", "expected_impact", "risk"}
    if not isinstance(response, Mapping) or set(response) != required:
        raise SeoImprovementProposalError("mock proposal response fields are invalid")
    if not _valid_text(response.get("improvement_hypothesis"), 8, 500) or not _valid_text(response.get("expected_impact"), 8, 500) or response.get("risk") not in RISK_LEVELS:
        raise SeoImprovementProposalError("mock proposal response is invalid")
    changes = response.get("proposed_changes")
    if not isinstance(changes, list) or not 1 <= len(changes) <= 3:
        raise SeoImprovementProposalError("mock proposed changes are invalid")
    safe_changes = []
    for change in changes:
        if not isinstance(change, Mapping) or set(change) != {"scope", "rationale", "suggested_direction"} or change.get("scope") not in CHANGE_SCOPES or not _valid_text(change.get("rationale"), 4, 400) or not _valid_text(change.get("suggested_direction"), 4, 400):
            raise SeoImprovementProposalError("mock proposed change is invalid")
        safe_changes.append(dict(change))
    output = {"improvement_hypothesis": response["improvement_hypothesis"].strip(), "proposed_changes": safe_changes, "expected_impact": response["expected_impact"].strip(), "risk": response["risk"]}
    _reject_sensitive(output)
    return output


def _proposal_id(proposal: Mapping[str, Any]) -> str:
    identity = {key: proposal[key] for key in proposal if key != "proposal_id"}
    return "seo_proposal_" + sha256(_canonical_json(identity).encode("utf-8")).hexdigest()[:24]


def build_mock_proposal(proposal_input: Mapping[str, Any], mock_response: Mapping[str, Any]) -> dict[str, Any]:
    """Validate a mock-only response as a non-executable proposal; no provider call."""
    safe_input, safe_response = _validate_input(proposal_input), _validate_mock_response(mock_response)
    proposal = {
        "schema_version": PROPOSAL_SCHEMA_VERSION,
        "article_id": safe_input["article_id"], "candidate_fingerprint": safe_input["candidate_fingerprint"],
        "accepted_review_id": safe_input["accepted_review_id"], "evidence_summary": safe_input["evidence_summary"],
        **safe_response, "requires_human_review": True, "article_change_authorized": False,
        "publication_authorized": False, "execution_authorized": False,
        "proposal_version": safe_input["proposal_version"], "model_version": safe_input["model_version"],
    }
    proposal["proposal_id"] = _proposal_id(proposal)
    return proposal


def validate_proposal(proposal: Mapping[str, Any], proposal_input: Mapping[str, Any]) -> None:
    """Fail closed unless the proposal exactly reflects its verified input."""
    safe_input = _validate_input(proposal_input)
    if not isinstance(proposal, Mapping) or set(proposal) != _PROPOSAL_FIELDS or proposal.get("schema_version") != PROPOSAL_SCHEMA_VERSION:
        raise SeoImprovementProposalError("proposal schema is invalid")
    for key in ("article_id", "candidate_fingerprint", "accepted_review_id", "evidence_summary", "proposal_version", "model_version"):
        if proposal.get(key) != safe_input[key]:
            raise SeoImprovementProposalError(f"proposal {key} does not match input")
    _validate_mock_response({key: proposal.get(key) for key in ("improvement_hypothesis", "proposed_changes", "expected_impact", "risk")})
    if proposal.get("requires_human_review") is not True or any(proposal.get(key) is not False for key in ("article_change_authorized", "publication_authorized", "execution_authorized")):
        raise SeoImprovementProposalError("proposal authorization boundary is invalid")
    _reject_sensitive(proposal)
    if proposal.get("proposal_id") != _proposal_id(proposal):
        raise SeoImprovementProposalError("proposal identity is invalid")
