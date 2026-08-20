import copy,importlib.util,pathlib,sys,unittest
ROOT=pathlib.Path(__file__).parents[1]
def load(name):
 spec=importlib.util.spec_from_file_location(name,ROOT/'scripts'/(name+'.py'));mod=importlib.util.module_from_spec(spec);assert spec and spec.loader;sys.modules[name]=mod;spec.loader.exec_module(mod);return mod
env=load('search_console_improvement_candidate_review');cr=load('search_console_improvement_candidate_review_workflow');proposal=load('seo_improvement_proposal');pr=load('seo_improvement_proposal_review_workflow');plans=load('seo_improvement_change_plan');planr=load('seo_improvement_change_plan_review_workflow');load('ai_recommendation_review');load('ai_recommendation_review_workflow');load('ai_change_plan');candidate=load('seo_improvement_change_candidate');workflow=load('seo_improvement_change_candidate_review_workflow')
def source():
 e={'schema_version':env.REVIEW_SCHEMA_VERSION,'status':'pending_review','article_id':1,'title':'Current title has enough length','category':'saas-cloud','recommendation_type':'seo_review','reason_code':'position_opportunity_with_low_ctr','current_metrics':{'start':'2026-08-08','end':'2026-08-14','clicks':1,'impressions':70,'ctr':.01,'position':10},'previous_metrics':{'start':'2026-08-01','end':'2026-08-07','clicks':2,'impressions':80,'ctr':.02,'position':9},'evidence':{'current_period':{},'previous_period':{},'delta':{},'data_status':'sufficient'},'requires_human_review':True};e['candidate_fingerprint']=env.candidate_fingerprint(e)
 ar=cr.build_review_record(e,{'status':'accepted','candidate_fingerprint':e['candidate_fingerprint'],'article_id':1,'candidate_reason_code':e['reason_code'],'reviewer_id':'operator','reviewed_at':'2026-08-21T01:00:00Z','review_reason_code':'improvement_generation_candidate_approved','previous_review_id':None});pi=proposal.build_proposal_input(e,ar,model_version='gpt-5.6-terra');p=proposal.build_mock_proposal(pi,{'improvement_hypothesis':'検索結果における選択理由を明確にする。','proposed_changes':[{'scope':'snippet','rationale':'反応を検証する。','suggested_direction':'対象課題を明確にする。'}],'expected_impact':'反応変化を観測できる。','risk':'low'});rr=pr.build_review_record(p,pi,{'status':'accepted','proposal_id':p['proposal_id'],'proposal_fingerprint':pr.proposal_fingerprint(p,pi),'article_id':1,'candidate_fingerprint':p['candidate_fingerprint'],'accepted_review_id':p['accepted_review_id'],'reviewer_id':'operator','reviewed_at':'2026-08-21T01:02:00Z','review_reason_code':'proposal_approved_for_change_plan','previous_review_id':None});plani=plans.build_change_plan_input(p,pi,[rr]);plan=plans.build_pending_change_plan(plani);plr=planr.build_review_record(plan,plani,{**{k:plan[k] for k in planr._SOURCE_FIELDS},'status':'accepted','reviewer_id':'operator','reviewed_at':'2026-08-21T01:03:00Z','review_reason_code':'change_candidate_creation_approved','previous_review_id':None});snap={'article_id':1,'title':'Current title has enough length','description':'Current description is sufficiently long to satisfy the snapshot validation requirement.','category':'saas-cloud','content_sha256':'a'*64,'body_markdown_sha256':'b'*64,'published_at':'2026-01-01T00:00:00Z','updated_at':'2026-01-02T00:00:00Z','seo_status':'ready'};ci=candidate.build_change_candidate_input(plan,plani,[plr],snap,{'title':'Improved title that is sufficiently descriptive'});return candidate.build_change_candidate(ci),ci
def decision(item,status='pending_review',**changes):
 reasons={'pending_review':'candidate_created','accepted':'execution_candidate_creation_approved','rejected':'candidate_not_selected','deferred':'candidate_deferred'};value={key:item[key] for key in workflow._SOURCE};value.update({'status':status,'reviewer_id':'operator','reviewed_at':'2026-08-21T01:04:00Z','review_reason_code':reasons.get(status,'unknown'),'previous_review_id':None});return {**value,**changes}
class TestCandidateReview(unittest.TestCase):
 def record(self,status='pending_review',**changes):
  item,ci=source();return workflow.build_review_record(item,ci,decision(item,status,**changes)),item,ci
 def test_initial_and_statuses(self):
  for status in ('pending_review','accepted','rejected','deferred'):
   r,item,ci=self.record(status);workflow.validate_review_record(r,item,ci);self.assertEqual(status,r['status'])
 def test_candidate_fingerprint_and_source_mismatch(self):
  r,item,ci=self.record();self.assertEqual(item['candidate_fingerprint'],r['candidate_fingerprint'])
  for field,value in (('candidate_fingerprint','0'*64),('candidate_id','other'),('plan_id','other')):
   with self.assertRaises(workflow.SeoImprovementChangeCandidateReviewError):workflow.build_review_record(item,ci,decision(item,**{field:value}))
 def test_chain_and_latest_status(self):
  first,item,ci=self.record();chain=workflow.append_review_record([],first,item,ci);second=workflow.build_review_record(item,ci,decision(item,'accepted',previous_review_id=first['candidate_review_id'],reviewed_at='2026-08-21T01:05:00Z'));chain=workflow.append_review_record(chain,second,item,ci);self.assertEqual('accepted',workflow.latest_review_status(chain,item,ci))
 def test_broken_chain_unknown_status_and_authorization(self):
  first,item,ci=self.record();broken=copy.deepcopy(first);broken['previous_review_id']='other';broken['candidate_review_id']=workflow._review_id(broken)
  with self.assertRaises(workflow.SeoImprovementChangeCandidateReviewError):workflow.append_review_record([broken],first,item,ci)
  for field,value in (('status','unknown'),('execution_authorized',True)):
   bad=copy.deepcopy(first);bad[field]=value
   with self.assertRaises(workflow.SeoImprovementChangeCandidateReviewError):workflow.validate_review_record(bad,item,ci)
 def test_no_d1_write_dependency(self):
  r,item,ci=self.record();self.assertEqual('pending_review',workflow.latest_review_status([r],item,ci))
if __name__=='__main__':unittest.main()
