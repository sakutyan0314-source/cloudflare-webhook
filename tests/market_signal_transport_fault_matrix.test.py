"""No-network fault matrix for Market Analysis transport and final CLI output."""
import importlib.util, io, json, pathlib, sys, unittest
from contextlib import redirect_stdout
from unittest.mock import patch
from urllib.error import HTTPError, URLError
import http.client

ROOT = pathlib.Path(__file__).parents[1]

def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec); assert spec and spec.loader
    sys.modules[name] = module; spec.loader.exec_module(module); return module

load("search_console_improvement_candidates"); load("topic_candidate"); load("market_signal_serp_adapter")
load("market_signal_report"); load("market_signal_analysis"); load("market_signal_analysis_adapter")
openai = load("openai_market_signal_analysis_adapter")
load("search_console_collector"); load("search_console_d1_reader"); load("ai_recommendation_d1_reader")
load("search_console_affiliate_reader"); load("search_console_improvement_candidate_review")
load("phase2a_candidate_read_cli"); cli = load("market_signal_report_cli")


class Response:
    def __init__(self, raw=None, error=None): self.raw, self.error = raw, error
    def __enter__(self): return self
    def __exit__(self, *_): return False
    def read(self):
        if self.error: raise self.error
        return self.raw


def response_json(text="{}"):
    return {"status": "completed", "output": [{"type": "reasoning"}, {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": text}]}]}


class TransportFaultMatrix(unittest.TestCase):
    def call_transport(self, opener):
        transport = openai.OpenAiMarketSignalAnalysisTransport(api_key="test-key")
        with patch.object(openai, "urlopen", opener):
            return transport.analyze({}, model_id="gpt-5.6-terra", max_input_tokens=1800,
                                     max_output_tokens=600, timeout_seconds=20, store=False, tools=None)

    def test_completed_response_is_one_request(self):
        calls = []
        def opener(*args, **kwargs): calls.append((args, kwargs)); return Response(json.dumps(response_json()).encode())
        self.assertEqual({}, self.call_transport(opener)); self.assertEqual(1, len(calls))

    def test_http_errors_keep_status_and_safe_diagnostic(self):
        for status in (400, 401, 403, 429, 500):
            with self.subTest(status=status):
                body = json.dumps({"error": {"type": "api_error", "code": "safe_code", "message": "secret: hidden"}}).encode()
                error = HTTPError("https://api.openai.com/v1/responses", status, "failure", None, io.BytesIO(body))
                with self.assertRaises(openai.OpenAiMarketSignalAnalysisResponseError) as raised:
                    self.call_transport(lambda *_args, **_kwargs: (_ for _ in ()).throw(error))
                self.assertEqual("http_error", raised.exception.code)
                self.assertEqual(status, raised.exception.diagnostic["http_status"])
                self.assertEqual("known", raised.exception.diagnostic["delivery_state"])
                self.assertNotIn("hidden", str(raised.exception.diagnostic))

    def test_transport_faults_are_typed_and_delivery_safe(self):
        cases = [
            (ConnectionResetError(), "connection_reset", "unknown"),
            (http.client.RemoteDisconnected(), "connection_closed", "unknown"),
            (URLError("unavailable"), "transport_exception", "unknown"),
            (OSError(), "transport_exception", "unknown"),
            (RuntimeError(), "delivery_state_unknown", "unknown"),
        ]
        for fault, code, delivery in cases:
            with self.subTest(code=code):
                with self.assertRaises(Exception) as raised:
                    self.call_transport(lambda *_args, **_kwargs: (_ for _ in ()).throw(fault))
                self.assertEqual(code, getattr(raised.exception, "code", None))
                self.assertEqual(delivery, getattr(raised.exception, "diagnostic", {}).get("delivery_state"))
        with self.assertRaises(TimeoutError):
            self.call_transport(lambda *_args, **_kwargs: (_ for _ in ()).throw(TimeoutError()))
        with self.assertRaises(TimeoutError):
            self.call_transport(lambda *_args, **_kwargs: Response(error=TimeoutError()))

    def test_response_read_decode_and_non_object_are_typed(self):
        cases = [
            (Response(error=OSError()), "unknown"),
            (Response(b"\xff"), "known"),
            (Response(b"not-json"), "known"),
            (Response(b"[]"), "known"),
        ]
        for response, delivery in cases:
            with self.subTest(delivery=delivery):
                with self.assertRaises(openai.OpenAiMarketSignalAnalysisTransportError) as raised:
                    self.call_transport(lambda *_args, **_kwargs: response)
                self.assertEqual("response_read_failed", raised.exception.code)
                self.assertEqual(delivery, raised.exception.diagnostic["delivery_state"])

    def test_credential_and_provider_configuration_are_typed_before_request(self):
        with self.assertRaises(openai.OpenAiMarketSignalAnalysisError) as credential:
            openai.OpenAiMarketSignalAnalysisTransport(api_key="")
        self.assertEqual("credential_error", credential.exception.code)
        self.assertEqual("not_attempted", credential.exception.diagnostic["delivery_state"])
        transport = openai.OpenAiMarketSignalAnalysisTransport(api_key="test-key")
        with self.assertRaises(openai.OpenAiMarketSignalAnalysisError) as configuration:
            transport.analyze({}, model_id="wrong", max_input_tokens=1800, max_output_tokens=600,
                              timeout_seconds=20, store=False, tools=None)
        self.assertEqual("provider_configuration_error", configuration.exception.code)
        self.assertEqual("not_attempted", configuration.exception.diagnostic["delivery_state"])


class FinalCliFaultMatrix(unittest.TestCase):
    args = ["--query", "Microsoft 365 Copilot エージェント", "--observed-at", "2026-08-25T00:00:00Z",
            "--serp-fixture", "tests/fixtures/market-signal-serp-fixture.json", "--own-site-fixture",
            "tests/fixtures/market-signal-own-site-fixture.json", "--live-analysis", "--format", "json"]

    def run_cli(self, factory):
        original = cli.OpenAiMarketSignalAnalysisTransport; cli.OpenAiMarketSignalAnalysisTransport = factory
        output = io.StringIO()
        try:
            with redirect_stdout(output): result = cli.main(self.args)
        finally:
            cli.OpenAiMarketSignalAnalysisTransport = original
        return result, json.loads(output.getvalue())

    def test_all_known_fault_codes_reach_final_json_without_content(self):
        responses = [
            ("timeout", lambda: TimeoutError()),
            ("connection_reset", lambda: openai.OpenAiMarketSignalAnalysisTransportError("connection_reset", delivery_state="unknown")),
            ("connection_closed", lambda: openai.OpenAiMarketSignalAnalysisTransportError("connection_closed", delivery_state="unknown")),
            ("response_read_failed", lambda: openai.OpenAiMarketSignalAnalysisTransportError("response_read_failed", delivery_state="known")),
            ("transport_exception", lambda: openai.OpenAiMarketSignalAnalysisTransportError("transport_exception", delivery_state="unknown")),
            ("delivery_state_unknown", lambda: openai.OpenAiMarketSignalAnalysisTransportError("delivery_state_unknown", delivery_state="unknown")),
            ("credential_error", lambda: openai.OpenAiMarketSignalAnalysisError("safe", code="credential_error", diagnostic={"delivery_state":"not_attempted"})),
            ("provider_configuration_error", lambda: openai.OpenAiMarketSignalAnalysisError("safe", code="provider_configuration_error", diagnostic={"delivery_state":"not_attempted"})),
            ("http_error", lambda: openai.OpenAiMarketSignalAnalysisResponseError("http_error", {"http_status":400,"delivery_state":"known"})),
            ("incomplete", lambda: openai.OpenAiMarketSignalAnalysisResponseError("incomplete", {"delivery_state":"known"})),
            ("refusal", lambda: openai.OpenAiMarketSignalAnalysisResponseError("refusal", {"delivery_state":"known"})),
            ("missing_output_text", lambda: openai.OpenAiMarketSignalAnalysisResponseError("missing_output_text", {"delivery_state":"known"})),
            ("ambiguous_output_text", lambda: openai.OpenAiMarketSignalAnalysisResponseError("ambiguous_output_text", {"delivery_state":"known"})),
            ("unknown_output_type", lambda: openai.OpenAiMarketSignalAnalysisResponseError("unknown_output_type", {"delivery_state":"known"})),
            ("unknown_content_type", lambda: openai.OpenAiMarketSignalAnalysisResponseError("unknown_content_type", {"delivery_state":"known"})),
            ("malformed_json", lambda: openai.OpenAiMarketSignalAnalysisResponseError("malformed_json", {"delivery_state":"known"})),
        ]
        for code, error_factory in responses:
            class Failing:
                def analyze(self, *_args, **_kwargs): raise error_factory()
            with self.subTest(code=code):
                result, value = self.run_cli(lambda: Failing())
                self.assertEqual(1, result); self.assertEqual(code, value["failure_classification"])
                self.assertNotIn("secret", str(value).lower()); self.assertNotIn("response_id", str(value))

    def test_schema_policy_failure_reaches_final_json(self):
        class Invalid:
            def analyze(self, *_args, **_kwargs): return {"schema_version":"wrong"}
        result, value = self.run_cli(lambda: Invalid())
        self.assertEqual(1, result); self.assertEqual("schema_or_policy_failure", value["failure_classification"])


if __name__ == "__main__": unittest.main()
