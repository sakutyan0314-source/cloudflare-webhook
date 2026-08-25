"""Read-only, cache-only preflight for the exact live Market Analysis input contract."""
import importlib.util, io, json, pathlib, sys, tempfile, unittest
from contextlib import redirect_stdout
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


load("search_console_improvement_candidates")
load("topic_candidate")
serp = load("market_signal_serp_adapter")
load("market_signal_report")
load("market_signal_analysis")
load("market_signal_analysis_adapter")
load("openai_market_signal_analysis_adapter")
load("search_console_collector")
load("search_console_d1_reader")
load("ai_recommendation_d1_reader")
load("search_console_affiliate_reader")
load("search_console_improvement_candidate_review")
load("phase2a_candidate_read_cli")
cli = load("market_signal_report_cli")

QUERY = "Microsoft 365 Copilot エージェント"
OBSERVED_AT = "2026-08-26T00:00:00Z"


def cached_results():
    return [
        {"schema_version": "market-signal-serp-result-v1", "position": index,
         "title": f"Copilot エージェント ガバナンス {index}",
         "url": f"https://example{index}.test/copilot-agent",
         "domain": f"example{index}.test", "snippet": "導入とガバナンスの概要", "published_at": None}
        for index in range(1, 10)
    ]


class MarketAnalysisPreflight(unittest.TestCase):
    def _args(self, cache_dir):
        return [
            "--query", QUERY, "--observed-at", OBSERVED_AT, "--live-serp", "--analysis-preflight",
            "--property-uri", "https://cloudflare-webhook.tyansaku3325.workers.dev/",
            "--period-start", "2026-08-12", "--period-end", "2026-08-25",
            "--cache-dir", str(cache_dir), "--cache-ttl-seconds", "604800", "--format", "json",
        ]

    def test_exact_live_arguments_preflight_from_cache_uses_zero_openai_calls(self):
        original_read = cli.read_own_site
        original_transport = cli._PreflightTransport.analyze
        calls = []

        def read_only_source(*_args):
            return ([{"article_id": 40, "title": "Microsoft 365 Copilot エージェント導入ガバナンス",
                      "description": "権限と棚卸し", "category": "security-governance"}], [],
                    [{"article_id": 40, "placement": "article"}, {"article_id": 40, "placement": "discord"}])

        cli.read_own_site = read_only_source
        cli._PreflightTransport.analyze = lambda *_args, **_kwargs: calls.append("forbidden")
        try:
            with tempfile.TemporaryDirectory() as directory:
                cache = serp.LocalNormalizedSerpCache(pathlib.Path(directory), ttl_seconds=604800)
                cache.put(serp.serp_cache_key(query=QUERY, locale="ja", region="jp", result_count=10), cached_results(),
                          now=datetime.now(timezone.utc))
                output = io.StringIO()
                with redirect_stdout(output):
                    self.assertEqual(0, cli.main(self._args(directory)))
                value = json.loads(output.getvalue())
        finally:
            cli.read_own_site = original_read
            cli._PreflightTransport.analyze = original_transport

        self.assertEqual("pass", value["status"])
        self.assertTrue(value["analysis_input_valid"])
        self.assertEqual("cache", value["serp_source"])
        self.assertEqual(9, value["serp_result_count"])
        self.assertEqual(1, value["own_site_overlap_count"])
        self.assertEqual("insufficient_data", value["search_console_status"])
        self.assertIn("unknown", value["affiliate_reliability_status"])
        self.assertTrue(value["openai_request_ready"])
        self.assertEqual(0, value["openai_call"])
        self.assertEqual([], calls)
        self.assertEqual(64, len(value["analysis_input_fingerprint"].rsplit("_", 1)[1]))

    def test_cache_miss_stops_without_serp_or_openai_request(self):
        original_read = cli.read_own_site
        cli.read_own_site = lambda *_args: ([], [], [])
        try:
            with tempfile.TemporaryDirectory() as directory:
                output = io.StringIO()
                with redirect_stdout(output):
                    self.assertEqual(1, cli.main(self._args(directory)))
                value = json.loads(output.getvalue())
        finally:
            cli.read_own_site = original_read
        self.assertEqual("fail", value["status"])
        self.assertEqual("serp_cache", value["validation_stage"])
        self.assertEqual("cache_miss", value["failure_rule"])
        self.assertFalse(value["openai_request_ready"])
        self.assertEqual(0, value["openai_call"])

    def test_analysis_input_failure_is_sanitized(self):
        value = cli._failure_output(cli.MarketSignalPreflightError("analysis_input_builder", Exception("query_invalid")), preflight=True)
        self.assertEqual("query_invalid", value["failure_rule"])
        self.assertEqual("query", value["field_name"])
        self.assertNotIn(QUERY, json.dumps(value, ensure_ascii=False))


if __name__ == "__main__":
    unittest.main()
