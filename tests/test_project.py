import ast
import json
import logging
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
import register_global as installer
from observability import AccessFilter, CompactFormatter, ConsoleFilter, body_value, LIMIT


class InstallerTests(unittest.TestCase):
    def test_merge_is_idempotent_and_preserves_other_settings(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            paths={"codex":root/"codex.toml", "claude":root/"claude.json", "opencode":root/"opencode.jsonc"}
            paths["codex"].write_text('# keep comment\nmodel="existing"\n[mcp_servers.other]\nurl="http://other"\n')
            paths["claude"].write_text('{"keep":true,"mcpServers":{"other":{"url":"http://other"}}}')
            paths["opencode"].write_text('{// comment\n"theme":"existing","mcp":{},}')
            for path,before,after in installer.plan_configs(paths,list(paths),"http://127.0.0.1:30765/mcp"):
                installer.atomic_write(path,after)
            self.assertEqual(installer.plan_configs(paths,list(paths),"http://127.0.0.1:30765/mcp"),[])
            self.assertIn("# keep comment",paths["codex"].read_text())
            self.assertEqual(installer.tomlkit.parse(paths["codex"].read_text())["mcp_servers"]["other"]["url"],"http://other")
            self.assertTrue(json.loads(paths["claude"].read_text())["keep"])
            self.assertEqual(json.loads(paths["opencode"].read_text())["theme"],"existing")

    def test_auto_with_no_agents_keeps_service_setup_usable(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(installer.os.environ, {}, clear=True), patch.object(installer.Path, "home", return_value=Path(tmp)), patch.object(installer.shutil, "which", return_value=None), patch.object(installer, "probe", return_value={"inference":"billing"}):
                report=installer.install("auto", dry_run=True)
            self.assertEqual(report["targets"], [])
            self.assertEqual(report["changed"], [])

    def test_invalid_configuration_is_not_written(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"broken.json";path.write_text('{broken')
            with self.assertRaises(ValueError): installer.plan_configs({"claude":path},["claude"],"http://localhost/mcp")
            self.assertEqual(path.read_text(),'{broken')


class LoggingTests(unittest.TestCase):
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
