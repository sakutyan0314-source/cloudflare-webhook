import importlib.util
import json
import pathlib
import sys
import unittest
from urllib.error import URLError


ROOT = pathlib.Path(__file__).parents[1]
PATH = ROOT / "scripts" / "d1_read_only_session.py"
spec = importlib.util.spec_from_file_location("d1_read_only_session", PATH)
module = importlib.util.module_from_spec(spec)
assert spec and spec.loader
sys.modules["d1_read_only_session"] = module
spec.loader.exec_module(module)


class Response:
    def __init__(self, status=200, content_type="application/json", body=b'{"success":true,"result":{}}'):
        self.status, self.headers, self._body, self.closed = status, {"Content-Type": content_type}, body, False
    def read(self): return self._body
    def close(self): self.closed = True


class D1ReadOnlySessionTest(unittest.TestCase):
    def test_token_normalization_only_trims_outer_whitespace(self):
        self.assertEqual("cfat_abc-._123", module.normalize_d1_read_token(" \tcfat_abc-._123\r\n"))
        for value in ("", " \r\n", "cfat_a\ncfat_b", "cfat_a\rcfat_b", "cfat_$", None):
            with self.assertRaises(module.D1ReadTokenError): module.normalize_d1_read_token(value)

    def test_header_is_constructed_without_exposure(self):
        header = module.authorization_header("cfat_dummy")
        self.assertEqual("Bearer cfat_dummy", header)
        with self.assertRaises(module.D1ReadTokenError) as captured: module.authorization_header("cfat_bad\nvalue")
        self.assertNotIn("cfat_bad", str(captured.exception))

    def test_session_keeps_one_token_until_final_close_and_clears_once(self):
        calls=[]
        session = module.D1ReadTokenSession.from_clipboard(lambda: "cfat_dummy\n", lambda: calls.append("cleared"))
        self.assertEqual("cfat_dummy", session.token)
        self.assertEqual("cfat_dummy", session.token)
        self.assertEqual([], calls)
        session.close(); session.close()
        self.assertEqual(["cleared"], calls)
        with self.assertRaises(module.D1ReadTokenError): _ = session.token

    def test_http_json_success_and_metadata_are_read_only(self):
        response = Response(body=json.dumps({"success":True,"result":[{"success":True,"results":[],"meta":{"changed_db":False,"rows_written":0}}]}).encode())
        transport = module.D1ReadOnlyRestTransport("account", "database", "cfat_dummy", opener=lambda *_args, **_kwargs: response)
        parsed = transport.fixed_select_batch(({"sql":"SELECT 1", "params":[]},))
        sets = module.validate_read_only_result_sets(parsed.payload, 1)
        self.assertEqual(200, parsed.status); self.assertEqual("application/json", parsed.content_type); self.assertEqual(1, len(sets)); self.assertTrue(response.closed)

    def test_request_builder_uses_single_shape_for_one_select_and_batch_for_many(self):
        single_diagnostic, single_payload=module.build_fixed_select_request(({"sql":"SELECT ?","params":[1]},))
        batch_diagnostic, batch_payload=module.build_fixed_select_request(({"sql":"SELECT 1","params":[]},{"sql":"SELECT 2","params":[]}))
        self.assertEqual(("single",1),(single_diagnostic.payload_shape,single_diagnostic.statement_count)); self.assertEqual({"sql":"SELECT ?","params":[1]},single_payload)
        self.assertEqual(("batch",2),(batch_diagnostic.payload_shape,batch_diagnostic.statement_count)); self.assertEqual("batch",next(iter(batch_payload)))

    def test_bookmark_is_the_only_additional_read_only_route(self):
        response = Response(body=b'{"success":true,"result":{"bookmark":"safe-bookmark"}}')
        transport = module.D1ReadOnlyRestTransport("account", "database", "cfat_dummy", opener=lambda *_args, **_kwargs: response)
        bookmark = transport.current_bookmark()
        self.assertEqual(200, bookmark.status)
        self.assertEqual("safe-bookmark", bookmark.payload["result"]["bookmark"])

    def test_http_failure_and_parse_cases_fail_closed_without_body(self):
        cases = [
            Response(401, body=b'{"success":false,"errors":[{"message":"secret-like body"}]}'),
            Response(403, body=b'{"success":false}'), Response(500, body=b'{"success":false}'),
            Response(200, "text/html", b"<html>not-json</html>"), Response(200, "application/json", b""),
            Response(200, "application/json", b"{")
        ]
        for response in cases:
            transport = module.D1ReadOnlyRestTransport("account", "database", "cfat_dummy", opener=lambda *_args, r=response, **_kwargs: r)
            with self.assertRaises(module.D1ReadTransportError) as captured: transport.identity()
            self.assertNotIn("secret-like body", str(captured.exception))
        transport = module.D1ReadOnlyRestTransport("account", "database", "cfat_dummy", opener=lambda *_args, **_kwargs: (_ for _ in ()).throw(URLError("network")))
        with self.assertRaises(module.D1ReadTransportError) as captured: transport.identity()
        self.assertEqual("transport_exception", captured.exception.code)

    def test_http_400_json_diagnostic_exposes_only_safe_metadata(self):
        body=json.dumps({"success":False,"errors":[{"code":7500,"message":"SQL syntax error near secret-like body"}]}).encode()
        transport=module.D1ReadOnlyRestTransport("account","database","cfat_dummy",opener=lambda *_args,**_kwargs:Response(400,body=body))
        with self.assertRaises(module.D1ReadTransportError) as captured: transport.fixed_select_batch(({"sql":"SELECT ?","params":[1]},))
        error=captured.exception
        self.assertEqual("invalid_sql_shape",error.code); self.assertEqual(400,error.status)
        self.assertEqual((400,"application/json",False,1,"7500","invalid_sql_shape"),(error.diagnostic.http_status,error.diagnostic.content_type,error.diagnostic.success_flag,error.diagnostic.error_count,error.diagnostic.error_code,error.diagnostic.error_message_class))
        self.assertNotIn("secret-like body",str(error)); self.assertNotIn("secret-like body",repr(error.diagnostic))

    def test_400_non_json_empty_and_other_statuses_remain_fail_closed(self):
        cases=[(Response(400,"text/plain",b"not json"),"unexpected_content_type"),(Response(400,"application/json",b""),"empty_response"),(Response(401,body=b'{"success":false}'),"http_status"),(Response(403,body=b'{"success":false}'),"http_status"),(Response(500,body=b'{"success":false}'),"http_status")]
        for response, code in cases:
            transport=module.D1ReadOnlyRestTransport("account","database","cfat_dummy",opener=lambda *_args,r=response,**_kwargs:r)
            with self.assertRaises(module.D1ReadTransportError) as captured: transport.identity()
            self.assertEqual(code,captured.exception.code)

    def test_http_400_error_messages_map_to_safe_categories_without_text(self):
        cases=[("malformed request payload","malformed_request"),("bind parameter count mismatch","parameter_mismatch"),("unsupported query operation","unsupported_query"),("database not found","database_not_found"),("invalid account database id","account_or_database_mismatch"),("unrecognized validation fault","cloudflare_api_validation_error"),(None,"unknown_http_400")]
        for message, expected in cases:
            errors=[] if message is None else [{"code":1000,"message":message}]
            body=json.dumps({"success":False,"errors":errors}).encode()
            transport=module.D1ReadOnlyRestTransport("account","database","cfat_dummy",opener=lambda *_args,b=body,**_kwargs:Response(400,body=b))
            with self.assertRaises(module.D1ReadTransportError) as captured: transport.identity()
            self.assertEqual(expected,captured.exception.code)
            if message is not None: self.assertNotIn(message,str(captured.exception))

    def test_api_success_false_and_metadata_write_signal_stop(self):
        api_false = Response(body=b'{"success":false,"result":{}}')
        transport = module.D1ReadOnlyRestTransport("account", "database", "cfat_dummy", opener=lambda *_args, **_kwargs: api_false)
        with self.assertRaises(module.D1ReadTransportError) as captured: transport.identity()
        self.assertEqual("api_success_false", captured.exception.code)
        for changed, rows in ((True, 0), (False, 1)):
            payload={"success":True,"result":[{"success":True,"results":[],"meta":{"changed_db":changed,"rows_written":rows}}]}
            with self.assertRaises(module.D1ReadSafetyError): module.validate_read_only_result_sets(payload, 1)

    def test_rejects_non_fixed_or_multiple_select_sql_before_http(self):
        calls=[]
        transport = module.D1ReadOnlyRestTransport("account", "database", "cfat_dummy", opener=lambda *_args, **_kwargs: calls.append(1))
        for sql in ("UPDATE x SET y=1", "SELECT 1; DELETE FROM x", ""):
            with self.assertRaises(module.D1ReadSafetyError): transport.fixed_select_batch(({"sql":sql},))
        self.assertEqual([], calls)

    def test_static_request_shape_rejects_invalid_sql_and_parameter_count_before_http(self):
        diagnostic=module.validate_fixed_select_batch(({"sql":"SELECT ? AS value","params":[1]}, {"sql":"SELECT 'literal ?' AS value","params":[]}))
        self.assertEqual(("/query","batch",2,True,True,True),(diagnostic.endpoint_path,diagnostic.payload_shape,diagnostic.statement_count,diagnostic.sql_field_present,diagnostic.params_field_present,diagnostic.validator_passed))
        for statement, code in (({"sql":"SELECT ?","params":[]},"parameter_mismatch"),({"sql":"SELECT 1; SELECT 2","params":[]},"invalid_sql_shape"),({"sql":"UPDATE x SET y=1","params":[]},"invalid_sql_shape")):
            with self.assertRaisesRegex(module.D1ReadSafetyError,code): module.validate_fixed_select_batch((statement,))


if __name__ == "__main__":
    unittest.main()
