import copy
import importlib.util
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).parents[1]
def load(name):
    spec=importlib.util.spec_from_file_location(name, ROOT/'scripts'/(name+'.py')); module=importlib.util.module_from_spec(spec); assert spec and spec.loader; sys.modules[name]=module; spec.loader.exec_module(module); return module
envelope_mod=load('search_console_improvement_candidate_review'); candidate_workflow=load('search_console_improvement_candidate_review_workflow'); proposal_mod=load('seo_improvement_proposal'); workflow=load('seo_improvement_proposal_review_workflow')

def envelope():
    value={'schema_version':envelope_mod.REVIEW_SCHEMA_VERSION,'status':'pending_review','article_id':1,'title':'Ready','category':'saas-cloud','recommendation_type':'seo_review','reason_code':'position_opportunity_with_low_ctr','current_metrics':{'start':'2026-08-08','end':'2026-08-14','clicks':1,'impressions':70,'ctr':.01,'position':10},'previous_metrics':{'start':'2026-08-01','end':'2026-08-07','clicks':2,'impressions':80,'ctr':.02,'position':9},'evidence':{'current_period':{},'previous_period':{},'delta':{},'data_status':'sufficient'},'requires_human_review':True}; value['candidate_fingerprint']=envelope_mod.candidate_fingerprint(value); return value
def source():
    item=envelope(); accepted=candidate_workflow.build_review_record(item,{'status':'accepted','candidate_fingerprint':item['candidate_fingerprint'],'article_id':1,'candidate_reason_code':item['reason_code'],'reviewer_id':'operator','reviewed_at':'2026-08-20T01:00:00Z','review_reason_code':'improvement_generation_candidate_approved','previous_review_id':None}); proposal_input=proposal_mod.build_proposal_input(item,accepted,model_version='gpt-5.6-terra'); proposal=proposal_mod.build_mock_proposal(proposal_input,{'improvement_hypothesis':'検索結果における選択理由を明確にする。','proposed_changes':[{'scope':'snippet','rationale':'反応を検証する。','suggested_direction':'対象課題を明確にする。'}],'expected_impact':'反応変化を観測できる。','risk':'low'}); return proposal,proposal_input
def decision(proposal, proposal_input, status='pending_review', **changes):
    reasons={'pending_review':'proposal_created','accepted':'proposal_approved_for_change_plan','rejected':'proposal_not_selected','deferred':'proposal_deferred'}
    value={'status':status,'proposal_id':proposal['proposal_id'],'proposal_fingerprint':workflow.proposal_fingerprint(proposal,proposal_input),'article_id':proposal['article_id'],'candidate_fingerprint':proposal['candidate_fingerprint'],'accepted_review_id':proposal['accepted_review_id'],'reviewer_id':'operator','reviewed_at':'2026-08-20T01:02:03Z','review_reason_code':reasons.get(status,'unknown'),'previous_review_id':None}; return {**value,**changes}

class TestProposalReviewWorkflow(unittest.TestCase):
    def record(self,status='pending_review',**changes):
        proposal,proposal_input=source(); return workflow.build_review_record(proposal,proposal_input,decision(proposal,proposal_input,status,**changes)),proposal,proposal_input
    def test_initial_pending_and_each_terminal_status(self):
        for status in ('pending_review','accepted','rejected','deferred'):
            record,proposal,proposal_input=self.record(status); workflow.validate_review_record(record,proposal,proposal_input); self.assertEqual(status,record['status'])
    def test_fingerprint_is_stable_and_content_change_is_detected(self):
        proposal,proposal_input=source(); first=workflow.proposal_fingerprint(proposal,proposal_input); self.assertEqual(first,workflow.proposal_fingerprint(copy.deepcopy(proposal),proposal_input)); changed=proposal_mod.build_mock_proposal(proposal_input,{'improvement_hypothesis':'検索結果における選択理由を明確にする。','proposed_changes':[{'scope':'snippet','rationale':'反応を検証する。','suggested_direction':'対象課題を明確にする。'}],'expected_impact':'別の影響を観測する。','risk':'low'})
        self.assertNotEqual(first,workflow.proposal_fingerprint(changed,proposal_input))
    def test_append_only_chain_and_latest_status(self):
        first,proposal,proposal_input=self.record(); chain=workflow.append_review_record([],first,proposal,proposal_input); second=workflow.build_review_record(proposal,proposal_input,decision(proposal,proposal_input,'accepted',previous_review_id=first['proposal_review_id'],reviewed_at='2026-08-20T01:03:03Z')); chain=workflow.append_review_record(chain,second,proposal,proposal_input); self.assertEqual('accepted',workflow.latest_review_status(chain,proposal,proposal_input))
    def test_broken_chain_status_identity_and_authorization_are_rejected(self):
        first,proposal,proposal_input=self.record(); broken=copy.deepcopy(first); broken['previous_review_id']='other'; broken['proposal_review_id']=workflow._review_id(broken)
        with self.assertRaises(workflow.SeoImprovementProposalReviewError): workflow.append_review_record([broken],first,proposal,proposal_input)
        for field,value in (('status','unknown'),('article_id',2),('article_change_authorized',True)):
            forged=copy.deepcopy(first); forged[field]=value
            with self.assertRaises(workflow.SeoImprovementProposalReviewError): workflow.validate_review_record(forged,proposal,proposal_input)
    def test_no_d1_write_dependency(self):
        record,proposal,proposal_input=self.record(); self.assertEqual('pending_review',workflow.latest_review_status([record],proposal,proposal_input))

if __name__=='__main__': unittest.main()
