import importlib.util, json, pathlib, sys, tempfile, unittest
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).parents[1]

def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / f'{name}.py')
    module = importlib.util.module_from_spec(spec); assert spec and spec.loader
    sys.modules[name] = module; spec.loader.exec_module(module); return module

local = load('market_signal_local_report')

def report():
    return {
        'schema_version':'market-signal-report-v1', 'report_fingerprint':'market_signal_' + 'a'*64,
        'query':'Microsoft 365 Copilot エージェント', 'observed_at':'2026-08-26T00:00:00Z',
        'source':{'provider':'serpapi_cache','returned_results_count':9},
        'market_analysis':{'common_intents':['how'], 'common_angles':['導入'],
                            'uncovered_questions':['hypothesis: 棚卸し手順'],
                            'own_site_gap_assessment':{'classification':'possible_gap','rationale':'metadata only'},
                            'confidence':'medium'},
        'own_site':{'overlap':{'classification':'potential_overlap','matched_articles':[{'article_id':40,'title':'既存記事','category':'security-governance','matched_terms':['copilot']}]},
                     'search_console_signal':{'status':'insufficient_data','observation_days':3,'impressions':4,'clicks':0,'ctr':0.0},
                     'affiliate_signal':{'article_click_count':1,'discord_click_count':11,'usable_click_count':1,'reliability_status':'discord_click_human_status_unknown_not_used'}},
        'candidate_drafts':[{'topic':'候補','reason':'metadata only','market_evidence':'SERP metadata','own_site_gap':'possible_gap','expected_search_intent':'how','target_audience':'管理者','user_problem':'手順不明','monetization_relevance':'not_evaluated','duplicate_risk':'low','confidence':'medium','requires_human_review':True,'content_generation_authorized':False,'execution_authorized':False,'publication_authorized':False}],
        'requires_human_review':True,'content_generation_authorized':False,'execution_authorized':False,'publication_authorized':False,
        'serp_results':[{'raw':'must-not-persist'}], 'market_analysis_usage':{'input_tokens':1800,'output_tokens':1000,'output_tokens_details':{'reasoning_tokens':700}},
    }

class TestLocalMarketSignalReport(unittest.TestCase):
    def test_success_report_is_allowlisted_and_saved_atomically(self):
        value = local.build_local_market_analysis_report(report=report(), model='gpt-5.6-terra', serpapi_request_count=0, openai_call_count=1, usage=report()['market_analysis_usage'])
        self.assertEqual('market-signal-local-report-v1', value['schema_version'])
        self.assertEqual(700, value['usage']['reasoning_tokens'])
        self.assertTrue(value['safety']['requires_human_review']); self.assertFalse(value['safety']['publication_authorized'])
        serialized = json.dumps(value, ensure_ascii=False)
        for forbidden in ('must-not-persist', 'matched_terms', 'raw', 'api_key', 'authorization'):
            self.assertNotIn(forbidden, serialized)
        with tempfile.TemporaryDirectory() as directory:
            path = local.save_local_market_analysis_report(value, pathlib.Path(directory), now=datetime(2026,8,26,12,30,tzinfo=timezone.utc))
            self.assertEqual('market-signal-20260826T123000Z-' + 'a'*64 + '.json', path.name)
            self.assertEqual(value, json.loads(path.read_text()))
            self.assertIn('MARKET ANALYSIS: SUCCESS', local.render_saved_market_analysis_summary(value, path))
            self.assertIn(str(path), local.render_saved_market_analysis_summary(value, path))

    def test_invalid_report_is_not_written(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                local.save_local_market_analysis_report({'schema_version':'wrong'}, pathlib.Path(directory))
            self.assertEqual([], list(pathlib.Path(directory).iterdir()))

if __name__ == '__main__':
    unittest.main()
