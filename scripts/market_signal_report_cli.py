"""Market Signal CLI; SerpApi is called only with an explicit live flag."""
from __future__ import annotations
import argparse, json, re
from datetime import date, timedelta
from hashlib import sha256
from pathlib import Path
from typing import Any, Mapping, Sequence
from ai_recommendation_d1_reader import AiRecommendationD1Reader
from search_console_affiliate_reader import SearchConsoleAffiliateReader
from search_console_d1_reader import D1ReadSafetyError
from phase2a_candidate_read_cli import Phase2ACandidateReadError, WranglerFixedSelectTransport
from market_signal_serp_adapter import LocalNormalizedSerpCache, SerpApiGoogleSearchAdapter, normalize_serp_response
from market_signal_report import build_market_signal_report, build_own_site_signal, render_human_report
from market_signal_analysis_adapter import MarketSignalAnalysisAdapter, MarketSignalAnalysisAdapterError
from market_signal_analysis import ANALYSIS_SCHEMA_VERSION, MAX_OUTPUT_TOKENS, MODEL_ID, MarketAnalysisError
from market_signal_serp_adapter import SerpApiSafetyError
from openai_market_signal_analysis_adapter import OpenAiMarketSignalAnalysisError, OpenAiMarketSignalAnalysisTransport, build_responses_payload

class MarketSignalReadError(RuntimeError): pass
class FixtureMarketAnalysisTransport:
    """Test/fixture-only transport; it cannot make an external request."""
    def __init__(self, response: Mapping[str, Any]): self.response, self.calls = response, 0
    def analyze(self, _payload: Mapping[str, Any], **_limits: Any) -> Mapping[str, Any]: self.calls += 1; return self.response
def read_own_site(property_uri: str, start: str, end: str, transport: Any) -> tuple[list[Mapping[str,Any]],list[Mapping[str,Any]],list[Mapping[str,Any]]]:
    pages, affiliate, articles=AiRecommendationD1Reader(transport).fetch_source(property_uri,"web",start,end)
    return articles,pages,affiliate
def load_planning_fixture(path: str) -> Mapping[str, Any]:
    value=json.loads(Path(path).read_text())
    if not isinstance(value,Mapping) or set(value)!={"analysis","opportunities"} or not isinstance(value["analysis"],Mapping) or not isinstance(value["opportunities"],list): raise MarketSignalReadError("planning_fixture_invalid")
    return value


class _PreflightTransport:
    def analyze(self, *_args: Any, **_kwargs: Any) -> Mapping[str, Any]:
        raise AssertionError("analysis preflight must not call OpenAI")


_SAFE_RULE = re.compile(r"^[a-z][a-z0-9_]{0,80}$")
_RULE_FIELDS = {
    "cache_miss": ("serp_cache", "fresh normalized cache", "missing_or_stale"),
    "cache_invalid": ("serp_cache", "normalized-serp-cache-v1", "invalid"),
    "normalized_cache_results_invalid": ("serp_results", "market-signal-serp-result-v1[]", "invalid"),
    "query_invalid": ("query", "non-empty string", "invalid"),
    "observed_at_invalid": ("observed_at", "UTC Z timestamp", "invalid"),
    "serp_results_invalid": ("serp_results", "array with at most 10 results", "invalid"),
    "serp_result_invalid": ("serp_results[]", "normalized result object", "invalid"),
    "own_site_signal_invalid": ("own_site_signal", "signal object", "invalid"),
    "own_site_overlap_invalid": ("own_site_signal.overlap", "matched article array", "invalid"),
    "analysis_input_exceeds_token_limit": ("analysis_input", "at most 1800 estimated tokens", "too_large"),
    "wrangler_read_failed": ("own_site_d1", "fixed SELECT response", "unavailable"),
    "wrangler_response_invalid": ("own_site_d1", "single read-only result", "invalid"),
    "unexpected_d1_write": ("own_site_d1", "changed_db=false / rows_written=0", "write_detected"),
    "analysis_input_fingerprint_mismatch": ("analysis_input_fingerprint", "same canonical SHA-256", "mismatch"),
}


class MarketSignalPreflightError(RuntimeError):
    def __init__(self, stage: str, error: BaseException):
        super().__init__(stage)
        self.stage, self.error = stage, error


def _safe_rule(error: BaseException) -> str:
    candidate = str(error)
    return candidate if _SAFE_RULE.fullmatch(candidate) else "unclassified_input_failure"


def _failure_output(error: MarketSignalPreflightError, *, preflight: bool) -> dict[str, Any]:
    rule = _safe_rule(error.error)
    output: dict[str, Any] = {"schema_version": "market-signal-analysis-preflight-v1" if preflight else "market-signal-report-v1",
                               "status": "fail", "error_class": "market_signal_input_invalid",
                               "validation_stage": error.stage, "failure_rule": rule}
    field = _RULE_FIELDS.get(rule)
    if field:
        output.update({"field_name": field[0], "expected_type": field[1], "actual_type": field[2]})
    if preflight:
        output.update({"analysis_input_valid": False, "openai_request_ready": False, "openai_call": 0})
    return output


def _analysis_input_fingerprint(value: Mapping[str, Any]) -> str:
    canonical = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "market_signal_analysis_input_" + sha256(canonical.encode()).hexdigest()


def _analysis_input_component_fingerprints(value: Mapping[str, Any]) -> dict[str, str]:
    """Safe change diagnostics: hashes only, never analysis input values."""
    fields = ("schema_version", "query", "observed_at", "serp_results", "own_site_overlap",
              "search_console_signal", "affiliate_signal", "intent_taxonomy", "analysis_instructions")
    return {field: sha256(json.dumps(value.get(field), ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest() for field in fields}


def _verify_preflight_live_identity(preflight_input: Mapping[str, Any], outgoing_input: Mapping[str, Any]) -> str:
    """Fail closed before transport when the canonical input would change."""
    preflight_fingerprint = _analysis_input_fingerprint(preflight_input)
    outgoing_fingerprint = _analysis_input_fingerprint(outgoing_input)
    if preflight_fingerprint != outgoing_fingerprint:
        raise MarketSignalPreflightError("preflight_to_live_identity", MarketAnalysisError("analysis_input_fingerprint_mismatch"))
    return preflight_fingerprint


def _load_live_serp(args: Any, *, cache_only: bool) -> tuple[list[Mapping[str, Any]], str]:
    try:
        return SerpApiGoogleSearchAdapter(cache=LocalNormalizedSerpCache(Path(args.cache_dir), ttl_seconds=args.cache_ttl_seconds)).search(query=args.query, cache_only=cache_only)
    except SerpApiSafetyError as error:
        raise MarketSignalPreflightError("serp_cache", error) from error


def _build_live_context(args: Any, *, articles: list[Mapping[str, Any]], pages: list[Mapping[str, Any]],
                        affiliate: list[Mapping[str, Any]], results: list[Mapping[str, Any]], mode: str) -> dict[str, Any]:
    """The shared live/preflight input and request-payload contract, without sending."""
    try:
        signal = build_own_site_signal(query=args.query, articles=articles, page_daily=pages, affiliate_events=affiliate)
    except ValueError as error:
        raise MarketSignalPreflightError("own_site_signal", error) from error
    try:
        input_builder = MarketSignalAnalysisAdapter(_PreflightTransport())
        analysis_input = input_builder.build_input(query=args.query, observed_at=args.observed_at, serp_results=results, own_site_signal=signal)
    except MarketAnalysisError as error:
        raise MarketSignalPreflightError("analysis_input_builder", error) from error
    try:
        request_payload = build_responses_payload(analysis_input, model_id=MODEL_ID, max_output_tokens=MAX_OUTPUT_TOKENS, store=False, tools=None)
    except OpenAiMarketSignalAnalysisError as error:
        raise MarketSignalPreflightError("openai_request_payload", error) from error
    return {"articles": articles, "pages": pages, "affiliate": affiliate, "results": results, "mode": mode,
            "signal": signal, "analysis_input": analysis_input, "request_payload": request_payload}


def _prepare_live_context(args: Any, *, cache_only: bool) -> dict[str, Any]:
    """Production D1 + cached/live SERP producer chain; only OpenAI sending is outside it."""
    try:
        end = args.period_end or date.today().isoformat()
        start = args.period_start or (date.fromisoformat(end) - timedelta(days=13)).isoformat()
        articles, pages, affiliate = read_own_site(args.property_uri, start, end, WranglerFixedSelectTransport())
    except (OSError, KeyError, ValueError, MarketSignalReadError, Phase2ACandidateReadError, D1ReadSafetyError) as error:
        raise MarketSignalPreflightError("own_site_d1_read", error) from error
    results, mode = _load_live_serp(args, cache_only=cache_only)
    return _build_live_context(args, articles=articles, pages=pages, affiliate=affiliate, results=results, mode=mode)


def _preflight_report(context: Mapping[str, Any]) -> dict[str, Any]:
    signal = context["signal"]
    return {"schema_version": "market-signal-analysis-preflight-v1", "status": "pass", "analysis_input_valid": True,
            "serp_source": "cache" if context["mode"] == "cache_hit" else context["mode"],
            "serp_result_count": len(context["results"]), "own_site_overlap_count": len(signal["overlap"]["matched_articles"]),
            "search_console_status": signal["search_console_signal"]["status"],
            "affiliate_reliability_status": signal["affiliate_signal"]["reliability_status"],
            "analysis_schema_version": ANALYSIS_SCHEMA_VERSION,
            "analysis_input_fingerprint": _analysis_input_fingerprint(context["analysis_input"]),
            "analysis_input_component_fingerprints": _analysis_input_component_fingerprints(context["analysis_input"]),
            "openai_request_ready": True, "openai_call": 0}

def main(argv: Sequence[str]|None=None)->int:
    parser=argparse.ArgumentParser(description="Build a Market Signal report; SERP is fixture-only unless --live-serp is explicit.")
    parser.add_argument("--query",required=True); parser.add_argument("--observed-at",required=True); parser.add_argument("--serp-fixture"); parser.add_argument("--live-serp",action="store_true"); parser.add_argument("--own-site-fixture"); parser.add_argument("--planning-fixture"); parser.add_argument("--analysis-response-fixture"); parser.add_argument("--live-analysis",action="store_true"); parser.add_argument("--analysis-preflight",action="store_true"); parser.add_argument("--preflight-to-live-identity-guard",action="store_true"); parser.add_argument("--period-start"); parser.add_argument("--period-end"); parser.add_argument("--property-uri",default="https://cloudflare-webhook.tyansaku3325.workers.dev/"); parser.add_argument("--cache-dir",default=".market-signal-cache"); parser.add_argument("--cache-ttl-seconds",type=int,default=7*24*60*60); parser.add_argument("--format",choices=("summary","json"),default="summary")
    args=parser.parse_args(argv)
    try:
        if args.analysis_preflight:
            if not args.live_serp or args.live_analysis or args.analysis_response_fixture or args.own_site_fixture or args.planning_fixture:
                raise MarketSignalReadError("preflight_mode_invalid")
            context = _prepare_live_context(args, cache_only=True)
            print(json.dumps(_preflight_report(context), ensure_ascii=False, sort_keys=True)); return 0
        if args.preflight_to_live_identity_guard and (not args.live_serp or not args.live_analysis or args.own_site_fixture or args.planning_fixture or args.analysis_response_fixture):
            raise MarketSignalReadError("preflight_to_live_guard_mode_invalid")
        if args.live_serp == bool(args.serp_fixture) or (args.live_analysis and args.analysis_response_fixture): raise MarketSignalReadError("execution_mode_invalid")
        planning=load_planning_fixture(args.planning_fixture) if args.planning_fixture else None
        if args.own_site_fixture:
            own=json.loads(Path(args.own_site_fixture).read_text())
            articles, pages, affiliate=own["articles"], own["page_daily"], own["affiliate_events"]
        else:
            if args.live_analysis:
                context = _prepare_live_context(args, cache_only=args.preflight_to_live_identity_guard)
                articles, pages, affiliate, results, mode, signal = context["articles"], context["pages"], context["affiliate"], context["results"], context["mode"], context["signal"]
            else:
                if planning is None: raise MarketSignalReadError("planning_fixture_required")
                end=args.period_end or date.today().isoformat(); start=args.period_start or (date.fromisoformat(end)-timedelta(days=13)).isoformat()
                articles,pages,affiliate=read_own_site(args.property_uri,start,end,WranglerFixedSelectTransport())
        if args.live_analysis:
            if args.own_site_fixture:
                results, mode = _load_live_serp(args, cache_only=False)
                context = _build_live_context(args, articles=articles, pages=pages, affiliate=affiliate, results=results, mode=mode)
            provider="serpapi" if context["mode"]=="live_request" else "serpapi_cache"
            results, signal = context["results"], context["signal"]
        elif args.live_serp:
            results, mode=SerpApiGoogleSearchAdapter(cache=LocalNormalizedSerpCache(Path(args.cache_dir),ttl_seconds=args.cache_ttl_seconds)).search(query=args.query)
            provider="serpapi" if mode=="live_request" else "serpapi_cache"
        else:
            results=normalize_serp_response(json.loads(Path(args.serp_fixture).read_text())); provider="fixture_only"
        if not args.live_analysis:
            signal=build_own_site_signal(query=args.query,articles=articles,page_daily=pages,affiliate_events=affiliate)
        if args.analysis_response_fixture or args.live_analysis:
            transport = FixtureMarketAnalysisTransport(json.loads(Path(args.analysis_response_fixture).read_text())) if args.analysis_response_fixture else OpenAiMarketSignalAnalysisTransport()
            analysis_adapter = MarketSignalAnalysisAdapter(transport)
            analysis_input = context["analysis_input"] if args.live_analysis else analysis_adapter.build_input(query=args.query, observed_at=args.observed_at, serp_results=results, own_site_signal=signal)
            if args.preflight_to_live_identity_guard:
                identity_fingerprint = _verify_preflight_live_identity(context["analysis_input"], analysis_input)
            model_analysis = analysis_adapter.analyze_input(analysis_input)
            analysis = {"common_intents": model_analysis["common_intents"], "common_angles": model_analysis["common_angles"], "uncovered_questions": [f"{item['classification']}: {item['question']}" for item in model_analysis["uncovered_questions"]]}
            opportunities = [{"topic": item["topic"], "reason": item["reason"], "market_evidence": item["market_evidence"], "own_site_gap": item["own_site_gap"], "expected_search_intent": item["common_intent"], "target_audience": item["target_audience"], "monetization_relevance": item["monetization_relevance"], "duplicate_risk": item["duplicate_risk"], "common_intent": item["common_intent"], "user_problem": item["user_problem"], "confidence": item["confidence"]} for item in model_analysis["candidate_drafts"]]
        else:
            if planning is not None: analysis, opportunities = planning["analysis"], planning["opportunities"]
            else: analysis, opportunities = own["analysis"], own["opportunities"]
        report=build_market_signal_report(query=args.query,observed_at=args.observed_at,source={"provider":provider,"engine":"google","locale":"ja","region":"jp","requested_result_count":10},serp_results=results,analysis=analysis,own_site_signal=signal,opportunities=opportunities)
        if args.preflight_to_live_identity_guard:
            report["preflight_to_live_identity_guard"] = {"status": "pass", "analysis_input_fingerprint": identity_fingerprint}
        if args.live_analysis and isinstance(getattr(transport, "last_diagnostic", None), Mapping):
            usage = transport.last_diagnostic.get("usage")
            if isinstance(usage, Mapping):
                report["market_analysis_usage"] = dict(usage)
    except MarketSignalPreflightError as error:
        print(json.dumps(_failure_output(error, preflight=args.analysis_preflight), ensure_ascii=False, sort_keys=True)); return 1
    except (MarketSignalAnalysisAdapterError, OpenAiMarketSignalAnalysisError) as error:
        output={"schema_version":"market-signal-report-v1","status":"fail","error_class":"market_signal_analysis_failed"}
        if isinstance(error.code,str): output["failure_classification"]=error.code
        if isinstance(error.diagnostic,Mapping): output["response_structure_diagnostic"]=error.diagnostic
        print(json.dumps(output,ensure_ascii=False,sort_keys=True)); return 1
    except (OSError,KeyError,ValueError,MarketSignalReadError) as error:
        print(json.dumps(_failure_output(MarketSignalPreflightError("cli_input", error), preflight=args.analysis_preflight), ensure_ascii=False, sort_keys=True)); return 1
    print(json.dumps(report,ensure_ascii=False,sort_keys=True) if args.format=="json" else render_human_report(report)); return 0
if __name__=="__main__": raise SystemExit(main())
