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

    def test_malformed_or_failed_responses_stop_without_token_or_body_in_error(self):
        cases=[Response({"success":False}),Response({"success":True,"result":{}},content_type="text/html"),Response({"success":True,"result":{}},status=500)]
        for response in cases:
            transport=module.FixedIdentityD1BackupTransport(self.identity(),"opaque_token",lambda *_args,r=response,**_kwargs:r)
            with self.assertRaises((module.D1BackupSafetyError,module.D1BackupTransportError)) as caught: transport.verify_identity()
            self.assertNotIn("opaque_token",str(caught.exception)); self.assertNotIn("Authorization",str(caught.exception))

if __name__ == "__main__": unittest.main()
