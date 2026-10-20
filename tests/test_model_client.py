import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import URLError

from edu_context.model_client import JSONModelClient, ModelCallError
from edu_context.text import EvidenceTextCompressor


class Reply:
    def __init__(self, finish='stop', content='{"ok":true}'):
        self.body = json.dumps({'model':'test','choices':[{'finish_reason':finish,
                  'message':{'content':content}}],'usage':{'total_tokens':8}}).encode()
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def read(self): return self.body


class ModelClientTests(unittest.TestCase):
    def test_cache_reuse_and_call_budget(self):
        with tempfile.TemporaryDirectory() as directory, patch('edu_context.model_client.build_opener') as opener:
            opener.return_value.open.return_value = Reply()
            client = JSONModelClient(api_key='private-key',base_url='https://example.com/v1',
                                     model='test',cache_dir=directory,max_calls=1)
            kwargs = dict(system='system',request={'task':'one'})
            self.assertEqual(client(**kwargs), {'ok':True})
            self.assertEqual(client(**kwargs), {'ok':True})
            self.assertEqual(client.network_calls,1)
            self.assertTrue(client.calls[-1]['cached'])
            self.assertNotIn('private-key',json.dumps(client.calls))
            self.assertNotIn('private-key',next(Path(directory).glob('*.json')).read_text())
            with self.assertRaises(ModelCallError):
                client(system='system',request={'task':'different'})

    def test_incomplete_and_nonobject_outputs_rejected(self):
        for reply in (Reply('length'), Reply(content='[]'), Reply(content='invalid'),
                      Reply(content='{"x":1,"x":2}'), Reply(content='{"x":NaN}')):
            with patch('edu_context.model_client.build_opener') as opener:
                opener.return_value.open.return_value = reply
                client = JSONModelClient(api_key='x',base_url='https://example.com',model='test')
                with self.assertRaises(ModelCallError):
                    client(system='s',request={})

    def test_network_error_does_not_expose_provider_detail(self):
        with patch('edu_context.model_client.build_opener') as opener:
            opener.return_value.open.side_effect = URLError('private-key diagnostic')
            client = JSONModelClient(api_key='x',base_url='https://example.com',model='test')
            with self.assertRaises(ModelCallError) as caught:
                client(system='s',request={})
            self.assertNotIn('private-key',str(caught.exception))

    def test_text_retry_then_multibatch_exact_delivery(self):
        calls = []
        def model(**kw):
            calls.append(kw)
            if len(calls)==1:
                raise ModelCallError('incomplete output')
            docs = kw['request']['documents']
            return {'reviewed_indices':[d['index'] for d in docs],
                    'findings':[{'finding':'明确操作流程','evidence':[
                        {'index':docs[0]['index'],'quote':docs[0]['text'][:20]}]}]}
        compressor = EvidenceTextCompressor(model,batch_chars=1000)
        documents = [{'index':i,'text':'建议补充具体实例并清晰解释关键操作步骤。'*30} for i in range(3)]
        result = compressor(task='评语',documents=documents,token_budget=2000)
        self.assertEqual(result['document_count'],3)
        self.assertEqual(len(result['batches']),3)
        self.assertEqual([b['reviewed_indices'] for b in result['batches']],[[0],[1],[2]])
        self.assertIn('validation_feedback',calls[1]['request'])


if __name__ == '__main__':
    unittest.main()
