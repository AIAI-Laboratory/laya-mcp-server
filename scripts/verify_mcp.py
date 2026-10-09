import asyncio, json, os
import urllib.request
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

async def main():
    url=os.environ.get("LAYA_MCP_URL", "http://127.0.0.1:8000/mcp")
    base=url.removesuffix("/mcp")
    checked=[]
    for path in ["/", "/docs", "/health", "/llms.txt", "/guide.md", "/skill.md", "/rules.md", "/integrations.json", "/openapi.json", "/assets/logo.png"]:
        with urllib.request.urlopen(base+path,timeout=10) as response:
            assert response.status==200, path
            body=response.read()
            if path=="/openapi.json": assert "/v1/decide" in json.loads(body)["paths"]
            if path=="/health":
                health=json.loads(body)
                assert health["device"]=="cpu" and "multilingual" in health["loaded"],health
        checked.append(path)
    request={"state":"Please refund my duplicate payment.","questions":[{"id":"route","type":"choice","instructions":"Classify this request.","criteria":{"billing":"Payments and refunds","account":"Login and passwords"}}],"caller":"setup-verifier","task":"rest-smoke"}
    with urllib.request.urlopen(urllib.request.Request(base+"/v1/decide",data=json.dumps(request).encode(),headers={"Content-Type":"application/json"}),timeout=45) as response:
        rest=json.load(response)
        assert rest["schema_version"]=="1.0" and rest["decisions"][0]["value"]=="billing",rest
    async with streamable_http_client(url) as streams:
        async with ClientSession(streams[0], streams[1]) as session:
            await session.initialize()
            listed=await session.list_tools()
            names=[t.name for t in listed.tools]
            assert {"laya_status", "laya_classify", "laya_decide", "laya_guide", "laya_route_task",
                    "laya_route_subtask", "laya_capability_search", "laya_get_route", "laya_report_execution",
                    "laya_get_routing_policy", "laya_update_routing_policy"} <= set(names), names
            guide=await session.call_tool("laya_guide", {})
            assert not guide.is_error, guide
            normalized=await session.call_tool("laya_decide", {"state":"Please refund my duplicate payment.",
                "questions":[{"id":"route","type":"choice","instructions":"Classify this request.","criteria":{"billing":"Payments and refunds","account":"Login and password"}}],
                "caller":"mcp-smoke-test","task":"normalized-contract"})
            assert not normalized.is_error, normalized
            contract=normalized.structured_content
            if contract is None:contract=json.loads(next(c.text for c in normalized.content if getattr(c,"type",None)=="text"))
            assert contract["schema_version"]=="1.0" and contract["decisions"][0]["value"]=="billing",contract
            routed=await session.call_tool("laya_route_task", {"task_summary":"Fix a bug and add tests",
                "request_id":"mcp-contract-smoke"})
            assert not routed.is_error, routed
            route=routed.structured_content
            if route is None:route=json.loads(next(c.text for c in routed.content if getattr(c,"type",None)=="text"))
            assert route["route"]["execution"]=="not_executed",route
            fetched=await session.call_tool("laya_get_route", {"trace_id":route["trace_id"]})
            assert not fetched.is_error, fetched
            report=await session.call_tool("laya_report_execution", {"trace_id":route["trace_id"],"status":"completed"})
            assert not report.is_error, report
            report_data=report.structured_content
            if report_data is None:report_data=json.loads(next(c.text for c in report.content if getattr(c,"type",None)=="text"))
            assert report_data["event"]=="execution.reported" and report_data["data"]["verified"] is False,report_data
            candidates=await session.call_tool("laya_capability_search", {"query":"browser", "candidates":[
                {"id":"browser_automation","description":"Automate browser workflows"},
                {"id":"filesystem","description":"Read local files"}]})
            assert not candidates.is_error,candidates
            candidate_data=candidates.structured_content
            if candidate_data is None:candidate_data=json.loads(next(c.text for c in candidates.content if getattr(c,"type",None)=="text"))
            assert candidate_data["items"][0]["id"]=="browser_automation",candidate_data
            policy=await session.call_tool("laya_get_routing_policy", {})
            assert not policy.is_error,policy
            updated=await session.call_tool("laya_update_routing_policy", {"patch":{"routing":{"enabled":True}}})
            assert not updated.is_error,updated
            status=await session.call_tool("laya_status", {})
            assert not status.is_error, status
            result=await session.call_tool("laya_classify", {"caller":"mcp-smoke-test", "task":"kiểm tra hoàn tiền", "text":"Tôi bị trừ tiền hai lần, cần hoàn tiền.",
                "labels":{"billing":"Payment, invoice, refund", "account":"Login and password problems"}})
            assert not result.is_error, result
            payload=result.structured_content
            if payload is None:
                payload=json.loads(next(c.text for c in result.content if getattr(c,"type",None)=="text"))
            assert payload["answers"]["category"]["choice"]=="billing", payload
            rejected=await session.call_tool("laya_classify", {"text":"test", "labels":{"only":"one label"}})
            assert rejected.is_error, "Invalid labels were accepted"
            print(json.dumps({"url":url,"http_routes":checked,"rest_inference":"billing","tools":names,"health_ok":True,"classification":payload,"invalid_input_rejected":True},ensure_ascii=False,indent=2))

asyncio.run(main())
