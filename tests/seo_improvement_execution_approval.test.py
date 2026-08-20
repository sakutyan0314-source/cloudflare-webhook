import copy
import importlib.util
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


# Reuse the Phase 2E fixture chain without an external service or write.
fixture_spec = importlib.util.spec_from_file_location("seo_improvement_execution_candidate_test", ROOT / "tests" / "seo_improvement_execution_candidate.test.py")
execution_fixture = importlib.util.module_from_spec(fixture_spec)
assert fixture_spec and fixture_spec.loader
sys.modules["seo_improvement_execution_candidate_test"] = execution_fixture
fixture_spec.loader.exec_module(execution_fixture)
execution = sys.modules["seo_improvement_execution_candidate"]
approval = load("seo_improvement_execution_approval")


def source(status="approved", **overrides):
    item, item_input, _, _, _, snapshot = execution_fixture.TestSeoExecutionCandidate().build()
    decision = {
        "execution_candidate_id": item["execution_candidate_id"],
        "execution_candidate_fingerprint": item["execution_candidate_fingerprint"],
        "article_id": item["article_id"],
        **{field: item[field] for field in approval._SOURCE_FIELDS},
        "status": status,
        "approved_by": "operator",
        "approved_at": "2026-08-21T02:00:00Z",
        "expires_at": "2026-08-21T02:30:00Z",
        "single_use": True,
    }
    decision.update(overrides)
    return approval.build_execution_approval(item, item_input, decision), item, item_input, snapshot


class TestSeoExecutionApproval(unittest.TestCase):
    def test_approval_generation_and_identity_match(self):
        record, item, item_input, snapshot = source()
        approval.validate_execution_approval(record, item, item_input, now="2026-08-21T02:10:00Z", current_snapshot=snapshot)
        self.assertEqual(item["execution_candidate_fingerprint"], record["execution_candidate_fingerprint"])

    def test_fingerprint_identity_is_deterministic_and_changes(self):
        record, *_ = source()
        same, *_ = source()
        changed, *_ = source(approved_at="2026-08-21T02:01:00Z", expires_at="2026-08-21T02:31:00Z")
        self.assertEqual(record["execution_approval_id"], same["execution_approval_id"])
        self.assertNotEqual(record["execution_approval_id"], changed["execution_approval_id"])

    def test_expired_single_use_and_stale_records_are_rejected(self):
        record, item, item_input, snapshot = source()
        with self.assertRaises(approval.SeoImprovementExecutionApprovalError):
            approval.validate_execution_approval(record, item, item_input, now="2026-08-21T02:30:00Z")
        with self.assertRaises(approval.SeoImprovementExecutionApprovalError):
            approval.validate_execution_approval(record, item, item_input, now="2026-08-21T02:10:00Z", used_approval_ids=[record["execution_approval_id"]])
        stale = copy.deepcopy(snapshot)
        stale["updated_at"] = "2026-08-22T00:00:00Z"
        with self.assertRaises(approval.SeoImprovementExecutionApprovalError):
            approval.validate_execution_approval(record, item, item_input, now="2026-08-21T02:10:00Z", current_snapshot=stale)

    def test_source_authorization_and_schema_mismatches_are_rejected(self):
        record, item, item_input, _ = source()
        for field, value in (("candidate_fingerprint", "0" * 64), ("plan_id", "other"), ("execution_authorized", True), ("schema_version", "other")):
            forged = copy.deepcopy(record)
            forged[field] = value
            with self.assertRaises(approval.SeoImprovementExecutionApprovalError):
                approval.validate_execution_approval(forged, item, item_input, now="2026-08-21T02:10:00Z")

    def test_nonapproved_status_and_no_d1_write_dependency(self):
        record, item, item_input, _ = source(status="pending_approval")
        with self.assertRaises(approval.SeoImprovementExecutionApprovalError):
            approval.validate_execution_approval(record, item, item_input, now="2026-08-21T02:10:00Z")
        self.assertEqual("approved", source()[0]["status"])


if __name__ == "__main__":
    unittest.main()
