import importlib.util, pathlib, sqlite3, sys, tempfile, threading, unittest

ROOT=pathlib.Path(__file__).parents[1]
def load(name):
 spec=importlib.util.spec_from_file_location(name,ROOT/"scripts"/f"{name}.py"); module=importlib.util.module_from_spec(spec); assert spec and spec.loader; sys.modules[name]=module; spec.loader.exec_module(module); return module
repo_module=load("production_execution_repository")

class ProductionExecutionRepositoryTest(unittest.TestCase):
 def db(self):
  conn=sqlite3.connect(":memory:"); conn.execute("PRAGMA foreign_keys = ON")
  for path in sorted((ROOT/"migrations").glob("*.sql")): conn.executescript(path.read_text())
  return conn
 def repo(self, **kwargs): return repo_module.ProductionExecutionRepository(self.db(),**kwargs)
 def acquire(self, repo, suffix="one"):
  return repo.acquire(production_execution_id=f"production_execution_{suffix}",production_input_id=f"production_input_{suffix}",production_input_fingerprint=f"fingerprint_{suffix}",approval_id=f"production_approval_{suffix}",topic_candidate_id="topic_canary",human_review_id="review_canary",created_at="2026-08-18T02:00:00.000Z")
 def transition(self, repo, row, to, classification=None, reason=None): return repo.transition(production_execution_id=row["production_execution_id"],expected_state=row["state"],expected_version=row["state_version"],to_state=to,classification=classification,reason_code=reason,occurred_at=f"2026-08-18T02:00:0{row['state_version']+1}.000Z")
 def test_migrations_schema_and_foreign_keys(self):
  db=self.db(); self.assertEqual([],db.execute("PRAGMA foreign_key_check").fetchall()); names={row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}; self.assertTrue({"production_executions","production_execution_events","quality_gate_audits"}<=names)
 def test_acquire_unique_and_concurrent_style_race(self):
  repo=self.repo(); row=self.acquire(repo); self.assertEqual("planned",row["state"]); self.assertEqual(1,repo.total_count())
  with self.assertRaises(repo_module.ProductionExecutionDuplicateError): self.acquire(repo)
  with self.assertRaises(repo_module.ProductionExecutionDuplicateError): repo.acquire(production_execution_id="other",production_input_id=row["production_input_id"],production_input_fingerprint="x",approval_id="other",topic_candidate_id="topic",human_review_id="review",created_at="2026-08-18T02:00:00.000Z")
  with self.assertRaises(repo_module.ProductionExecutionDuplicateError): repo.acquire(production_execution_id="other2",production_input_id="other",production_input_fingerprint="x",approval_id=row["approval_id"],topic_candidate_id="topic",human_review_id="review",created_at="2026-08-18T02:00:00.000Z")
 def test_concurrent_acquire_allows_exactly_one(self):
  with tempfile.NamedTemporaryFile(suffix=".sqlite") as file:
   seed=sqlite3.connect(file.name)
   for path in sorted((ROOT/"migrations").glob("*.sql")): seed.executescript(path.read_text())
   seed.close(); barrier=threading.Barrier(2); outcomes=[]
   def acquire_once():
    connection=sqlite3.connect(file.name,timeout=2); repository=repo_module.ProductionExecutionRepository(connection)
    try:
     barrier.wait(); self.acquire(repository,"race"); outcomes.append("success")
    except repo_module.ProductionExecutionDuplicateError: outcomes.append("duplicate")
    finally: connection.close()
   first=threading.Thread(target=acquire_once); second=threading.Thread(target=acquire_once); first.start(); second.start(); first.join(); second.join()
   self.assertEqual(["duplicate","success"],sorted(outcomes))
 def test_transitions_cas_events_and_terminals(self):
  repo=self.repo(); row=self.acquire(repo); row=self.transition(repo,row,"preflight_verified"); row=self.transition(repo,row,"approval_verified"); row=self.transition(repo,row,"send_started"); row=self.transition(repo,row,"outcome_known_success","success")
  self.assertEqual(4,row["state_version"]); self.assertEqual("outcome_known_success",row["state"]); self.assertEqual([0,1,2,3,4],[event["event_sequence"] for event in repo.event_rows(row["production_execution_id"])])
  with self.assertRaises(repo_module.ProductionExecutionStateConflict): self.transition(repo,row,"outcome_known_success","success")
 def test_stale_version_reverse_cron_and_reason_rejected(self):
  repo=self.repo(); row=self.acquire(repo); row=self.transition(repo,row,"preflight_verified")
  with self.assertRaises(repo_module.ProductionExecutionStateConflict): repo.transition(production_execution_id=row["production_execution_id"],expected_state="planned",expected_version=0,to_state="preflight_verified",occurred_at="2026-08-18T02:01:00.000Z")
  with self.assertRaises(repo_module.ProductionExecutionStateConflict): self.transition(repo,row,"planned")
  with self.assertRaises(repo_module.ProductionExecutionSafetyError): repo.transition(production_execution_id=row["production_execution_id"],expected_state=row["state"],expected_version=row["state_version"],to_state="approval_verified",reason_code="free_text",occurred_at="2026-08-18T02:01:00.000Z")
  with self.assertRaises(repo_module.ProductionExecutionSafetyError): repo.acquire(production_execution_id="cron",production_input_id="cron",production_input_fingerprint="f",approval_id="cron",topic_candidate_id="t",human_review_id="h",created_at="x",publication_authorized=True)
 def test_snapshot_event_atomicity(self):
  repo=self.repo(fail_event_insert=True)
  with self.assertRaises(repo_module.ProductionExecutionDuplicateError): self.acquire(repo)
  self.assertEqual(0,repo.total_count())
  repo=self.repo(); row=self.acquire(repo); repo.fail_event_insert=True
  with self.assertRaises(repo_module.ProductionExecutionStateConflict): self.transition(repo,row,"preflight_verified")
  self.assertEqual("planned",repo.by_execution_id(row["production_execution_id"])["state"]); self.assertEqual(1,len(repo.event_rows(row["production_execution_id"])))
 def test_approval_consumption_crash_boundaries_and_read_only_helpers(self):
  repo=self.repo(); row=self.acquire(repo); self.assertTrue(repo.unresolved_rows()); self.assertFalse(repo.send_started(row["production_execution_id"]))
  row=self.transition(repo,row,"preflight_verified"); row=self.transition(repo,row,"approval_verified"); self.assertEqual("approval_verified",row["state"]); self.assertEqual(1,len(repo.pre_send_resume_candidates())) # crash A: explicit pre-send resume candidate only
  row=self.transition(repo,row,"send_started"); self.assertTrue(repo.send_started(row["production_execution_id"])); self.assertEqual(1,len(repo.outcome_unknown_review_candidates())) # crash B/C/D: no resend
  row=self.transition(repo,row,"outcome_unknown","outcome_unknown","outcome_unknown_requires_review")
  self.assertEqual(1,repo.outcome_unknown_count()); self.assertEqual({"outcome_unknown":1},repo.state_counts()); self.assertEqual({"outcome_unknown":1},repo.classification_counts()); self.assertEqual([],repo.linked_rows()); self.assertEqual([],repo.unresolved_rows())
  with self.assertRaises(repo_module.ProductionExecutionDuplicateError): self.acquire(repo)
 def test_forbidden_metadata_and_fixed_queries_only(self):
  repo=self.repo()
  with self.assertRaises(repo_module.ProductionExecutionSafetyError): repo.acquire(production_execution_id="id",production_input_id="input",production_input_fingerprint="f",approval_id="approval",topic_candidate_id={"prompt":"forbidden"},human_review_id="review",created_at="now")
  self.assertEqual({},repo.state_counts()); self.assertEqual({},repo.classification_counts()); self.assertEqual(0,repo.outcome_unknown_count())
if __name__=="__main__": unittest.main()
