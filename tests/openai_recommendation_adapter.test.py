import importlib.util, pathlib, sys, unittest
ROOT=pathlib.Path(__file__).parents[1]
def load(name):
 spec=importlib.util.spec_from_file_location(name,ROOT/'scripts'/f'{name}.py');mod=importlib.util.module_from_spec(spec);sys.modules[name]=mod;spec.loader.exec_module(mod);return mod
load('search_console_collector');load('ai_recommendation_schema');load('ai_recommendation_adapter');adapter=load('openai_recommendation_adapter')
class OpenAiAdapterTest(unittest.TestCase):
 def test_payload_uses_responses_structured_outputs_and_no_tools(self):
  p=adapter.build_responses_payload({'x':1},'gpt-5.6-terra',500);self.assertFalse(p['store']);self.assertEqual('json_schema',p['text']['format']['type']);self.assertTrue(p['text']['format']['strict']);self.assertNotIn('tools',p)
 def test_rejects_unapproved_model_and_missing_key(self):
  with self.assertRaises(ValueError):adapter.build_responses_payload({},'gpt-4o',500)
  with self.assertRaises(adapter.OpenAiRecommendationError):adapter.OpenAiResponsesTransport('gpt-5.6-luna',api_key='')
 def test_output_text_requires_explicit_structured_value(self):
  with self.assertRaises(adapter.OpenAiRecommendationError):adapter._output_text({})
if __name__=='__main__':unittest.main()
