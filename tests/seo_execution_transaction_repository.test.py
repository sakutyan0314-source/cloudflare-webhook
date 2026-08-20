import importlib.util, pathlib, sqlite3, sys, unittest

ROOT=pathlib.Path(__file__).parents[1]
def load(name):
 spec=importlib.util.spec_from_file_location(name,ROOT/'scripts'/(name+'.py'));mod=importlib.util.module_from_spec(spec);assert spec and spec.loader;sys.modules[name]=mod;spec.loader.exec_module(mod);return mod
fixture_spec=importlib.util.spec_from_file_location('seo_improvement_execution_attempt_test',ROOT/'tests'/'seo_improvement_execution_attempt.test.py');fixture=importlib.util.module_from_spec(fixture_spec);assert fixture_spec and fixture_spec.loader;sys.modules['seo_improvement_execution_attempt_test']=fixture;fixture_spec.loader.exec_module(fixture)
load('d1_conditional_update_audit')
repo=load('seo_execution_transaction_repository')
MIGRATION=(ROOT/'migrations'/'0010_seo_execution_transactions.sql').read_text()
def setup():
 db=sqlite3.connect(':memory:');db.execute('PRAGMA foreign_keys=ON');db.executescript(MIGRATION);return db,repo.SeoExecutionTransactionRepository(db)
def source(): return fixture.source()
class TestSeoExecutionTransactions(unittest.TestCase):
 def test_migration_schema_and_append_only_events(self):
  db,r=setup();self.assertEqual({'seo_execution_attempts','seo_execution_attempt_events','seo_execution_post_verifications'},{x[0] for x in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'seo_execution_%'")})
  item,*_=source();r.reserve_approval(item,created_at='2026-08-21T02:10:00Z')
  with self.assertRaises(sqlite3.DatabaseError):db.execute("DELETE FROM seo_execution_attempt_events")
 def test_duplicate_approval_and_preflight_rejected(self):
  _,r=setup();first,*_=source();r.reserve_approval(first,created_at='2026-08-21T02:10:00Z')
  for field in ('execution_approval_id','preflight_id'):
   second,*_=source();second['execution_attempt_id']='another_attempt';second[field]=first[field]
   with self.assertRaises(repo.SeoExecutionDuplicateError):r.reserve_approval(second,created_at='2026-08-21T02:10:01Z')
 def test_cas_transition_append_only_and_outcome_unknown(self):
  _,r=setup();item,*_=source();row=r.reserve_approval(item,created_at='2026-08-21T02:10:00Z');row=r.transition(execution_attempt_id=item['execution_attempt_id'],expected_state='planned',expected_version=0,to_state='approval_reserved',classification='approval_reserved',occurred_at='2026-08-21T02:10:01Z');row=r.transition(execution_attempt_id=item['execution_attempt_id'],expected_state='approval_reserved',expected_version=1,to_state='update_started',classification='update_started',occurred_at='2026-08-21T02:10:02Z');row=r.transition(execution_attempt_id=item['execution_attempt_id'],expected_state='update_started',expected_version=2,to_state='outcome_unknown',classification='outcome_unknown',reason_code='outcome_unknown',occurred_at='2026-08-21T02:10:03Z');self.assertEqual('outcome_unknown',row['state']);self.assertEqual(4,len(r.events(item['execution_attempt_id'])))
  with self.assertRaises(repo.SeoExecutionStateConflict):r.transition(execution_attempt_id=item['execution_attempt_id'],expected_state='update_started',expected_version=2,to_state='outcome_known_success',classification='success',occurred_at='2026-08-21T02:10:04Z')
 def test_stale_conditional_update_and_returning_mismatch(self):
  item,_,_,candidate,_,snapshot=source();row={'id':1,'title':snapshot['title'],'description':snapshot['description'],'category':snapshot['category'],'content':'fixture content','body_markdown':'fixture body','published_at':snapshot['published_at'],'updated_at':snapshot['updated_at'],'seo_status':'ready'}
  import hashlib;candidate=dict(candidate,before_snapshot=dict(candidate['before_snapshot'],content_sha256=hashlib.sha256(row['content'].encode()).hexdigest(),body_markdown_sha256=hashlib.sha256(row['body_markdown'].encode()).hexdigest()))
  statement=repo.build_conditional_snippet_update(candidate,row);self.assertIn('RETURNING id',statement['sql'])
  row['title']='stale'
  with self.assertRaises(repo.SeoExecutionTransactionError):repo.build_conditional_snippet_update(candidate,row)
  with self.assertRaises(repo.SeoExecutionTransactionError):repo.validate_conditional_returning({'success':True,'result':[{'success':True,'meta':{'changed_db':True,'changes':1},'results':[{'id':2}]}]},1)
 def test_post_verification_mismatch_and_rollback_candidate(self):
  db,r=setup();item,_,_,candidate,_,_=fixture.source('outcome_known_success');r.reserve_approval(dict(item,state='planned',classification='not_started',completed_at=None,changed_db=False,changes=0,returned_article_id=None),created_at='2026-08-21T02:10:00Z')
  verification=fixture.attempt.build_post_verification(item,candidate,candidate['after_snapshot']);r.save_post_verification(verification,created_at='2026-08-21T02:12:00Z')
  with self.assertRaises(repo.SeoExecutionDuplicateError):r.save_post_verification(verification,created_at='2026-08-21T02:12:01Z')
  rollback=fixture.attempt.build_rollback_candidate(item,candidate,verification);self.assertFalse(rollback['rollback_authorized'])
if __name__=='__main__':unittest.main()
