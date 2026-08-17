import copy
import importlib.util
import json
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).parents[1]
spec = importlib.util.spec_from_file_location("topic_candidate", ROOT / "scripts" / "topic_candidate.py")
topic_candidate = importlib.util.module_from_spec(spec); assert spec and spec.loader
sys.modules["topic_candidate"] = topic_candidate; spec.loader.exec_module(topic_candidate)
FIXTURE = json.loads((ROOT / "tests" / "fixtures" / "topic-candidates-phase1a.json").read_text())

class TopicCandidateTest(unittest.TestCase):
    def candidate(self, key="how", **changes):
        value = copy.deepcopy(FIXTURE["candidates"][key]); value.update(changes)
        return topic_candidate.build_topic_candidate(value)

    def test_deterministic_id_and_identity_changes(self):
        one, two = self.candidate(), self.candidate()
        self.assertEqual(one["topic_candidate_id"], two["topic_candidate_id"])
        changed = self.candidate(target_audience_key="different_audience")
        self.assertNotEqual(one["topic_candidate_id"], changed["topic_candidate_id"])

    def test_mechanical_normalization_and_unapproved_alias_boundary(self):
        self.assertEqual("ai エージェント", topic_candidate.normalize_topic(" ＡＩ  エージェント "))
        self.assertNotEqual(topic_candidate.normalize_topic("AIエージェント"), topic_candidate.normalize_topic("ai agent"))
        self.assertEqual("aiエージェント", topic_candidate.normalize_topic_with_alias("ai agent", {"ai agent": "AIエージェント"}))

    def test_intent_validation_and_secondary_limit(self):
        with self.assertRaises(topic_candidate.TopicCandidateSafetyError): self.candidate(primary_intent="unknown")
        with self.assertRaises(topic_candidate.TopicCandidateSafetyError): self.candidate(secondary_intents=["what", "how", "compare"])

    def test_overlap_interface(self):
        self.assertEqual("exact_duplicate", topic_candidate.classify_overlap(normalized_topic_key="same", primary_intent="how", cluster_id="ai-agent-foundation", related_existing=[{"topic_key":"same"}]))
        self.assertEqual("same_intent_overlap", topic_candidate.classify_overlap(normalized_topic_key="new", primary_intent="how", cluster_id="ai-agent-foundation", related_existing=[{"topic_key":"other","primary_intent":"how","satisfies_same_intent":True}]))
        self.assertEqual("semantic_near_duplicate", topic_candidate.classify_overlap(normalized_topic_key="new", primary_intent="how", cluster_id="ai-agent-foundation", related_existing=[], injected_semantic_result="semantic_near_duplicate"))

    def test_high_requires_at_least_one_demand_evidence(self):
        high = self.candidate(); self.assertEqual("HIGH", high["priority"])
        no_evidence = self.candidate(demand_evidence=[])
        self.assertNotEqual("HIGH", no_evidence["priority"]); self.assertEqual("needs_more_evidence", no_evidence["routing_decision"])
        self.assertFalse(no_evidence["search_volume_known"])

    def test_routing_existing_content_and_content_gap(self):
        same = self.candidate(overlap_classification="same_intent_overlap")
        self.assertEqual("existing_content_improvement", same["routing_decision"])
        self.assertEqual("new_content_planning", self.candidate()["routing_decision"])

    def test_legacy_dependency_holds(self):
        candidate = self.candidate(related_article_ids=[22])
        self.assertEqual(("HOLD", "hold"), (candidate["priority"], candidate["routing_decision"]))

    def test_cluster_and_schema_validation_fail_closed(self):
        with self.assertRaises(topic_candidate.TopicCandidateSafetyError): self.candidate(cluster_id="invented")
        value = self.candidate(); value["cluster_id"] = "invented"
        with self.assertRaises(topic_candidate.TopicCandidateSafetyError): topic_candidate.validate_topic_candidate(value)

    def test_search_console_states_do_not_conflate_missing_and_zero(self):
        self.assertEqual("missing", topic_candidate.classify_search_console_state(data_present=False, final_data_days=0, impressions=0))
        self.assertEqual("observed_zero", topic_candidate.classify_search_console_state(data_present=True, final_data_days=0, impressions=0))
        self.assertEqual("insufficient_data", topic_candidate.classify_search_console_state(data_present=True, final_data_days=1, impressions=1))

    def test_authorizations_are_forced_false_and_human_review_true(self):
        candidate = self.candidate(content_generation_authorized=True, publication_authorized=True, execution_authorized=True)
        self.assertTrue(candidate["requires_human_review"])
        self.assertFalse(candidate["content_generation_authorized"])
        self.assertFalse(candidate["publication_authorized"])
        self.assertFalse(candidate["execution_authorized"])
        forged = dict(candidate, execution_authorized=True)
        with self.assertRaises(topic_candidate.TopicCandidateSafetyError): topic_candidate.validate_topic_candidate(forged)

    def test_high_without_evidence_is_rejected_even_if_forged(self):
        candidate = self.candidate(demand_evidence=[])
        forged = dict(candidate, priority="HIGH")
        with self.assertRaises(topic_candidate.TopicCandidateSafetyError): topic_candidate.validate_topic_candidate(forged)

    def test_sensitive_content_and_raw_response_are_rejected(self):
        for field in ("token", "Authorization", "raw_response", "content", "body_markdown"):
            with self.assertRaises(topic_candidate.TopicCandidateSafetyError): self.candidate(**{field:"forbidden"})

    def test_fixture_candidates_are_planning_only(self):
        for key in ("what", "how", "compare"):
            candidate = self.candidate(key)
            self.assertEqual("pending_human_review", candidate["candidate_status"])
            self.assertFalse(candidate["execution_authorized"])

if __name__ == "__main__":
    unittest.main()
