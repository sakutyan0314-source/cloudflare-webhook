import copy
import hashlib
import importlib.util
import pathlib
import sqlite3
import sys
import unittest

ROOT = pathlib.Path(__file__).parents[1]
def load(name):
    spec=importlib.util.spec_from_file_location(name, ROOT/'scripts'/(name+'.py')); module=importlib.util.module_from_spec(spec); sys.modules[name]=module; spec.loader.exec_module(module); return module

load('d1_conditional_update_audit')
read_session=load('d1_read_only_session')
runner=load('v1_9_1_legacy_backfill_runner')
module=load('v1_9_1_legacy_backfill_d1_transport')
MANIFEST=ROOT/'ops'/'v1.9.1-seo-ready-legacy-18-19-21-23-24-27-manifest.json'
ORDER=(18,19,21,23,24,27)
BASELINE={'pipeline_completed_sent':6,'sending':0,'reconciliation_events':0,'sync_runs':4,'page_daily_metrics':3,'query_page_daily_metrics':0,'affiliate_click_events':3}

def content(article_id): return f'# fixture {article_id}\n\n## section\n\nbody'

class Response:
    def __init__(self,payload): self.payload=payload

class ReadClient:
    def __init__(self, plans, fail_pre=None, post_bad=None, baseline=BASELINE):
        self.plans,self.fail_pre,self.post_bad,self.baseline_value,self.rows,self.calls=plans,fail_pre,post_bad,baseline,{},[]
        for article_id, plan in plans.items(): self.rows[article_id]={'id':article_id,'content':content(article_id),**plan['expected']}
    def identity(self): self.calls.append(('identity',)); return Response({'success':True,'result':{'name':'prod','uuid':'db'}})
    def fixed_select_batch(self, statements):
        sql,params=statements[0]['sql'],statements[0]['params']; self.calls.append(('select',sql,tuple(params)))
        if sql==module.ARTICLE_SELECT:
            article_id=params[0]
            if article_id==self.fail_pre: self.rows[article_id]['category']='wrong'
            row=dict(self.rows[article_id])
            if article_id==self.post_bad and self.rows[article_id]['seo_status']=='ready': row['title']='wrong'
            rows=[row]
        elif sql==module.FK_SELECT: rows=[]
        else:
            key=next((key for key,candidate in module.BASELINE_SELECTS if candidate==sql),None)
            rows=[{key:self.baseline_value[key]}] if key else []
        return Response({'success':True,'result':[{'success':True,'meta':{'changed_db':False,'rows_written':0},'results':rows}]})

class EditClient:
    def __init__(self, read, mode='ok'): self.read,self.mode,self.calls=read,mode,[]
    def query(self, sql, params):
        article_id=params[7]; self.calls.append((article_id,sql,params))
        if self.mode=='unknown': raise runner.OutcomeUnknownError('unknown')
        if self.mode=='changes': return {'success':True,'result':[{'success':True,'meta':{'changed_db':True,'changes':2,'rows_written':1},'results':[{'id':article_id}]}]}
        if self.mode=='returning': return {'success':True,'result':[{'success':True,'meta':{'changed_db':True,'changes':1,'rows_written':1},'results':[{'id':999}]}]}
        row=self.read.rows[article_id]; row.update({'title':params[0],'description':params[1],'body_markdown':params[2],'category':params[3],'published_at':params[4],'updated_at':params[5],'seo_status':params[6]})
        return {'success':True,'result':[{'success':True,'meta':{'changed_db':True,'changes':1,'rows_written':0},'results':[{'id':article_id}]}]}

class TestLegacyBackfillD1Transport(unittest.TestCase):
    def plans(self):
        plans=copy.deepcopy(runner.load_manifest(MANIFEST))
        for article_id, plan in plans.items():
            digest=hashlib.sha256(content(article_id).encode()).hexdigest(); plan['expected']['content_sha256']=digest; plan['target']['body_markdown_sha256']=digest
        return plans
    def setup(self, mode='ok', fail_pre=None, post_bad=None):
        plans=self.plans(); read_client=ReadClient(plans,fail_pre,post_bad); edit_client=EditClient(read_client,mode); target=module.LegacyD1Target('account','db','prod')
        received={'read':[],'edit':[]}
        def make_read(_target, token): received['read'].append(token); return read_client
        def make_edit(_target, token): received['edit'].append(token); return edit_client
        read_factory=module.ReadD1TransportFactory(target,make_read)
        edit_factory=module.EditD1TransportFactory(target,make_edit)
        return plans,read_client,edit_client,read_factory,edit_factory,received
    def execute_session(self, mode='ok', **kwargs):
        plans,read,edit,read_factory,edit_factory,received=self.setup(mode,**kwargs); cleared=[]; tokens=runner.InMemoryTokenPair('read_dummy','edit_dummy',lambda:cleared.append(True))
        return runner.run_backfill_session(tokens,read_factory,edit_factory,plans,BASELINE),read,edit,cleared,received
    def test_six_articles_fixed_order_with_read_edit_read_and_zero_rows_written_reference(self):
        results,read,edit,cleared,received=self.execute_session()
        self.assertEqual(list(ORDER),[result.article_id for result in results]); self.assertEqual(list(ORDER),[call[0] for call in edit.calls]); self.assertTrue(all(result.rows_written_reference==0 for result in results)); self.assertEqual([True],cleared)
        self.assertEqual(['read_dummy'],received['read']); self.assertEqual(['edit_dummy'],received['edit'])
        for article_id in ORDER:
            article_reads=[call for call in read.calls if call[0]=='select' and call[1]==module.ARTICLE_SELECT and call[2]==(article_id,)]
            self.assertEqual(2,len(article_reads))
    def test_read_identity_or_precondition_failure_sends_no_update(self):
        plans,read,edit,read_factory,edit_factory,_received=self.setup(fail_pre=18); tokens=runner.InMemoryTokenPair('read','edit',lambda:None)
        with self.assertRaisesRegex(runner.BackfillSafetyError,'stale_category'): runner.run_backfill_session(tokens,read_factory,edit_factory,plans,BASELINE)
        self.assertEqual([],edit.calls)
        target=module.LegacyD1Target('account','db','wrong'); factory=module.ReadD1TransportFactory(target,lambda _target, token: read)
        with self.assertRaisesRegex(runner.BackfillSafetyError,'d1_identity_name_mismatch'): factory.create_read_transport('read')
    def test_unknown_changes_and_returning_fail_closed_without_continuation(self):
        for mode, error in [('unknown',runner.OutcomeUnknownError),('changes',runner.BackfillSafetyError),('returning',runner.BackfillSafetyError)]:
            plans,read,edit,rf,ef,_received=self.setup(mode); tokens=runner.InMemoryTokenPair('read','edit',lambda:None)
            with self.assertRaises(error): runner.run_backfill_session(tokens,rf,ef,plans,BASELINE)
            self.assertEqual([18],[call[0] for call in edit.calls])
    def test_post_read_failure_stops_and_transport_never_records_token_or_body(self):
        plans,read,edit,rf,ef,_received=self.setup(post_bad=18); tokens=runner.InMemoryTokenPair('read_opaque','edit_opaque',lambda:None)
        with self.assertRaisesRegex(runner.BackfillSafetyError,'post_update_title_mismatch') as caught:
            runner.run_backfill_session(tokens,rf,ef,plans,BASELINE)
        self.assertEqual([18],[call[0] for call in edit.calls])
        # The fake records request inputs solely to simulate D1. Production
        # transports have no audit/logging path; exposed failures are codes.
        self.assertNotIn('read_opaque',str(caught.exception)); self.assertNotIn('edit_opaque',str(caught.exception)); self.assertNotIn(content(18),str(caught.exception))
    def test_edit_sql_is_fixed_conditional_and_cannot_be_reused_as_read(self):
        plans,read,edit,rf,ef,_received=self.setup(); transport=ef.create_edit_transport('edit')
        response=transport.conditional_update(plans[18],content(18)); self.assertTrue(response['success'])
        self.assertIn('WHERE id=? AND seo_status=?',edit.calls[0][1]); self.assertIn('RETURNING id',edit.calls[0][1]); self.assertNotIn(';',edit.calls[0][1])
        with self.assertRaises(runner.BackfillSafetyError): runner.run_backfill_session(runner.InMemoryTokenPair('read','edit',lambda:None),ef,rf,plans,BASELINE)

    def test_actual_preflight_select_payload_has_only_fixed_selects_and_matching_params(self):
        article,_=read_session.build_fixed_select_request(({'sql':module.ARTICLE_SELECT,'params':[18]},))
        fk,_=read_session.build_fixed_select_request(({'sql':module.FK_SELECT,'params':[]},))
        self.assertEqual(('/query','single',1,True),(article.endpoint_path,article.payload_shape,article.statement_count,article.validator_passed))
        self.assertEqual(('/query','single',1,True),(fk.endpoint_path,fk.payload_shape,fk.statement_count,fk.validator_passed))
        for _key, sql in module.BASELINE_SELECTS:
            baseline,_=read_session.build_fixed_select_request(({'sql':sql,'params':[]},))
            self.assertEqual(('/query','single',1,True),(baseline.endpoint_path,baseline.payload_shape,baseline.statement_count,baseline.validator_passed))

    def test_actual_fixed_selects_compile_in_local_sqlite(self):
        connection=sqlite3.connect(':memory:')
        connection.executescript('''
            CREATE TABLE curation_logs (id INTEGER, content TEXT, seo_status TEXT, category TEXT, title TEXT, description TEXT, body_markdown TEXT, published_at TEXT, updated_at TEXT);
            CREATE TABLE pipeline_runs (status TEXT);
            CREATE TABLE reconciliation_events (id INTEGER);
            CREATE TABLE search_console_sync_runs (id INTEGER);
            CREATE TABLE search_console_page_daily_metrics (id INTEGER);
            CREATE TABLE search_console_query_page_daily_metrics (id INTEGER);
            CREATE TABLE affiliate_click_events (id INTEGER);
        ''')
        for sql, params in ((module.ARTICLE_SELECT,(18,)),(module.FK_SELECT,()),*((sql,()) for _key,sql in module.BASELINE_SELECTS)):
            connection.execute(sql,params).fetchall()

    def test_baseline_aggregation_handles_zero_counts_and_rejects_malformed_or_write_metadata(self):
        plans,read,edit,rf,ef,_received=self.setup(); reader=rf.create_read_transport('read')
        self.assertEqual(BASELINE,reader.baseline())
        zero_reader=module.LegacyReadD1Transport(ReadClient(plans,baseline={key:0 for key in BASELINE}))
        self.assertEqual({key:0 for key in BASELINE},zero_reader.baseline())
        class BadBaselineClient(ReadClient):
            def fixed_select_batch(self, statements):
                response=super().fixed_select_batch(statements)
                sql=statements[0]['sql']
                if any(candidate==sql for _key,candidate in module.BASELINE_SELECTS):
                    response.payload['result'][0]['meta']['changed_db']=True
                return response
        bad=BadBaselineClient(plans); reader=module.LegacyReadD1Transport(bad)
        with self.assertRaises(read_session.D1ReadSafetyError): reader.baseline()
        class MalformedBaselineClient(ReadClient):
            def fixed_select_batch(self, statements):
                response=super().fixed_select_batch(statements)
                sql=statements[0]['sql']
                if any(candidate==sql for _key,candidate in module.BASELINE_SELECTS): response.payload['result'][0]['results']=[{'wrong_key':0}]
                return response
        with self.assertRaises(runner.BackfillSafetyError): module.LegacyReadD1Transport(MalformedBaselineClient(plans)).baseline()

if __name__=='__main__': unittest.main()
