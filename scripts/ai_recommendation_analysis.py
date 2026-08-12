"""Orchestration-only v2.0-A analysis.  No D1, file, Worker, or model SDK I/O."""

from __future__ import annotations

from typing import Any, Mapping

from ai_recommendation_rules import assess
from ai_recommendation_schema import INPUT_SCHEMA_VERSION, build_recommendation, validate_input


def build_input(article: Mapping[str, Any], observation: Mapping[str, Any]) -> dict[str, Any]:
    """Build deterministic input, including rule output from normalized observation."""
    payload = {"schema_version": INPUT_SCHEMA_VERSION, "article": dict(article), "observation": dict(observation),
               "rule_assessment": assess(observation)}
    return validate_input(payload)


def analyze(article: Mapping[str, Any], observation: Mapping[str, Any], adapter: Any | None = None, *, generated_at: str | None = None) -> dict[str, Any]:
    """Return a proposal; data insufficiency never calls the supplied adapter."""
    payload = build_input(article, observation)
    ai_response = adapter.recommend(payload) if payload["rule_assessment"]["ai_eligible"] and adapter is not None else None
    return build_recommendation(payload, ai_response, generated_at)
