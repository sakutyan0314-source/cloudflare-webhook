import copy
import importlib.util
import pathlib
import sys
import unittest
ROOT=pathlib.Path(__file__).parents[1]
def load(name):
 spec=importlib.util.spec_from_file_location(name,ROOT/'scripts'/(name+'.py'));mod=importlib.util.module_from_spec(spec);assert spec and spec.loader;sys.modules[name]=mod;spec.loader.exec_module(mod);return mod
env=load('search_console_improvement_candidate_review');cr=load('search_console_improvement_candidate_review_workflow');proposal_mod=load('seo_improvement_proposal');pr=load('seo_improvement_proposal_review_workflow');plans=load('seo_improvement_change_plan');plan_reviews=load('seo_improvement_change_plan_review_workflow');load('ai_recommendation_review');load('ai_recommendation_review_workflow');load('ai_change_plan');candidate=load('seo_improvement_change_candidate')
def source():
 e={'schema_version':env.REVIEW_SCHEMA_VERSION,'status':'pending_review','article_id':1,'title':'Current title has enough length','category':'saas-cloud','recommendation_type':'seo_review','reason_code':'position_opportunity_with_low_ctr','current_metrics':{'start':'2026-08-08','end':'2026-08-14','clicks':1,'impressions':70,'ctr':.01,'position':10},'previous_metrics':{'start':'2026-08-01','end':'2026-08-07','clicks':2,'impressions':80,'ctr':.02,'position':9},'evidence':{'current_period':{},'previous_period':{},'delta':{},'data_status':'sufficient'},'requires_human_review':True};e['candidate_fingerprint']=env.candidate_fingerprint(e)
 ar=cr.build_review_record(e,{'status':'accepted','candidate_fingerprint':e['candidate_fingerprint'],'article_id':1,'candidate_reason_code':e['reason_code'],'reviewer_id':'operator','reviewed_at':'2026-08-21T01:00:00Z','review_reason_code':'improvement_generation_candidate_approved','previous_review_id':None});pi=proposal_mod.build_proposal_input(e,ar,model_version='gpt-5.6-terra');p=proposal_mod.build_mock_proposal(pi,{'improvement_hypothesis':'検索結果における選択理由を明確にする。','proposed_changes':[{'scope':'snippet','rationale':'反応を検証する。','suggested_direction':'対象課題を明確にする。'}],'expected_impact':'反応変化を観測できる。','risk':'low'});rr=pr.build_review_record(p,pi,{'status':'accepted','proposal_id':p['proposal_id'],'proposal_fingerprint':pr.proposal_fingerprint(p,pi),'article_id':1,'candidate_fingerprint':p['candidate_fingerprint'],'accepted_review_id':p['accepted_review_id'],'reviewer_id':'operator','reviewed_at':'2026-08-21T01:02:00Z','review_reason_code':'proposal_approved_for_change_plan','previous_review_id':None});plan_input=plans.build_change_plan_input(p,pi,[rr]);plan=plans.build_pending_change_plan(plan_input);plan_r=plan_reviews.build_review_record(plan,plan_input,{**{k:plan[k] for k in plan_reviews._SOURCE_FIELDS},'status':'accepted','reviewer_id':'operator','reviewed_at':'2026-08-21T01:03:00Z','review_reason_code':'change_candidate_creation_approved','previous_review_id':None});snapshot={'article_id':1,'title':'Current title has enough length','description':'Current description is sufficiently long to satisfy the snapshot validation requirement.','category':'saas-cloud','content_sha256':'a'*64,'body_markdown_sha256':'b'*64,'published_at':'2026-01-01T00:00:00Z','updated_at':'2026-01-02T00:00:00Z','seo_status':'ready'};return plan,plan_input,[plan_r],snapshot
class TestSeoChangeCandidate(unittest.TestCase):
 def build(self,changes={'title':'Improved title that is sufficiently descriptive'}):
  plan,plan_input,reviews,snapshot=source();i=candidate.build_change_candidate_input(plan,plan_input,reviews,snapshot,changes);return candidate.build_change_candidate(i),i,snapshot
 def test_accepted_plan_generates_candidate_and_title_or_description(self):
  item,i,_=self.build();candidate.validate_change_candidate(item,i);self.assertIn('title',item['proposed_changes']);item,i,_=self.build({'description':'Improved description contains enough useful detail for the search result snippet.'});self.assertIn('description',item['proposed_changes'])
 def test_fingerprint_stability_change_and_deterministic_identity(self):
  item,i,_=self.build();self.assertEqual(item['candidate_fingerprint'],candidate.candidate_fingerprint(copy.deepcopy(item)));second,_,_=self.build({'title':'Different improved title that remains sufficiently descriptive'});self.assertNotEqual(item['candidate_fingerprint'],second['candidate_fingerprint']);self.assertEqual(item['candidate_id'],candidate.build_change_candidate(copy.deepcopy(i))['candidate_id'])
 def test_stale_source_and_forbidden_changes_are_rejected(self):
  item,i,snapshot=self.build();stale=copy.deepcopy(snapshot);stale['updated_at']='2026-01-03T00:00:00Z'
  with self.assertRaises(candidate.SeoImprovementChangeCandidateError):candidate.validate_change_candidate(item,i,current_snapshot=stale)
  plan,plan_input,reviews,snapshot=source()
  for changes in ({'body_markdown':'forbidden'},{'sql':'UPDATE'},{'title':'short'}):
   with self.assertRaises(candidate.SeoImprovementChangeCandidateError):candidate.build_change_candidate_input(plan,plan_input,reviews,snapshot,changes)
 def test_source_mismatch_and_authorization_are_rejected(self):
  item,i,_=self.build()
  for field,value in (('plan_fingerprint','0'*64),('proposal_fingerprint','0'*64),('article_id',2),('article_change_authorized',True)):
   forged=copy.deepcopy(item);forged[field]=value
   with self.assertRaises(candidate.SeoImprovementChangeCandidateError):candidate.validate_change_candidate(forged,i)
 def test_no_d1_write_dependency(self):
  item,i,_=self.build();self.assertTrue(item['requires_human_review'])
if __name__=='__main__':unittest.main()
