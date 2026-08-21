import importlib.util
import io
import pathlib
import sys
import unittest
from contextlib import redirect_stdout

ROOT = pathlib.Path(__file__).parents[1]
def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / (name + ".py")); module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader; sys.modules[name] = module; spec.loader.exec_module(module); return module

load("search_console_collector"); load("search_console_d1_reader"); load("ai_recommendation_d1_reader")
load("search_console_improvement_candidates"); load("search_console_improvement_candidate_review")
cli = load("phase2a_candidate_read_cli")

class Reader:
    def fetch_source(self, *_):
        pages = []
        for day in range(8, 15): pages.append({"metric_date": f"2026-08-{day:02d}", "property_uri": "https://example.test/", "search_type": "web", "page_url": "https://example.test/article/1", "url_kind": "article", "article_id": 1, "clicks": 0, "impressions": 10, "ctr": 0, "position": 10, "observed_at": "x"})
        for day in range(1, 8): pages.append({"metric_date": f"2026-08-{day:02d}", "property_uri": "https://example.test/", "search_type": "web", "page_url": "https://example.test/article/1", "url_kind": "article", "article_id": 1, "clicks": 1, "impressions": 10, "ctr": .1, "position": 9, "observed_at": "x"})
        return pages, [], [{"article_id": 1, "title": "Ready title", "description": "Ready description", "category": "saas-cloud", "published_at": "x", "updated_at": "x", "seo_status": "ready"}]

class TestPhase2ACandidateReadCli(unittest.TestCase):
    def test_listing_is_minimized_and_has_fingerprint(self):
        result = cli.build_candidate_listing(Reader(), "https://example.test/", "2026-08-14")
        self.assertEqual(1, result["candidate_count"]); item = result["candidates"][0]
        self.assertEqual({"article_id", "title", "category", "recommendation_type", "reason_code", "current_metrics", "candidate_fingerprint"}, set(item))
        self.assertEqual(64, len(item["candidate_fingerprint"]))
    def test_transport_rejects_non_select(self):
        transport = cli.WranglerFixedSelectTransport(runner=lambda *_, **__: None)
        with self.assertRaises(cli.Phase2ACandidateReadError): transport.request("POST", "/query", {"batch": [{"sql": "DELETE FROM curation_logs", "params": []}] * 3})
    def test_fixed_parameter_rendering_escapes_values(self):
        self.assertEqual("SELECT 'a''b'", cli._render_fixed_select("SELECT ?", ["a'b"]))
    def test_cli_wraps_transport_in_existing_phase2a_reader(self):
        original_reader, original_transport = cli.AiRecommendationD1Reader, cli.WranglerFixedSelectTransport
        output = io.StringIO()
        try:
            cli.AiRecommendationD1Reader = lambda transport: Reader()
            cli.WranglerFixedSelectTransport = lambda: object()
            with redirect_stdout(output):
                self.assertEqual(0, cli.main(["--property-uri", "https://example.test/", "--current-period-end", "2026-08-14"]))
            self.assertIn('"status":"pass"', output.getvalue())
        finally:
            cli.AiRecommendationD1Reader, cli.WranglerFixedSelectTransport = original_reader, original_transport

if __name__ == "__main__": unittest.main()
