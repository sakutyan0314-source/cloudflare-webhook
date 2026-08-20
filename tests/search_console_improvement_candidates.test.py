import importlib.util
import pathlib
import sys
import unittest


ROOT = pathlib.Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location("candidates", ROOT / "scripts" / "search_console_improvement_candidates.py")
candidates = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules["candidates"] = candidates
SPEC.loader.exec_module(candidates)


CURRENT_START, CURRENT_END = "2026-08-08", "2026-08-14"
CURRENT_DATES = [f"2026-08-{day:02d}" for day in range(8, 15)]
PREVIOUS_DATES = [f"2026-08-{day:02d}" for day in range(1, 8)]


def article(article_id, *, status="ready"):
    return {"article_id": article_id, "title": f"Article {article_id}", "seo_status": status}


def metrics(article_id, dates, *, clicks, impressions, position=10, url=None):
    return [{
        "metric_date": day,
        "property_uri": "https://example.test/",
        "page_url": url or f"https://example.test/article/{article_id}",
        "url_kind": "article",
        "article_id": article_id,
        "clicks": clicks,
        "impressions": impressions,
        "position": position,
    } for day in dates]


def report(page_rows, article_rows):
    return candidates.build_improvement_candidate_report(page_rows, article_rows, CURRENT_START, CURRENT_END)


class ImprovementCandidateTest(unittest.TestCase):
    def assessment(self, output, article_id):
        return next(item for item in output["assessments"] if item["article_id"] == article_id)

    def test_position_opportunity_and_low_ctr_becomes_improve_ctr(self):
        rows = metrics(1, PREVIOUS_DATES, clicks=1, impressions=10, position=10) + metrics(1, CURRENT_DATES, clicks=0, impressions=10, position=10)
        rows[-7]["clicks"] = 1
        output = report(rows, [article(1)])
        item = self.assessment(output, 1)
        self.assertEqual("improve_ctr", item["recommendation_type"])
        self.assertEqual("position_opportunity_with_low_ctr", item["reason_code"])
        self.assertTrue(item["is_candidate"])

    def test_declining_clicks_and_impressions_becomes_refresh_content(self):
        rows = metrics(2, PREVIOUS_DATES, clicks=2, impressions=20) + metrics(2, CURRENT_DATES, clicks=1, impressions=10)
        item = self.assessment(report(rows, [article(2)]), 2)
        self.assertEqual("refresh_content", item["recommendation_type"])
        self.assertEqual("clicks_and_impressions_declined", item["reason_code"])

    def test_zero_clicks_with_sufficient_impressions_is_neutral_snippet_candidate(self):
        rows = metrics(3, PREVIOUS_DATES, clicks=1, impressions=10) + metrics(3, CURRENT_DATES, clicks=0, impressions=10)
        item = self.assessment(report(rows, [article(3)]), 3)
        self.assertEqual("improve_snippet", item["recommendation_type"])
        self.assertEqual("impressions_with_zero_clicks", item["reason_code"])

    def test_current_period_below_seven_days_is_insufficient(self):
        rows = metrics(4, PREVIOUS_DATES, clicks=1, impressions=10) + metrics(4, CURRENT_DATES[:-1], clicks=1, impressions=10)
        item = self.assessment(report(rows, [article(4)]), 4)
        self.assertEqual(("insufficient_data", "observation_days_below_minimum"), (item["recommendation_type"], item["reason_code"]))

    def test_previous_period_below_seven_days_is_insufficient(self):
        rows = metrics(5, PREVIOUS_DATES[:-1], clicks=1, impressions=10) + metrics(5, CURRENT_DATES, clicks=1, impressions=10)
        item = self.assessment(report(rows, [article(5)]), 5)
        self.assertEqual("insufficient_data", item["recommendation_type"])

    def test_impressions_below_minimum_is_insufficient(self):
        rows = metrics(6, PREVIOUS_DATES, clicks=1, impressions=1) + metrics(6, CURRENT_DATES, clicks=1, impressions=1)
        item = self.assessment(report(rows, [article(6)]), 6)
        self.assertEqual(("insufficient_data", "impressions_below_minimum"), (item["recommendation_type"], item["reason_code"]))

    def test_growing_and_stable_articles_continue_observation(self):
        growing = metrics(7, PREVIOUS_DATES, clicks=1, impressions=10) + metrics(7, CURRENT_DATES, clicks=2, impressions=10)
        stable = metrics(8, PREVIOUS_DATES, clicks=1, impressions=10) + metrics(8, CURRENT_DATES, clicks=1, impressions=10)
        output = report(growing + stable, [article(7), article(8)])
        self.assertEqual(("continue_observation", "growing_trend"), (self.assessment(output, 7)["recommendation_type"], self.assessment(output, 7)["reason_code"]))
        self.assertEqual(("continue_observation", "stable_or_non_actionable_trend"), (self.assessment(output, 8)["recommendation_type"], self.assessment(output, 8)["reason_code"]))

    def test_non_ready_article_no_article_id_and_invalid_url_are_excluded(self):
        non_ready = metrics(9, PREVIOUS_DATES, clicks=1, impressions=10) + metrics(9, CURRENT_DATES, clicks=1, impressions=10)
        no_article_id = [{**row, "article_id": None} for row in metrics(10, PREVIOUS_DATES + CURRENT_DATES, clicks=1, impressions=10)]
        invalid_url = metrics(11, PREVIOUS_DATES + CURRENT_DATES, clicks=1, impressions=10, url="https://example.test/article/12")
        output = report(non_ready + no_article_id + invalid_url, [article(9, status="legacy"), article(10), article(11)])
        self.assertEqual([], output["assessments"])
        self.assertEqual(1, output["diagnostics"]["excluded_article_metadata_rows"])
        self.assertGreaterEqual(output["diagnostics"]["excluded_metric_rows"], 28)

    def test_existing_fixed_reader_connection_is_read_only(self):
        class Reader:
            def __init__(self): self.calls = 0
            def fetch_source(self, property_uri, search_type, start, end):
                self.calls += 1
                self.args = (property_uri, search_type, start, end)
                return metrics(12, PREVIOUS_DATES + CURRENT_DATES, clicks=1, impressions=10), [], [article(12)]
        reader = Reader()
        output = candidates.read_and_build_improvement_candidate_report(reader, "https://example.test/", "web", CURRENT_START, CURRENT_END)
        self.assertEqual(1, reader.calls)
        self.assertEqual(("https://example.test/", "web", CURRENT_START, CURRENT_END), reader.args)
        self.assertEqual("phase-2a-improvement-candidates-v1", output["schema_version"])


if __name__ == "__main__":
    unittest.main()
