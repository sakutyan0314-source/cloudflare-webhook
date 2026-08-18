import copy, importlib.util, json, pathlib, sys, unittest

ROOT=pathlib.Path(__file__).parents[1]
def load(name):
 spec=importlib.util.spec_from_file_location(name,ROOT/"scripts"/f"{name}.py"); module=importlib.util.module_from_spec(spec); assert spec and spec.loader; sys.modules[name]=module; spec.loader.exec_module(module); return module
topic=load("topic_candidate"); review=load("topic_candidate_review"); phase1c=load("topic_candidate_production_input"); canary=load("topic_candidate_canary_production")
SOURCE=json.loads((ROOT/"tests/fixtures/topic-candidates-phase1a.json").read_text()); FIXTURE=json.loads((ROOT/"tests/fixtures/topic-candidate-canary-production-phase1d.json").read_text())

class CanaryProductionTest(unittest.TestCase):
 def source(self):
  candidate=topic.build_topic_candidate(copy.deepcopy(SOURCE["candidates"]["how"]))
  human=review.build_human_review(candidate,decision="approve_for_content_planning",reason_codes=["demand_evidence_sufficient","content_gap_confirmed"],reviewed_at="2026-08-18T00:00:00.000Z")
  approved=review.build_approved_topic_planning_handoff(candidate,[human],created_at="2026-08-18T00:01:00.000Z")
  handoff=phase1c.build_content_planning_handoff(candidate,[human],approved,created_at="2026-08-18T00:03:00.000Z")
  input=phase1c.build_approved_content_production_input(handoff,created_at="2026-08-18T00:04:00.000Z")
  a=FIXTURE["approval"]; approval=canary.build_content_production_approval(input,**a,max_ttl_seconds=7200)
  return candidate,[human],approved,handoff,input,approval
 def execute(self,mode="success", **changes):
  candidate,reviews,approved,handoff,input,approval=self.source(); registry=canary.LocalExecutionRegistry(); transport=canary.MockBriefTransport(mode); result=canary.execute_approved_canary(candidate=candidate,reviews=reviews,approved_planning=approved,content_handoff=handoff,production_input=input,approval=approval,allowlist=canary.CanaryAllowlist(input["production_input_id"]),registry=registry,transport=transport,started_at=FIXTURE["started_at"],completed_at=FIXTURE["completed_at"],**changes); return result,registry,transport,(candidate,reviews,approved,handoff,input,approval)
 def test_valid_canary_brief_and_success(self):
  result,_,transport,(_,_,_,_,input,_)=self.execute(); self.assertEqual("outcome_known_success",result["state"]); self.assertEqual(1,len(transport.calls)); self.assertEqual(input["production_input_id"],transport.calls[0]["production_input_id"]); self.assertTrue(all(transport.calls[0][x] is False for x in ("ai_generation_authorized","publication_authorized","execution_authorized"))); canary.validate_production_execution_audit(result)
 def test_pre_send_integrity_and_approval_fail_closed_without_consuming(self):
  candidate,reviews,approved,handoff,input,approval=self.source(); registry=canary.LocalExecutionRegistry(); transport=canary.MockBriefTransport(); forged=dict(input,production_input_id="bad")
  with self.assertRaises(canary.CanaryProductionSafetyError): canary.execute_approved_canary(candidate=candidate,reviews=reviews,approved_planning=approved,content_handoff=handoff,production_input=forged,approval=approval,allowlist=canary.CanaryAllowlist(input["production_input_id"]),registry=registry,transport=transport,started_at=FIXTURE["started_at"],completed_at=FIXTURE["completed_at"])
  self.assertEqual([],transport.calls); self.assertIsNone(registry.record("unknown"))
  with self.assertRaises(canary.CanaryProductionSafetyError): canary.validate_content_production_approval(approval,production_input=input,now="2026-08-18T03:00:00.000Z")
  bad_allowlist=canary.CanaryAllowlist("production_input_other")
  with self.assertRaises(canary.CanaryProductionSafetyError): canary.execute_approved_canary(candidate=candidate,reviews=reviews,approved_planning=approved,content_handoff=handoff,production_input=input,approval=approval,allowlist=bad_allowlist,registry=registry,transport=transport,started_at=FIXTURE["started_at"],completed_at=FIXTURE["completed_at"])
  self.assertEqual([],transport.calls)
 def test_candidate_review_routing_and_approval_mismatch_reject_before_transport(self):
  candidate,reviews,approved,handoff,input,approval=self.source(); registry=canary.LocalExecutionRegistry(); transport=canary.MockBriefTransport(); allowlist=canary.CanaryAllowlist(input["production_input_id"])
  changed_candidate=dict(candidate,proposed_title_hint="tampered")
  with self.assertRaises(canary.CanaryProductionSafetyError): canary.execute_approved_canary(candidate=changed_candidate,reviews=reviews,approved_planning=approved,content_handoff=handoff,production_input=input,approval=approval,allowlist=allowlist,registry=registry,transport=transport,started_at=FIXTURE["started_at"],completed_at=FIXTURE["completed_at"])
  superseded=review.build_human_review(candidate,decision="hold",reason_codes=["timing_not_ready"],reviewed_at="2026-08-18T00:02:00.000Z",previous_review=reviews[0])
  with self.assertRaises(canary.CanaryProductionSafetyError): canary.execute_approved_canary(candidate=candidate,reviews=[reviews[0],superseded],approved_planning=approved,content_handoff=handoff,production_input=input,approval=approval,allowlist=allowlist,registry=registry,transport=transport,started_at=FIXTURE["started_at"],completed_at=FIXTURE["completed_at"])
  rerouted=dict(approved,routing="existing_content_improvement")
  with self.assertRaises(canary.CanaryProductionSafetyError): canary.execute_approved_canary(candidate=candidate,reviews=reviews,approved_planning=rerouted,content_handoff=handoff,production_input=input,approval=approval,allowlist=allowlist,registry=registry,transport=transport,started_at=FIXTURE["started_at"],completed_at=FIXTURE["completed_at"])
  mismatched=dict(approval,production_input_id="production_input_other")
  with self.assertRaises(canary.CanaryProductionSafetyError): canary.validate_content_production_approval(mismatched,production_input=input,now=FIXTURE["started_at"])
  self.assertEqual([],transport.calls)
 def test_deterministic_approval_execution_and_single_use(self):
  *_,input,approval=self.source(); second=canary.build_content_production_approval(input,**FIXTURE["approval"]); self.assertEqual(approval["approval_id"],second["approval_id"]); self.assertEqual(canary.deterministic_production_execution_id(production_input_id=input["production_input_id"],approval_id=approval["approval_id"]),canary.deterministic_production_execution_id(production_input_id=input["production_input_id"],approval_id=approval["approval_id"]))
  result,registry,transport,source=self.execute(); candidate,reviews,approved,handoff,input,approval=source
  with self.assertRaises(canary.CanaryProductionSafetyError): canary.execute_approved_canary(candidate=candidate,reviews=reviews,approved_planning=approved,content_handoff=handoff,production_input=input,approval=approval,allowlist=canary.CanaryAllowlist(input["production_input_id"]),registry=registry,transport=transport,started_at=FIXTURE["started_at"],completed_at=FIXTURE["completed_at"])
 def test_known_failure_and_unknown_are_consumed_without_retry(self):
  for mode, state in (("known_failure","outcome_known_failed"),("timeout","outcome_unknown"),("connection_failure","outcome_unknown"),("malformed_response","outcome_unknown"),("process_interrupted","outcome_unknown")):
   result,registry,transport,source=self.execute(mode); self.assertEqual(state,result["state"]); self.assertEqual(1,len(transport.calls)); candidate,reviews,approved,handoff,input,approval=source
   with self.assertRaises(canary.CanaryProductionSafetyError): canary.execute_approved_canary(candidate=candidate,reviews=reviews,approved_planning=approved,content_handoff=handoff,production_input=input,approval=approval,allowlist=canary.CanaryAllowlist(input["production_input_id"]),registry=registry,transport=transport,started_at=FIXTURE["started_at"],completed_at=FIXTURE["completed_at"])
 def test_canary_policy_is_one_attempt_and_cron_not_redefined(self):
  self.assertEqual("approved_canary",canary.ExecutionPolicy().trigger_type); self.assertEqual(1,canary.ExecutionPolicy().max_attempts)
  with self.assertRaises(canary.CanaryProductionSafetyError): canary.ExecutionPolicy(trigger_type="cron",max_attempts=1)
  with self.assertRaises(canary.CanaryProductionSafetyError): canary.ExecutionPolicy(max_attempts=2)
 def test_brief_and_audit_reject_secret_prompt_raw_or_article(self):
  result,_,transport,_=self.execute(); self.assertNotIn("prompt",transport.calls[0]); self.assertNotIn("content",transport.calls[0])
  for field in ("token","Authorization","prompt","raw_ai_response","body_markdown"):
   forged=dict(result); forged[field]="forbidden"
   with self.assertRaises(canary.CanaryProductionSafetyError): canary.validate_production_execution_audit(forged)
  self.assertFalse(self.source()[-1]["publication_authorized"])
if __name__=="__main__": unittest.main()
