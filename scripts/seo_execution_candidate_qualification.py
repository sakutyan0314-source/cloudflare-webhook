"""Fail-closed, zero-write qualification for a first SEO execution candidate.

This module validates the entire human-review chain without opening a D1
transport, reserving an approval, or changing an article.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from search_console_improvement_candidate_review_workflow import latest_review_status as seo_review_status
from seo_improvement_proposal import build_proposal_input, validate_proposal
from seo_improvement_proposal_review_workflow import latest_review_status as proposal_review_status
from seo_improvement_change_plan import build_change_plan_input, validate_change_plan
from seo_improvement_change_plan_review_workflow import latest_review_status as plan_review_status
from seo_improvement_change_candidate import build_change_candidate_input, validate_change_candidate
from seo_improvement_change_candidate_review_workflow import latest_review_status as candidate_review_status
from seo_improvement_execution_candidate import build_execution_candidate_input, validate_execution_candidate
from seo_improvement_execution_approval import validate_execution_approval
from seo_improvement_execution_preflight import build_execution_preflight


QUALIFICATION_SCHEMA_VERSION = "seo-improvement-first-execution-qualification-v1"


class SeoExecutionCandidateQualificationError(ValueError):
    """The supplied candidate has not passed every required review boundary."""


def _same(actual: Mapping[str, Any], expected: Mapping[str, Any], stage: str) -> None:
    if actual != expected:
        raise SeoExecutionCandidateQualificationError(stage + " input does not match its verified source")


def qualify_first_execution_candidate(
    artifacts: Mapping[str, Any],
    *,
    now: str,
    used_approval_ids: Sequence[str] = (),
) -> dict[str, Any]:
    """Return a fresh, non-authorizing preflight only for an accepted full chain."""
    if not isinstance(artifacts, Mapping):
        raise SeoExecutionCandidateQualificationError("qualification artifacts are invalid")
    try:
        envelope = artifacts["envelope"]
        seo_reviews = artifacts["seo_review_records"]
        proposal_input = artifacts["proposal_input"]
        proposal = artifacts["proposal"]
        proposal_reviews = artifacts["proposal_review_records"]
        plan_input = artifacts["plan_input"]
        plan = artifacts["plan"]
        plan_reviews = artifacts["plan_review_records"]
        candidate_input = artifacts["change_candidate_input"]
        candidate = artifacts["change_candidate"]
        candidate_reviews = artifacts["change_candidate_review_records"]
        execution_input = artifacts["execution_candidate_input"]
        execution_candidate = artifacts["execution_candidate"]
        approval = artifacts["execution_approval"]
        latest_snapshot = artifacts["latest_snapshot"]

        if not seo_reviews or seo_review_status(seo_reviews) != "accepted":
            raise SeoExecutionCandidateQualificationError("SEO improvement review is not accepted")
        _same(proposal_input, build_proposal_input(envelope, seo_reviews[-1], model_version=proposal_input["model_version"]), "proposal")
        validate_proposal(proposal, proposal_input)

        if not proposal_reviews or proposal_review_status(proposal_reviews, proposal, proposal_input) != "accepted":
            raise SeoExecutionCandidateQualificationError("proposal review is not accepted")
        _same(plan_input, build_change_plan_input(proposal, proposal_input, proposal_reviews), "change plan")
        validate_change_plan(plan, plan_input)

        if not plan_reviews or plan_review_status(plan_reviews, plan, plan_input) != "accepted":
            raise SeoExecutionCandidateQualificationError("change plan review is not accepted")
        _same(candidate_input, build_change_candidate_input(plan, plan_input, plan_reviews, candidate["before_snapshot"], candidate["proposed_changes"]), "change candidate")
        validate_change_candidate(candidate, candidate_input, current_snapshot=latest_snapshot)

        if not candidate_reviews or candidate_review_status(candidate_reviews, candidate, candidate_input) != "accepted":
            raise SeoExecutionCandidateQualificationError("change candidate review is not accepted")
        _same(execution_input, build_execution_candidate_input(candidate, candidate_input, candidate_reviews), "execution candidate")
        validate_execution_candidate(execution_candidate, execution_input, current_snapshot=latest_snapshot)
        validate_execution_approval(approval, execution_candidate, execution_input, now=now, current_snapshot=latest_snapshot, used_approval_ids=used_approval_ids)
        preflight = build_execution_preflight(approval, execution_candidate, execution_input, latest_snapshot, now=now, used_approval_ids=used_approval_ids)
    except (KeyError, TypeError, ValueError) as error:
        if isinstance(error, SeoExecutionCandidateQualificationError):
            raise
        raise SeoExecutionCandidateQualificationError("qualification failed closed") from error

    return {
        "schema_version": QUALIFICATION_SCHEMA_VERSION,
        "article_id": execution_candidate["article_id"],
        "candidate_fingerprint": execution_candidate["candidate_fingerprint"],
        "execution_candidate_id": execution_candidate["execution_candidate_id"],
        "execution_approval_id": approval["execution_approval_id"],
        "preflight": preflight,
        "changed_db": False,
        "rows_written": 0,
        "approval_consumed": False,
        "status": "qualified",
    }
