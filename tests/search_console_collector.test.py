import importlib.util
import io
import json
import pathlib
import sqlite3
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout


ROOT = pathlib.Path(__file__).parents[1]
MODULE_PATH = ROOT / "scripts" / "search_console_collector.py"
FIXTURE_PATH = ROOT / "tests" / "fixtures" / "search-console-collector-fixture.json"
SPEC = importlib.util.spec_from_file_location("search_console_collector", MODULE_PATH)
collector = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = collector
SPEC.loader.exec_module(collector)


def page_request():
    return collector.SyncRequest(
        property_uri="https://example.test/", search_type="web", metric_family=collector.PAGE_DAILY,
        sync_kind="manual", metric_start_date="2026-08-01", metric_end_date="2026-08-01",
        dimensions=("date", "page"), row_limit=10,
    )


class IsolatedSqliteWriter:
    def __init__(self, connection):
        self.connection = connection

    def execute_batch(self, statements):
        try:
            self.connection.execute("BEGIN")
            results = []
            for statement in statements:
                cursor = self.connection.execute(statement.sql, statement.params)
                results.append({"changes": cursor.rowcount})
            self.connection.execute("COMMIT")
            return results
        except Exception:
            self.connection.execute("ROLLBACK")
            raise


class SearchConsoleCollectorTest(unittest.TestCase):
    def setUp(self):
        self.connection = sqlite3.connect(":memory:")
        self.connection.execute("PRAGMA foreign_keys = ON")
        for migration in sorted((ROOT / "migrations").glob("*.sql")):
            self.connection.executescript(migration.read_text(encoding="utf-8"))

    def tearDown(self):
        self.connection.close()

    def acquire_run(self, request=None):
        run = collector.build_sync_run(request or page_request(), "2026-08-11T00:00:00.000Z")
        writer = IsolatedSqliteWriter(self.connection)
        writer.execute_batch([collector.build_sync_run_insert(run)])
        run_id = self.connection.execute(
            "SELECT id FROM search_console_sync_runs WHERE idempotency_key=?", (run.idempotency_key,)
        ).fetchone()[0]
        return run, run_id, writer

    def test_idempotency_key_is_stable_and_insert_prevents_a_duplicate_run(self):
        request = page_request()
        first, first_id, writer = self.acquire_run(request)
        second = collector.build_sync_run(request, "2026-08-11T00:01:00.000Z")
        writer.execute_batch([collector.build_sync_run_insert(second)])
        self.assertEqual(first.idempotency_key, second.idempotency_key)
        self.assertEqual(1, self.connection.execute("SELECT COUNT(*) FROM search_console_sync_runs").fetchone()[0])
        self.assertEqual(first_id, self.connection.execute("SELECT id FROM search_console_sync_runs").fetchone()[0])

    def test_fixture_dry_run_is_deterministic_and_never_emits_query_text(self):
        report = collector.dry_run_from_fixture(FIXTURE_PATH, "https://example.test/", "2026-08-11T00:00:00.000Z")
        serialized = json.dumps(report, sort_keys=True)
        self.assertEqual("dry-run", report["mode"])
        self.assertFalse(report["changed_db"])
        self.assertEqual(0, report["rows_written"])
        self.assertNotIn("private fixture query", serialized)
        self.assertEqual(3, report["reports"][0]["rows_received"])
        self.assertEqual(2, report["reports"][1]["rows_received"])

    def test_cli_allows_only_fixture_dry_run_and_redacts_query_text(self):
        output = io.StringIO()
        with redirect_stdout(output):
            result = collector.main([
                "--dry-run", "--fixture", str(FIXTURE_PATH), "--property-uri", "https://example.test/",
                "--observed-at", "2026-08-11T00:00:00.000Z",
            ])
        self.assertEqual(0, result)
        self.assertNotIn("private fixture query", output.getvalue())
        with redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                collector.main([])

    def test_url_normalization_classifies_article_category_listing_top_and_unknown(self):
        cases = {
            "https://example.test/article/17?x=1#fragment": ("article", 17, "https://example.test/article/17"),
            "https://example.test/category/ai-automation": ("category", None, "https://example.test/category/ai-automation"),
            "https://example.test/?page=2": ("listing", None, "https://example.test/?page=2"),
            "https://example.test/": ("top", None, "https://example.test/"),
            "https://example.test/other?x=1#fragment": ("unknown", None, "https://example.test/other?x=1"),
        }
        for raw_url, expected in cases.items():
            normalized = collector.normalize_page_url(raw_url, "https://example.test/")
            self.assertEqual(expected, (normalized.url_kind, normalized.article_id, normalized.page_url))
        with self.assertRaises(ValueError):
            collector.normalize_page_url("https://outside.test/article/17", "https://example.test/")

    def test_metric_conversion_and_upsert_save_only_to_isolated_sqlite(self):
        fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
        request = page_request()
        metrics = collector.transform_metrics(fixture["page_daily"]["response"], request, "2026-08-11T00:00:00.000Z")
        _, run_id, writer = self.acquire_run(request)
        writer.execute_batch(collector.build_success_batch(run_id, metrics, "2026-08-11T00:01:00.000Z"))
        self.assertEqual(3, self.connection.execute("SELECT COUNT(*) FROM search_console_page_daily_metrics").fetchone()[0])
        status, saved = self.connection.execute(
            "SELECT status, rows_saved FROM search_console_sync_runs WHERE id=?", (run_id,)
        ).fetchone()
        self.assertEqual(("succeeded", 3), (status, saved))

    def test_transaction_failure_rolls_back_metric_rows_and_success_status(self):
        fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
        request = page_request()
        metrics = collector.transform_metrics(fixture["page_daily"]["response"], request, "2026-08-11T00:00:00.000Z")
        _, run_id, writer = self.acquire_run(request)
        statements = collector.build_success_batch(run_id, metrics, "2026-08-11T00:01:00.000Z")
        statements.insert(1, collector.SqlStatement("INSERT INTO missing_table VALUES (1)", ()))
        with self.assertRaises(sqlite3.OperationalError):
            writer.execute_batch(statements)
        self.assertEqual(0, self.connection.execute("SELECT COUNT(*) FROM search_console_page_daily_metrics").fetchone()[0])
        self.assertEqual("running", self.connection.execute(
            "SELECT status FROM search_console_sync_runs WHERE id=?", (run_id,)
        ).fetchone()[0])

    def test_failure_summary_is_bounded_and_does_not_include_error_message(self):
        summary = collector.error_summary("api_fetch", ValueError("secret-looking-error-message"), 429, True)
        self.assertEqual("stage=api_fetch;error_type=ValueError;http_status=429;retryable=true", summary)
        self.assertNotIn("secret-looking-error-message", summary)
        self.assertLessEqual(len(summary), 1000)

    def test_invalid_dimensions_and_metrics_stop_before_save_plan(self):
        bad = collector.SyncRequest(
            property_uri="https://example.test/", search_type="web", metric_family=collector.PAGE_DAILY,
            sync_kind="manual", metric_start_date="2026-08-01", metric_end_date="2026-08-01",
            dimensions=("page",), row_limit=10,
        )
        with self.assertRaises(ValueError):
            collector.build_sync_run(bad)
        with self.assertRaises(ValueError):
            collector.transform_metrics(
                {"rows": [{"keys": ["2026-08-01", "https://example.test/article/17"], "clicks": 1, "impressions": 2, "ctr": 1.5, "position": 1}]},
                page_request(), "2026-08-11T00:00:00.000Z",
            )


if __name__ == "__main__":
    unittest.main()
