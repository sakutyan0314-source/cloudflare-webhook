"""Local-only persistence for sanitized successful Market Analysis reports."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


LOCAL_REPORT_SCHEMA_VERSION = "market-signal-local-report-v1"


def build_local_market_analysis_report(*, report: Mapping[str, Any], model: str,
                                       serpapi_request_count: int, openai_call_count: int,
                                       usage: Mapping[str, Any] | None) -> dict[str, Any]:
    """Return the allowlisted subset only; never retain SERP rows or provider payloads."""
    own = report["own_site"]
    overlap = own["overlap"]
    safe_usage = usage if isinstance(usage, Mapping) else {}
    details = safe_usage.get("output_tokens_details")
    return {
        "schema_version": LOCAL_REPORT_SCHEMA_VERSION,
        "report_fingerprint": report["report_fingerprint"],
        "query": report["query"],
        "observed_at": report["observed_at"],
        "serp": {"source": report["source"]["provider"],
                 "result_count": report["source"]["returned_results_count"]},
        "market_analysis": {
            "common_intents": list(report["market_analysis"]["common_intents"]),
            "common_angles": list(report["market_analysis"]["common_angles"]),
            "uncovered_questions": list(report["market_analysis"]["uncovered_questions"]),
            "own_site_gap_assessment": _assessment(report),
            "confidence": report["market_analysis"].get("confidence"),
        },
        "own_site_summary": {
            "overlap_classification": overlap["classification"],
            "matched_articles": [{key: item[key] for key in ("article_id", "title", "category")}
                                 for item in overlap["matched_articles"]],
            "search_console": {key: own["search_console_signal"].get(key)
                               for key in ("status", "observation_days", "impressions", "clicks", "ctr")},
            "affiliate": {key: own["affiliate_signal"].get(key)
                          for key in ("article_click_count", "discord_click_count", "usable_click_count", "reliability_status")},
        },
        "candidate_drafts": [dict(item) for item in report["candidate_drafts"]],
        "safety": {key: report[key] for key in ("requires_human_review", "content_generation_authorized",
                                                  "execution_authorized", "publication_authorized")},
        "usage": {
            "model": model,
            "input_tokens": safe_usage.get("input_tokens") if isinstance(safe_usage.get("input_tokens"), int) else None,
            "output_tokens": safe_usage.get("output_tokens") if isinstance(safe_usage.get("output_tokens"), int) else None,
            "reasoning_tokens": details.get("reasoning_tokens") if isinstance(details, Mapping) and isinstance(details.get("reasoning_tokens"), int) else None,
            "serpapi_request_count": serpapi_request_count,
            "openai_call_count": openai_call_count,
        },
    }


def _assessment(report: Mapping[str, Any]) -> dict[str, Any] | None:
    value = report["market_analysis"].get("own_site_gap_assessment")
    if not isinstance(value, Mapping):
        return None
    return {key: value.get(key) for key in ("classification", "rationale")}


def save_local_market_analysis_report(report: Mapping[str, Any], directory: Path, *, now: datetime | None = None) -> Path:
    """Atomically write one report to a caller-provided, gitignored local directory."""
    if not isinstance(report, Mapping) or report.get("schema_version") != LOCAL_REPORT_SCHEMA_VERSION:
        raise ValueError("local_market_analysis_report_invalid")
    fingerprint = report.get("report_fingerprint")
    if not isinstance(fingerprint, str) or not fingerprint.startswith("market_signal_"):
        raise ValueError("local_market_analysis_report_invalid")
    timestamp = (now or datetime.now(timezone.utc)).strftime("%Y%m%dT%H%M%SZ")
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"market-signal-{timestamp}-{fingerprint.removeprefix('market_signal_')}.json"
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
    temporary.replace(path)
    return path


def render_saved_market_analysis_summary(report: Mapping[str, Any], path: Path) -> str:
    analysis = report["market_analysis"]
    usage = report["usage"]
    lines = ["MARKET ANALYSIS: SUCCESS", "", f"Query: {report['query']}",
             "", "Common intents:"]
    lines += [f"- {item}" for item in analysis["common_intents"]]
    lines += ["", "Common angles:"] + [f"- {item}" for item in analysis["common_angles"]]
    lines += ["", "Possible gaps:"] + [f"- {item}" for item in analysis["uncovered_questions"]]
    lines += ["", "Recommended candidates:"]
    for index, candidate in enumerate(report["candidate_drafts"], 1):
        lines += [f"{index}. {candidate['topic']}", f"   reason: {candidate['reason']}",
                  f"   duplicate risk: {candidate['duplicate_risk']}"]
    lines += ["", "Usage:", f"SerpApi: {usage['serpapi_request_count']}",
              f"OpenAI: {usage['openai_call_count']}", f"input tokens: {usage['input_tokens']}",
              f"output tokens: {usage['output_tokens']}", f"reasoning tokens: {usage['reasoning_tokens']}",
              "", f"requires_human_review: {str(report['safety']['requires_human_review']).lower()}",
              "", f"Saved report: {path}"]
    return "\n".join(lines)
