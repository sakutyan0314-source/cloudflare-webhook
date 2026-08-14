import copy
import importlib.util
import json
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


review = load("ai_recommendation_review")
workflow = load("ai_recommendation_review_workflow")
plan_module = load("ai_change_plan")
ENVELOPE = json.loads((ROOT / "tests" / "fixtures" / "v2a-review-envelope.json").read_text())
FIXTURE = json.loads((ROOT / "tests" / "fixtures" / "v2c-change-plan-fixture.json").read_text())
REVIEW_RUBRIC = {field: 2 for field in workflow.RUBRIC_FIELDS}
PLAN_RUBRIC = {field: 2 for field in plan_module.PLAN_RUBRIC_FIELDS}


class ChangePlanTest(unittest.TestCase):
    def decision(self, envelope=ENVELOPE):
        record = workflow.build_review_record(envelope, reviewer_id="operator_primary", decision="approve", rubric=REVIEW_RUBRIC,
            reason_code="human_review_complete", review_id="review_fixture", reviewed_at="2026-08-15T01:02:03Z")
        return workflow.build_v2c_review_decision_envelope(record)

    def plan(self, **changes):
        params = {"plan_type": "improve_title", "proposed_changes": FIXTURE["proposed_changes"], "evidence_references": FIXTURE["evidence_references"]}
        params.update(changes)
        return plan_module.build_change_plan(ENVELOPE, self.decision(), FIXTURE["article_snapshot"], **params)

    def test_only_eligible_approve_enters_and_execution_is_always_false(self):
        plan = self.plan()
        self.assertFalse(plan["execution_authorized"])
        invalid = dict(self.decision(), execution_authorized=True)
        with self.assertRaises(plan_module.ChangePlanError):
            plan_module.build_change_plan(ENVELOPE, invalid, FIXTURE["article_snapshot"], plan_type="improve_title", proposed_changes=FIXTURE["proposed_changes"], evidence_references=FIXTURE["evidence_references"])

    def test_recommendation_fingerprint_id_review_id_and_version_must_match(self):
        for key, value in (("recommendation_id", "other"), ("recommendation_fingerprint", "0" * 64), ("review_id", ""), ("review_version", 0)):
            invalid = dict(self.decision(), **{key: value})
            with self.assertRaises(plan_module.ChangePlanError):
                plan_module.build_change_plan(ENVELOPE, invalid, FIXTURE["article_snapshot"], plan_type="improve_title", proposed_changes=FIXTURE["proposed_changes"], evidence_references=FIXTURE["evidence_references"])

    def test_type_scopes_prohibited_fields_and_evidence_references_are_enforced(self):
        with self.assertRaises(plan_module.ChangePlanError): self.plan(plan_type="improve_description")
        with self.assertRaises(plan_module.ChangePlanError): self.plan(proposed_changes={"content": "forbidden"})
        with self.assertRaises(plan_module.ChangePlanError): self.plan(evidence_references=["observation.unknown"])
        with self.assertRaises(plan_module.ChangePlanError): self.plan(proposed_changes={"title": "token: forbidden"})

    def test_plan_id_is_deterministic_and_input_change_changes_it(self):
        first, second = self.plan(), self.plan()
        self.assertEqual(first["plan_id"], second["plan_id"])
        changed = self.plan(proposed_changes={"title": "検索意図に合わせた別の検証済みタイトル改善案"})
        self.assertNotEqual(first["plan_id"], changed["plan_id"])

    def test_stale_snapshot_rejects_without_regeneration(self):
        plan = self.plan()
        plan_module.assert_plan_not_stale(plan, FIXTURE["article_snapshot"])
        stale = copy.deepcopy(FIXTURE["article_snapshot"]); stale["updated_at"] = "2026-08-16T00:00:00.000Z"
        with self.assertRaisesRegex(plan_module.ChangePlanError, "stale_plan"):
            plan_module.assert_plan_not_stale(plan, stale)

    def test_content_plans_are_scope_only_not_full_body_replacement(self):
        content_envelope = copy.deepcopy(ENVELOPE); content_envelope["recommendation_type"] = "refresh_content"
        content_envelope["recommendation_id"] = "rec_v2a_content_fixture"
        decision = self.decision(content_envelope)
        scope = {"content_revision_scope": {"target_h2": "要点", "revision_policy": "観測済みの論点を補強する方針を計画する。"}}
        plan = plan_module.build_change_plan(content_envelope, decision, FIXTURE["article_snapshot"], plan_type="refresh_content", proposed_changes=scope, evidence_references=FIXTURE["evidence_references"])
        self.assertIn("content_revision_scope", plan["proposed_changes"])
        with self.assertRaises(plan_module.ChangePlanError):
            plan_module.build_change_plan(content_envelope, decision, FIXTURE["article_snapshot"], plan_type="refresh_content", proposed_changes={"body_markdown": "forbidden"}, evidence_references=FIXTURE["evidence_references"])

    def test_plan_rubric_requires_two_safety_scores_and_never_auto_executes(self):
        plan = self.plan()
        approved = plan_module.build_plan_review_decision(plan, decision="approve", rubric=PLAN_RUBRIC)
        self.assertTrue(approved["approval_eligible"]); self.assertFalse(approved["execution_authorized"])
        for rubric in (dict(PLAN_RUBRIC, scope_safety=1), dict(PLAN_RUBRIC, recommendation_alignment=0, specificity_actionability=0)):
            with self.assertRaises(plan_module.ChangePlanError):
                plan_module.build_plan_review_decision(plan, decision="approve", rubric=rubric)
        self.assertEqual("hold", plan_module.build_plan_review_decision(plan, decision="hold", rubric=PLAN_RUBRIC)["decision"])
        self.assertEqual("reject", plan_module.build_plan_review_decision(plan, decision="reject", rubric=PLAN_RUBRIC)["decision"])


if __name__ == "__main__":
    unittest.main()
