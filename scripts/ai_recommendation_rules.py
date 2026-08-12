"""Deterministic safety and eligibility rules for v2.0-A."""

from __future__ import annotations

from typing import Any, Mapping


MIN_OBSERVATION_DAYS = 7
MIN_IMPRESSIONS = 10


class InvalidObservationError(ValueError):
    """Input integrity errors are stop conditions, not recommendations."""


def assess(observation: Mapping[str, Any]) -> dict[str, Any]:
    required = ("impressions", "search_clicks", "affiliate_click_count", "observation_days", "trend")
    if not isinstance(observation, Mapping) or any(key not in observation for key in required):
        raise InvalidObservationError("observation fields are incomplete")
    for key in required[:-1]:
        value = observation[key]
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise InvalidObservationError(f"{key} is invalid")
    if observation["trend"] not in {"growing", "declining", "stable", "insufficient_data"}:
        raise InvalidObservationError("trend is invalid")
    impressions, clicks, affiliate, days = (observation[key] for key in ("impressions", "search_clicks", "affiliate_click_count", "observation_days"))
    if days < MIN_OBSERVATION_DAYS or impressions < MIN_IMPRESSIONS:
        return {"ai_eligible": False, "data_sufficiency": "insufficient_data", "candidate_types": ["insufficient_data"],
                "reasons": ["observation_below_fixed_minimum"]}
    if observation["trend"] == "growing":
        return {"ai_eligible": False, "data_sufficiency": "sufficient", "candidate_types": ["continue_observation"],
                "reasons": ["growing_trend_should_be_observed"]}
    candidates = []
    if observation["trend"] == "declining":
        candidates.append("refresh_content")
    if clicks == 0:
        candidates.extend(["improve_title", "improve_description", "improve_ctr"])
    elif affiliate == 0:
        candidates.append("improve_affiliate_cta")
    else:
        candidates.append("improve_internal_links")
    return {"ai_eligible": True, "data_sufficiency": "sufficient", "candidate_types": candidates,
            "reasons": ["fixed_thresholds_met"]}
