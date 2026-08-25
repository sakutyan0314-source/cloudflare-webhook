import importlib.util
import json
import pathlib
import sys
import unittest
from datetime import date

ROOT = pathlib.Path(__file__).parents[1]
def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec); assert spec and spec.loader
    sys.modules[name] = module; spec.loader.exec_module(module); return module

load("search_console_improvement_candidates")
kpi = load("kpi_baseline_report_cli")


class Reader:
    def fetch(self, *_):
        pipeline = [
            {"id": 1, "trigger_type": "cron", "status": "completed", "stage": "done", "article_id": 20, "notification_status": "sent", "error_code": None, "error_summary": None, "event_at": "2026-08-01T03:00:00Z"},
            {"id": 2, "trigger_type": "cron", "status": "failed", "stage": "seo_quality", "article_id": None, "notification_status": "pending", "error_code": "seo_quality_failed", "error_summary": "sanitized", "event_at": "2026-08-02T03:00:00Z"},
            {"id": 3, "trigger_type": "manual", "status": "completed", "stage": "done", "article_id": 21, "notification_status": "sent", "error_code": None, "error_summary": None, "event_at": "2026-08-03T03:00:00Z"},
        ]
        metrics = []
        for day in range(1, 15):
            metrics.append({"metric_date": f"2026-08-{day:02d}", "article_id": 20, "clicks": 1, "impressions": 10, "position": 8.0})
        return {"pipeline_runs": pipeline, "canary_runs": [{"pipeline_run_id": 3}], "quality_audits": [{"audit_id": "a1", "pipeline_run_id": 1, "classification": "pass", "evaluated_at": "2026-08-01T03:00:00Z"}, {"audit_id": "a2", "pipeline_run_id": 2, "classification": "fail", "evaluated_at": "2026-08-02T03:00:00Z"}], "quality_reasons": [{"audit_id": "a2", "reason_code": "h1_missing_or_invalid"}], "search_console": metrics, "affiliate_clicks": [{"article_id": 20, "placement": "article", "category": "security-governance", "clicked_at": "2026-08-03T00:00:00Z"}, {"article_id": 20, "placement": "article", "category": "security-governance", "clicked_at": "2026-08-04T00:00:00Z"}, {"article_id": 21, "placement": "discord", "category": "ai-automation", "clicked_at": "2026-08-04T00:00:00Z"}]}


class TestKpiBaselineReport(unittest.TestCase):
    def setUp(self): self.report = kpi.build_kpi_baseline_report(Reader(), "2026-08-01", "2026-08-14")
    def test_14_day_content_and_no_update_days(self):
        self.assertEqual(14, self.report["period"]["days"])
        self.assertEqual(2, self.report["content_supply"]["scheduled_pipeline_runs"])
        self.assertEqual(1, self.report["content_supply"]["scheduled_failed_runs"])
        self.assertEqual(2, self.report["content_supply"]["published_article_count"])
        self.assertEqual(12, len(self.report["content_supply"]["calendar_no_update_days"]))
        self.assertEqual({"runs": 1, "published_articles": 1}, self.report["content_supply"]["topic_aware_canary"])
    def test_quality_pass_fail_rate_and_reasons(self):
        quality = self.report["quality"]
        self.assertEqual(1, quality["quality_gate_pass_count"]); self.assertEqual(1, quality["quality_gate_fail_count"])
        self.assertEqual(.5, quality["quality_gate_pass_rate"])
        self.assertEqual({"h1_missing_or_invalid": 1}, quality["fail_reasons"])
    def test_existing_search_rules_are_reused(self):
        evidence = self.report["search_console"]["evidence_sufficiency"]
        self.assertEqual("sufficient", evidence["status"])
        self.assertEqual(7, evidence["min_observation_days"]); self.assertEqual(10, evidence["min_impressions"])
    def test_affiliate_aggregates_are_article_placement_and_category_bound(self):
        affiliate = self.report["affiliate"]
        self.assertEqual(3, affiliate["affiliate_click_count"])
        self.assertEqual({"20": 2, "21": 1}, affiliate["article_click_counts"])
        self.assertEqual({"article": 2, "discord": 1}, affiliate["placement_click_counts"])
    def test_schema_and_read_only_guarantee_are_stable(self):
        self.assertEqual(kpi.REPORT_SCHEMA_VERSION, self.report["schema_version"])
        self.assertEqual({"fixed_select_only": True, "changed_db": False, "rows_written": 0}, self.report["read_only"])
        self.assertIn("KPI BASELINE", kpi.render_summary(self.report))
    def test_insufficient_search_data_and_default_period(self):
        source = Reader().fetch(None, None, None); source["search_console"] = source["search_console"][:6]
        class Sparse:
            def fetch(self, *_): return source
        report = kpi.build_kpi_baseline_report(Sparse(), "2026-08-01", "2026-08-14")
        self.assertEqual("insufficient_data", report["search_console"]["evidence_sufficiency"]["status"])
        self.assertEqual(("2026-08-12", "2026-08-25"), kpi.resolve_period(None, None, today=date(2026, 8, 25)))
    def test_select_surface_rejects_arbitrary_sql(self):
        with self.assertRaises(kpi.KpiBaselineReadError): kpi._render_fixed_select("DELETE FROM curation_logs", ())
    def test_transport_accepts_only_zero_write_responses(self):
        class Completed:
            returncode = 0
            stdout = json.dumps([{"results": [], "meta": {"changed_db": False, "rows_written": 0}}])
        seen = []
        def runner(command, **_): seen.append(command); return Completed()
        result = kpi.WranglerFixedKpiReader(runner=runner).fetch("2026-08-01", "2026-08-14", "https://example.test/")
        self.assertEqual(6, len(seen)); self.assertEqual(6, len(result))
        class Changed:
            returncode = 0
            stdout = json.dumps([{"results": [], "meta": {"changed_db": True, "rows_written": 1}}])
        with self.assertRaises(kpi.KpiBaselineReadError):
            kpi.WranglerFixedKpiReader(runner=lambda *_, **__: Changed()).fetch("2026-08-01", "2026-08-14", "https://example.test/")

if __name__ == "__main__": unittest.main()
