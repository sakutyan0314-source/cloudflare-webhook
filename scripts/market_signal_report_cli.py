"""Fixture-first Market Signal CLI; it has no SERP API connection."""
from __future__ import annotations
import argparse, json, subprocess
from pathlib import Path
from typing import Any, Mapping, Sequence
from ai_recommendation_d1_reader import AiRecommendationD1Reader
from search_console_affiliate_reader import SearchConsoleAffiliateReader
from search_console_d1_reader import D1ReadSafetyError, _validate_fixed_select
from phase2a_candidate_read_cli import DATABASE_NAME, _parse_wrangler_json, _render_fixed_select
from market_signal_serp_adapter import normalize_serp_response
from market_signal_report import build_market_signal_report, build_own_site_signal, render_human_report

class MarketSignalReadError(RuntimeError): pass
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
    parser=argparse.ArgumentParser(description="Build a read-only market-signal report from a local SERP fixture.")
    parser.add_argument("--query",required=True); parser.add_argument("--observed-at",required=True); parser.add_argument("--serp-fixture",required=True); parser.add_argument("--own-site-fixture",required=True); parser.add_argument("--format",choices=("summary","json"),default="summary")
    args=parser.parse_args(argv)
    try:
        fixture=json.loads(Path(args.serp_fixture).read_text()); own=json.loads(Path(args.own_site_fixture).read_text())
        results=normalize_serp_response(fixture); signal=build_own_site_signal(query=args.query,articles=own["articles"],page_daily=own["page_daily"],affiliate_events=own["affiliate_events"])
        report=build_market_signal_report(query=args.query,observed_at=args.observed_at,source={"provider":"fixture_only","engine":"google","locale":"ja-JP","region":"JP","requested_result_count":10},serp_results=results,analysis=own["analysis"],own_site_signal=signal,opportunities=own["opportunities"])
    except (OSError,KeyError,ValueError,MarketSignalReadError): print(json.dumps({"schema_version":"market-signal-report-v1","status":"fail","error_class":"market_signal_input_invalid"})); return 1
    print(json.dumps(report,ensure_ascii=False,sort_keys=True) if args.format=="json" else render_human_report(report)); return 0
if __name__=="__main__": raise SystemExit(main())
