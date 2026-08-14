import importlib.util, pathlib, sys, unittest
ROOT=pathlib.Path(__file__).parents[1]
def load(name):
 spec=importlib.util.spec_from_file_location(name,ROOT/'scripts'/f'{name}.py');mod=importlib.util.module_from_spec(spec);sys.modules[name]=mod;spec.loader.exec_module(mod);return mod
review=load('ai_recommendation_review')
REC={'article_id':17,'category':'ai-automation','title':'題名','current_state':{'impressions':10},'recommendation_id':'rec_safe','recommendation_type':'improve_title','priority':'high','confidence':'high','risk_level':'low','evidence':[{'field':'observation.impressions','value':10}],'reasons':'根拠。','suggested_action':'改善する。','expected_effect':'効果を観測する。','requires_human_review':True,'data_sufficiency':'sufficient','generated_at':'2026-08-14T00:00:00Z'}
class ReviewTest(unittest.TestCase):
 def test_envelope_has_only_approved_review_fields(self):
  envelope=review.build_review_envelope(REC);self.assertEqual('pending',envelope['review_status']);self.assertNotIn('response',envelope);self.assertTrue(envelope['requires_human_review'])
 def test_rubric_requires_evidence_two_and_total_eight(self):
  envelope=review.build_review_envelope(REC);good={field:2 for field in review.RUBRIC_FIELDS};self.assertTrue(review.score_review(envelope,good)['eligible_for_v2_0_b_human_approval']);bad=dict(good,evidence_accuracy=1);self.assertFalse(review.score_review(envelope,bad)['eligible_for_v2_0_b_human_approval'])
 def test_invalid_review_cannot_be_scored(self):
  with self.assertRaises(Exception):review.score_review({'schema_version':'bad'}, {})
if __name__=='__main__':unittest.main()
