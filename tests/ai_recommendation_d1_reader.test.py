import importlib.util, pathlib, sqlite3, sys, unittest
ROOT=pathlib.Path(__file__).parents[1]
def load(name):
 spec=importlib.util.spec_from_file_location(name,ROOT/'scripts'/f'{name}.py');mod=importlib.util.module_from_spec(spec);sys.modules[name]=mod;spec.loader.exec_module(mod);return mod
load('search_console_collector');load('search_console_d1_reader');reader=load('ai_recommendation_d1_reader')
class Transport:
 def __init__(self,reply):self.reply=reply;self.calls=[]
 def request(self,*args):self.calls.append(args);return self.reply
def reply(changed=False,written=0):return {'success':True,'result':[{'meta':{'changed_db':changed,'rows_written':written},'results':[]} for _ in range(3)]}
class ReaderTest(unittest.TestCase):
 def test_exactly_three_fixed_selects(self):
  transport=Transport(reply());reader.AiRecommendationD1Reader(transport).fetch_source('https://example.test/','web','2026-08-08','2026-08-09');batch=transport.calls[0][2]['batch'];self.assertEqual(3,len(batch));self.assertTrue(all(item['sql'].lstrip().upper().startswith('SELECT ') and ';' not in item['sql'] for item in batch));self.assertNotIn('content',batch[2]['sql'].lower());self.assertIn("url_kind='article'",batch[0]['sql']);self.assertIn('article_id IS NOT NULL',batch[0]['sql'])
 def test_article_only_sql_covers_mixed_top_null_and_empty_cases(self):
  statement=reader.build_recommendation_source_selects('https://example.test/','web','2026-08-08','2026-08-09')[0]
  # These source shapes are intentionally filtered by SQL, not silently by
  # Python: an article passes; top and NULL-ID rows do not; empty is safe.
  db=sqlite3.connect(':memory:');db.execute('CREATE TABLE search_console_page_daily_metrics (metric_date TEXT, property_uri TEXT, search_type TEXT, page_url TEXT, url_kind TEXT, article_id INTEGER, clicks INTEGER, impressions INTEGER, ctr REAL, position REAL, observed_at TEXT)')
  db.executemany('INSERT INTO search_console_page_daily_metrics VALUES (?,?,?,?,?,?,?,?,?,?,?)',[
   ('2026-08-08','https://example.test/','web','https://example.test/article/17','article',17,1,10,.1,3,'x'),
   ('2026-08-08','https://example.test/','web','https://example.test/','top',None,1,10,.1,3,'x'),
   ('2026-08-08','https://example.test/','web','https://example.test/article/bad','article',None,1,10,.1,3,'x'),
  ])
  rows=db.execute(statement.sql,statement.params).fetchall();self.assertEqual(1,len(rows));self.assertEqual(17,rows[0][5]);db.execute('DELETE FROM search_console_page_daily_metrics');self.assertEqual([],db.execute(statement.sql,statement.params).fetchall())
 def test_write_metadata_stops(self):
  for item in (reply(changed=True),reply(written=1)):
   with self.assertRaises(Exception):reader.AiRecommendationD1Reader(Transport(item)).fetch_source('https://example.test/','web','2026-08-08','2026-08-09')
if __name__=='__main__':unittest.main()
