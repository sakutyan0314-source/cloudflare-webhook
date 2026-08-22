import importlib.util
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]
def load(name):
 spec=importlib.util.spec_from_file_location(name,ROOT/'scripts'/f'{name}.py');module=importlib.util.module_from_spec(spec);assert spec and spec.loader;sys.modules[name]=module;spec.loader.exec_module(module);return module
topic=load('topic_candidate');review=load('topic_candidate_review');input_module=load('topic_candidate_production_input');canary=load('topic_candidate_canary_production');bundle_module=load('approved_content_authorization_bundle')

class BundleTests(unittest.TestCase):
 def chain(self):
  at='2026-08-22T18:52:32.000Z'; candidate=topic.build_topic_candidate({'created_at':at,'topic':'Microsoft 365 Copilot エージェントのガバナンス導入手順','proposed_title_hint':'Microsoft 365 Copilot エージェントのガバナンス手順','primary_intent':'how','secondary_intents':['problem'],'target_audience':'Microsoft 365管理者','target_audience_key':'Microsoft 365管理者','problem_to_solve':'棚卸しとアクセス制御','demand_evidence':[{'evidence_type':'official_product_documentation','evidence_source':'Microsoft Learn guide','evidence_observed_at':at},{'evidence_type':'serp_result','evidence_source':'SERP observed','evidence_observed_at':at}],'search_volume_known':False,'trend_direction_known':False,'related_article_ids':[28,31],'possible_parent_article_id':23,'possible_child_article_ids':[],'duplicate_risk':'low','cannibalization_risk':'low','content_gap_type':'how_to_gap','cluster_id':'ai-agent-foundation'},injected_overlap='cluster_sibling')
  human=review.build_human_review(candidate,decision='approve_for_content_planning',reason_codes=['demand_evidence_sufficient','priority_confirmed','cluster_fit_confirmed'],reviewed_at='2026-08-22T19:00:00.000Z');planned=review.build_approved_topic_planning_handoff(candidate,[human],created_at='2026-08-22T19:01:00.000Z');handoff=input_module.build_content_planning_handoff(candidate,[human],planned,created_at='2026-08-22T19:02:00.000Z');production=input_module.build_approved_content_production_input(handoff,created_at='2026-08-22T19:03:00.000Z');approval=canary.build_content_production_approval(production,approved_by='human_reviewer',approved_at='2026-08-22T19:04:00.000Z',expires_at='2026-08-22T20:04:00.000Z',max_ttl_seconds=7200)
  return candidate,[human],planned,handoff,production,approval
 def test_validated_bundle_is_immutable_and_stores_no_article_content(self):
  candidate,reviews,planned,handoff,production,approval=self.chain();bundle=bundle_module.build_authorization_bundle(candidate=candidate,reviews=reviews,approved_planning=planned,content_handoff=handoff,production_input=production,approval=approval,created_at='2026-08-22T19:05:00.000Z',max_ttl_seconds=7200);self.assertEqual(bundle['production_input_id'],production['production_input_id']);self.assertTrue(bundle['single_use']);self.assertNotIn('category',bundle['production_input_snapshot']);self.assertNotIn('"content":',topic.canonical_json(bundle))
  db=sqlite3.connect(':memory:');db.executescript((ROOT/'migrations'/'0011_approved_content_authorization_bundles.sql').read_text());repo=bundle_module.AuthorizationBundleRepository(db);repo.insert(bundle)
  with self.assertRaises(bundle_module.ApprovedContentAuthorizationBundleError):repo.insert(bundle)
 def test_tampered_source_is_rejected_before_bundle_creation(self):
  candidate,reviews,planned,handoff,production,approval=self.chain();approval=dict(approval,topic_candidate_id='other')
  with self.assertRaises(bundle_module.ApprovedContentAuthorizationBundleError):bundle_module.build_authorization_bundle(candidate=candidate,reviews=reviews,approved_planning=planned,content_handoff=handoff,production_input=production,approval=approval,created_at='2026-08-22T19:05:00.000Z')
if __name__=='__main__':unittest.main()
