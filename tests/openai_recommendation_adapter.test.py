import importlib.util, json, pathlib, sys, unittest
ROOT=pathlib.Path(__file__).parents[1]
def load(name):
 spec=importlib.util.spec_from_file_location(name,ROOT/'scripts'/f'{name}.py');mod=importlib.util.module_from_spec(spec);sys.modules[name]=mod;spec.loader.exec_module(mod);return mod
load('search_console_collector');load('ai_recommendation_schema');load('ai_recommendation_adapter');adapter=load('openai_recommendation_adapter')
class OpenAiAdapterTest(unittest.TestCase):
 def test_payload_uses_responses_structured_outputs_and_no_tools(self):
  p=adapter.build_responses_payload({'x':1},'gpt-5.6-terra',500);self.assertFalse(p['store']);self.assertEqual('json_schema',p['text']['format']['type']);self.assertTrue(p['text']['format']['strict']);self.assertNotIn('tools',p)
  self.assertEqual(['string','number','null'],[item['type'] for item in p['text']['format']['schema']['properties']['evidence']['items']['properties']['value']['anyOf']])
  self.assertIn('observation.impressions',p['text']['format']['schema']['properties']['evidence']['items']['properties']['field']['enum']);self.assertIn('article.article_id',p['text']['format']['schema']['properties']['evidence']['items']['properties']['field']['enum'])
 def test_rejects_unapproved_model_and_missing_key(self):
  with self.assertRaises(ValueError):adapter.build_responses_payload({},'gpt-4o',500)
  with self.assertRaises(adapter.OpenAiRecommendationError):adapter.OpenAiResponsesTransport('gpt-5.6-luna',api_key='')
  with self.assertRaises(adapter.OpenAiRecommendationError):adapter.OpenAiResponsesTransport('gpt-5.6-luna',api_key='x',client_request_id='非ASCII')
 def test_output_text_requires_explicit_structured_value(self):
  with self.assertRaises(adapter.OpenAiRecommendationError):adapter._output_text({})
 def test_extracts_completed_message_output_text(self):
  response={'status':'completed','output':[{'type':'reasoning'},{'type':'message','role':'assistant','content':[{'type':'output_text','text':'{"ok":true}'}]}]}
  self.assertEqual('{"ok":true}',adapter._output_text(response));self.assertEqual(['reasoning','message'],adapter.response_structure_diagnostic(response)['output_item_types'])
 def test_refusal_incomplete_unknown_and_bad_json_fail_closed(self):
  for response in ({'status':'completed','output':[{'type':'message','role':'assistant','content':[{'type':'refusal','refusal':'no'}]}]}, {'status':'incomplete','incomplete_details':{'reason':'max_output_tokens'},'output':[]}, {'status':'completed','output':[{'type':'message','role':'assistant','content':[{'type':'output_image'}]}]}):
   with self.assertRaises(adapter.OpenAiRecommendationResponseError):adapter._output_text(response)
  with self.assertRaises(json.JSONDecodeError):json.loads(adapter._output_text({'status':'completed','output':[{'type':'message','role':'assistant','content':[{'type':'output_text','text':'not-json'}]}]}))
 def test_http_diagnostic_redacts_token_like_text(self):
  self.assertEqual('Bearer [REDACTED]',adapter._redact_error_message('Bearer sk-should-not-appear'))
 def test_transport_diagnostics_are_safe_categories(self):
  self.assertEqual('connection_reset',adapter._transport_error_code(ConnectionResetError()))
  self.assertEqual('response_read_failed',adapter._transport_error_code(json.JSONDecodeError('safe','{',0)))
  self.assertEqual('transport_exception',adapter._transport_error_code(adapter.URLError('safe')))
if __name__=='__main__':unittest.main()
