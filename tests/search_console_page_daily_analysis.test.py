import importlib.util
import json
import pathlib
import unittest


ROOT = pathlib.Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location("analysis", ROOT / "scripts" / "search_console_page_daily_analysis.py")
analysis = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(analysis)
FIXTURE = json.loads((ROOT / "tests" / "fixtures" / "search-console-page-daily-analysis-fixture.json").read_text())


class SearchConsolePageDailyAnalysisTest(unittest.TestCase):
    def test_fixed_json_report_compares_equal_length_windows(self):
        report = analysis.build_page_daily_report(FIXTURE, "2026-08-06", "2026-08-07")
        self.assertEqual(analysis.REPORT_SCHEMA_VERSION, report["schema_version"])
        self.assertEqual({"start": "2026-08-04", "end": "2026-08-05"}, report["comparison_period"])
        current = report["overall"]["current"]
        self.assertEqual(10, current["clicks"])
        self.assertEqual(60, current["impressions"])
        self.assertEqual(round(10 / 60, 6), current["ctr"])
        self.assertEqual(round(320 / 60, 6), current["position"])
        self.assertEqual(8, report["diagnostics"]["accepted_rows"])

    def test_article_growth_and_top_decline_are_detected(self):
        report = analysis.build_page_daily_report(FIXTURE, "2026-08-06", "2026-08-07")
        pages = {entry["page_url"]: entry for entry in report["pages"]}
        self.assertEqual("growing", pages["https://example.test/article/17"]["trend"]["classification"])
        self.assertEqual("declining", pages["https://example.test/"]["trend"]["classification"])
        self.assertEqual("growing", report["articles"][0]["trend"]["classification"])

    def test_ctr_and_position_are_impression_weighted(self):
        rows = [
            {"metric_date": "2026-08-06", "page_url": "https://example.test/article/1", "url_kind": "article", "article_id": 1, "clicks": 1, "impressions": 10, "ctr": .1, "position": 2},
            {"metric_date": "2026-08-07", "page_url": "https://example.test/article/1", "url_kind": "article", "article_id": 1, "clicks": 9, "impressions": 90, "ctr": .1, "position": 8},
        ]
        entry = analysis.build_page_daily_report(rows, "2026-08-06", "2026-08-07")["pages"][0]["current"]
        self.assertEqual(.1, entry["ctr"])
        self.assertEqual(7.4, entry["position"])

    def test_insufficient_data_prevents_false_growth_or_decline(self):
        report = analysis.build_page_daily_report(FIXTURE[:2], "2026-08-06", "2026-08-07")
        self.assertEqual("insufficient_data", report["overall"]["trend"]["classification"])
        self.assertEqual("insufficient_data", report["pages"][0]["trend"]["classification"])

    def test_invalid_rows_and_configuration_stop(self):
        with self.assertRaises(ValueError):
            analysis.build_page_daily_report([], "2026-08-07", "2026-08-06")
        invalid = dict(FIXTURE[0]); invalid["url_kind"] = "bad"
        with self.assertRaises(ValueError):
            analysis.build_page_daily_report([invalid], "2026-08-06", "2026-08-07")
        with self.assertRaises(ValueError):
            analysis.build_page_daily_report([], "2026-08-06", "2026-08-07", min_comparison_days=0)


if __name__ == "__main__":
    unittest.main()
