import copy, importlib.util, json, pathlib, sys, tempfile, unittest
ROOT=pathlib.Path(__file__).parents[1]
def load(name):
 spec=importlib.util.spec_from_file_location(name,ROOT/'scripts'/(name+'.py'));mod=importlib.util.module_from_spec(spec);sys.modules[name]=mod;spec.loader.exec_module(mod);return mod
m=load('ai_effect_measurement')
F=json.loads((ROOT/'tests'/'fixtures'/'v2e-measurement-fixture.json').read_text())

class MeasurementTest(unittest.TestCase):
 def rows(self): return F['before_rows']+F['after_rows']
 def measure(self, **kwargs):
  values={'page_rows':self.rows(),'affiliate_events':[],'latest_final_date':F['latest_final_date']};values.update(kwargs);return m.build_measurement(F['execution'],**values)
 def test_windows_are_deterministic_and_los_angeles_based(self):
  windows=m.build_measurement_windows(F['execution']['applied_at']);self.assertEqual({'start':'2026-07-18','end':'2026-07-31'},windows['before_window']);self.assertEqual({'start':'2026-08-01','end':'2026-08-07'},windows['exclusion_window']);self.assertEqual({'start':'2026-08-08','end':'2026-08-21'},windows['after_window'])
 def test_finality_and_minimum_data_states(self):
  self.assertEqual('measurement_pending',self.measure(latest_final_date='2026-08-20')['measurement_classification'])
  self.assertEqual('insufficient_data',self.measure(page_rows=F['before_rows'][:6]+F['after_rows'])['measurement_classification'])
  low=[dict(row,impressions=1) for row in self.rows()];self.assertEqual('insufficient_data',self.measure(page_rows=low)['measurement_classification'])
 def test_weighted_metrics_delta_and_zero_missing_affiliate_are_explicit(self):
  result=self.measure();self.assertEqual('classification_pending_threshold',result['measurement_classification']);self.assertEqual(round(8/80,6),result['before_metrics']['ctr']);self.assertEqual(0,result['before_metrics']['affiliate_click_count']);self.assertEqual('increase',result['metric_deltas']['clicks']['direction']);self.assertEqual('unchanged',result['metric_deltas']['ctr']['direction'])
  zero=[dict(row,clicks=0,impressions=0,position=None) for row in self.rows()];z=self.measure(page_rows=zero);self.assertIsNone(z['before_metrics']['ctr']);self.assertIsNone(z['before_metrics']['average_position']);self.assertIsNone(self.measure(affiliate_events=None)['before_metrics']['affiliate_click_count'])
 def test_contamination_only_inside_windows_and_anomaly_interface(self):
  outside=[{'at':'2026-07-01T00:00:00Z','fields':['title'],'execution_id':'other'}];self.assertEqual('clean',self.measure(change_events=outside)['contamination_status'])
  inside=[{'at':'2026-08-12T00:00:00Z','fields':['title'],'execution_id':'other'}];self.assertEqual('contaminated',self.measure(change_events=inside)['measurement_classification'])
  anomaly=[{'code':'search_console_logging','start_date':'2026-08-10','end_date':'2026-08-11'}];self.assertIn('search_console_data_anomaly',self.measure(anomalies=anomaly)['contamination_reason_codes'])
 def test_measurement_id_determinism_and_execution_subject_rejection(self):
  self.assertEqual(self.measure()['measurement_id'],self.measure()['measurement_id'])
  bad=dict(F['execution'],execution_result_classification='outcome_unknown')
  with self.assertRaises(m.MeasurementSafetyError):m.build_measurement(bad,page_rows=self.rows(),affiliate_events=[],latest_final_date=F['latest_final_date'])
 def test_threshold_unapproved_blocks_accept_and_audit_is_safe(self):
  result=self.measure()
  with self.assertRaises(m.MeasurementSafetyError):m.build_measurement_review(result,decision='accept_result',reviewer_id='operator_primary')
  self.assertEqual('hold',m.build_measurement_review(result,decision='hold',reviewer_id='operator_primary')['decision'])
  with tempfile.TemporaryDirectory() as d:
   ledger=m.AppendOnlyMeasurementLedger(pathlib.Path(d));ledger.append({'measurement_id':result['measurement_id'],'execution_id':'execution_25_v1','article_id':25,'state':'planned','at':'2026-08-30T00:00:00Z'});self.assertEqual(0o700,ledger.path.parent.stat().st_mode&0o777);self.assertEqual(0o600,ledger.path.stat().st_mode&0o777)
   with self.assertRaises(m.MeasurementSafetyError):ledger.append({'token':'forbidden'})
if __name__=='__main__':unittest.main()
