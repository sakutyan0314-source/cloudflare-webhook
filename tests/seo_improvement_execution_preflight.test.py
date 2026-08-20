import copy
import importlib.util
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).parents[1]


def load_script(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


fixture_spec = importlib.util.spec_from_file_location("seo_improvement_execution_approval_test", ROOT / "tests" / "seo_improvement_execution_approval.test.py")
fixture = importlib.util.module_from_spec(fixture_spec)
assert fixture_spec and fixture_spec.loader
sys.modules["seo_improvement_execution_approval_test"] = fixture
fixture_spec.loader.exec_module(fixture)
preflight = load_script("seo_improvement_execution_preflight")


class TestSeoExecutionPreflight(unittest.TestCase):
    def build(self):
        approval, candidate, candidate_input, snapshot = fixture.source()
        item = preflight.build_execution_preflight(approval, candidate, candidate_input, snapshot, now="2026-08-21T02:10:00Z")
        return item, approval, candidate, candidate_input, snapshot

    def test_valid_preflight_and_fixed_zero_write_boundary(self):
        item, approval, candidate, candidate_input, snapshot = self.build()
        preflight.validate_execution_preflight(item, approval, candidate, candidate_input, snapshot, now="2026-08-21T02:10:00Z")
        self.assertFalse(item["changed_db"])
        self.assertEqual(0, item["rows_written"])

    def test_approval_and_candidate_identity_are_bound(self):
        item, approval, candidate, candidate_input, snapshot = self.build()
        self.assertEqual(approval["execution_approval_id"], item["execution_approval_id"])
        self.assertEqual(candidate["execution_candidate_fingerprint"], item["execution_candidate_fingerprint"])
        for field, value in (("candidate_id", "other"), ("plan_fingerprint", "0" * 64)):
            forged = copy.deepcopy(item)
            forged[field] = value
            with self.assertRaises(preflight.SeoImprovementExecutionPreflightError):
                preflight.validate_execution_preflight(forged, approval, candidate, candidate_input, snapshot, now="2026-08-21T02:10:00Z")

    def test_expired_stale_and_used_approval_are_rejected(self):
        item, approval, candidate, candidate_input, snapshot = self.build()
        with self.assertRaises(preflight.SeoImprovementExecutionPreflightError):
            preflight.validate_execution_preflight(item, approval, candidate, candidate_input, snapshot, now="2026-08-21T02:30:00Z")
        stale = copy.deepcopy(snapshot)
        stale["updated_at"] = "2026-08-22T00:00:00Z"
        with self.assertRaises(preflight.SeoImprovementExecutionPreflightError):
            preflight.validate_execution_preflight(item, approval, candidate, candidate_input, stale, now="2026-08-21T02:10:00Z")
        with self.assertRaises(preflight.SeoImprovementExecutionPreflightError):
            preflight.validate_execution_preflight(item, approval, candidate, candidate_input, snapshot, now="2026-08-21T02:10:00Z", used_approval_ids=[approval["execution_approval_id"]])

    def test_diff_forbidden_field_and_authorization_changes_are_rejected(self):
        item, approval, candidate, candidate_input, snapshot = self.build()
        for field, value in (("expected_diff", {"body_markdown": {"current": "x", "proposed": "y"}}), ("sql", "UPDATE"), ("execution_authorized", True)):
            forged = copy.deepcopy(item)
            forged[field] = value
            with self.assertRaises(preflight.SeoImprovementExecutionPreflightError):
                preflight.validate_execution_preflight(forged, approval, candidate, candidate_input, snapshot, now="2026-08-21T02:10:00Z")

    def test_deterministic_identity_and_no_d1_write_dependency(self):
        item, approval, candidate, candidate_input, snapshot = self.build()
        same = preflight.build_execution_preflight(approval, candidate, candidate_input, snapshot, now="2026-08-21T02:10:00Z")
        self.assertEqual(item["preflight_id"], same["preflight_id"])


if __name__ == "__main__":
    unittest.main()
