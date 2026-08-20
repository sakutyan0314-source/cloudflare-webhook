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


fixture_spec = importlib.util.spec_from_file_location("seo_improvement_execution_preflight_test", ROOT / "tests" / "seo_improvement_execution_preflight.test.py")
fixture = importlib.util.module_from_spec(fixture_spec)
assert fixture_spec and fixture_spec.loader
sys.modules["seo_improvement_execution_preflight_test"] = fixture
fixture_spec.loader.exec_module(fixture)
attempt = load_script("seo_improvement_execution_attempt")


def source(state="planned", **overrides):
    preflight, approval, candidate, candidate_input, snapshot = fixture.TestSeoExecutionPreflight().build()
    facts = {"state": state, "classification": attempt._STATE_CLASSIFICATION[state], "started_at": "2026-08-21T02:10:00Z", "completed_at": None, "changed_db": False, "changes": 0, "returned_article_id": None}
    if state == "outcome_known_success": facts.update({"completed_at": "2026-08-21T02:11:00Z", "changed_db": True, "changes": 1, "returned_article_id": 1})
    if state == "outcome_unknown": facts.update({"completed_at": "2026-08-21T02:11:00Z", "changed_db": None, "changes": None})
    facts.update(overrides)
    item = attempt.build_execution_attempt(preflight, approval, candidate, candidate_input, snapshot, facts, now="2026-08-21T02:10:00Z")
    return item, preflight, approval, candidate, candidate_input, snapshot


class TestSeoExecutionAttempt(unittest.TestCase):
    def test_attempt_generation_and_preflight_handoff(self):
        item, preflight, approval, candidate, candidate_input, snapshot = source()
        attempt.validate_execution_attempt(item, preflight, approval, candidate, candidate_input, snapshot, now="2026-08-21T02:10:00Z")
        self.assertEqual(preflight["preflight_id"], item["preflight_id"])

    def test_approval_and_fingerprint_mismatch_are_rejected(self):
        item, preflight, approval, candidate, candidate_input, snapshot = source()
        for field, value in (("execution_approval_id", "other"), ("execution_candidate_fingerprint", "0" * 64)):
            forged = copy.deepcopy(item)
            forged[field] = value
            with self.assertRaises(attempt.SeoImprovementExecutionAttemptError):
                attempt.validate_execution_attempt(forged, preflight, approval, candidate, candidate_input, snapshot, now="2026-08-21T02:10:00Z")

    def test_forward_only_transitions_and_outcome_unknown(self):
        attempt.validate_attempt_transition("planned", "preflight_verified")
        with self.assertRaises(attempt.SeoImprovementExecutionAttemptError):
            attempt.validate_attempt_transition("planned", "update_started")
        item, *_ = source("outcome_unknown")
        self.assertEqual("outcome_unknown", item["classification"])

    def test_failure_classification_and_authorization_are_rejected(self):
        _, preflight, approval, candidate, candidate_input, snapshot = source()
        facts = {"state": "planned", "classification": "unknown", "started_at": "2026-08-21T02:10:00Z", "completed_at": None, "changed_db": False, "changes": 0, "returned_article_id": None}
        with self.assertRaises(attempt.SeoImprovementExecutionAttemptError):
            attempt.build_execution_attempt(preflight, approval, candidate, candidate_input, snapshot, facts, now="2026-08-21T02:10:00Z")
        item, *_ = source()
        item["execution_authorized"] = True
        with self.assertRaises(attempt.SeoImprovementExecutionAttemptError):
            attempt.validate_execution_attempt(item, preflight, approval, candidate, candidate_input, snapshot, now="2026-08-21T02:10:00Z")

    def test_post_verification_and_rollback_candidate_are_pure(self):
        item, _, _, candidate, _, _ = source("outcome_known_success")
        verification = attempt.build_post_verification(item, candidate, candidate["after_snapshot"])
        attempt.validate_post_verification(verification, item, candidate, candidate["after_snapshot"])
        rollback = attempt.build_rollback_candidate(item, candidate, verification)
        self.assertFalse(rollback["rollback_authorized"])
        stale_after = copy.deepcopy(candidate["after_snapshot"])
        stale_after["content_sha256"] = "c" * 64
        failed = attempt.build_post_verification(item, candidate, stale_after)
        self.assertEqual("fail", failed["classification"])


if __name__ == "__main__":
    unittest.main()
