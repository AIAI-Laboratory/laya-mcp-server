import copy
import json
import unittest
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
from decisions import DecisionRequest, BackendError, normalize, configure_decisions
from web_docs import configure_docs

REQUEST={"state":"Please refund the duplicate payment.","questions":[{"id":"route","type":"choice","instructions":"Route this message.","criteria":{"billing":"Payments and refunds","account":"Passwords and access"}}]}
RAW={"model":"test-model","routing":{"model":"multilingual"},"answers":{"route":{"type":"choice","choice":"billing","probabilities":{"billing":0.95,"account":0.05},"confidence":0.7}},"usage":{"input_tokens":25,"output_tokens":0,"truncated":False}}

class DecisionTests(unittest.TestCase):
    def test_choice_normalized_contract(self):
        result=normalize(RAW,DecisionRequest(**REQUEST),12.3456)
        self.assertEqual(result.schema_version,"1.0")
        self.assertEqual(result.decisions[0].value,"billing")
        self.assertFalse(result.decisions[0].needs_review)
        self.assertTrue(result.advisory)
        self.assertEqual(result.decisions[0].margin,0.9)

    def test_ambiguous_choice_requires_review(self):
        raw=copy.deepcopy(RAW);raw["answers"]["route"]["probabilities"]={"billing":0.55,"account":0.45}
        self.assertTrue(normalize(raw,DecisionRequest(**REQUEST),1).decisions[0].needs_review)

    def test_bad_upstream_answers_fail_closed(self):
        for mutate in [lambda r:r['answers']['route'].update(choice='invented'),
                       lambda r:r['answers']['route'].update(probabilities={'billing':float('nan'),'account':0.1}),
                       lambda r:r['answers']['route'].update(probabilities={'billing':0.3,'account':0.05}),
                       lambda r:r['usage'].update(truncated=True),
                       lambda r:r['usage'].update(truncated_questions=['route']),
                       lambda r:r['usage'].update(input_tokens=-1)]:
            with self.subTest(mutate=mutate):
                raw=copy.deepcopy(RAW);mutate(raw)
                with self.assertRaises(BackendError):normalize(raw,DecisionRequest(**REQUEST),1)

    def test_rejects_duplicates_and_wrong_criteria(self):
        for questions in [REQUEST['questions']*2,REQUEST['questions']*4,
                          [{'id':'x','type':'noul','instructions':'True?','criteria':['yes','no']}],
                          [{'id':'x','type':'score','instructions':'Rate','criteria':['same','same']}]]:
            with self.assertRaises(ValidationError):DecisionRequest(state='test',questions=questions)

    def test_noul_and_score_always_require_review(self):
        for kind,answer,criteria in [('noul',{'type':'noul','noul':.9},None),('score',{'type':'score','score':.9,'probabilities':{'0':.1,'1':.9}},['low','high'])]:
            q={'id':'x','type':kind,'instructions':'Evaluate'}
            if criteria:q['criteria']=criteria
            req=DecisionRequest(state='test',questions=[q])
            raw=copy.deepcopy(RAW);raw['answers']={'x':answer}
            self.assertTrue(normalize(raw,req,1).decisions[0].needs_review)

class ApiTests(unittest.TestCase):
    def setUp(self):
        self.app=FastAPI()
        @self.app.post('/v1/systemone')
        def raw():return {}
        configure_decisions(self.app)
        configure_docs(self.app)
        self.client=TestClient(self.app)

    def test_rest_same_normalized_contract(self):
        with patch('decisions.backend_request',new=AsyncMock(return_value=RAW)):
            response=self.client.post('/v1/decide',json=REQUEST)
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json()['decisions'][0]['value'],'billing')

    def test_invalid_input_never_calls_model(self):
        with patch('decisions.backend_request',new=AsyncMock()) as backend:
            self.assertEqual(self.client.post('/v1/decide',json={'state':'','questions':[]}).status_code,422)
            backend.assert_not_called()

    def test_service_failure_is_explicit(self):
        with patch('decisions.backend_request',new=AsyncMock(side_effect=BackendError('busy',503))):
            self.assertEqual(self.client.post('/v1/decide',json=REQUEST).status_code,503)

    @unittest.skipUnless(shutil.which("node"), "Node unavailable for JavaScript syntax check")
    def test_console_javascript_syntax(self):
        html=(Path(__file__).resolve().parents[1]/"static/console.html").read_text()
        source=re.search(r"<script>(.*?)</script>",html,re.S).group(1)
        with tempfile.NamedTemporaryFile(suffix=".js",mode="w") as script:
            script.write(source);script.flush()
            result=subprocess.run(["node","--check",script.name],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)

    def test_discovery_assets_and_typed_schema(self):
        for route in ['/','/guide.md','/llms.txt','/rules.md','/skill.md','/integrations.json','/assets/logo.png']:
            self.assertEqual(self.client.get(route).status_code,200,route)
        schema=self.client.get('/openapi.json').json()
        op=schema['paths']['/v1/decide']['post']
        self.assertIn('requestBody',op)
        self.assertIn('DecisionResponse',schema['components']['schemas'])
        settings=self.client.get('/integrations.json').json()
        self.assertTrue(settings['mcp_url'].endswith('/mcp'))

if __name__=='__main__':unittest.main()
