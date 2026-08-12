import importlib.util, pathlib, unittest
ROOT = pathlib.Path(__file__).parents[1]
spec = importlib.util.spec_from_file_location('rules', ROOT / 'scripts' / 'ai_recommendation_rules.py'); rules = importlib.util.module_from_spec(spec); spec.loader.exec_module(rules)

def obs(**overrides):
    value = {'impressions': 100, 'search_clicks': 1, 'affiliate_click_count': 0, 'observation_days': 14, 'trend': 'stable'}; value.update(overrides); return value

class RulesTest(unittest.TestCase):
    def test_insufficient_and_growing_do_not_call_ai(self):
        self.assertFalse(rules.assess(obs(impressions=1))['ai_eligible'])
        self.assertEqual('continue_observation', rules.assess(obs(trend='growing'))['candidate_types'][0])
    def test_candidate_rules(self):
        self.assertIn('improve_affiliate_cta', rules.assess(obs())['candidate_types'])
        self.assertIn('refresh_content', rules.assess(obs(trend='declining'))['candidate_types'])
        self.assertIn('improve_ctr', rules.assess(obs(search_clicks=0))['candidate_types'])
        self.assertTrue(rules.assess(obs(affiliate_click_count=1))['ai_eligible'])  # high-value-like valid input
    def test_integrity_errors_are_stop_conditions(self):
        with self.assertRaises(rules.InvalidObservationError): rules.assess(obs(impressions=-1))
        with self.assertRaises(rules.InvalidObservationError): rules.assess({'impressions': 1})
if __name__ == '__main__': unittest.main()
