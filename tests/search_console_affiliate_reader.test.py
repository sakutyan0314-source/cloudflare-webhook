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


load("search_console_collector", ROOT / "scripts" / "search_console_collector.py")
load("search_console_d1_reader", ROOT / "scripts" / "search_console_d1_reader.py")
reader = load("search_console_affiliate_reader", ROOT / "scripts" / "search_console_affiliate_reader.py")


class FakeTransport:
    def __init__(self, response):
        self.response, self.calls = response, []

    def request(self, method, path, payload=None):
        self.calls.append((method, path, payload))
        return self.response


def response(page_rows=None, affiliate_rows=None, *, changed=False, written=0):
    return {"success": True, "result": [
        {"meta": {"changed_db": changed, "rows_written": written}, "results": page_rows or []},
        {"meta": {"changed_db": changed, "rows_written": written}, "results": affiliate_rows or []},
    ]}


class SearchConsoleAffiliateReaderTest(unittest.TestCase):
    def test_uses_only_two_fixed_selects(self):
        transport = FakeTransport(response([{"article_id": 17}], [{"article_id": 17}]))
        pages, affiliates = reader.SearchConsoleAffiliateReader(transport).fetch_article_metrics(
            "https://example.test/", "web", "2026-08-08", "2026-08-09"
        )
        self.assertEqual([{"article_id": 17}], pages)
        self.assertEqual([{"article_id": 17}], affiliates)
        method, path, payload = transport.calls[0]
        self.assertEqual(("POST", "/query"), (method, path))
        self.assertEqual(2, len(payload["batch"]))
        for statement in payload["batch"]:
            self.assertTrue(statement["sql"].lstrip().upper().startswith("SELECT"))
            self.assertNotIn(";", statement["sql"])
        self.assertIn("url_kind='article'", payload["batch"][0]["sql"])

    def test_stops_on_write_metadata_or_invalid_response(self):
        for reply in (response(changed=True), response(written=1), {"success": True, "result": []}):
            with self.assertRaises(reader.D1ReadSafetyError):
                reader.SearchConsoleAffiliateReader(FakeTransport(reply)).fetch_article_metrics(
                    "https://example.test/", "web", "2026-08-08", "2026-08-09"
                )

    def test_invalid_request_stops_before_transport(self):
        transport = FakeTransport(response())
        with self.assertRaises(ValueError):
            reader.SearchConsoleAffiliateReader(transport).fetch_article_metrics(
                "https://example.test", "web", "2026-08-08", "2026-08-09"
            )
        self.assertEqual([], transport.calls)


if __name__ == "__main__":
    unittest.main()
