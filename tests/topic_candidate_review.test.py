import copy
import importlib.util
import json
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).parents[1]
def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec); assert spec and spec.loader
    sys.modules[name] = module; spec.loader.exec_module(module); return module

topic = load("topic_candidate", ROOT / "scripts" / "topic_candidate.py")
review = load("topic_candidate_review", ROOT / "scripts" / "topic_candidate_review.py")
SOURCE = json.loads((ROOT / "tests" / "fixtures" / "topic-candidates-phase1a.json").read_text())
FIXTURE = json.loads((ROOT / "tests" / "fixtures" / "topic-candidate-review-phase1b.json").read_text())

class TopicCandidateReviewTest(unittest.TestCase):
    def candidate(self, key="how", **changes):
        data = copy.deepcopy(SOURCE["candidates"][key]); data.update(changes)
        return topic.build_topic_candidate(data)

    def review(self, candidate, decision="approve_for_content_planning", reasons=("demand_evidence_sufficient", "content_gap_confirmed"), previous=None):
        return review.build_human_review(candidate, decision=decision, reason_codes=reasons, reviewed_at=FIXTURE["reviewed_at"], previous_review=previous)

    def ledger(self, directory):
        return review.TopicCandidateReviewLedger(pathlib.Path(directory) / "phase1b.jsonl", repository_root=ROOT)

    def test_canary_candidate_review_and_non_executable_handoff(self):
        canary = FIXTURE["canary"]
        candidate = self.candidate(canary["candidate_key"])
        human = self.review(candidate, canary["decision"], tuple(canary["reason_codes"]))
        with tempfile.TemporaryDirectory() as directory:
            ledger = self.ledger(directory); ledger.append_candidate(candidate); ledger.append_review(candidate, human)
            handoff = review.build_approved_topic_planning_handoff(candidate, ledger.reviews_for(candidate["topic_candidate_id"]), created_at=FIXTURE["handoff_created_at"])
        self.assertEqual("AIエージェント導入の進め方", handoff["topic"])
        self.assertEqual("HIGH", handoff["priority"])
        self.assertEqual("new_content_planning", handoff["routing"])
        self.assertTrue(all(handoff[key] is False for key in ("content_generation_authorized", "publication_authorized", "execution_authorized")))
        self.assertEqual(handoff["handoff_id"], review.deterministic_handoff_id(topic_candidate_id=candidate["topic_candidate_id"],candidate_fingerprint=review.candidate_identity_fingerprint(candidate),human_review_id=human["review_id"]))

    def test_candidate_integrity_and_authorization_fail_closed(self):
        candidate = self.candidate(); forged = dict(candidate, topic_candidate_id="topic_forged")
        with self.assertRaises(review.TopicCandidateReviewSafetyError): review.validate_candidate_for_review(forged)
        forged = dict(candidate, execution_authorized=True)
        with self.assertRaises(review.TopicCandidateReviewSafetyError): review.validate_candidate_for_review(forged)
        legacy = self.candidate(related_article_ids=[22])
        with self.assertRaises(review.TopicCandidateReviewSafetyError): self.review(legacy)
        legacy_parent = self.candidate(possible_parent_article_id=22)
        with self.assertRaises(review.TopicCandidateReviewSafetyError): self.review(legacy_parent)

    def test_fixed_decisions_and_reason_codes(self):
        candidate = self.candidate()
        with self.assertRaises(review.TopicCandidateReviewSafetyError): self.review(candidate, decision="unknown")
        with self.assertRaises(review.TopicCandidateReviewSafetyError): self.review(candidate, reasons=("unknown",))
        held = self.review(candidate, decision="hold", reasons=("timing_not_ready",))
        self.assertEqual("hold", held["decision"])

    def test_only_latest_approve_new_content_can_handoff(self):
        candidate = self.candidate()
        for decision, reasons in (("hold",("timing_not_ready",)), ("reject",("out_of_scope",)), ("needs_more_evidence",("demand_evidence_insufficient",)), ("strengthen_existing",("existing_content_more_appropriate",))):
            item = self.review(candidate, decision, reasons)
            with self.assertRaises(review.TopicCandidateReviewSafetyError): review.build_approved_topic_planning_handoff(candidate,[item],created_at=FIXTURE["handoff_created_at"])
        human_route = self.candidate(overlap_classification="partial_overlap")
        approved = self.review(human_route)
        with self.assertRaises(review.TopicCandidateReviewSafetyError): review.build_approved_topic_planning_handoff(human_route,[approved],created_at=FIXTURE["handoff_created_at"])

    def test_append_only_supersede_and_duplicate_rejection(self):
        candidate = self.candidate()
        first = self.review(candidate, "needs_more_evidence", ("demand_evidence_insufficient",))
        second = review.build_human_review(candidate, decision="approve_for_content_planning", reason_codes=("demand_evidence_sufficient",), reviewed_at="2026-08-18T00:02:00.000Z", previous_review=first)
        with tempfile.TemporaryDirectory() as directory:
            ledger=self.ledger(directory); ledger.append_candidate(candidate); ledger.append_review(candidate,first); before=ledger.path.read_bytes(); ledger.append_review(candidate,second)
            self.assertEqual(first,ledger.reviews_for(candidate["topic_candidate_id"])[0]); self.assertEqual(first["review_id"],second["supersedes_review_id"])
            self.assertTrue(ledger.path.read_bytes().startswith(before))
            with self.assertRaises(review.TopicCandidateReviewSafetyError): ledger.append_review(candidate,second)

    def test_identity_mismatch_and_invalid_review_chain_rejected(self):
        candidate = self.candidate(); first = self.review(candidate, "needs_more_evidence", ("demand_evidence_insufficient",))
        altered = dict(candidate, proposed_title_hint="同一IDでも異なる候補")
        review.validate_candidate_for_review(altered)
        with tempfile.TemporaryDirectory() as directory:
            ledger=self.ledger(directory); ledger.append_candidate(candidate); ledger.append_review(candidate,first)
            with self.assertRaises(review.TopicCandidateReviewSafetyError): ledger.append_review(altered,first)
        forged = dict(first, previous_review_id="topic_other", supersedes_review_id="topic_other")
        forged["review_id"] = review.deterministic_review_id(topic_candidate_id=forged["topic_candidate_id"],candidate_fingerprint=forged["candidate_identity_fingerprint"],decision=forged["decision"],reason_codes=forged["reason_codes"],reviewed_at=forged["reviewed_at"],previous_review_id=forged["previous_review_id"])
        with self.assertRaises(review.TopicCandidateReviewSafetyError): review.build_approved_topic_planning_handoff(candidate,[forged],created_at=FIXTURE["handoff_created_at"])

    def test_ledger_permissions_partial_write_and_repository_rejection(self):
        with self.assertRaises(review.TopicCandidateReviewSafetyError): review.TopicCandidateReviewLedger(ROOT / "topic-ledger.jsonl", repository_root=ROOT)
        with tempfile.TemporaryDirectory() as directory:
            ledger=self.ledger(directory); self.assertEqual(0o700,ledger.path.parent.stat().st_mode & 0o777); self.assertEqual(0o600,ledger.path.stat().st_mode & 0o777)
            ledger.path.write_bytes(b'{"record_type":"partial"}')
            with self.assertRaises(review.TopicCandidateReviewSafetyError): ledger.reviews_for("topic_x")

    def test_sensitive_raw_and_body_fields_rejected(self):
        candidate=self.candidate()
        for field in ("token","Authorization","content","body_markdown","raw_external_response"):
            forged=dict(candidate); forged[field]="forbidden"
            with self.assertRaises(review.TopicCandidateReviewSafetyError): review.validate_candidate_for_review(forged)

    def test_phase1a_priority_and_search_states_remain_unchanged(self):
        self.assertEqual("HIGH",self.candidate()["priority"])
        self.assertNotEqual("HIGH",self.candidate(demand_evidence=[])["priority"])
        self.assertEqual("missing",topic.classify_search_console_state(data_present=False,final_data_days=0,impressions=0))
        self.assertEqual("observed_zero",topic.classify_search_console_state(data_present=True,final_data_days=0,impressions=0))

if __name__ == "__main__": unittest.main()
