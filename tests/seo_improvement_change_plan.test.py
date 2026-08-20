import copy
import importlib.util
import pathlib
import sys
import unittest
ROOT=pathlib.Path(__file__).parents[1]
def load(name):
 spec=importlib.util.spec_from_file_location(name,ROOT/'scripts'/(name+'.py'));mod=importlib.util.module_from_spec(spec);assert spec and spec.loader;sys.modules[name]=mod;spec.loader.exec_module(mod);return mod
env_mod=load('search_console_improvement_candidate_review');candidate_review=load('search_console_improvement_candidate_review_workflow');proposal_mod=load('seo_improvement_proposal');proposal_review=load('seo_improvement_proposal_review_workflow');plans=load('seo_improvement_change_plan')
def source(status='accepted'):
 env={'schema_version':env_mod.REVIEW_SCHEMA_VERSION,'status':'pending_review','article_id':1,'title':'Ready','category':'saas-cloud','recommendation_type':'seo_review','reason_code':'position_opportunity_with_low_ctr','current_metrics':{'start':'2026-08-08','end':'2026-08-14','clicks':1,'impressions':70,'ctr':.01,'position':10},'previous_metrics':{'start':'2026-08-01','end':'2026-08-07','clicks':2,'impressions':80,'ctr':.02,'position':9},'evidence':{'current_period':{},'previous_period':{},'delta':{},'data_status':'sufficient'},'requires_human_review':True};env['candidate_fingerprint']=env_mod.candidate_fingerprint(env)
 accepted=candidate_review.build_review_record(env,{'status':'accepted','candidate_fingerprint':env['candidate_fingerprint'],'article_id':1,'candidate_reason_code':env['reason_code'],'reviewer_id':'operator','reviewed_at':'2026-08-20T01:00:00Z','review_reason_code':'improvement_generation_candidate_approved','previous_review_id':None})
 proposal_input=proposal_mod.build_proposal_input(env,accepted,model_version='gpt-5.6-terra');proposal=proposal_mod.build_mock_proposal(proposal_input,{'improvement_hypothesis':'検索結果における選択理由を明確にする。','proposed_changes':[{'scope':'snippet','rationale':'反応を検証する。','suggested_direction':'対象課題を明確にする。'}],'expected_impact':'反応変化を観測できる。','risk':'low'})
 reasons={'accepted':'proposal_approved_for_change_plan','rejected':'proposal_not_selected','deferred':'proposal_deferred','pending_review':'proposal_created'};decision={'status':status,'proposal_id':proposal['proposal_id'],'proposal_fingerprint':proposal_review.proposal_fingerprint(proposal,proposal_input),'article_id':1,'candidate_fingerprint':proposal['candidate_fingerprint'],'accepted_review_id':proposal['accepted_review_id'],'reviewer_id':'operator','reviewed_at':'2026-08-20T01:02:03Z','review_reason_code':reasons[status],'previous_review_id':None};record=proposal_review.build_review_record(proposal,proposal_input,decision);return proposal,proposal_input,[record]
class TestSeoChangePlan(unittest.TestCase):
 def plan(self):
  proposal,proposal_input,reviews=source(); input=plans.build_change_plan_input(proposal,proposal_input,reviews); return plans.build_pending_change_plan(input),input
 def test_accepted_proposal_generates_pending_plan(self):
  plan,input=self.plan();plans.validate_change_plan(plan,input);self.assertEqual('pending_review',plan['plan_status'])
 def test_rejected_proposal_is_rejected(self):
  proposal,proposal_input,reviews=source('rejected')
  with self.assertRaises(plans.SeoImprovementChangePlanError):plans.build_change_plan_input(proposal,proposal_input,reviews)
 def test_fingerprint_is_stable_and_changes_with_valid_plan_input(self):
  plan,input=self.plan();self.assertEqual(plan['plan_fingerprint'],plans.plan_fingerprint(copy.deepcopy(plan)));changed=copy.deepcopy(input);changed['change_units'][0]['suggested_direction']='別の抽象方向を検討する。';second=plans.build_pending_change_plan(changed);self.assertNotEqual(plan['plan_fingerprint'],second['plan_fingerprint'])
 def test_source_identity_scope_metrics_and_authorization_fail_closed(self):
  plan,input=self.plan()
  for field,value in (('proposal_id','other'),('article_id',2),('candidate_fingerprint','0'*64)):
   forged=copy.deepcopy(plan);forged[field]=value
   with self.assertRaises(plans.SeoImprovementChangePlanError):plans.validate_change_plan(forged,input)
  for path,value in ((('change_units',0,'scope'),'unknown'),(('verification_plan','metrics'),['clicks']),(('article_change_authorized',),True)):
   forged=copy.deepcopy(plan)
   if len(path)==3:forged[path[0]][path[1]][path[2]]=value
   elif len(path)==2:forged[path[0]][path[1]]=value
   else:forged[path[0]]=value
   with self.assertRaises(plans.SeoImprovementChangePlanError):plans.validate_change_plan(forged,input)
 def test_deterministic_identity_and_no_d1_dependency(self):
  plan,input=self.plan();self.assertEqual(plan['plan_id'],plans.build_pending_change_plan(copy.deepcopy(input))['plan_id'])
if __name__=='__main__':unittest.main()
