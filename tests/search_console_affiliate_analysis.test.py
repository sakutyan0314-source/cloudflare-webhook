import importlib.util
import pathlib
import unittest


ROOT = pathlib.Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location("analysis", ROOT / "scripts" / "search_console_affiliate_analysis.py")
analysis = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(analysis)


def page(article_id, clicks, impressions, position=10, metric_date="2026-08-08"):
    return {"metric_date": metric_date, "article_id": article_id, "clicks": clicks,
            "impressions": impressions, "position": position}


def affiliate(article_id, clicked_at="2026-08-08T12:00:00.000Z"):
    return {"article_id": article_id, "link_type": "amazon_search", "placement": "article",
            "category": "ai-automation", "clicked_at": clicked_at}


class SearchConsoleAffiliateAnalysisTest(unittest.TestCase):
    def test_combines_both_sources_and_uses_fixed_thresholds(self):
        report = analysis.build_search_affiliate_report([page(17, 2, 20, 5)], [affiliate(17)], "2026-08-08", "2026-08-09")
        article = report["articles"][0]
        self.assertEqual(analysis.REPORT_SCHEMA_VERSION, report["schema_version"])
        self.assertEqual("high_value", article["classification"])
        self.assertEqual(0.1, article["ctr"])
        self.assertEqual(0.5, article["affiliate_click_rate"])
        self.assertEqual(5.0, article["position"])
        self.assertEqual(10, report["thresholds"]["min_impressions_for_classification"])

    def test_page_only_and_affiliate_only_are_reproducible(self):
        report = analysis.build_search_affiliate_report([page(20, 1, 10)], [affiliate(26)], "2026-08-08", "2026-08-09")
        articles = {item["article_id"]: item for item in report["articles"]}
        self.assertEqual("traffic_only", articles[20]["classification"])
        self.assertEqual("insufficient_data", articles[26]["classification"])
        self.assertEqual(1, articles[26]["affiliate_click_count"])

    def test_conversion_candidate_and_zero_division(self):
        report = analysis.build_search_affiliate_report([page(21, 0, 10), page(22, 0, 0)], [], "2026-08-08", "2026-08-09")
        articles = {item["article_id"]: item for item in report["articles"]}
        self.assertEqual("conversion_candidate", articles[21]["classification"])
        self.assertEqual(0.0, articles[22]["ctr"])
        self.assertIsNone(articles[22]["affiliate_click_rate"])
        self.assertIsNone(articles[22]["position"])

    def test_invalid_article_id_or_row_stops(self):
        with self.assertRaises(ValueError):
            analysis.build_search_affiliate_report([page(0, 1, 10)], [], "2026-08-08", "2026-08-09")
        bad_event = affiliate(17); bad_event["placement"] = "external"
        with self.assertRaises(ValueError):
            analysis.build_search_affiliate_report([], [bad_event], "2026-08-08", "2026-08-09")
        with self.assertRaises(ValueError):
            analysis.build_search_affiliate_report([], [], "2026-08-09", "2026-08-08")


if __name__ == "__main__":
    unittest.main()
