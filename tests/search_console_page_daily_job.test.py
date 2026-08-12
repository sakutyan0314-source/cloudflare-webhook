import importlib.util
import pathlib
import sys
import unittest
from datetime import date


ROOT = pathlib.Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


collector = load("search_console_collector", ROOT / "scripts" / "search_console_collector.py")
writer_module = load("search_console_d1_writer", ROOT / "scripts" / "search_console_d1_writer.py")
job = load("search_console_page_daily_job", ROOT / "scripts" / "search_console_page_daily_job.py")


class FakeClient:
    def __init__(self, response=None, error=None):
        self.response, self.error, self.calls = response or {"rows": []}, error, []
    def property_permission_level(self): return "siteFullUser"
    def query_search_analytics(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        if self.error: raise self.error
        return self.response


class FakeWriter:
    def __init__(self, record, save_error=None):
        self.record, self.save_error, self.identity, self.failed, self.saved = record, save_error, [], [], []
    def verify_database_identity(self, name): self.identity.append(name)
    def acquire_sync_run(self, run): self.run = run; return self.record
    def save_acquired_metrics(self, record, metrics, completed_at):
        self.saved.append((record, metrics, completed_at))
        if self.save_error: raise self.save_error
        return writer_module.SaveResult(record.sync_run_id, "succeeded", len(metrics))
    def mark_failed(self, run_id, error, completed_at): self.failed.append((run_id, type(error).__name__, completed_at))


def record(status="running", inserted=True):
    return writer_module.SyncRunRecord(42, status, inserted)


class SearchConsolePageDailyJobTest(unittest.TestCase):
    def test_settlement_lag_and_scheduled_request_are_fixed(self):
        self.assertEqual("2026-08-09", job.settled_metric_date(date(2026, 8, 12)))
        request = job.scheduled_request("https://example.test/", "2026-08-09")
        self.assertEqual(("scheduled", "page_daily", ("date", "page"), 100), (request.sync_kind, request.metric_family, request.dimensions, request.row_limit))

    def test_success_uses_one_settled_day_and_writer_after_d1_assigned_run(self):
        client = FakeClient({"rows": [{"keys": ["2026-08-09", "https://example.test/article/17"], "clicks": 1, "impressions": 2, "ctr": .5, "position": 3}]})
        writer = FakeWriter(record())
        result = job.run_scheduled_page_daily(client, writer, "https://example.test/", as_of="2026-08-12", observed_at="2026-08-12T00:00:00.000Z")
        self.assertEqual({"status": "succeeded", "metric_date": "2026-08-09", "metric_family": "page_daily", "rows_received": 1, "rows_saved": 1}, result)
        self.assertEqual([job.EXPECTED_DATABASE_NAME], writer.identity)
        self.assertEqual(("2026-08-09", "2026-08-09", ["date", "page"]), (client.calls[0][0][0], client.calls[0][0][1], client.calls[0][0][2]))
        self.assertEqual(42, writer.saved[0][0].sync_run_id)

    def test_succeeded_is_idempotently_skipped_without_search_console_call(self):
        client, writer = FakeClient(), FakeWriter(record("succeeded", False))
        result = job.run_scheduled_page_daily(client, writer, "https://example.test/", as_of="2026-08-12")
        self.assertEqual("skipped", result["status"])
        self.assertEqual([], client.calls)
        self.assertEqual([], writer.saved)

    def test_running_or_failed_run_stops_without_auto_retry(self):
        for status in ("running", "failed"):
            with self.assertRaises(job.ScheduledCollectionError):
                job.run_scheduled_page_daily(FakeClient(), FakeWriter(record(status, False)), "https://example.test/", as_of="2026-08-12")

    def test_fetch_or_save_failure_marks_the_acquired_run_failed_without_details(self):
        writer = FakeWriter(record())
        with self.assertRaises(job.ScheduledCollectionError) as captured:
            job.run_scheduled_page_daily(FakeClient(error=ValueError("secret response text")), writer, "https://example.test/", as_of="2026-08-12")
        self.assertNotIn("secret response text", str(captured.exception))
        self.assertEqual(1, len(writer.failed))
        self.assertEqual((42, "ValueError"), writer.failed[0][:2])

    def test_workflow_is_scheduled_minimal_permission_and_never_pull_request_triggered(self):
        workflow = (ROOT / ".github" / "workflows" / "search-console-page-daily.yml").read_text()
        self.assertIn("contents: read", workflow)
        self.assertIn("schedule:", workflow)
        self.assertNotIn("pull_request:", workflow)
        self.assertIn("github.event_name != 'pull_request'", workflow)
        self.assertIn("SEARCH_CONSOLE_D1_WRITE_TOKEN", workflow)
        self.assertNotIn("cfat_", workflow)


if __name__ == "__main__":
    unittest.main()
