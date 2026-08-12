import importlib.util
import pathlib
import sys
import unittest


ROOT = pathlib.Path(__file__).parents[1]
COLLECTOR_PATH = ROOT / "scripts" / "search_console_collector.py"
WRITER_PATH = ROOT / "scripts" / "search_console_d1_writer.py"


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


collector = load("search_console_collector", COLLECTOR_PATH)
writer_module = load("search_console_d1_writer", WRITER_PATH)


def request(family=collector.PAGE_DAILY):
    return collector.SyncRequest(
        property_uri="https://example.test/", search_type="web", metric_family=family,
        sync_kind="manual", metric_start_date="2026-08-01", metric_end_date="2026-08-01",
        dimensions=("date", "page") if family == collector.PAGE_DAILY else ("date", "query", "page"), row_limit=5,
    )


class FakeTransport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, method, path, payload=None):
        self.calls.append((method, path, payload))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def batch(*sets):
    return {"success": True, "result": list(sets)}


def rows(*items, changes=0):
    return {"results": list(items), "meta": {"changes": changes}}


class SearchConsoleD1WriterTest(unittest.TestCase):
    def setUp(self):
        self.config = writer_module.D1RuntimeConfig("account-id", "nonprod-db-id", "token-never-log-this")

    def test_config_requires_all_environment_values_without_exposing_them(self):
        with self.assertRaises(writer_module.D1WriterConfigurationError) as captured:
            writer_module.D1RuntimeConfig.from_environment({"CLOUDFLARE_API_TOKEN": "secret-value"})
        self.assertNotIn("secret-value", str(captured.exception))

    def test_identity_uses_get_and_rejects_unapproved_name(self):
        transport = FakeTransport([{"success": True, "result": {"name": "approved-test-db"}}])
        subject = writer_module.SearchConsoleD1Writer(self.config, transport)
        subject.verify_database_identity("approved-test-db")
        self.assertEqual(("GET", "", None), transport.calls[0])
        bad = writer_module.SearchConsoleD1Writer(self.config, FakeTransport([{"success": True, "result": {"name": "wrong"}}]))
        with self.assertRaises(writer_module.D1WriterSafetyError):
            bad.verify_database_identity("approved-test-db")

    def test_acquire_uses_db_assigned_sync_run_id_after_insert_and_key_select(self):
        transport = FakeTransport([batch(rows(changes=1), rows({"id": 42, "status": "running"}))])
        subject = writer_module.SearchConsoleD1Writer(self.config, transport)
        run = collector.build_sync_run(request(), "2026-08-11T00:00:00.000Z")
        record = subject.acquire_sync_run(run)
        self.assertEqual((42, "running", True), (record.sync_run_id, record.status, record.inserted))
        payload = transport.calls[0][2]
        self.assertEqual(2, len(payload["batch"]))
        self.assertIn("INSERT INTO search_console_sync_runs", payload["batch"][0]["sql"])
        self.assertIn("SELECT id, status", payload["batch"][1]["sql"])
        self.assertEqual([run.idempotency_key], payload["batch"][1]["params"])

    def test_succeeded_key_is_skipped_and_running_or_failed_keys_do_not_auto_retry(self):
        run = collector.build_sync_run(request(), "2026-08-11T00:00:00.000Z")
        succeeded = writer_module.SearchConsoleD1Writer(self.config, FakeTransport([batch(rows(changes=0), rows({"id": 7, "status": "succeeded"}))]))
        result = succeeded.save_metrics(run, [])
        self.assertTrue(result.skipped)
        for status in ("running", "failed"):
            subject = writer_module.SearchConsoleD1Writer(self.config, FakeTransport([batch(rows(changes=0), rows({"id": 7, "status": status}))]))
            with self.assertRaises(writer_module.D1WriterSafetyError):
                subject.save_metrics(run, [])

    def test_metrics_and_succeeded_are_one_batch_using_the_d1_assigned_id(self):
        metric = collector.MetricRow("2026-08-01", "https://example.test/", "web", "https://example.test/article/17", "article", 17, 1, 2, .5, 3., "2026-08-11T00:00:00.000Z")
        transport = FakeTransport([
            batch(rows(changes=1), rows({"id": 88, "status": "running"})),
            batch(rows(), rows()),
        ])
        subject = writer_module.SearchConsoleD1Writer(self.config, transport)
        result = subject.save_metrics(collector.build_sync_run(request(), "2026-08-11T00:00:00.000Z"), [metric], "2026-08-11T00:01:00.000Z")
        self.assertEqual((88, "succeeded", 1), (result.sync_run_id, result.status, result.rows_saved))
        payload = transport.calls[1][2]["batch"]
        self.assertEqual(2, len(payload))
        self.assertIn("search_console_page_daily_metrics", payload[0]["sql"])
        self.assertEqual(88, payload[0]["params"][0])
        self.assertIn("SET status='succeeded'", payload[1]["sql"])
        self.assertEqual(88, payload[1]["params"][-1])

    def test_write_error_records_only_safe_failure_summary(self):
        run = collector.build_sync_run(request(), "2026-08-11T00:00:00.000Z")
        error = writer_module.D1ApiError("http_request", 503)
        sensitive_metric = collector.MetricRow(
            "2026-08-01", "https://example.test/", "web", "https://example.test/article/17",
            "article", 17, 1, 2, .5, 3., "2026-08-11T00:00:00.000Z", "sensitive query text",
        )
        transport = FakeTransport([
            batch(rows(changes=1), rows({"id": 4, "status": "running"})), error,
            batch(rows()),
        ])
        subject = writer_module.SearchConsoleD1Writer(self.config, transport)
        with self.assertRaises(writer_module.D1ApiError):
            subject.save_metrics(run, [sensitive_metric])
        failure_payload = transport.calls[2][2]["batch"][0]
        self.assertIn("SET status='failed'", failure_payload["sql"])
        summary = failure_payload["params"][0]
        self.assertIn("http_status=503", summary)
        self.assertNotIn("token-never-log-this", str(transport.calls))
        self.assertNotIn("sensitive query text", summary)
        self.assertNotIn("response body", summary)

    def test_malformed_response_stops_without_using_response_body(self):
        subject = writer_module.SearchConsoleD1Writer(self.config, FakeTransport([{"success": True, "result": "bad"}]))
        with self.assertRaises(writer_module.D1WriterSafetyError) as captured:
            subject.acquire_sync_run(collector.build_sync_run(request(), "2026-08-11T00:00:00.000Z"))
        self.assertNotIn("bad", str(captured.exception))


if __name__ == "__main__":
    unittest.main()
