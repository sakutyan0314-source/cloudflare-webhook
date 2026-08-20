"""Pure Phase 2A.5 review envelopes for Phase 2A SEO candidates.

This module deliberately does not analyse Search Console data, call D1, or
persist a decision.  It only joins already-produced Phase 2A candidates to
the existing ready-article metadata supplied by the fixed read-only reader.
"""

from __future__ import annotations

from hashlib import sha256
import json
from typing import Any, Mapping, Sequence


REVIEW_SCHEMA_VERSION = "phase-2a-improvement-candidate-review-v1"
CANDIDATE_SCHEMA_VERSION = "phase-2a-improvement-candidates-v1"
REVIEW_STATUS = "pending_review"
RECOMMENDATION_TYPE = "seo_review"
_KNOWN_CANDIDATES = {
    "position_opportunity_with_low_ctr": "improve_ctr",
    "clicks_and_impressions_declined": "refresh_content",
    "impressions_with_zero_clicks": "improve_snippet",
}
KNOWN_CANDIDATE_REASON_CODES = frozenset(_KNOWN_CANDIDATES)
_METRIC_FIELDS = ("clicks", "impressions", "ctr", "position")
_DELTA_FIELDS = ("clicks_delta", "impressions_delta", "ctr_delta", "position_delta")


class ImprovementCandidateReviewError(ValueError):
    """Phase 2A candidate or metadata did not meet the review contract."""


def _canonical_json(value: Mapping[str, Any]) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as error:
        raise ImprovementCandidateReviewError("review envelope cannot be canonically encoded") from error


def _valid_text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _number(value: object, field: str) -> int | float | None:
    if value is None and field in {"ctr", "position"}:
        return None
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ImprovementCandidateReviewError(f"{field} is invalid")
    return value


def _metadata_by_article(article_rows: Sequence[Mapping[str, Any]]) -> dict[int, Mapping[str, Any]]:
    output: dict[int, Mapping[str, Any]] = {}
    for row in article_rows:
        article_id = row.get("article_id")
        if (
            isinstance(article_id, int)
            and article_id > 0
            and article_id not in output
            and row.get("seo_status") == "ready"
            and _valid_text(row.get("title"))
            and _valid_text(row.get("category"))
        ):
            output[article_id] = row
    return output


def _period(candidate: Mapping[str, Any], prefix: str) -> dict[str, Any]:
    start, end = candidate.get(f"{prefix}_period_start"), candidate.get(f"{prefix}_period_end")
    if not _valid_text(start) or not _valid_text(end):
        raise ImprovementCandidateReviewError("candidate period is invalid")
    return {
        "start": start,
        "end": end,
        **{field: _number(candidate.get(f"{prefix}_{field}"), field) for field in _METRIC_FIELDS},
    }


def _evidence(candidate: Mapping[str, Any], current: Mapping[str, Any], previous: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "current_period": dict(current),
        "previous_period": dict(previous),
        "delta": {field.removesuffix("_delta"): _number(candidate.get(field), field.removesuffix("_delta")) for field in _DELTA_FIELDS},
        "data_status": "sufficient",
    }


def _candidate_is_reviewable(candidate: Mapping[str, Any]) -> bool:
    article_id = candidate.get("article_id")
    return (
        candidate.get("is_candidate") is True
        and candidate.get("data_status") == "sufficient"
        and isinstance(article_id, int)
        and article_id > 0
        and _KNOWN_CANDIDATES.get(candidate.get("reason_code")) == candidate.get("recommendation_type")
    )


def _fingerprint_input(envelope: Mapping[str, Any]) -> dict[str, Any]:
    return {key: envelope[key] for key in envelope if key != "candidate_fingerprint"}


def candidate_fingerprint(envelope: Mapping[str, Any]) -> str:
    """Return the deterministic SHA-256 identity of a fixed review envelope."""
    return sha256(_canonical_json(_fingerprint_input(envelope)).encode("utf-8")).hexdigest()


def build_review_envelopes(candidate_report: Mapping[str, Any], article_rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Build pending human-review envelopes from a Phase 2A report, with no I/O.

    Non-candidates and malformed, stale, or incomplete records are excluded
    fail-closed.  Phase 2A remains the sole owner of candidate classification.
    """
    if candidate_report.get("schema_version") != CANDIDATE_SCHEMA_VERSION:
        raise ImprovementCandidateReviewError("candidate report schema is invalid")
    candidates = candidate_report.get("candidates")
    if not isinstance(candidates, Sequence) or isinstance(candidates, (str, bytes, bytearray)):
        raise ImprovementCandidateReviewError("candidate report candidates are invalid")
    metadata = _metadata_by_article(article_rows)
    envelopes: list[dict[str, Any]] = []
    seen: set[int] = set()
    for candidate in candidates:
        if not isinstance(candidate, Mapping) or not _candidate_is_reviewable(candidate):
            continue
        article_id = candidate["article_id"]
        if article_id in seen or article_id not in metadata:
            continue
        try:
            current, previous = _period(candidate, "current"), _period(candidate, "previous")
            row = metadata[article_id]
            envelope = {
                "schema_version": REVIEW_SCHEMA_VERSION,
                "status": REVIEW_STATUS,
                "article_id": article_id,
                "title": row["title"].strip(),
                "category": row["category"].strip(),
                "recommendation_type": RECOMMENDATION_TYPE,
                "reason_code": candidate["reason_code"],
                "current_metrics": current,
                "previous_metrics": previous,
                "evidence": _evidence(candidate, current, previous),
                "requires_human_review": True,
            }
        except ImprovementCandidateReviewError:
            continue
        envelope["candidate_fingerprint"] = candidate_fingerprint(envelope)
        envelopes.append(envelope)
        seen.add(article_id)
    return envelopes
