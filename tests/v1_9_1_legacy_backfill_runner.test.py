import copy
import hashlib
import importlib.util
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).parents[1]
def load(name):
    spec=importlib.util.spec_from_file_location(name,ROOT/'scripts'/(name+'.py')); module=importlib.util.module_from_spec(spec); sys.modules[name]=module; spec.loader.exec_module(module); return module

audit=load('d1_conditional_update_audit')
read_module=load('d1_read_only_session')
runner_module=load('v1_9_1_legacy_backfill_runner')
MANIFEST=ROOT/'ops'/'v1.9.1-seo-ready-legacy-18-19-21-23-24-27-manifest.json'

def fixture_content(article_id):
    return f'# 記事 {article_id} の十分に長い本文です。\n\n## 要点\n\n本文。'

class ReadMock:
    role='read'
    def __init__(self, plans, baseline):
        self.plans, self.baseline_value, self.rows, self.calls = plans, baseline, {}, []
        for article_id, plan in plans.items():
            self.rows[article_id]={'id':article_id,'content':fixture_content(article_id), **plan['expected']}
    def read_article(self, article_id): self.calls.append(('read',article_id)); return dict(self.rows[article_id])
    def foreign_key_check(self): self.calls.append(('fk',)); return 0
    def baseline(self): self.calls.append(('baseline',)); return dict(self.baseline_value)

class EditMock:
    role='edit'
    def __init__(self, read, mode='ok'): self.read, self.mode, self.calls = read, mode, []
    def conditional_update(self, plan, content):
        article_id=next(key for key,value in self.read.plans.items() if value is plan)
        self.calls.append(('edit',article_id))
        if self.mode=='unknown': raise runner_module.OutcomeUnknownError('unknown')
        if self.mode=='bad_response': return {'success':True,'result':[{'success':True,'meta':{'changed_db':True,'changes':0},'results':[]}]}
        row=self.read.rows[article_id]; row.update({key:plan['target'][key] for key in ('title','description','category','published_at','updated_at','seo_status')}); row['body_markdown']=content
        return {'success':True,'result':[{'success':True,'meta':{'changed_db':True,'changes':1,'rows_written':3},'results':[{'id':article_id}]}]}

class ReadFactory:
    role='read'
    def __init__(self, read): self.read, self.tokens = read, []
    def create_read_transport(self, token): self.tokens.append(token); return self.read

class EditFactory:
    role='edit'
    def __init__(self, edit): self.edit, self.tokens = edit, []
    def create_edit_transport(self, token): self.tokens.append(token); return self.edit

class ResumeEditFactory(EditFactory):
    def create_resume_edit_transport(self, token): self.tokens.append(token); return self.edit

class LegacyRunnerTest(unittest.TestCase):
    def plans(self):
        plans=copy.deepcopy(runner_module.load_manifest(MANIFEST))
        for article_id, plan in plans.items():
            digest=hashlib.sha256(fixture_content(article_id).encode()).hexdigest()
            plan['expected']['content_sha256']=digest
            plan['target']['body_markdown_sha256']=digest
        return plans
    def setup_runner(self, mode='ok'):
        plans=self.plans(); baseline={'pipeline_completed_sent':6,'sending':0,'reconciliation_events':0,'sync_runs':4,'page_daily_metrics':3,'query_page_daily_metrics':0,'affiliate_click_events':3}; read=ReadMock(plans,baseline); edit=EditMock(read,mode); return read,edit,runner_module.LegacyBackfillRunner(read,edit,plans),baseline
    def test_token_roles_are_distinct_redacted_and_cleaned(self):
        cleared=[]; pair=runner_module.InMemoryTokenPair('read_dummy','edit_dummy',lambda:cleared.append(True))
        self.assertNotIn('read_dummy',repr(pair)); self.assertNotIn('edit_dummy',repr(pair)); self.assertEqual('read_dummy',pair.read_token()); self.assertEqual('edit_dummy',pair.edit_token()); pair.close(); self.assertEqual([True],cleared)
        with self.assertRaises(runner_module.BackfillSafetyError): runner_module.InMemoryTokenPair('same','same')

    def test_resume_target_set_is_fixed_before_tokens_and_excludes_id_18(self):
        valid=runner_module.load_resume_manifest(MANIFEST,(19,21,23,24,27))
        self.assertEqual((19,21,23,24,27),tuple(valid)); self.assertNotIn(18,valid)
        for invalid in ((18,19,21,23,24,27),(19,22,21,23,24,27),(19,25,21,23,24,27),(19,21,23,24),(21,19,23,24,27),(19,21,21,24,27)):
            with self.assertRaisesRegex(runner_module.BackfillSafetyError,'resume_target_set_rejected'):
                runner_module.load_resume_manifest(MANIFEST,invalid)
    def test_sequential_read_edit_read_completes_in_fixed_order(self):
        read,edit,runner,baseline=self.setup_runner(); results=runner.run(baseline)
        self.assertEqual(list(runner_module.BACKFILL_ORDER),[item.article_id for item in results]); self.assertEqual(list(runner_module.BACKFILL_ORDER),[item[1] for item in edit.calls]); self.assertTrue(all(item.changes==1 and item.returned_id==item.article_id for item in results)); self.assertEqual(27,len([item for item in read.calls if item[0]=='read']))
    def test_stale_stops_before_first_edit_and_remaining_articles(self):
        read,edit,runner,baseline=self.setup_runner(); read.rows[19]['category']='changed'
        with self.assertRaisesRegex(runner_module.BackfillSafetyError,'remaining_target_state_changed'): runner.run(baseline)
        self.assertEqual([('edit',18)],edit.calls)
    def test_outcome_unknown_never_retries_or_continues(self):
        read,edit,runner,baseline=self.setup_runner('unknown')
        with self.assertRaises(runner_module.OutcomeUnknownError): runner.run(baseline)
        self.assertEqual([('edit',18)],edit.calls)
    def test_bad_update_response_and_post_state_failure_stop(self):
        read,edit,runner,baseline=self.setup_runner('bad_response')
        with self.assertRaisesRegex(runner_module.BackfillSafetyError,'update_result_invalid'): runner.run(baseline)
        self.assertEqual([('edit',18)],edit.calls)
    def test_monotonic_counter_increases_continue_and_are_audited(self):
        read,edit,runner,baseline=self.setup_runner(); original=read.baseline
        def increased(): return dict(original(),pipeline_completed_sent=7,sync_runs=5,page_daily_metrics=4,affiliate_click_events=4)
        read.baseline=increased
        results=runner.run(baseline)
        self.assertEqual(6,len(results)); audit=runner.non_target_audit[0].counters
        for key in ('pipeline_completed_sent','sync_runs','page_daily_metrics','affiliate_click_events'):
            self.assertEqual('monotonic_increase_observed',audit[key]['classification'])

    def test_decrease_and_safety_critical_state_stop_after_verified_update(self):
        for changed, code in (({'pipeline_completed_sent':5},'unexpected_decrease'),({'sending':1},'safety_critical_change'),({'reconciliation_events':1},'safety_critical_change')):
            read,edit,runner,baseline=self.setup_runner(); original=read.baseline
            read.baseline=lambda changed=changed: dict(original(),**changed)
            with self.assertRaisesRegex(runner_module.BackfillSafetyError,code): runner.run(baseline)
            self.assertEqual([('edit',18)],edit.calls)
            record=runner.execution_audit[-1]
            self.assertIn('update_result_verified',record.states)
            self.assertTrue(record.changed_db); self.assertEqual(1,record.changes); self.assertEqual(18,record.returned_id)

    def test_parallel_change_to_a_remaining_target_stops_after_verified_update(self):
        read,edit,runner,baseline=self.setup_runner(); original=read.foreign_key_check
        def changed_remaining_target():
            read.rows[19]['category']='changed'
            return original()
        read.foreign_key_check=changed_remaining_target
        with self.assertRaisesRegex(runner_module.BackfillSafetyError,'remaining_target_state_changed'): runner.run(baseline)
        self.assertEqual([('edit',18)],edit.calls)
        self.assertIn('post_read_verified',runner.execution_audit[-1].states)

    def test_verified_update_audit_survives_later_stop_without_sensitive_data(self):
        read,edit,_runner,baseline=self.setup_runner(); original=read.baseline
        read.baseline=lambda: dict(original(),sending=1)
        pair=runner_module.InMemoryTokenPair('read_token','edit_token',lambda:None)
        with self.assertRaises(runner_module.BackfillSafetyError) as caught:
            runner_module.run_backfill_session(pair,ReadFactory(read),EditFactory(edit),read.plans,baseline)
        records=caught.exception.execution_audit
        self.assertTrue(records); record=records[-1]
        self.assertIn('post_read_verified',record.states); self.assertTrue(record.changed_db)
        self.assertEqual(1,record.changes); self.assertEqual(18,record.returned_id); self.assertEqual(3,record.rows_written_reference)
        self.assertIsNotNone(record.confirmed_at)
        self.assertNotIn('本文',repr(records)); self.assertNotIn('read_token',repr(records)); self.assertNotIn('edit_token',repr(records))
    def test_duplicate_and_role_confusion_are_rejected(self):
        read,edit,runner,baseline=self.setup_runner(); runner._sent.add(18)
        with self.assertRaisesRegex(runner_module.BackfillSafetyError,'duplicate_update_attempt'): runner.run(baseline)
        with self.assertRaises(runner_module.BackfillSafetyError): runner_module.LegacyBackfillRunner(read,read,self.plans())

    def test_session_binds_each_token_to_its_only_role_and_cleans_up_on_failure(self):
        read,edit,_runner,baseline=self.setup_runner('unknown')
        read_factory,edit_factory=ReadFactory(read),EditFactory(edit)
        cleared=[]; pair=runner_module.InMemoryTokenPair('read_only_token','edit_only_token',lambda:cleared.append(True))
        with self.assertRaises(runner_module.OutcomeUnknownError):
            runner_module.run_backfill_session(pair,read_factory,edit_factory,read.plans,baseline)
        self.assertEqual(['read_only_token'],read_factory.tokens)
        self.assertEqual(['edit_only_token'],edit_factory.tokens)
        self.assertEqual([True],cleared)
        with self.assertRaises(runner_module.BackfillSafetyError): pair.read_token()
        role_error_cleanup=[]
        with self.assertRaises(runner_module.BackfillSafetyError):
            runner_module.run_backfill_session(runner_module.InMemoryTokenPair('read2','edit2',lambda:role_error_cleanup.append(True)),edit_factory,read_factory,read.plans,baseline)
        self.assertEqual([True],role_error_cleanup)

    def test_resume_session_executes_only_five_articles_without_six_article_fallback(self):
        read,edit,_runner,baseline=self.setup_runner(); plans={key:value for key,value in read.plans.items() if key in runner_module.RESUME_TARGET_ORDER}
        read.plans=plans
        pair=runner_module.InMemoryTokenPair('resume_read','resume_edit',lambda:None)
        results=runner_module.run_resume_backfill_session(pair,ReadFactory(read),ResumeEditFactory(edit),plans,baseline)
        self.assertEqual(list(runner_module.RESUME_TARGET_ORDER),[item.article_id for item in results])
        self.assertEqual(list(runner_module.RESUME_TARGET_ORDER),[call[1] for call in edit.calls])
        self.assertNotIn(18,[call[1] for call in edit.calls])

if __name__=='__main__': unittest.main()
