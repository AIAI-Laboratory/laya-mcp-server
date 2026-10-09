import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from routing import configure_routing
from routing.router import capability_search


class McpRoutingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        app = FastAPI()
        configure_routing(app, Path(self.tmp.name) / "routes.sqlite3")
        self.client = TestClient(app, base_url="http://127.0.0.1")

    def tearDown(self):
        self.client.close()
        self.tmp.cleanup()

    def test_route_uses_only_candidates_the_mcp_caller_supplies(self):
        payload = {"schema_version": "1.0", "request_id": "route-1",
                   "task": {"text": "Fix login bug and add tests"},
                   "environment": {"max_parallel_agents": 12},
                   "constraints": {
                       "available_models": ["model-from-client"],
                       "available_skills": ["debugging", "testing"],
                       "skill_metadata": [
                           {"id": "debugging", "description": "Trace and fix bugs"},
                           {"id": "testing", "description": "Add regression tests"}],
                       "available_mcp_capabilities": ["filesystem"],
                       "mcp_metadata": [{"id": "filesystem", "description": "Read and edit project files"}]}}
        response = self.client.post("/api/v1/routes", json=payload)
        self.assertEqual(response.status_code, 200)
        route = response.json()
        self.assertEqual(route["route"]["execution"], "not_executed")
        self.assertEqual(route["route"]["parallel_agents"], 3)
        self.assertEqual(route["route"]["model"]["applied"], False)
        self.assertEqual({item["id"] for item in route["route"]["skills"]}, {"debugging", "testing"})
        self.assertEqual(route["route"]["mcp_capabilities"], ["filesystem"])

    def test_unknown_explicit_model_fails_against_caller_inventory(self):
        payload = {"schema_version": "1.0", "request_id": "bad-model", "task": {"text": "Fix bug"},
                   "environment": {"explicit_model": "not-listed"}, "constraints": {"available_models": []}}
        self.assertEqual(self.client.post("/api/v1/routes", json=payload).status_code, 422)

    def test_classifier_failure_falls_back_without_selecting_a_model(self):
        self.client.post("/api/v1/config", json={"models": {"tiers": {"small": "client-model"}}})
        payload = {"schema_version": "1.0", "request_id": "fallback", "task": {"text": "Please handle this"},
                   "constraints": {"available_models": ["client-model"]}}
        with patch("routing.router.classify_unknown", return_value=None):
            route = self.client.post("/api/v1/routes/simulate", json=payload).json()
        self.assertEqual(route["status"], "fallback")
        self.assertEqual(route["route"]["model"]["strategy"], "inherit")
        self.assertIsNone(route["route"]["model"]["model_id"])

    def test_request_id_is_idempotent_under_concurrent_retries(self):
        payload = {"schema_version": "1.0", "request_id": "retry", "task": {"text": "Fix a bug"}}
        with ThreadPoolExecutor(max_workers=8) as pool:
            responses = list(pool.map(lambda _: self.client.post("/api/v1/routes", json=payload), range(8)))
        self.assertEqual([response.status_code for response in responses], [200] * 8)
        trace_ids = {response.json()["trace_id"] for response in responses}
        self.assertEqual(len(trace_ids), 1)
        trace = self.client.get(f"/api/v1/traces/{trace_ids.pop()}").json()
        self.assertEqual([event["event"] for event in trace["events"]], ["route.requested", "route.completed"])

    def test_mcp_self_report_is_unverified_and_requires_a_known_route(self):
        payload = {"schema_version": "1.0", "request_id": "report-route", "task": {"text": "Fix bug"}}
        route = self.client.post("/api/v1/routes", json=payload).json()
        report = self.client.app.state.routing_store.report_execution(route["trace_id"], "completed", {"prompt": "omit"})
        self.assertEqual(report["event"], "execution.reported")
        self.assertFalse(report["data"]["verified"])
        self.assertEqual(report["data"]["details"]["prompt"], "[OMITTED]")
        with self.assertRaises(ValueError):
            self.client.app.state.routing_store.report_execution("unknown", "completed")

    def test_capability_search_only_searches_supplied_metadata(self):
        results = capability_search("browser", [{"id": "browser", "description": "Automate browser tasks"},
                                                 {"id": "filesystem", "description": "Read local files"}], 8)
        self.assertEqual([item["id"] for item in results["items"]], ["browser"])


if __name__ == "__main__":
    unittest.main()
