"""Immutable persistence primitive for an already-approved canary chain.

This module adds no approval decision.  It validates existing Phase 1A/1B/1C
schemas before constructing a content-free snapshot suitable for D1 storage.
"""
from __future__ import annotations

from hashlib import sha256
import sqlite3
from typing import Any, Mapping, Sequence

from topic_candidate import canonical_json
from topic_candidate_canary_production import (
    CanaryProductionSafetyError, deterministic_production_execution_id,
    validate_content_production_approval,
)
from topic_candidate_production_input import (
    TopicCandidateProductionInputSafetyError, validate_approved_content_production_input,
    validate_content_planning_handoff, validate_phase1c_source,
)

BUNDLE_SCHEMA_VERSION = "approved-content-production-authorization-bundle-v1"
_FORBIDDEN = frozenset({"content", "body_markdown", "prompt", "token", "secret", "authorization", "api_key", "raw_response"})


class ApprovedContentAuthorizationBundleError(ValueError):
    pass


def _reject(value: Any) -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if not isinstance(key, str) or key.casefold() in _FORBIDDEN:
                raise ApprovedContentAuthorizationBundleError("forbidden_snapshot_field")
            _reject(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            _reject(child)


def _fingerprint(value: Mapping[str, Any]) -> str:
    return "authorization_bundle_" + sha256(canonical_json(dict(value)).encode("utf-8")).hexdigest()


def build_authorization_bundle(*, candidate: Mapping[str, Any], reviews: Sequence[Mapping[str, Any]], approved_planning: Mapping[str, Any], content_handoff: Mapping[str, Any], production_input: Mapping[str, Any], approval: Mapping[str, Any], created_at: str, max_ttl_seconds: int | None = None) -> dict[str, Any]:
    """Validate the complete existing chain, then snapshot it immutably."""
    try:
        validate_phase1c_source(candidate, reviews, approved_planning)
        validate_content_planning_handoff(content_handoff)
        validate_approved_content_production_input(production_input)
        validate_content_production_approval(approval, production_input=production_input, now=approval["approved_at"], max_ttl_seconds=max_ttl_seconds)
    except (CanaryProductionSafetyError, TopicCandidateProductionInputSafetyError, ValueError, KeyError) as error:
        raise ApprovedContentAuthorizationBundleError("source_integrity_invalid") from error
    if content_handoff.get("handoff_id") != production_input.get("source_handoff_id") or content_handoff.get("topic_candidate_id") != production_input.get("topic_candidate_id") or content_handoff.get("human_review_id") != production_input.get("human_review_id"):
        raise ApprovedContentAuthorizationBundleError("handoff_identity_mismatch")
    if approval.get("topic_candidate_id") != candidate.get("topic_candidate_id") or approval.get("human_review_id") != reviews[-1].get("review_id"):
        raise ApprovedContentAuthorizationBundleError("approval_identity_mismatch")
    snapshots = {
        "candidate_snapshot": dict(candidate), "review_snapshot": dict(reviews[-1]),
        "approved_planning_snapshot": dict(approved_planning), "content_handoff_snapshot": dict(content_handoff),
        "production_input_snapshot": dict(production_input), "approval_snapshot": dict(approval),
    }
    _reject(snapshots)
    identity = {
        "schema_version": BUNDLE_SCHEMA_VERSION, "topic_candidate_id": candidate["topic_candidate_id"],
        "review_id": reviews[-1]["review_id"], "production_input_id": production_input["production_input_id"],
        "production_approval_id": approval["approval_id"], "production_execution_id": deterministic_production_execution_id(production_input_id=production_input["production_input_id"], approval_id=approval["approval_id"]),
        "cluster_id": production_input["cluster"], "approved_at": approval["approved_at"], "expires_at": approval["expires_at"], "single_use": True,
        **snapshots,
    }
    fingerprint = _fingerprint(identity)
    return {
        "schema_version": BUNDLE_SCHEMA_VERSION,
        "authorization_bundle_id": "bundle_" + fingerprint.rsplit("_", 1)[-1][:24],
        **identity,
        "bundle_fingerprint": fingerprint, "created_at": created_at,
    }


def bundle_insert_values(bundle: Mapping[str, Any]) -> tuple[Any, ...]:
    required = {"schema_version", "authorization_bundle_id", "topic_candidate_id", "review_id", "production_input_id", "production_approval_id", "production_execution_id", "cluster_id", "approved_at", "expires_at", "single_use", "candidate_snapshot", "review_snapshot", "approved_planning_snapshot", "content_handoff_snapshot", "production_input_snapshot", "approval_snapshot", "bundle_fingerprint", "created_at"}
    if set(bundle) != required or bundle.get("schema_version") != BUNDLE_SCHEMA_VERSION or bundle.get("single_use") is not True:
        raise ApprovedContentAuthorizationBundleError("bundle_schema_invalid")
    return tuple(bundle[key] if key not in {"single_use", "candidate_snapshot", "review_snapshot", "approved_planning_snapshot", "content_handoff_snapshot", "production_input_snapshot", "approval_snapshot"} else (1 if key == "single_use" else canonical_json(bundle[key])) for key in ("authorization_bundle_id", "schema_version", "topic_candidate_id", "review_id", "production_input_id", "production_approval_id", "production_execution_id", "cluster_id", "approved_at", "expires_at", "single_use", "candidate_snapshot", "review_snapshot", "approved_planning_snapshot", "content_handoff_snapshot", "production_input_snapshot", "approval_snapshot", "bundle_fingerprint", "created_at"))


class AuthorizationBundleRepository:
    """Fixed INSERT/SELECT interface; no update or delete is available."""
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def insert(self, bundle: Mapping[str, Any]) -> None:
        values = bundle_insert_values(bundle)
        try:
            with self.connection:
                self.connection.execute("INSERT INTO approved_content_authorization_bundles (authorization_bundle_id,schema_version,topic_candidate_id,review_id,production_input_id,production_approval_id,production_execution_id,cluster_id,approved_at,expires_at,single_use,candidate_snapshot_json,review_snapshot_json,approved_planning_snapshot_json,content_handoff_snapshot_json,production_input_snapshot_json,approval_snapshot_json,bundle_fingerprint,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", values)
        except sqlite3.IntegrityError as error:
            raise ApprovedContentAuthorizationBundleError("immutable_bundle_insert_rejected") from error
