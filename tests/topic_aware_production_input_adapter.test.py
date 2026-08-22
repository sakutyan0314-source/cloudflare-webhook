import copy, importlib.util, json, pathlib, sys, unittest

ROOT=pathlib.Path(__file__).parents[1]
def load(name):
 spec=importlib.util.spec_from_file_location(name,ROOT/'scripts'/f'{name}.py'); module=importlib.util.module_from_spec(spec); assert spec and spec.loader; sys.modules[name]=module; spec.loader.exec_module(module); return module
topic=load('topic_candidate'); review=load('topic_candidate_review'); phase1c=load('topic_candidate_production_input'); canary=load('topic_candidate_canary_production'); adapter=load('topic_aware_production_input_adapter')
SOURCE=json.loads((ROOT/'tests/fixtures/topic-candidates-phase1a.json').read_text()); FIXTURE=json.loads((ROOT/'tests/fixtures/topic-candidate-canary-production-phase1d.json').read_text())

class TopicAwareProductionInputAdapterTest(unittest.TestCase):
 def source(self):
  candidate=topic.build_topic_candidate(copy.deepcopy(SOURCE['candidates']['how']))
  human=review.build_human_review(candidate,decision='approve_for_content_planning',reason_codes=['demand_evidence_sufficient','content_gap_confirmed'],reviewed_at='2026-08-18T00:00:00.000Z')
  approved=review.build_approved_topic_planning_handoff(candidate,[human],created_at='2026-08-18T00:01:00.000Z')
  handoff=phase1c.build_content_planning_handoff(candidate,[human],approved,created_at='2026-08-18T00:03:00.000Z')
  production_input=phase1c.build_approved_content_production_input(handoff,created_at='2026-08-18T00:04:00.000Z')
  approval=canary.build_content_production_approval(production_input,**FIXTURE['approval'],max_ttl_seconds=7200)
  return candidate,[human],approved,handoff,production_input,approval
 def test_approved_chain_builds_existing_content_free_brief(self):
  candidate,reviews,approved,handoff,production_input,approval=self.source()
  brief=adapter.build_topic_aware_gemini_brief(candidate=candidate,reviews=reviews,approved_planning=approved,content_handoff=handoff,production_input=production_input,approval=approval,now=FIXTURE['started_at'],max_ttl_seconds=7200)
  self.assertEqual(production_input['topic'],brief['topic']); self.assertEqual(production_input['primary_intent'],brief['primary_intent']); self.assertEqual(production_input['internal_link_guidance'],brief['internal_link_guidance'])
  self.assertTrue(all(brief[key] is False for key in ('ai_generation_authorized','publication_authorized','execution_authorized')))
  specification=adapter.build_topic_aware_pipeline_specification(candidate=candidate,reviews=reviews,approved_planning=approved,content_handoff=handoff,production_input=production_input,approval=approval,now=FIXTURE['started_at'],max_ttl_seconds=7200)
  self.assertEqual(f"manual:topic:{production_input['production_input_id']}",specification['idempotencyKey']); self.assertEqual(brief,specification['topicAwareBrief'])
 def test_invalid_or_unapproved_chain_fails_before_brief(self):
  candidate,reviews,approved,handoff,production_input,approval=self.source()
  held=review.build_human_review(candidate,decision='hold',reason_codes=['timing_not_ready'],reviewed_at='2026-08-18T00:02:00.000Z',previous_review=reviews[0])
  with self.assertRaises(adapter.TopicAwareProductionInputAdapterError): adapter.build_topic_aware_gemini_brief(candidate=candidate,reviews=[reviews[0],held],approved_planning=approved,content_handoff=handoff,production_input=production_input,approval=approval,now=FIXTURE['started_at'])
  with self.assertRaises(adapter.TopicAwareProductionInputAdapterError): adapter.build_topic_aware_gemini_brief(candidate=candidate,reviews=reviews,approved_planning=approved,content_handoff=handoff,production_input=production_input,approval=dict(approval,production_input_id='other'),now=FIXTURE['started_at'])
if __name__=='__main__': unittest.main()
