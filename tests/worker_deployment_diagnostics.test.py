import importlib.util
import pathlib
import sys
import unittest

P=pathlib.Path(__file__).parents[1]/"scripts/worker_deployment_diagnostics.py"; S=importlib.util.spec_from_file_location("diag",P); diag=importlib.util.module_from_spec(S); sys.modules[S.name]=diag; S.loader.exec_module(diag)
def payload(versions): return {"success":True,"result":{"deployments":[{"versions":versions}]}}
class DeploymentDiagnosticsTest(unittest.TestCase):
 def test_single_version_full_traffic(self):
  got=diag.parse_latest_deployment(payload([{"version_id":"v1","percentage":100}]));self.assertEqual(1,got.version_count);self.assertEqual(100,got.traffic_total)
 def test_split_traffic(self): self.assertEqual(2,diag.parse_latest_deployment(payload([{"version_id":"a","percentage":40},{"version_id":"b","percentage":60}])).version_count)
 def test_invalid_shapes_fail_closed(self):
  cases=[{}, {"success":True,"result":{"deployments":[]}},payload([]),payload([{}]),payload([{"percentage":100}]),payload([{"version_id":"x"}]),payload([{"version_id":"x","percentage":0}]),payload([{"version_id":"x","percentage":99}])]
  for value in cases:
   with self.assertRaises(diag.DeploymentShapeError):diag.parse_latest_deployment(value)
 def test_safe_result_has_no_response_or_secret_fields(self):
  got=diag.parse_latest_deployment(payload([{"version_id":"v","percentage":100,"token":"x"}]));self.assertNotIn("token",repr(got));self.assertNotIn("raw",repr(got))
if __name__=="__main__":unittest.main()
