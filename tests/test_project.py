import ast
import json
import logging
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from observability import AccessFilter, CompactFormatter, ConsoleFilter, body_value, LIMIT


class LoggingTests(unittest.TestCase):
    def test_compact_route_tool_log_never_prints_task_summary(self):
        row={"timestamp":"2026-10-09T10:00:00.000+00:00","event":"request.end","transport":"mcp",
             "tool":"laya_route_task","path":"/mcp","status":200,"duration_ms":1,"success":True,
             "caller":"mcp-client","task":"password=do-not-log","trace_id":"0123456789abcdef"}
        line=CompactFormatter().format(logging.LogRecord("test",20,"",1,json.dumps(row),(),None))
        self.assertNotIn("password",line)
        self.assertNotIn("do-not-log",line)

    def test_redacts_structured_credentials_and_omits_large_payloads(self):
        raw=json.dumps({"api_key":"secret","nested":{"password":"secret"},"state":"hello"}).encode()
        value=body_value(raw,len(raw))
        self.assertEqual(value["api_key"],"[REDACTED]")
        self.assertEqual(value["nested"]["password"],"[REDACTED]")
        self.assertEqual(value["state"],"hello")
        self.assertIn("omitted",body_value(b"x"*LIMIT,LIMIT+1))

    def test_compact_log_and_health_filter(self):
        row={"timestamp":"2026-10-04T09:14:28.213+00:00","event":"request.end","transport":"rest", "path":"/v1/systemone","status":200,"duration_ms":137.3,"success":True,"caller":"test", "task":"triage", "trace_id":"0123456789abcdef","output":{"answers":{"category":{"choice":"billing"}}}}
        record=logging.LogRecord("test",20,"",1,json.dumps(row),(),None)
        self.assertTrue(ConsoleFilter().filter(record))
        line=CompactFormatter().format(record)
        self.assertIn('result="billing"',line);self.assertNotIn("\n",line)
        row["event"]="request.start"
        self.assertFalse(ConsoleFilter().filter(logging.LogRecord("test",20,"",1,json.dumps(row),(),None)))
        for status,wanted in [(200,False),(503,True)]:
            record=logging.LogRecord("access",20,"",1,"%s %s %s %s %s",("peer","GET","/health","1.1",status),None)
            self.assertEqual(AccessFilter().filter(record),wanted)


class DocsTests(unittest.TestCase):
    def test_swagger_is_self_hosted_and_has_examples(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from web_docs import configure_docs
        app=FastAPI()
        @app.post("/v1/systemone")
        def endpoint(): return {}
        configure_docs(app)
        client=TestClient(app)
        html=client.get("/docs").text
        self.assertNotIn("cdn.jsdelivr.net",html)
        for name in ["swagger-ui-bundle.js","swagger-ui.css","favicon.svg"]:
            self.assertEqual(client.get("/static/swagger/"+name).status_code,200)
        schema=client.get("/openapi.json").json()
        self.assertEqual(set(schema["paths"]["/v1/systemone"]["post"]["requestBody"]["content"]["application/json"]["examples"]),{"support","sentiment"})

    def test_version_and_python_syntax(self):
        version=(ROOT/"VERSION").read_text().strip()
        self.assertEqual(version,"0.1.0")
        self.assertIn('org.opencontainers.image.version="'+version+'"',(ROOT/"Dockerfile").read_text())
        self.assertIn('${LAYA_VERSION:-'+version+'}',(ROOT/"compose.yaml").read_text())
        for path in list(ROOT.glob("*.py"))+list((ROOT/"scripts").glob("*.py")):
            ast.parse(path.read_text())


if __name__=="__main__": unittest.main()
