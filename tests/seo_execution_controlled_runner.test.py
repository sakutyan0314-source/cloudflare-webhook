import copy
import importlib.util
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).parents[1]

def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / (name + ".py"))
    module = importlib.util.module_from_spec(spec); assert spec and spec.loader
    sys.modules[name] = module; spec.loader.exec_module(module); return module

spec = importlib.util.spec_from_file_location("seo_execution_candidate_qualification_test", ROOT / "tests" / "seo_execution_candidate_qualification.test.py")
fixture = importlib.util.module_from_spec(spec); assert spec and spec.loader
sys.modules["seo_execution_candidate_qualification_test"] = fixture; spec.loader.exec_module(fixture)
load("d1_conditional_update_audit")
load("seo_improvement_execution_attempt")
load("seo_execution_transaction_repository")
load("seo_execution_d1_write_adapter")
runner = load("seo_execution_controlled_runner")

class Transport:
    def __init__(self, snapshot, response=None, fail_update=False):
        self.snapshot, self.response, self.fail_update = snapshot, response, fail_update
        self.calls = []
    def reserve_attempt(self, attempt): self.calls.append(("reserve", attempt["execution_attempt_id"]))
    def transition(self, attempt, state, classification, **kwargs): self.calls.append(("transition", state, classification, kwargs.get("reason_code")))
    def conditional_snippet_update(self, statement):
        self.calls.append(("update", tuple(statement["set_fields"])))
        if self.fail_update: raise RuntimeError("transport")
        return self.response
    def read_article_snapshot(self, article_id): self.calls.append(("read", article_id)); return self.snapshot
    def save_post_verification(self, verification): self.calls.append(("verify", verification["classification"]))

def response(article_id):
    return {"success": True, "result": [{"success": True, "meta": {"changed_db": True, "changes": 1, "rows_written": 1}, "results": [{"id": article_id}]}]}

class TestControlledRunner(unittest.TestCase):
    def setUp(self):
        self.artifacts = fixture.artifacts()
        self.row = {"id": 1, "title": self.artifacts["latest_snapshot"]["title"], "description": self.artifacts["latest_snapshot"]["description"], "category": "saas-cloud", "content": "fixture content", "body_markdown": "fixture body", "published_at": self.artifacts["latest_snapshot"]["published_at"], "updated_at": self.artifacts["latest_snapshot"]["updated_at"], "seo_status": "ready"}
    def test_explicit_confirmation_and_target_preflight_fail_closed(self):
        with self.assertRaises(runner.SeoControlledExecutionError): runner.run_first_controlled_execution(self.artifacts, self.row, Transport(self.artifacts["latest_snapshot"]), target_article_id=1, now="2026-08-21T02:10:00Z")
        with self.assertRaises(runner.SeoControlledExecutionError): runner.run_first_controlled_execution(self.artifacts, self.row, Transport(self.artifacts["latest_snapshot"]), target_article_id=2, now="2026-08-21T02:10:00Z", execute=True)
    def test_update_failure_is_unknown_and_has_no_retry(self):
        module = sys.modules["seo_execution_controlled_runner"]
        original = module.build_conditional_update_statement
        module.build_conditional_update_statement = lambda *_: {"set_fields": ["title"], "sql": "UPDATE curation_logs SET title=?", "params": [], "expected_article_id": 1}
        try:
            transport = Transport(self.artifacts["latest_snapshot"], fail_update=True)
            result = runner.run_first_controlled_execution(self.artifacts, self.row, transport, target_article_id=1, now="2026-08-21T02:10:00Z", execute=True)
            self.assertEqual("outcome_unknown", result["status"]); self.assertEqual(1, len([x for x in transport.calls if x[0] == "update"]))
        finally: module.build_conditional_update_statement = original
    def test_returning_and_post_verification_failure_stop_without_rollback(self):
        module = sys.modules["seo_execution_controlled_runner"]
        original = module.build_conditional_update_statement
        module.build_conditional_update_statement = lambda *_: {"set_fields": ["title"], "sql": "UPDATE curation_logs SET title=?", "params": [], "expected_article_id": 1}
        try:
            transport = Transport({**self.artifacts["latest_snapshot"], "title": "wrong"}, response(1))
            result = runner.run_first_controlled_execution(self.artifacts, self.row, transport, target_article_id=1, now="2026-08-21T02:10:00Z", execute=True)
            self.assertEqual("outcome_known_failure", result["status"]); self.assertNotIn("rollback", str(transport.calls))
            transport = Transport(self.artifacts["latest_snapshot"], response(2))
            result = runner.run_first_controlled_execution(self.artifacts, self.row, transport, target_article_id=1, now="2026-08-21T02:10:00Z", execute=True)
            self.assertEqual("outcome_unknown", result["status"])
        finally: module.build_conditional_update_statement = original

    def test_single_snippet_success_has_post_verification(self):
        module = sys.modules["seo_execution_controlled_runner"]
        original = module.build_conditional_update_statement
        module.build_conditional_update_statement = lambda *_: {"set_fields": ["title"], "sql": "UPDATE curation_logs SET title=?", "params": [], "expected_article_id": 1}
        try:
            transport = Transport(self.artifacts["execution_candidate"]["after_snapshot"], response(1))
            result = runner.run_first_controlled_execution(self.artifacts, self.row, transport, target_article_id=1, now="2026-08-21T02:10:00Z", execute=True)
            self.assertEqual("outcome_known_success", result["status"])
            self.assertEqual(1, len([x for x in transport.calls if x[0] == "update"]))
            self.assertIn(("verify", "pass"), transport.calls)
        finally: module.build_conditional_update_statement = original


if __name__ == "__main__":
    unittest.main()
