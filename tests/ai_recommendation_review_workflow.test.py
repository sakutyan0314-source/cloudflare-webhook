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
FIXTURE = json.loads((ROOT / "tests" / "fixtures" / "v2a-review-envelope.json").read_text())
PERFECT = {field: 2 for field in workflow.RUBRIC_FIELDS}


class ReviewWorkflowTest(unittest.TestCase):
    def record(self, *, decision="approve", rubric=PERFECT, review_id="review_1", version=1, supersedes=None, envelope=FIXTURE, note=None):
        return workflow.build_review_record(
            envelope, reviewer_id="operator_primary", decision=decision, rubric=rubric,
            reason_code="human_review_complete", human_note=note, review_id=review_id,
            reviewed_at="2026-08-15T01:02:03Z", review_version=version,
            supersedes_review_id=supersedes,
        )

    def test_perfect_score_approve_handoffs_only_to_v2c_planning(self):
        registry = workflow.InMemoryReviewRegistry()
        record = registry.append(self.record())
        handoff = workflow.build_v2c_review_decision_envelope(record)
        self.assertTrue(record["approval_eligible"])
        self.assertEqual("approve", handoff["decision"])
        self.assertEqual("v2_0_c_change_plan_only", handoff["handoff_scope"])
        self.assertFalse(handoff["execution_authorized"])

    def test_evidence_one_or_total_seven_cannot_approve(self):
        evidence_low = dict(PERFECT, evidence_accuracy=1)
        total_seven = dict(PERFECT, japanese_clarity=1, actionability=0)
        for rubric in (evidence_low, total_seven):
            with self.assertRaises(workflow.ReviewWorkflowError):
                self.record(rubric=rubric)

    def test_eligible_human_reject_and_hold_are_allowed_without_handoff(self):
        for decision in ("reject", "hold"):
            record = self.record(decision=decision, review_id="review_" + decision)
            self.assertTrue(record["approval_eligible"])
            with self.assertRaises(workflow.ReviewWorkflowError):
                workflow.build_v2c_review_decision_envelope(record)

    def test_duplicate_approve_is_rejected_and_rereview_is_append_only(self):
        registry = workflow.InMemoryReviewRegistry()
        first = registry.append(self.record(decision="hold"))
        second = registry.append(self.record(decision="approve", review_id="review_2", version=2, supersedes=first["review_id"]))
        self.assertEqual(2, len(registry.records()))
        with self.assertRaises(workflow.ReviewWorkflowError):
            registry.append(self.record(decision="approve", review_id="review_3", version=3, supersedes=second["review_id"]))

    def test_fingerprint_is_deterministic_and_changes_with_envelope(self):
        first = workflow.recommendation_fingerprint(FIXTURE)
        self.assertEqual(first, workflow.recommendation_fingerprint(copy.deepcopy(FIXTURE)))
        changed = copy.deepcopy(FIXTURE)
        changed["title"] = "別の検証済み記事タイトル"
        self.assertNotEqual(first, workflow.recommendation_fingerprint(changed))

    def test_fingerprint_or_recommendation_mismatch_is_rejected_for_rereview(self):
        registry = workflow.InMemoryReviewRegistry()
        first = registry.append(self.record(decision="hold"))
        changed = copy.deepcopy(FIXTURE)
        changed["recommendation_id"] = "rec_v2a_other"
        with self.assertRaises(workflow.ReviewWorkflowError):
            registry.append(self.record(decision="approve", review_id="review_other", version=2, supersedes=first["review_id"], envelope=changed))
        changed = copy.deepcopy(FIXTURE)
        changed["title"] = "同じIDでも異なる封筒"
        with self.assertRaises(workflow.ReviewWorkflowError):
            registry.append(self.record(decision="approve", review_id="review_changed", version=2, supersedes=first["review_id"], envelope=changed))

    def test_invalid_inputs_and_sensitive_material_are_rejected(self):
        with self.assertRaises(workflow.ReviewWorkflowError):
            self.record(decision="execute")
        with self.assertRaises(workflow.ReviewWorkflowError):
            self.record(rubric=dict(PERFECT, japanese_clarity=3))
        with self.assertRaises(workflow.ReviewWorkflowError):
            self.record(note="api_key: prohibited")
        unsafe = copy.deepcopy(FIXTURE)
        unsafe["raw_response"] = "not allowed"
        with self.assertRaises(workflow.ReviewWorkflowError):
            workflow.recommendation_fingerprint(unsafe)

    def test_record_retains_only_audit_metadata_not_recommendation_content(self):
        record = self.record()
        for field in ("evidence", "reasons", "suggested_action", "expected_effect", "current_state", "title", "category"):
            self.assertNotIn(field, record)
        self.assertIn("recommendation_fingerprint", record)


if __name__ == "__main__":
    unittest.main()
