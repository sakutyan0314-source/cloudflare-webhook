import importlib.util
import json
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).parents[1]

def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module

load("d1_read_only_session")
module = load("d1_backup_export_session")

ACCOUNT = "29837b450b7135d3766c22160e3a2504"
DATABASE = "99ef2162-afd8-459a-87eb-d197127528e2"
NAME = "zero-capital-insight-db"

class Response:
    def __init__(self, payload, status=200, content_type="application/json"):
        self.status, self.headers = status, {"Content-Type": content_type}
        self._body = json.dumps(payload).encode()
        self.closed = False
    def read(self): return self._body
    def close(self): self.closed = True

class D1BackupExportSessionTest(unittest.TestCase):
    def identity(self):
        return module.ApprovedD1BackupIdentity(ACCOUNT, DATABASE, NAME)

    def test_endpoint_is_built_only_from_exact_approved_identity(self):
        seen=[]
        def opener(request, timeout):
            seen.append((request.full_url, request.method, request.data))
            return Response({"success":True,"result":{"uuid":DATABASE,"name":NAME}})
        transport=module.FixedIdentityD1BackupTransport(self.identity(),"dummy_token",opener)
        transport.verify_identity()
        self.assertEqual(f"https://api.cloudflare.com/client/v4/accounts/{ACCOUNT}/d1/database/{DATABASE}", seen[0][0])
        self.assertEqual("GET",seen[0][1]); self.assertIsNone(seen[0][2])

    def test_invalid_or_mismatched_identity_is_rejected_without_fallback(self):
        for account, database, name in (("bad",DATABASE,NAME),(ACCOUNT,"bad",NAME),(ACCOUNT,DATABASE,"")):
            with self.assertRaises(module.D1BackupSafetyError): module.ApprovedD1BackupIdentity(account,database,name)
        for payload, code in (({"uuid":"0"*36,"name":NAME},"database_id_mismatch"),({"uuid":DATABASE,"name":"other"},"database_name_mismatch")):
            transport=module.FixedIdentityD1BackupTransport(self.identity(),"dummy",lambda *_args,p=payload,**_kwargs:Response({"success":True,"result":p}))
            with self.assertRaisesRegex(module.D1BackupSafetyError,code): transport.verify_identity()

    def test_no_account_discovery_or_candidate_selection_route_exists(self):
        calls=[]
        def opener(request, timeout):
            calls.append(request.full_url)
            return Response({"success":True,"result":{"uuid":DATABASE,"name":NAME}})
        transport=module.FixedIdentityD1BackupTransport(self.identity(),"dummy",opener)
        transport.verify_identity()
        self.assertEqual(1,len(calls)); self.assertNotEqual("https://api.cloudflare.com/client/v4/accounts",calls[0])
        with self.assertRaises(module.D1BackupSafetyError): transport._request("GET","/query")

    def test_bookmark_must_succeed_before_export_and_export_shape_is_fixed(self):
        responses=[Response({"success":True,"result":{"bookmark":"b"}}),Response({"success":True,"result":{"at_bookmark":"b","status":"complete","result":{"signed_url":"https://signed"}}})]
        seen=[]
        def opener(request, timeout):
            seen.append((request.full_url,request.method,request.data))
            return responses.pop(0)
        transport=module.FixedIdentityD1BackupTransport(self.identity(),"dummy",opener)
        transport.current_bookmark(); transport.export_polling()
        self.assertEqual("/time_travel/bookmark",seen[0][0].split(DATABASE,1)[1])
        self.assertEqual({"output_format":"polling"},json.loads(seen[1][2]))
        with self.assertRaises(module.D1BackupSafetyError): transport.export_polling("")

    def test_export_starts_once_then_polls_same_bookmark_until_complete(self):
        responses=[
            Response({"success":True,"result":{"at_bookmark":"poll-bookmark"}}),
            Response({"success":True,"result":{"at_bookmark":"poll-bookmark"}}),
            Response({"success":True,"result":{"at_bookmark":"poll-bookmark","status":"complete","result":{"signed_url":"https://download.example/export.sql"}}}),
        ]
        seen=[]
        def opener(request, timeout):
            seen.append(json.loads(request.data)); return responses.pop(0)
        transport=module.FixedIdentityD1BackupTransport(self.identity(),"opaque_token",opener)
        session=module.D1ExportPollingSession(transport,max_polls=2,poll_interval_seconds=0,clock=lambda:0,download_opener=lambda _url,timeout:Response({"unused":True}))
        completed=session.complete()
        self.assertEqual("poll-bookmark",completed.at_bookmark); self.assertEqual(3,len(seen)); self.assertEqual({"output_format":"polling"},seen[0]); self.assertEqual({"output_format":"polling","current_bookmark":"poll-bookmark"},seen[1]); self.assertEqual(seen[1],seen[2])
        with self.assertRaisesRegex(module.D1BackupSafetyError,"export_start_reuse_rejected"):session.complete()

    def test_export_complete_only_allows_download_and_keeps_url_token_out_of_errors(self):
        transport=module.FixedIdentityD1BackupTransport(self.identity(),"opaque_token",lambda *_args,**_kwargs:Response({"success":True,"result":{"at_bookmark":"b","status":"complete","result":{"signed_url":"https://download.example/opaque"}}}))
        session=module.D1ExportPollingSession(transport,poll_interval_seconds=0,download_opener=lambda _url,timeout:type("Download",(),{"read":lambda self:b"sqlite export", "close":lambda self:None})())
        completed=session.complete(); self.assertEqual(b"sqlite export",session.download(completed))
        with self.assertRaises(module.D1BackupSafetyError):session.download(module.D1ExportInProgress("b"))
        for bad in (
            {"success":True,"result":{"at_bookmark":"b","status":"error"}},
            {"success":True,"result":{"at_bookmark":"b","status":"unexpected"}},
            {"success":True,"result":{"at_bookmark":"b","status":"complete","result":{}}},
            {"success":True,"result":{}},
        ):
            response=module.D1BackupResponse(200,"application/json",1,bad)
            with self.assertRaises((module.D1BackupSafetyError,module.D1BackupTransportError)) as caught:module.parse_export_polling_response(response)
            self.assertNotIn("opaque_token",str(caught.exception)); self.assertNotIn("download.example",str(caught.exception))

    def test_safe_shape_diagnostic_reports_structure_without_values(self):
        bookmark="bookmark-not-for-output"; signed="https://download.example/not-for-output"
        response=module.D1BackupResponse(200,"application/json",1,{"success":True,"result":{"at_bookmark":bookmark,"status":"complete","result":{"signed_url":signed}},"errors":[],"messages":["not-for-output"]})
        diagnostic=module.safe_export_response_shape(response)
        self.assertEqual(200,diagnostic.http_status);self.assertIs(True,diagnostic.success);self.assertEqual("object",diagnostic.result_type);self.assertEqual(("at_bookmark","result","status"),diagnostic.result_fields);self.assertTrue(diagnostic.status_present);self.assertEqual("str",diagnostic.status_type);self.assertTrue(diagnostic.at_bookmark_present);self.assertTrue(diagnostic.signed_url_present);self.assertEqual(0,diagnostic.error_count);self.assertEqual(1,diagnostic.message_count)
        text=str(diagnostic);self.assertNotIn(bookmark,text);self.assertNotIn(signed,text);self.assertNotIn("not-for-output",text)
        malformed=module.safe_export_response_shape(module.D1BackupResponse(200,"application/json",1,{"success":"true","result":[]}))
        self.assertIsNone(malformed.success);self.assertEqual("list",malformed.result_type);self.assertFalse(malformed.status_present);self.assertFalse(malformed.at_bookmark_present);self.assertFalse(malformed.signed_url_present)

    def test_export_polling_limit_timeout_and_bookmark_change_fail_closed(self):
        def transport_for(responses):
            return module.FixedIdentityD1BackupTransport(self.identity(),"opaque",lambda *_args,**_kwargs:responses.pop(0))
        processing=lambda bookmark:Response({"success":True,"result":{"at_bookmark":bookmark}})
        with self.assertRaisesRegex(module.D1BackupSafetyError,"export_poll_limit_reached"):
            module.D1ExportPollingSession(transport_for([processing("b"),processing("b"),processing("b")]),max_polls=2,poll_interval_seconds=0,clock=lambda:0).complete()
        clocks=iter((0,1))
        with self.assertRaisesRegex(module.D1BackupSafetyError,"export_poll_timeout"):
            module.D1ExportPollingSession(transport_for([processing("b")]),max_polls=1,timeout_seconds=1,poll_interval_seconds=0,clock=lambda:next(clocks)).complete()
        with self.assertRaisesRegex(module.D1BackupSafetyError,"export_polling_bookmark_changed"):
            module.D1ExportPollingSession(transport_for([processing("b"),processing("other")]),max_polls=1,poll_interval_seconds=0,clock=lambda:0).complete()

    def test_malformed_or_failed_responses_stop_without_token_or_body_in_error(self):
        cases=[Response({"success":False}),Response({"success":True,"result":{}},content_type="text/html"),Response({"success":True,"result":{}},status=500)]
        for response in cases:
            transport=module.FixedIdentityD1BackupTransport(self.identity(),"opaque_token",lambda *_args,r=response,**_kwargs:r)
            with self.assertRaises((module.D1BackupSafetyError,module.D1BackupTransportError)) as caught: transport.verify_identity()
            self.assertNotIn("opaque_token",str(caught.exception)); self.assertNotIn("Authorization",str(caught.exception))

if __name__ == "__main__": unittest.main()
