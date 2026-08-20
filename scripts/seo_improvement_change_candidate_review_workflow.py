"""Pure append-only human-review records for SEO change candidates."""

from __future__ import annotations

from datetime import datetime
from hashlib import sha256
import json
import re
from typing import Any, Mapping, Sequence

from seo_improvement_change_candidate import SeoImprovementChangeCandidateError, validate_change_candidate

REVIEW_RECORD_SCHEMA_VERSION = "seo-improvement-change-candidate-review-record-v1"
REVIEW_STATUSES = frozenset({"pending_review", "accepted", "rejected", "deferred"})
_REASONS = {"pending_review": frozenset({"candidate_created"}), "accepted": frozenset({"execution_candidate_creation_approved"}), "rejected": frozenset({"candidate_not_selected"}), "deferred": frozenset({"candidate_deferred"})}
_REVIEWER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_SOURCE = ("candidate_id", "candidate_fingerprint", "article_id", "accepted_review_id", "proposal_id", "proposal_fingerprint", "accepted_proposal_review_id", "plan_id", "plan_fingerprint", "accepted_plan_review_id")
_FIELDS = frozenset({"schema_version", "candidate_review_id", *_SOURCE, "status", "reviewer_id", "reviewed_at", "review_reason_code", "previous_review_id", "article_change_authorized", "publication_authorized", "execution_authorized"})

class SeoImprovementChangeCandidateReviewError(ValueError):
    """Candidate review data violates the fixed non-execution boundary."""

def _json(value: Mapping[str, Any]) -> str:
    try: return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as error: raise SeoImprovementChangeCandidateReviewError("candidate review cannot be canonically encoded") from error

def validate_status(value: object) -> str:
    if not isinstance(value, str) or value not in REVIEW_STATUSES: raise SeoImprovementChangeCandidateReviewError("candidate review status is invalid")
    return value

def _time(value: object) -> str:
    if not isinstance(value, str): raise SeoImprovementChangeCandidateReviewError("reviewed_at is invalid")
    try: datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error: raise SeoImprovementChangeCandidateReviewError("reviewed_at is invalid") from error
    return value

def _source(candidate: Mapping[str, Any]) -> dict[str, Any]: return {key: candidate[key] for key in _SOURCE}
def _review_id(record: Mapping[str, Any]) -> str:
    source={key:record[key] for key in ("schema_version", *_SOURCE, "status", "reviewer_id", "reviewed_at", "previous_review_id")}
    return "seo_change_candidate_review_"+sha256(_json(source).encode()).hexdigest()[:24]

def build_review_record(candidate: Mapping[str, Any], candidate_input: Mapping[str, Any], decision: Mapping[str, Any]) -> dict[str, Any]:
    try: validate_change_candidate(candidate, candidate_input)
    except SeoImprovementChangeCandidateError as error: raise SeoImprovementChangeCandidateReviewError("change candidate is invalid") from error
    if not isinstance(decision, Mapping): raise SeoImprovementChangeCandidateReviewError("candidate review decision is invalid")
    for key,value in _source(candidate).items():
        if decision.get(key)!=value: raise SeoImprovementChangeCandidateReviewError(f"candidate review {key} does not match candidate")
    status=validate_status(decision.get("status")); reviewer=decision.get("reviewer_id")
    if not isinstance(reviewer,str) or not _REVIEWER.fullmatch(reviewer): raise SeoImprovementChangeCandidateReviewError("candidate reviewer ID is invalid")
    if decision.get("review_reason_code") not in _REASONS[status]: raise SeoImprovementChangeCandidateReviewError("candidate review reason code is invalid")
    previous=decision.get("previous_review_id")
    if previous is not None and (not isinstance(previous,str) or not previous): raise SeoImprovementChangeCandidateReviewError("previous candidate review ID is invalid")
    record={"schema_version":REVIEW_RECORD_SCHEMA_VERSION,**_source(candidate),"status":status,"reviewer_id":reviewer,"reviewed_at":_time(decision.get("reviewed_at")),"review_reason_code":decision["review_reason_code"],"previous_review_id":previous,"article_change_authorized":False,"publication_authorized":False,"execution_authorized":False}
    record["candidate_review_id"]=_review_id(record);return record

def validate_review_record(record: Mapping[str, Any], candidate: Mapping[str, Any], candidate_input: Mapping[str, Any]) -> None:
    if not isinstance(record,Mapping) or set(record)!=_FIELDS or record.get("schema_version")!=REVIEW_RECORD_SCHEMA_VERSION: raise SeoImprovementChangeCandidateReviewError("candidate review record schema is invalid")
    try: validate_change_candidate(candidate,candidate_input)
    except SeoImprovementChangeCandidateError as error: raise SeoImprovementChangeCandidateReviewError("change candidate is invalid") from error
    for key,value in _source(candidate).items():
        if record.get(key)!=value: raise SeoImprovementChangeCandidateReviewError(f"candidate review {key} is invalid")
    status=validate_status(record.get("status"))
    if record.get("review_reason_code") not in _REASONS[status]: raise SeoImprovementChangeCandidateReviewError("candidate review reason code is invalid")
    if not isinstance(record.get("reviewer_id"),str) or not _REVIEWER.fullmatch(record["reviewer_id"]): raise SeoImprovementChangeCandidateReviewError("candidate reviewer ID is invalid")
    _time(record.get("reviewed_at")); previous=record.get("previous_review_id")
    if previous is not None and (not isinstance(previous,str) or not previous): raise SeoImprovementChangeCandidateReviewError("previous candidate review ID is invalid")
    if record.get("candidate_review_id")!=_review_id(record): raise SeoImprovementChangeCandidateReviewError("candidate review ID is invalid")
    if any(record.get(key) is not False for key in ("article_change_authorized","publication_authorized","execution_authorized")): raise SeoImprovementChangeCandidateReviewError("candidate review authorization boundary is invalid")

def append_review_record(records: Sequence[Mapping[str, Any]], record: Mapping[str, Any], candidate: Mapping[str, Any], candidate_input: Mapping[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(records,Sequence) or isinstance(records,(str,bytes,bytearray)): raise SeoImprovementChangeCandidateReviewError("candidate review records are invalid")
    copied=[dict(item) for item in records]
    for index,item in enumerate(copied):
        validate_review_record(item,candidate,candidate_input)
        if index==0 and item["previous_review_id"] is not None: raise SeoImprovementChangeCandidateReviewError("initial candidate review cannot supersede another review")
        if index and item["previous_review_id"]!=copied[index-1]["candidate_review_id"]: raise SeoImprovementChangeCandidateReviewError("candidate review chain is invalid")
    validate_review_record(record,candidate,candidate_input)
    if copied:
        if record["previous_review_id"]!=copied[-1]["candidate_review_id"]: raise SeoImprovementChangeCandidateReviewError("candidate review is not appended after latest")
    elif record["previous_review_id"] is not None: raise SeoImprovementChangeCandidateReviewError("initial candidate review cannot supersede another review")
    if any(item["candidate_review_id"]==record["candidate_review_id"] for item in copied): raise SeoImprovementChangeCandidateReviewError("duplicate candidate review record")
    return [*copied,dict(record)]

def latest_review_status(records: Sequence[Mapping[str, Any]], candidate: Mapping[str, Any], candidate_input: Mapping[str, Any]) -> str|None:
    if not records:return None
    return append_review_record(records[:-1],records[-1],candidate,candidate_input)[-1]["status"]
