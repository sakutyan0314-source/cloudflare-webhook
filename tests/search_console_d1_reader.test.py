import importlib.util
import pathlib
import sys
import unittest


ROOT = pathlib.Path(__file__).parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


collector = load("search_console_collector", ROOT / "scripts" / "search_console_collector.py")
reader = load("search_console_d1_reader", ROOT / "scripts" / "search_console_d1_reader.py")


class FakeTransport:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def request(self, method, path, payload=None):
        self.calls.append((method, path, payload))
        return self.response


def response(rows, *, changed=False, written=0):
    return {"success": True, "result": [{"meta": {"changed_db": changed, "rows_written": written}, "results": rows}]}


class SearchConsoleD1ReaderTest(unittest.TestCase):
    def test_fixed_select_uses_parameters_and_readonly_d1_metadata(self):
        transport = FakeTransport(response([{"metric_date": "2026-08-08"}]))
        rows = reader.SearchConsoleD1Reader(transport).fetch_page_daily("https://example.test/", "web", "2026-08-08", "2026-08-09")
        self.assertEqual([{"metric_date": "2026-08-08"}], rows)
        method, path, payload = transport.calls[0]
        self.assertEqual(("POST", "/query"), (method, path))
        self.assertTrue(payload["sql"].lstrip().upper().startswith("SELECT"))
        self.assertEqual(["https://example.test/", "web", "2026-08-08", "2026-08-09"], payload["params"])

    def test_rejects_nonselect_and_multiple_statement_inputs(self):
        with self.assertRaises(reader.D1ReadSafetyError):
            reader._validate_fixed_select(collector.SqlStatement("UPDATE x SET y=1", ()))
        with self.assertRaises(reader.D1ReadSafetyError):
            reader._validate_fixed_select(collector.SqlStatement("SELECT 1; DELETE FROM x", ()))

    def test_rejects_d1_write_metadata_or_bad_response(self):
        for reply in (response([], changed=True), response([], written=1), {"success": True, "result": []}):
            with self.assertRaises(reader.D1ReadSafetyError):
                reader.SearchConsoleD1Reader(FakeTransport(reply)).fetch_page_daily("https://example.test/", "web", "2026-08-08", "2026-08-09")

    def test_invalid_bounds_and_property_stop_before_transport(self):
        transport = FakeTransport(response([]))
        subject = reader.SearchConsoleD1Reader(transport)
        with self.assertRaises(ValueError):
            subject.fetch_page_daily("https://example.test", "web", "2026-08-08", "2026-08-09")
        with self.assertRaises(ValueError):
            subject.fetch_page_daily("https://example.test/", "web", "2026-08-10", "2026-08-09")
        self.assertEqual([], transport.calls)


if __name__ == "__main__":
    unittest.main()
