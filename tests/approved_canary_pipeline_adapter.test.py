import copy, importlib.util, json, pathlib, sqlite3, sys, unittest

ROOT=pathlib.Path(__file__).parents[1]
def load(name):
 spec=importlib.util.spec_from_file_location(name,ROOT/"scripts"/f"{name}.py"); module=importlib.util.module_from_spec(spec); assert spec and spec.loader; sys.modules[name]=module; spec.loader.exec_module(module); return module
topic=load("topic_candidate"); review=load("topic_candidate_review"); input_module=load("topic_candidate_production_input"); canary=load("topic_candidate_canary_production"); execution=load("production_execution_repository"); publication=load("publication_boundary_repository"); adapter_module=load("approved_canary_pipeline_adapter")
SOURCE=json.loads((ROOT/"tests/fixtures/topic-candidates-phase1a.json").read_text()); FIX=json.loads((ROOT/"tests/fixtures/topic-candidate-canary-production-phase1d.json").read_text())

class Stages:
 def __init__(self,mode="success"):self.mode=mode;self.calls=[]
 def produce(self,brief,*,max_attempts):
  self.calls.append((dict(brief),max_attempts))
  if self.mode=="timeout":raise canary.TransportTimeout()
  if self.mode=="connection":raise canary.TransportConnectionFailure()
  if self.mode=="malformed":return {"bad":"response"}
  if self.mode=="failure":raise RuntimeError("known")
  return {"content":"# Canary title\n\n## Detail\n"+"x"*260,"title":"Canary title","description":"description","body_markdown":"## Detail\n"+"x"*260,"category":"ai-automation","published_at":"2026-08-18T03:00:00.000Z","updated_at":"2026-08-18T03:00:00.000Z"}
class Quality:
 def __init__(self,db,result="pass"):self.db=db;self.result=result;self.calls=0
 def evaluate(self,*,pipeline_run_id,article,now):
  self.calls+=1
  if self.result!="pass":return {"classification":self.result,"audit_id":"not_saved"}
  self.db.execute("INSERT INTO quality_gate_audits (audit_id,pipeline_run_id,schema_version,stage,classification,threshold_version,evaluated_at) VALUES ('audit_one',?,'quality-gate-audit-v1','seo_quality','pass','seo_quality_threshold_v1',?)",(pipeline_run_id,now));self.db.commit();return {"classification":"pass","audit_id":"audit_one"}

class AdapterTest(unittest.TestCase):
 def setup(self,mode="success",quality="pass"):
  db=sqlite3.connect(":memory:");db.execute("PRAGMA foreign_keys=ON")
  for path in sorted((ROOT/"migrations").glob("*.sql")):db.executescript(path.read_text())
  db.execute("INSERT INTO pipeline_runs (execution_id,idempotency_key,trigger_type,status,stage,attempt_count,notification_status,lease_expires_at,started_at,updated_at) VALUES ('pipe','canary:one','approved_canary','running','gemini',1,'pending','2026-08-18T04:00:00.000Z','2026-08-18T02:00:00.000Z','2026-08-18T02:00:00.000Z')");db.commit();pipeline_id=db.execute("SELECT id FROM pipeline_runs").fetchone()[0]
  candidate=topic.build_topic_candidate(copy.deepcopy(SOURCE["candidates"]["how"]));human=review.build_human_review(candidate,decision="approve_for_content_planning",reason_codes=["demand_evidence_sufficient","content_gap_confirmed"],reviewed_at="2026-08-18T00:00:00.000Z");planned=review.build_approved_topic_planning_handoff(candidate,[human],created_at="2026-08-18T00:01:00.000Z");handoff=input_module.build_content_planning_handoff(candidate,[human],planned,created_at="2026-08-18T00:03:00.000Z");item=input_module.build_approved_content_production_input(handoff,created_at="2026-08-18T00:04:00.000Z");approval=canary.build_content_production_approval(item,**FIX["approval"],max_ttl_seconds=7200);execution_id=canary.deterministic_production_execution_id(production_input_id=item["production_input_id"],approval_id=approval["approval_id"])
  request=adapter_module.ApprovedCanaryRequest(candidate,[human],planned,handoff,item,approval,execution_id,pipeline_id,FIX["started_at"],FIX["completed_at"]);stages=Stages(mode);repo=execution.ProductionExecutionRepository(db);pub=publication.PublicationBoundaryRepository(db);quality_sink=Quality(db,quality);adapter=adapter_module.ApprovedCanaryPipelineAdapter(repo,pub,canary.CanaryAllowlist(item["production_input_id"]),stages,quality_sink);return db,request,adapter,stages,quality_sink
 def test_success_stages_nonpublic_draft_and_safe_audit(self):
  db,request,adapter,stages,_=self.setup();result=adapter.run(request);self.assertEqual("outcome_known_success",result["state"]);self.assertEqual(1,stages.calls[0][1]);self.assertEqual(1,db.execute("SELECT COUNT(*) FROM content_staging_drafts").fetchone()[0]);self.assertEqual(0,db.execute("SELECT COUNT(*) FROM curation_logs").fetchone()[0]);self.assertEqual("publication_pending",db.execute("SELECT publication_status FROM content_staging_drafts").fetchone()[0]);self.assertFalse(result["publication_authorized"]);self.assertNotIn("content",result)
 def test_missing_expired_or_tampered_preflight_never_sends(self):
  for field,value in (("approval",None),("production_execution_id","bad")):
   db,request,adapter,stages,_=self.setup();request=copy.copy(request);object.__setattr__(request,field,value)
   with self.assertRaises(Exception):adapter.run(request)
   self.assertEqual([],stages.calls);self.assertEqual(0,db.execute("SELECT COUNT(*) FROM production_executions").fetchone()[0])
  db,request,adapter,stages,_=self.setup();request=copy.copy(request);bad=dict(request.approval,expires_at="2026-08-18T00:05:00.000Z");object.__setattr__(request,"approval",bad)
  with self.assertRaises(Exception):adapter.run(request)
  self.assertEqual([],stages.calls)
 def test_allowlist_and_cron_confusion_rejected(self):
  db,request,adapter,stages,_=self.setup();adapter.allowlist=canary.CanaryAllowlist("other")
  with self.assertRaises(Exception):adapter.run(request)
  self.assertEqual([],stages.calls);self.assertEqual("approved_canary",adapter_module.APPROVED_CANARY_TRIGGER_TYPE)
 def test_unknown_transport_consumes_without_resend(self):
  for mode in ("timeout","connection","malformed"):
   db,request,adapter,stages,_=self.setup(mode);result=adapter.run(request);self.assertEqual("outcome_unknown",result["state"]);self.assertEqual(1,len(stages.calls));self.assertEqual(0,db.execute("SELECT COUNT(*) FROM content_staging_drafts").fetchone()[0])
   with self.assertRaises(Exception):adapter.run(request)
 def test_quality_nonpass_never_stages_or_publishes(self):
  for verdict in ("fail","needs_review"):
   db,request,adapter,_,quality=self.setup(quality=verdict);result=adapter.run(request);self.assertEqual("outcome_known_failed",result["state"]);self.assertEqual(0,db.execute("SELECT COUNT(*) FROM content_staging_drafts").fetchone()[0]);self.assertEqual(0,db.execute("SELECT COUNT(*) FROM curation_logs").fetchone()[0])
 def test_pipeline_link_state_and_cron_source_unchanged(self):
  db,request,adapter,_,_=self.setup();result=adapter.run(request);row=db.execute("SELECT trigger_type,pipeline_run_id,quality_gate_audit_id,publication_authorized FROM production_executions").fetchone();self.assertEqual(("approved_canary",request.pipeline_run_id,"audit_one",0),tuple(row));self.assertIn("triggerType: \"cron\"",(ROOT/"src/index.ts").read_text());self.assertEqual("not_applicable",db.execute("SELECT notification_classification FROM production_executions").fetchone()[0]);self.assertEqual(result["staging_draft_id"],db.execute("SELECT staging_draft_id FROM content_staging_drafts").fetchone()[0])
if __name__=="__main__":unittest.main()
