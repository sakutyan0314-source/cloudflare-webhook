import importlib.util
import pathlib
import unittest
from datetime import date
from unittest.mock import Mock


MODULE_PATH = pathlib.Path(__file__).parents[1] / "scripts" / "search_console_client.py"
SPEC = importlib.util.spec_from_file_location("search_console_client", MODULE_PATH)
search_console_client = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(search_console_client)


class SearchConsoleClientTest(unittest.TestCase):
    def setUp(self):
        self.request = Mock()
        self.request.execute.return_value = {"rows": [{"keys": ["/article/17"]}]}
        self.search_analytics = Mock(spec=["query"])
        self.search_analytics.query.return_value = self.request
        self.sites_request = Mock()
        self.sites_request.execute.return_value = {"siteEntry": []}
        self.sites = Mock(spec=["list"])
        self.sites.list.return_value = self.sites_request
        self.service = Mock(spec=["searchanalytics", "sites"])
        self.service.searchanalytics.return_value = self.search_analytics
        self.service.sites.return_value = self.sites
        self.client = search_console_client.SearchConsoleClient(
            self.service, "https://example.com/"
        )

    def test_queries_only_read_endpoint_with_requested_dimensions(self):
        result = self.client.query_search_analytics(
            date(2026, 8, 1), "2026-08-10", ["page", "query", "device"], row_limit=50
        )
        self.assertEqual({"rows": [{"keys": ["/article/17"]}]}, result)
        self.search_analytics.query.assert_called_once_with(
            siteUrl="https://example.com/",
            body={
                "startDate": "2026-08-01", "endDate": "2026-08-10",
                "dimensions": ["page", "query", "device"], "rowLimit": 50,
                "startRow": 0, "type": "web",
            },
        )
        self.assertFalse(hasattr(self.service, "sitemaps"))

    def test_query_supports_paging_filters_and_optional_api_fields(self):
        filters = [{"filters": [{"dimension": "page", "operator": "equals", "expression": "/article/17"}]}]
        self.client.query_search_analytics(
            "2026-08-01", "2026-08-10", ["page"], start_row=25,
            dimension_filter_groups=filters, aggregation_type="byPage", data_state="all",
        )
        body = self.search_analytics.query.call_args.kwargs["body"]
        self.assertEqual(filters, body["dimensionFilterGroups"])
        self.assertEqual("byPage", body["aggregationType"])
        self.assertEqual("all", body["dataState"])

    def test_list_sites_uses_read_only_sites_list(self):
        self.assertEqual({"siteEntry": []}, self.client.list_sites())
        self.sites.list.assert_called_once_with()
        self.sites_request.execute.assert_called_once_with()

    def test_invalid_dates_dimensions_and_pagination_are_rejected_before_api_call(self):
        invalid_cases = [
            lambda: self.client.query_search_analytics("2026-08-11", "2026-08-10"),
            lambda: self.client.query_search_analytics("invalid", "2026-08-10"),
            lambda: self.client.query_search_analytics("2026-08-01", "2026-08-10", ["unknown"]),
            lambda: self.client.query_search_analytics("2026-08-01", "2026-08-10", ["page", "page"]),
            lambda: self.client.query_search_analytics("2026-08-01", "2026-08-10", row_limit=0),
        ]
        for invoke in invalid_cases:
            with self.assertRaises((TypeError, ValueError)):
                invoke()
        self.search_analytics.query.assert_not_called()

    def test_environment_configuration_requires_values_without_loading_a_key(self):
        with self.assertRaises(search_console_client.SearchConsoleConfigurationError):
            search_console_client.SearchConsoleClient.from_environment({})
        with self.assertRaises(search_console_client.SearchConsoleConfigurationError):
            search_console_client.SearchConsoleClient.from_environment({
                "SEARCH_CONSOLE_PROPERTY_URL": "https://example.com/",
                "GOOGLE_APPLICATION_CREDENTIALS": "/not/a/real/key.json",
            })

    def test_property_must_be_exact_url_prefix(self):
        with self.assertRaises(search_console_client.SearchConsoleConfigurationError):
            search_console_client.SearchConsoleClient(self.service, "https://example.com")


if __name__ == "__main__":
    unittest.main()
