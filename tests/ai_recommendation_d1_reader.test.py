import importlib.util, pathlib, sys, unittest
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
  transport=Transport(reply());reader.AiRecommendationD1Reader(transport).fetch_source('https://example.test/','web','2026-08-08','2026-08-09');batch=transport.calls[0][2]['batch'];self.assertEqual(3,len(batch));self.assertTrue(all(item['sql'].lstrip().upper().startswith('SELECT ') and ';' not in item['sql'] for item in batch));self.assertNotIn('content',batch[2]['sql'].lower())
 def test_write_metadata_stops(self):
  for item in (reply(changed=True),reply(written=1)):
   with self.assertRaises(Exception):reader.AiRecommendationD1Reader(Transport(item)).fetch_source('https://example.test/','web','2026-08-08','2026-08-09')
if __name__=='__main__':unittest.main()
