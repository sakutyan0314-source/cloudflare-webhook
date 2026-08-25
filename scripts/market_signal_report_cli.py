"""Market Signal CLI; SerpApi is called only with an explicit live flag."""
from __future__ import annotations
import argparse, json, subprocess
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Mapping, Sequence
from ai_recommendation_d1_reader import AiRecommendationD1Reader
from search_console_affiliate_reader import SearchConsoleAffiliateReader
from search_console_d1_reader import D1ReadSafetyError, _validate_fixed_select
from phase2a_candidate_read_cli import DATABASE_NAME, _parse_wrangler_json, _render_fixed_select
from market_signal_serp_adapter import LocalNormalizedSerpCache, SerpApiGoogleSearchAdapter, normalize_serp_response
from market_signal_report import build_market_signal_report, build_own_site_signal, render_human_report
from market_signal_analysis_adapter import MarketSignalAnalysisAdapter
from openai_market_signal_analysis_adapter import OpenAiMarketSignalAnalysisTransport

class MarketSignalReadError(RuntimeError): pass
class FixtureMarketAnalysisTransport:
    """Test/fixture-only transport; it cannot make an external request."""
    def __init__(self, response: Mapping[str, Any]): self.response, self.calls = response, 0
    def analyze(self, _payload: Mapping[str, Any], **_limits: Any) -> Mapping[str, Any]: self.calls += 1; return self.response
def _root(): return Path(__file__).resolve().parents[1]
class FixedSelectTransport:
    def __init__(self, runner: Any = subprocess.run): self.runner=runner
    def request(self, method: str, path: str, payload: object | None=None):
        if method!="POST" or path!="/query" or not isinstance(payload, Mapping) or not isinstance(payload.get("batch"), list): raise MarketSignalReadError("read_request_invalid")
        result=[]
        for item in payload["batch"]:
            if not isinstance(item, Mapping) or not isinstance(item.get("sql"), str) or not isinstance(item.get("params"), list): raise MarketSignalReadError("fixed_select_invalid")
            try: _validate_fixed_select(type("S", (), {"sql":item["sql"]})())
            except D1ReadSafetyError as error: raise MarketSignalReadError("fixed_select_rejected") from error
            complete=self.runner(["node","--no-warnings","node_modules/wrangler/wrangler-dist/cli.js","d1","execute",DATABASE_NAME,"--remote","--config","./wrangler.toml","--command",_render_fixed_select(item["sql"],item["params"]),"--json"],cwd=_root(),capture_output=True,text=True,check=False)
            if complete.returncode: raise MarketSignalReadError("wrangler_read_failed")
            response=_parse_wrangler_json(complete.stdout); rows=response.get("result")
            if not isinstance(rows,list) or len(rows)!=1 or not isinstance(rows[0],Mapping): raise MarketSignalReadError("wrangler_response_invalid")
            if rows[0].get("meta",{}).get("changed_db") is not False or rows[0].get("meta",{}).get("rows_written")!=0: raise MarketSignalReadError("unexpected_d1_write")
            result.append(rows[0])
        return {"result":result}
def read_own_site(property_uri: str, start: str, end: str, transport: Any) -> tuple[list[Mapping[str,Any]],list[Mapping[str,Any]],list[Mapping[str,Any]]]:
    pages, affiliate, articles=AiRecommendationD1Reader(transport).fetch_source(property_uri,"web",start,end)
    return articles,pages,affiliate
def main(argv: Sequence[str]|None=None)->int:
    parser=argparse.ArgumentParser(description="Build a Market Signal report; SERP is fixture-only unless --live-serp is explicit.")
    parser.add_argument("--query",required=True); parser.add_argument("--observed-at",required=True); parser.add_argument("--serp-fixture"); parser.add_argument("--live-serp",action="store_true"); parser.add_argument("--own-site-fixture"); parser.add_argument("--planning-fixture"); parser.add_argument("--analysis-response-fixture"); parser.add_argument("--live-analysis",action="store_true"); parser.add_argument("--period-start"); parser.add_argument("--period-end"); parser.add_argument("--property-uri",default="https://cloudflare-webhook.tyansaku3325.workers.dev/"); parser.add_argument("--cache-dir",default=".market-signal-cache"); parser.add_argument("--cache-ttl-seconds",type=int,default=7*24*60*60); parser.add_argument("--format",choices=("summary","json"),default="summary")
    args=parser.parse_args(argv)
    try:
        if args.live_serp == bool(args.serp_fixture) or (args.live_analysis and args.analysis_response_fixture): raise MarketSignalReadError("execution_mode_invalid")
        if args.own_site_fixture:
            own=json.loads(Path(args.own_site_fixture).read_text())
            articles, pages, affiliate=own["articles"], own["page_daily"], own["affiliate_events"]
        else:
            if not args.planning_fixture: raise MarketSignalReadError("planning_fixture_required")
            own=json.loads(Path(args.planning_fixture).read_text())
            end=args.period_end or date.today().isoformat(); start=args.period_start or (date.fromisoformat(end)-timedelta(days=13)).isoformat()
            articles,pages,affiliate=read_own_site(args.property_uri,start,end,FixedSelectTransport())
        if args.live_serp:
            results, mode=SerpApiGoogleSearchAdapter(cache=LocalNormalizedSerpCache(Path(args.cache_dir),ttl_seconds=args.cache_ttl_seconds)).search(query=args.query)
            provider="serpapi" if mode=="live_request" else "serpapi_cache"
        else:
            results=normalize_serp_response(json.loads(Path(args.serp_fixture).read_text())); provider="fixture_only"
        signal=build_own_site_signal(query=args.query,articles=articles,page_daily=pages,affiliate_events=affiliate)
        if args.analysis_response_fixture or args.live_analysis:
            transport = FixtureMarketAnalysisTransport(json.loads(Path(args.analysis_response_fixture).read_text())) if args.analysis_response_fixture else OpenAiMarketSignalAnalysisTransport()
            model_analysis = MarketSignalAnalysisAdapter(transport).analyze(query=args.query, observed_at=args.observed_at, serp_results=results, own_site_signal=signal)
            analysis = {"common_intents": model_analysis["common_intents"], "common_angles": model_analysis["common_angles"], "uncovered_questions": [f"{item['classification']}: {item['question']}" for item in model_analysis["uncovered_questions"]]}
            opportunities = [{"topic": item["topic"], "reason": item["reason"], "market_evidence": item["market_evidence"], "own_site_gap": item["own_site_gap"], "expected_search_intent": item["common_intent"], "target_audience": item["target_audience"], "monetization_relevance": item["monetization_relevance"], "duplicate_risk": item["duplicate_risk"], "common_intent": item["common_intent"], "user_problem": item["user_problem"], "confidence": item["confidence"]} for item in model_analysis["candidate_drafts"]]
        else:
            analysis, opportunities = own["analysis"], own["opportunities"]
        report=build_market_signal_report(query=args.query,observed_at=args.observed_at,source={"provider":provider,"engine":"google","locale":"ja","region":"jp","requested_result_count":10},serp_results=results,analysis=analysis,own_site_signal=signal,opportunities=opportunities)
    except (OSError,KeyError,ValueError,MarketSignalReadError): print(json.dumps({"schema_version":"market-signal-report-v1","status":"fail","error_class":"market_signal_input_invalid"})); return 1
    print(json.dumps(report,ensure_ascii=False,sort_keys=True) if args.format=="json" else render_human_report(report)); return 0
if __name__=="__main__": raise SystemExit(main())
