import copy
import importlib.util
import pathlib
import sys
import unittest

ROOT=pathlib.Path(__file__).parents[1]
def load(name):
 spec=importlib.util.spec_from_file_location(name,ROOT/'scripts'/(name+'.py'));mod=importlib.util.module_from_spec(spec);assert spec and spec.loader;sys.modules[name]=mod;spec.loader.exec_module(mod);return mod
env_mod=load('search_console_improvement_candidate_review');candidate_review=load('search_console_improvement_candidate_review_workflow');proposal_mod=load('seo_improvement_proposal');proposal_review=load('seo_improvement_proposal_review_workflow');plans=load('seo_improvement_change_plan');workflow=load('seo_improvement_change_plan_review_workflow')
def source():
 env={'schema_version':env_mod.REVIEW_SCHEMA_VERSION,'status':'pending_review','article_id':1,'title':'Ready','category':'saas-cloud','recommendation_type':'seo_review','reason_code':'position_opportunity_with_low_ctr','current_metrics':{'start':'2026-08-08','end':'2026-08-14','clicks':1,'impressions':70,'ctr':.01,'position':10},'previous_metrics':{'start':'2026-08-01','end':'2026-08-07','clicks':2,'impressions':80,'ctr':.02,'position':9},'evidence':{'current_period':{},'previous_period':{},'delta':{},'data_status':'sufficient'},'requires_human_review':True};env['candidate_fingerprint']=env_mod.candidate_fingerprint(env)
 accepted=candidate_review.build_review_record(env,{'status':'accepted','candidate_fingerprint':env['candidate_fingerprint'],'article_id':1,'candidate_reason_code':env['reason_code'],'reviewer_id':'operator','reviewed_at':'2026-08-21T01:00:00Z','review_reason_code':'improvement_generation_candidate_approved','previous_review_id':None})
 pi=proposal_mod.build_proposal_input(env,accepted,model_version='gpt-5.6-terra');proposal=proposal_mod.build_mock_proposal(pi,{'improvement_hypothesis':'検索結果における選択理由を明確にする。','proposed_changes':[{'scope':'snippet','rationale':'反応を検証する。','suggested_direction':'対象課題を明確にする。'}],'expected_impact':'反応変化を観測できる。','risk':'low'})
 pr=proposal_review.build_review_record(proposal,pi,{'status':'accepted','proposal_id':proposal['proposal_id'],'proposal_fingerprint':proposal_review.proposal_fingerprint(proposal,pi),'article_id':1,'candidate_fingerprint':proposal['candidate_fingerprint'],'accepted_review_id':proposal['accepted_review_id'],'reviewer_id':'operator','reviewed_at':'2026-08-21T01:02:03Z','review_reason_code':'proposal_approved_for_change_plan','previous_review_id':None})
 plan_input=plans.build_change_plan_input(proposal,pi,[pr]);return plans.build_pending_change_plan(plan_input),plan_input
def decision(plan,status='pending_review',**changes):
 reasons={'pending_review':'plan_created','accepted':'change_candidate_creation_approved','rejected':'plan_not_selected','deferred':'plan_deferred'};value={key:plan[key] for key in workflow._SOURCE_FIELDS};value.update({'status':status,'reviewer_id':'operator','reviewed_at':'2026-08-21T01:03:03Z','review_reason_code':reasons.get(status,'unknown'),'previous_review_id':None});return {**value,**changes}
class TestChangePlanReviewWorkflow(unittest.TestCase):
 def record(self,status='pending_review',**changes):
  plan,plan_input=source();return workflow.build_review_record(plan,plan_input,decision(plan,status,**changes)),plan,plan_input
 def test_initial_and_all_statuses(self):
  for status in ('pending_review','accepted','rejected','deferred'):
   record,plan,plan_input=self.record(status);workflow.validate_review_record(record,plan,plan_input);self.assertEqual(status,record['status'])
 def test_plan_fingerprint_and_source_identity_are_required(self):
  record,plan,plan_input=self.record();self.assertEqual(plan['plan_fingerprint'],record['plan_fingerprint'])
  for field,value in (('plan_fingerprint','0'*64),('proposal_id','other'),('article_id',2)):
   with self.assertRaises(workflow.SeoImprovementChangePlanReviewError):workflow.build_review_record(plan,plan_input,decision(plan,**{field:value}))
 def test_chain_and_latest_status(self):
  first,plan,plan_input=self.record();chain=workflow.append_review_record([],first,plan,plan_input);second=workflow.build_review_record(plan,plan_input,decision(plan,'accepted',previous_review_id=first['plan_review_id'],reviewed_at='2026-08-21T01:04:03Z'));chain=workflow.append_review_record(chain,second,plan,plan_input);self.assertEqual('accepted',workflow.latest_review_status(chain,plan,plan_input))
 def test_broken_chain_status_and_authorization_are_rejected(self):
  first,plan,plan_input=self.record();broken=copy.deepcopy(first);broken['previous_review_id']='other';broken['plan_review_id']=workflow._review_id(broken)
  with self.assertRaises(workflow.SeoImprovementChangePlanReviewError):workflow.append_review_record([broken],first,plan,plan_input)
  for field,value in (('status','unknown'),('article_change_authorized',True)):
   forged=copy.deepcopy(first);forged[field]=value
   with self.assertRaises(workflow.SeoImprovementChangePlanReviewError):workflow.validate_review_record(forged,plan,plan_input)
 def test_no_d1_write_dependency(self):
  record,plan,plan_input=self.record();self.assertEqual('pending_review',workflow.latest_review_status([record],plan,plan_input))
if __name__=='__main__':unittest.main()
