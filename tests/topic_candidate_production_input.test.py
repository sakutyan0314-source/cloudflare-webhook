import copy
import importlib.util
import json
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).parents[1]
def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec); assert spec and spec.loader
    sys.modules[name] = module; spec.loader.exec_module(module); return module

topic = load("topic_candidate")
review = load("topic_candidate_review")
phase1c = load("topic_candidate_production_input")
SOURCE = json.loads((ROOT / "tests/fixtures/topic-candidates-phase1a.json").read_text())
FIXTURE = json.loads((ROOT / "tests/fixtures/topic-candidate-production-input-phase1c.json").read_text())

class TopicCandidateProductionInputTest(unittest.TestCase):
    def source(self, **changes):
        data = copy.deepcopy(SOURCE["candidates"]["how"]); data.update(changes)
        candidate = topic.build_topic_candidate(data)
        canary = FIXTURE["canary"]
        human = review.build_human_review(candidate, decision=canary["decision"], reason_codes=canary["reason_codes"], reviewed_at="2026-08-18T00:00:00.000Z")
        approved = review.build_approved_topic_planning_handoff(candidate, [human], created_at="2026-08-18T00:01:00.000Z")
        return candidate, [human], approved

    def handoff(self, **changes):
        candidate, reviews, approved = self.source(**changes)
        return candidate, reviews, approved, phase1c.build_content_planning_handoff(candidate, reviews, approved, created_at=FIXTURE["handoff_created_at"])

    def test_canary_end_to_end_is_non_executable(self):
        candidate, reviews, approved, handoff = self.handoff()
        output = phase1c.build_approved_content_production_input(handoff, created_at=FIXTURE["production_input_created_at"], quality_threshold_version=FIXTURE["quality_threshold_version"])
        self.assertEqual("AIエージェント導入の進め方", output["topic"])
        self.assertEqual([17, 18, 19, 23], output["related_article_ids"])
        self.assertEqual("new_content_planning", approved["routing"])
        self.assertTrue(all(output[field] is False for field in ("ai_generation_authorized", "publication_authorized", "execution_authorized")))
        self.assertEqual(candidate["topic_candidate_id"], output["topic_candidate_id"])

    def test_source_integrity_latest_approval_and_routing_fail_closed(self):
        candidate, reviews, approved = self.source()
        forged = dict(candidate, proposed_title_hint="tampered")
        with self.assertRaises(phase1c.TopicCandidateProductionInputSafetyError): phase1c.build_content_planning_handoff(forged, reviews, approved, created_at=FIXTURE["handoff_created_at"])
        later = review.build_human_review(candidate, decision="hold", reason_codes=["timing_not_ready"], reviewed_at="2026-08-18T00:02:00.000Z", previous_review=reviews[0])
        with self.assertRaises(phase1c.TopicCandidateProductionInputSafetyError): phase1c.build_content_planning_handoff(candidate, [reviews[0], later], approved, created_at=FIXTURE["handoff_created_at"])
        unsafe = dict(approved, execution_authorized=True)
        with self.assertRaises(phase1c.TopicCandidateProductionInputSafetyError): phase1c.build_content_planning_handoff(candidate, reviews, unsafe, created_at=FIXTURE["handoff_created_at"])
        rerouted = dict(approved, routing="existing_content_improvement")
        with self.assertRaises(phase1c.TopicCandidateProductionInputSafetyError): phase1c.build_content_planning_handoff(candidate, reviews, rerouted, created_at=FIXTURE["handoff_created_at"])

    def test_deterministic_ids_and_identity_changes(self):
        *_, first = self.handoff(); *_, second = self.handoff()
        one = phase1c.build_approved_content_production_input(first, created_at=FIXTURE["production_input_created_at"])
        two = phase1c.build_approved_content_production_input(second, created_at=FIXTURE["production_input_created_at"])
        self.assertEqual(first["handoff_id"], second["handoff_id"]); self.assertEqual(one["production_input_id"], two["production_input_id"])
        candidate, reviews, approved, changed = self.handoff(cluster_id="saas-post-saas")
        self.assertNotEqual(first["handoff_id"], changed["handoff_id"])

    def test_legacy_and_unsafe_fields_rejected(self):
        _, _, _, handoff = self.handoff()
        legacy = copy.deepcopy(handoff); legacy["related_article_ids"] = [22]
        with self.assertRaises(phase1c.TopicCandidateProductionInputSafetyError): phase1c.validate_content_planning_handoff(legacy)
        for field in ("token", "Authorization", "content", "body_markdown", "raw_response"):
            forged = dict(handoff); forged[field] = "forbidden"
            with self.assertRaises(phase1c.TopicCandidateProductionInputSafetyError): phase1c.validate_content_planning_handoff(forged)

    def test_unknown_demand_and_internal_links_are_safe_metadata(self):
        _, _, _, handoff = self.handoff()
        self.assertFalse(handoff["search_volume_known"]); self.assertFalse(handoff["trend_direction_known"])
        self.assertEqual([17, 18, 19, 23], handoff["internal_link_candidates"]["suggested_sibling_article_ids"])
        self.assertNotIn("anchor_text", handoff["internal_link_candidates"])

    def test_production_output_never_executes_or_calls_pipeline(self):
        _, _, _, handoff = self.handoff()
        output = phase1c.build_approved_content_production_input(handoff, created_at=FIXTURE["production_input_created_at"])
        self.assertEqual("seo_quality_threshold_v1", output["quality_threshold_version"])
        self.assertNotIn("prompt", output); self.assertNotIn("article", output)
        self.assertTrue(all(output[field] is False for field in ("ai_generation_authorized", "publication_authorized", "execution_authorized")))

if __name__ == "__main__": unittest.main()
