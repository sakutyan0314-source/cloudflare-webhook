import copy
import importlib.util
import json
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / (name + ".py")); module = importlib.util.module_from_spec(spec); sys.modules[name] = module; spec.loader.exec_module(module); return module


review = load("ai_recommendation_review")
workflow = load("ai_recommendation_review_workflow")
change = load("ai_change_plan")
execution = load("ai_execution_candidate")
ENVELOPE = json.loads((ROOT / "tests" / "fixtures" / "v2a-review-envelope.json").read_text())
PLAN_FIXTURE = json.loads((ROOT / "tests" / "fixtures" / "v2c-change-plan-fixture.json").read_text())
FIXTURE = json.loads((ROOT / "tests" / "fixtures" / "v2d-execution-fixture.json").read_text())


class ExecutionCandidateTest(unittest.TestCase):
    def plan(self, changes=None):
        rubric = {field: 2 for field in workflow.RUBRIC_FIELDS}
        record = workflow.build_review_record(ENVELOPE, reviewer_id="operator_primary", decision="approve", rubric=rubric, reason_code="accepted", review_id="review_25", reviewed_at="2026-08-15T01:00:00Z")
        decision = workflow.build_v2c_review_decision_envelope(record)
        return change.build_change_plan(ENVELOPE, decision, PLAN_FIXTURE["article_snapshot"], plan_type="improve_title", proposed_changes=changes or PLAN_FIXTURE["proposed_changes"], evidence_references=PLAN_FIXTURE["evidence_references"])

    def plan_review(self, plan):
        value = dict(FIXTURE["plan_review_approval"], plan_id=plan["plan_id"], plan_fingerprint=execution.plan_fingerprint(plan))
        return value

    def candidate(self, changes=None):
        plan = self.plan(changes); return execution.build_execution_candidate(plan, self.plan_review(plan))

    def approval(self, candidate, **overrides):
        value = dict(FIXTURE["execution_approval"], candidate_id=candidate["candidate_id"], candidate_fingerprint=candidate["candidate_fingerprint"], plan_id=candidate["plan_id"], article_id=candidate["article_id"])
        value.update(overrides); return value

    def current_row(self):
        snapshot = PLAN_FIXTURE["article_snapshot"]
        return {"id": snapshot["article_id"], "title": snapshot["title"], "description": snapshot["description"], "category": snapshot["category"], "content": "fixture content", "body_markdown": "fixture body" , "published_at": snapshot["published_at"], "updated_at": snapshot["updated_at"], "seo_status": snapshot["seo_status"]}

    def test_candidate_is_deterministic_and_title_description_are_only_allowlist(self):
        first, second = self.candidate(), self.candidate()
        self.assertEqual(first["candidate_id"], second["candidate_id"]); self.assertFalse(first["execution_authorized"])
        ctr_envelope = dict(ENVELOPE, recommendation_type="improve_ctr", recommendation_id="rec_v2a_ctr_25")
        rubric = {field: 2 for field in workflow.RUBRIC_FIELDS}
        record = workflow.build_review_record(ctr_envelope, reviewer_id="operator_primary", decision="approve", rubric=rubric, reason_code="accepted", review_id="review_ctr_25", reviewed_at="2026-08-15T01:00:00Z")
        decision = workflow.build_v2c_review_decision_envelope(record)
        both_plan = change.build_change_plan(ctr_envelope, decision, PLAN_FIXTURE["article_snapshot"], plan_type="improve_ctr", proposed_changes={"title": "検索意図を明確にした検証済み記事タイトルの改善案", "description": "十分な長さを持つ安全なdescriptionの改善案です。検索利用者に目的と価値を明確に伝えるためのfixture専用テキストです。"}, evidence_references=PLAN_FIXTURE["evidence_references"])
        both = execution.build_execution_candidate(both_plan, self.plan_review(both_plan))
        self.assertEqual({"title", "description"}, set(both["allowed_changes"]))
        with self.assertRaises((change.ChangePlanError, execution.ExecutionSafetyError)):
            self.plan({"category": "saas-cloud"})

    def test_execution_approval_is_distinct_unexpired_and_matches_chain(self):
        candidate = self.candidate(); approval = self.approval(candidate)
        self.assertEqual(approval["approval_id"], execution.validate_execution_approval(candidate, approval, now="2026-08-15T03:10:00Z")["approval_id"])
        self.assertEqual(1800, int(execution.INITIAL_EXECUTION_APPROVAL_TTL.total_seconds()))
        for overrides in ({"expires_at": "2026-08-15T03:00:00Z"}, {"expires_at": "2026-08-15T03:31:00Z"}, {"candidate_fingerprint": "0" * 64}, {"article_id": 26}):
            with self.assertRaises(execution.ExecutionSafetyError): execution.validate_execution_approval(candidate, self.approval(candidate, **overrides), now="2026-08-15T03:10:00Z")

    def test_stale_backup_and_dry_run_preflight_are_required(self):
        candidate = self.candidate(); execution.validate_current_state(candidate, PLAN_FIXTURE["article_snapshot"])
        stale = dict(PLAN_FIXTURE["article_snapshot"], title="changed")
        with self.assertRaises(execution.ExecutionSafetyError): execution.validate_current_state(candidate, stale)
        facts = dict(FIXTURE["preflight"], dry_run={"article_id": candidate["article_id"], "candidate_fingerprint": candidate["candidate_fingerprint"], "changed_db": False, "rows_written": 0, "expected_diff": candidate["expected_diff"]}, final_diff={"article_id": candidate["article_id"], "candidate_fingerprint": candidate["candidate_fingerprint"], "changes": candidate["expected_diff"]})
        self.assertTrue(execution.build_preflight_record(candidate, facts)["restore_verified"])
        with self.assertRaises(execution.ExecutionSafetyError): execution.build_preflight_record(candidate, dict(facts, dry_run=dict(facts["dry_run"], rows_written=1)))
        with self.assertRaises(execution.ExecutionSafetyError): execution.build_preflight_record(candidate, dict(facts, final_diff=dict(facts["final_diff"], changes={})))

    def test_conditional_update_is_allowlisted_and_returning_validation_uses_changes_not_rows_written(self):
        candidate = self.candidate(); row = self.current_row()
        # Fixture content SHA is intentionally replaced only in memory for this SQL-construction test.
        snapshot = dict(candidate["current_state_snapshot"])
        import hashlib
        snapshot["content_sha256"] = hashlib.sha256(row["content"].encode()).hexdigest(); snapshot["body_markdown_sha256"] = hashlib.sha256(row["body_markdown"].encode()).hexdigest()
        candidate = dict(candidate, current_state_snapshot=snapshot)
        statement = execution.build_conditional_update(candidate, row)
        self.assertIn("RETURNING id", statement["sql"]); self.assertEqual(["title"], statement["audit"]["set_fields"])
        result = execution.validate_update_response(candidate, {"changed_db": True, "changes": 1, "rows_written": 4}, [{"id": 25}])
        self.assertEqual(4, result["rows_written_reference"])
        for meta, rows in (({"changed_db": True, "changes": 0}, []), ({"changed_db": False, "changes": 1}, [{"id": 25}]), ({"changed_db": True, "changes": 1}, [{"id": 26}])):
            with self.assertRaises(execution.ExecutionSafetyError): execution.validate_update_response(candidate, meta, rows)

    def test_state_machine_blocks_duplicate_retry_and_outcome_unknown_reuse(self):
        machine = execution.ExecutionStateMachine(); machine.begin("execution_25_v1")
        machine.transition("execution_25_v1", "preflight_verified"); machine.transition("execution_25_v1", "approval_verified"); machine.transition("execution_25_v1", "send_started"); machine.transition("execution_25_v1", "outcome_unknown")
        with self.assertRaises(execution.ExecutionSafetyError): machine.begin("execution_25_v1")
        with self.assertRaises(execution.ExecutionSafetyError): machine.transition("execution_25_v1", "result_known")

    def test_append_only_ledger_and_rollback_v2e_interfaces_are_safe(self):
        with tempfile.TemporaryDirectory() as temporary:
            ledger = execution.AppendOnlyExecutionLedger(pathlib.Path(temporary))
            ledger.append({"execution_id": "execution_25_v1", "candidate_id": "candidate_25", "state": "planned", "at": "2026-08-15T03:00:00Z"})
            self.assertEqual(0o700, ledger.path.parent.stat().st_mode & 0o777); self.assertEqual(0o600, ledger.path.stat().st_mode & 0o777)
            with self.assertRaises(execution.ExecutionSafetyError): ledger.append({"execution_id": "execution_25_v1", "token": "forbidden"})
        source = {"execution_id": "execution_25_v1", "candidate_id": "candidate_25", "article_id": 25, "plan_id": "plan_25", "recommendation_id": "rec_25", "before_snapshot_fingerprint": "a", "after_snapshot_fingerprint": "b", "applied_at": "2026-08-15T03:00:00Z", "applied_fields": ["title"]}
        self.assertFalse(execution.build_rollback_candidate(source)["rollback_authorized"])
        self.assertFalse(execution.build_v2e_execution_handoff(source)["execution_authorized"])


if __name__ == "__main__": unittest.main()
