"""Pure v1 Market Signal report.  It cannot authorize or generate content."""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date
from hashlib import sha256
import json
import re
from typing import Any, Mapping, Sequence

from search_console_improvement_candidates import MIN_IMPRESSIONS, MIN_OBSERVATION_DAYS
from topic_candidate import normalize_topic

REPORT_SCHEMA_VERSION = "market-signal-report-v1"
MAX_CANDIDATE_DRAFTS = 3

class MarketSignalError(ValueError): pass

def _canonical(value: Mapping[str, Any]) -> str: return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
def _timestamp(value: object) -> str:
    if not isinstance(value, str) or not value.endswith("Z"): raise MarketSignalError("observed_at_invalid")
    return value
def _safe_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip(): raise MarketSignalError(f"{field}_invalid")
    return value.strip()

def build_market_analysis_input(*, query: str, observed_at: str, results: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    return {"schema_version": "market-signal-analysis-input-v1", "query": _safe_text(query, "query"), "observed_at": _timestamp(observed_at), "results": [dict(item) for item in results]}

def _tokens(value: str) -> set[str]: return {item for item in re.split(r"[^0-9A-Za-zぁ-んァ-ン一-龥]+", normalize_topic(value)) if len(item) >= 2}

def build_own_site_signal(*, query: str, articles: Sequence[Mapping[str, Any]], page_daily: Sequence[Mapping[str, Any]], affiliate_events: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    query_tokens = _tokens(query); overlaps = []
    for row in articles:
        if not isinstance(row.get("article_id"), int) or not isinstance(row.get("title"), str) or not isinstance(row.get("category"), str): continue
        text = row["title"] + " " + (row.get("description") if isinstance(row.get("description"), str) else "")
        shared = sorted(query_tokens & _tokens(text))
        if shared: overlaps.append({"article_id": row["article_id"], "title": row["title"], "category": row["category"], "matched_terms": shared})
    days, impressions, clicks = set(), 0, 0
    for row in page_daily:
        if isinstance(row.get("metric_date"), str): days.add(row["metric_date"])
        impressions += int(row.get("impressions", 0)); clicks += int(row.get("clicks", 0))
    sufficient = len(days) >= MIN_OBSERVATION_DAYS and impressions >= MIN_IMPRESSIONS
    article_clicks = sum(1 for row in affiliate_events if row.get("placement") == "article")
    discord_clicks = sum(1 for row in affiliate_events if row.get("placement") == "discord")
    return {"overlap": {"method": "deterministic_lexical_metadata_match", "matched_articles": overlaps, "classification": "potential_overlap" if overlaps else "no_observed_overlap"}, "search_console_signal": {"status": "sufficient_for_review" if sufficient else "insufficient_data", "observation_days": len(days), "impressions": impressions, "clicks": clicks, "ctr": round(clicks / impressions, 6) if impressions else None}, "affiliate_signal": {"article_click_count": article_clicks, "discord_click_count": discord_clicks, "usable_click_count": article_clicks, "reliability_status": "discord_click_human_status_unknown_not_used" if discord_clicks else "no_discord_clicks_observed", "conversion_or_revenue": "not_measured"}}

def build_candidate_drafts(opportunities: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    if not isinstance(opportunities, Sequence) or isinstance(opportunities, (str, bytes)): raise MarketSignalError("opportunities_invalid")
    output = []
    for item in opportunities[:MAX_CANDIDATE_DRAFTS]:
        if not isinstance(item, Mapping): raise MarketSignalError("candidate_draft_invalid")
        required = ("topic", "reason", "market_evidence", "own_site_gap", "expected_search_intent", "target_audience", "monetization_relevance", "duplicate_risk")
        if not all(isinstance(item.get(key), str) and item[key].strip() for key in required) or item["duplicate_risk"] not in {"none", "low", "medium", "high"}: raise MarketSignalError("candidate_draft_invalid")
        output.append({**{key: item[key].strip() for key in required}, "requires_human_review": True, "content_generation_authorized": False, "publication_authorized": False, "execution_authorized": False})
    return output

def build_market_signal_report(*, query: str, observed_at: str, source: Mapping[str, Any], serp_results: Sequence[Mapping[str, Any]], analysis: Mapping[str, Any], own_site_signal: Mapping[str, Any], opportunities: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    query, observed_at = _safe_text(query, "query"), _timestamp(observed_at)
    if set(source) != {"provider", "engine", "locale", "region", "requested_result_count"} or not all(isinstance(source.get(key), str) and source[key] for key in ("provider", "engine", "locale", "region")) or source.get("requested_result_count") != 10: raise MarketSignalError("source_invalid")
    if set(analysis) != {"common_intents", "common_angles", "uncovered_questions"} or not all(isinstance(analysis.get(key), list) and all(isinstance(item, str) and item for item in analysis[key]) for key in analysis): raise MarketSignalError("analysis_invalid")
    results = [dict(item) for item in serp_results]
    if len(results) > 10 or not all(set(item) == {"schema_version", "position", "title", "url", "domain", "snippet", "published_at"} for item in results): raise MarketSignalError("serp_results_invalid")
    candidate_drafts = build_candidate_drafts(opportunities)
    core = {"schema_version": REPORT_SCHEMA_VERSION, "query": query, "observed_at": observed_at, "source": {**source, "returned_results_count": len(results)}, "serp_results": results, "market_analysis": {**analysis, "competing_domains": sorted({item["domain"] for item in results})}, "own_site": dict(own_site_signal), "candidate_drafts": candidate_drafts}
    return {**core, "report_fingerprint": "market_signal_" + sha256(_canonical(core).encode()).hexdigest(), "requires_human_review": True, "content_generation_authorized": False, "publication_authorized": False, "execution_authorized": False}

def render_human_report(report: Mapping[str, Any]) -> str:
    own = report["own_site"]
    lines = ["MARKET SIGNAL REPORT", f"調査テーマ: {report['query']}", "", "市場で多い論点:"]
    lines += [f"- {item}" for item in report["market_analysis"]["common_angles"]]
    lines += ["不足している可能性がある論点:"] + [f"- {item}" for item in report["market_analysis"]["uncovered_questions"]]
    lines += [f"自サイト重複: {own['overlap']['classification']}", f"Search Console: {own['search_console_signal']['status']}", f"Affiliate: usable article clicks={own['affiliate_signal']['usable_click_count']} (Discord clicks are not used)", "", "RECOMMENDED TOPIC CANDIDATES:"]
    for index, item in enumerate(report["candidate_drafts"], 1): lines += [f"{index}. {item['topic']}", f"   reason: {item['reason']}", f"   duplicate risk: {item['duplicate_risk']}"]
    return "\n".join(lines)
