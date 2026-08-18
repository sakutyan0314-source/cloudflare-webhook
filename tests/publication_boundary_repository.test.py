import importlib.util, pathlib, sqlite3, sys, tempfile, threading, unittest

ROOT=pathlib.Path(__file__).parents[1]
def load(name):
 spec=importlib.util.spec_from_file_location(name,ROOT/"scripts"/f"{name}.py"); module=importlib.util.module_from_spec(spec); assert spec and spec.loader;sys.modules[name]=module;spec.loader.exec_module(module);return module
publication=load("publication_boundary_repository")

class PublicationBoundaryRepositoryTest(unittest.TestCase):
 def db(self):
  db=sqlite3.connect(":memory:");db.execute("PRAGMA foreign_keys=ON")
  for migration in sorted((ROOT/"migrations").glob("*.sql")):db.executescript(migration.read_text())
  return db
 def seed(self,db):
  db.execute("INSERT INTO pipeline_runs (execution_id,idempotency_key,trigger_type,status,stage,lease_expires_at,started_at,updated_at) VALUES ('pipe_exec','pipe_key','manual','completed','done','2026-08-18T00:00:00.000Z','2026-08-18T00:00:00.000Z','2026-08-18T00:00:00.000Z')")
  run_id=db.execute("SELECT id FROM pipeline_runs").fetchone()[0]
  db.execute("INSERT INTO quality_gate_audits (audit_id,pipeline_run_id,schema_version,stage,classification,threshold_version,evaluated_at) VALUES ('quality_pass',?,'quality-gate-audit-v1','seo_quality','pass','seo_quality_threshold_v1','2026-08-18T00:00:00.000Z')",(run_id,))
  db.execute("INSERT INTO production_executions (production_execution_id,schema_version,production_input_id,production_input_fingerprint,approval_id,topic_candidate_id,human_review_id,trigger_type,state,state_version,notification_classification,publication_authorized,created_at,pipeline_run_id) VALUES ('prod_exec','approved-canary-production-execution-v1','prod_input','fp','prod_approval','topic','review','approved_canary','outcome_known_success',4,'not_applicable',0,'2026-08-18T00:00:00.000Z',?)",(run_id,));db.commit()
 def repo(self,**kwargs):
  db=self.db();self.seed(db);return publication.PublicationBoundaryRepository(db,**kwargs)
 def draft(self,repo):
  return repo.create_staging_draft(staging_draft_id="draft_one",production_execution_id="prod_exec",production_input_id="prod_input",topic_candidate_id="topic",quality_gate_audit_id="quality_pass",content="# Canary\n\nbody",title="Canary",description="safe description",body_markdown="body",category="ai-automation",published_at_candidate="2026-08-18T03:00:00.000Z",updated_at_candidate="2026-08-18T03:00:00.000Z",created_at="2026-08-18T02:00:00.000Z")
 def approval(self,repo,draft):return repo.build_approval(draft,approved_by="reviewer_canary",approved_at="2026-08-18T02:10:00.000Z",expires_at="2026-08-18T03:10:00.000Z")
 def advance(self,repo,execution):
  for state in ("preflight_verified","approval_verified"):execution=repo.transition(execution_id=execution["publication_execution_id"],expected_state=execution["state"],expected_version=execution["state_version"],to_state=state,now="2026-08-18T02:11:00.000Z")
  return execution
 def test_migrations_schema_and_quality_pass_draft(self):
  repo=self.repo();draft=self.draft(repo);self.assertEqual("publication_pending",draft["publication_status"]);self.assertEqual([],repo.connection.execute("PRAGMA foreign_key_check").fetchall());tables={x[0] for x in repo.connection.execute("SELECT name FROM sqlite_master WHERE type='table'")};self.assertTrue({"content_staging_drafts","publication_executions","publication_execution_events"}<=tables)
 def test_quality_nonpass_and_fingerprint_determinism(self):
  repo=self.repo();values=dict(content="# Canary\n\nbody",title="Canary",description="safe description",body_markdown="body",category="ai-automation",published_at_candidate="2026-08-18T03:00:00.000Z",updated_at_candidate="2026-08-18T03:00:00.000Z")
  first=publication.final_content_fingerprint(**values);self.assertEqual(first,publication.final_content_fingerprint(**values));self.assertNotEqual(first,publication.final_content_fingerprint(**{**values,"body_markdown":"body!"}))
  for classification in ("needs_review","fail","input_invalid"):
   repo.connection.execute("UPDATE quality_gate_audits SET classification=? WHERE audit_id='quality_pass'",(classification,))
   with self.assertRaises(publication.PublicationSafetyError):self.draft(repo)
  repo.connection.execute("UPDATE quality_gate_audits SET classification='pass' WHERE audit_id='quality_pass'")
  draft=self.draft(repo);approval=self.approval(repo,draft);execution=self.advance(repo,repo.acquire(draft=draft,approval=approval,now="2026-08-18T02:11:00.000Z"));repo.connection.execute("UPDATE quality_gate_audits SET classification='fail' WHERE audit_id='quality_pass'")
  with self.assertRaises(publication.PublicationSafetyError):repo.publish_atomically(execution_id=execution["publication_execution_id"],expected_version=execution["state_version"],now="2026-08-18T02:12:00.000Z")
 def test_approval_single_use_and_preflight_rejection(self):
  repo=self.repo();draft=self.draft(repo);approval=self.approval(repo,draft);execution=repo.acquire(draft=draft,approval=approval,now="2026-08-18T02:11:00.000Z")
  self.assertTrue(repo.approval_consumed(approval["publication_approval_id"]))
  with self.assertRaises(publication.PublicationDuplicateError):repo.acquire(draft=draft,approval=approval,now="2026-08-18T02:11:00.000Z")
  expired=dict(approval,expires_at="2026-08-18T02:00:00.000Z")
  with self.assertRaises(publication.PublicationSafetyError):repo.acquire(draft=draft,approval=expired,now="2026-08-18T02:11:00.000Z")
  altered=dict(draft,final_content_fingerprint="wrong")
  with self.assertRaises(publication.PublicationSafetyError):repo.acquire(draft=altered,approval=approval,now="2026-08-18T02:11:00.000Z")
  with self.assertRaises(publication.PublicationSafetyError):repo.acquire(draft=draft,approval={"schema_version":"content-production-approval-v1"},now="2026-08-18T02:11:00.000Z")
 def test_cas_states_terminal_unknown_and_atomic_publish(self):
  repo=self.repo();draft=self.draft(repo);execution=self.advance(repo,repo.acquire(draft=draft,approval=self.approval(repo,draft),now="2026-08-18T02:11:00.000Z"));published=repo.publish_atomically(execution_id=execution["publication_execution_id"],expected_version=execution["state_version"],now="2026-08-18T02:12:00.000Z")
  self.assertEqual("published",published["state"]);self.assertEqual("eligible",published["notification_classification"]);self.assertIsInstance(published["final_article_id"],int);self.assertEqual(published["final_article_id"],repo.final_article_id(published["publication_execution_id"]));self.assertEqual("eligible",repo.notification_classification(published["publication_execution_id"]));self.assertEqual(1,repo.connection.execute("SELECT COUNT(*) FROM curation_logs").fetchone()[0]);article=repo.connection.execute("SELECT content,title,description,body_markdown,category,seo_status FROM curation_logs WHERE id=?",(published["final_article_id"],)).fetchone();self.assertEqual((draft["content"],draft["title"],draft["description"],draft["body_markdown"],draft["category"],"ready"),tuple(article))
  self.assertEqual([0,1,2,3,4],[x["event_sequence"] for x in repo.events(published["publication_execution_id"])])
  with self.assertRaises(publication.PublicationStateConflict):repo.publish_atomically(execution_id=execution["publication_execution_id"],expected_version=execution["state_version"],now="2026-08-18T02:13:00.000Z")
 def test_stale_reverse_unknown_and_transaction_rollback(self):
  repo=self.repo();draft=self.draft(repo);execution=repo.acquire(draft=draft,approval=self.approval(repo,draft),now="2026-08-18T02:11:00.000Z")
  with self.assertRaises(publication.PublicationStateConflict):repo.transition(execution_id=execution["publication_execution_id"],expected_state="planned",expected_version=1,to_state="preflight_verified",now="x")
  execution=repo.transition(execution_id=execution["publication_execution_id"],expected_state="planned",expected_version=0,to_state="preflight_verified",now="x")
  with self.assertRaises(publication.PublicationStateConflict):repo.transition(execution_id=execution["publication_execution_id"],expected_state="preflight_verified",expected_version=1,to_state="planned",now="x")
  execution=repo.transition(execution_id=execution["publication_execution_id"],expected_state="preflight_verified",expected_version=1,to_state="approval_verified",now="x");execution=repo.transition(execution_id=execution["publication_execution_id"],expected_state="approval_verified",expected_version=2,to_state="publish_started",now="x")
  unknown=repo.transition(execution_id=execution["publication_execution_id"],expected_state="publish_started",expected_version=3,to_state="publication_outcome_unknown",classification="outcome_unknown",reason_code="publication_outcome_unknown",now="x");self.assertEqual("publication_outcome_unknown",unknown["state"])
  with self.assertRaises(publication.PublicationStateConflict):repo.transition(execution_id=unknown["publication_execution_id"],expected_state=unknown["state"],expected_version=unknown["state_version"],to_state="published",classification="published",now="x")
  failed=self.repo(fail_curation_insert=True);draft=self.draft(failed);execution=self.advance(failed,failed.acquire(draft=draft,approval=self.approval(failed,draft),now="2026-08-18T02:11:00.000Z"));
  with self.assertRaises(publication.PublicationStateConflict):failed.publish_atomically(execution_id=execution["publication_execution_id"],expected_version=execution["state_version"],now="2026-08-18T02:12:00.000Z")
  self.assertEqual("approval_verified",failed.execution(execution["publication_execution_id"])["state"]);self.assertEqual(0,failed.connection.execute("SELECT COUNT(*) FROM curation_logs").fetchone()[0])
 def test_drafts_are_absent_from_all_public_surfaces(self):
  repo=self.repo();draft=self.draft(repo);self.assertEqual(0,repo.connection.execute("SELECT COUNT(*) FROM curation_logs").fetchone()[0]);self.assertEqual(1,repo.draft_count());self.assertEqual(1,repo.pending_count())
  # Existing Worker public pages query curation_logs only; staging has no article ID or URL.
  public_rows=repo.connection.execute("SELECT id FROM curation_logs WHERE seo_status != 'needs_review'").fetchall();self.assertEqual([],public_rows);self.assertIsNone(repo.connection.execute("SELECT id FROM curation_logs WHERE id=?",("draft_one",)).fetchone());self.assertEqual([],repo.links());self.assertEqual(0,repo.rejected_count())
  worker_source=(ROOT/"src"/"index.ts").read_text();self.assertNotIn("content_staging_drafts",worker_source)
 def test_concurrent_publish_one_and_no_sensitive_audit_fields(self):
  with tempfile.NamedTemporaryFile(suffix=".sqlite") as file:
   db=sqlite3.connect(file.name);db.execute("PRAGMA foreign_keys=ON")
   for migration in sorted((ROOT/"migrations").glob("*.sql")):db.executescript(migration.read_text())
   self.seed(db);repo=publication.PublicationBoundaryRepository(db);draft=self.draft(repo);approval=self.approval(repo,draft);execution=self.advance(repo,repo.acquire(draft=draft,approval=approval,now="2026-08-18T02:11:00.000Z"));db.close();outcomes=[];barrier=threading.Barrier(2)
  def publish_once():
   connection=sqlite3.connect(file.name,timeout=2);repository=publication.PublicationBoundaryRepository(connection)
   try:
    barrier.wait();repository.publish_atomically(execution_id=execution["publication_execution_id"],expected_version=execution["state_version"],now="2026-08-18T02:12:00.000Z");outcomes.append("success")
   except (publication.PublicationStateConflict,sqlite3.OperationalError):outcomes.append("conflict")
   finally:connection.close()
   one=threading.Thread(target=publish_once);two=threading.Thread(target=publish_once);one.start();two.start();one.join();two.join();self.assertEqual(["conflict","success"],sorted(outcomes))
   verify=publication.PublicationBoundaryRepository(sqlite3.connect(file.name));self.assertEqual(1,verify.published_count());self.assertEqual(1,verify.connection.execute("SELECT COUNT(*) FROM curation_logs").fetchone()[0]);text=" ".join(map(str,verify.events(execution["publication_execution_id"])));self.assertNotIn("body",text);self.assertNotIn("prompt",text);verify.connection.close()
if __name__=="__main__":unittest.main()
