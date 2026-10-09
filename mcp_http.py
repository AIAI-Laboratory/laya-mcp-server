"""Stateless MCP, one shared resident inference model, no cloud fallback."""
from contextlib import asynccontextmanager
from pathlib import Path
from decisions import DecisionRequest, Question, DecisionResponse, evaluate, backend_request, BackendError
from routing.router import capability_search
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError


def attach_mcp(app, backend="http://127.0.0.1:8000"):
    mcp = MCPServer("laya-mcp-server", version=(Path(__file__).parent / "VERSION").read_text().strip(), instructions=(
        "Local CPU decision service. Read laya_guide for contracts and use short bounded tasks. "
        "Results are advisory, not proof; do not replace tests or calculations."))

    async def request(path, payload=None, caller="", task=""):
        try:
            return await backend_request(backend,path,payload,caller,task)
        except BackendError as exc:
            raise ToolError(str(exc)) from exc

    @mcp.tool()
    async def laya_status(caller: str = "", task: str = "") -> dict:
        """Check the shared model's health, actual device and loaded revision."""
        return await request("/health", caller=caller, task=task)

    @mcp.tool()
    async def laya_classify(text: str, labels: dict[str, str], instructions: str = "Classify the input using these labels.", caller: str = "", task: str = "") -> dict:
        """Classify short text. labels maps 2-10 label IDs to precise descriptions. Returns probabilities and model metadata; confidence is not proof of correctness. Supply caller (agent/app name) and task (task ID or purpose) for debug logs."""
        if not text.strip() or len(text)>4000:
            raise ToolError("text must contain 1-4000 characters; send a short relevant excerpt.")
        if not 2 <= len(labels) <= 10 or any(not k.strip() or not v.strip() or len(k)>64 or len(v)>300 for k,v in labels.items()):
            raise ToolError("Provide 2-10 nonempty labels, IDs <=64 and descriptions <=300 characters.")
        if not instructions.strip() or len(instructions)>1000:
            raise ToolError("instructions must contain 1-1000 characters.")
        result = await request("/v1/systemone", {"model": "multilingual", "state": text, "max_len": 512,
            "questions": {"category": {"type": "choice", "instructions": instructions, "criteria": labels}}}, caller=caller, task=task)
        if result.get("usage", {}).get("truncated"):
            raise ToolError("Input was truncated by the model. Shorten the text or labels and retry.")
        return result

    @mcp.tool()
    async def laya_decide(state: str, questions: list[Question], caller: str = "", task: str = "") -> DecisionResponse:
        """Make 1-3 bounded decisions over short text. choice: 2-10 labeled criteria; noul: yes/no probability, no criteria; score: 2-5 ordered descriptions (experimental). Returns schema_version, decisions, needs_review, usage and timing. Read laya_guide first; never use scores to authorize actions."""
        try:
            return await evaluate(DecisionRequest(state=state,questions=questions,caller=caller,task=task),backend)
        except (BackendError,ValueError) as exc:
            raise ToolError(str(exc)) from exc

    @mcp.tool()
    def laya_guide() -> str:
        """Read local usage rules, tool selection, output contract, latency guidance and limitations without inference."""
        return (Path(__file__).parent / "docs/AGENT_GUIDE.md").read_text()

    @mcp.resource("laya://guide")
    def agent_guide() -> str:
        return laya_guide()

    def route_payload(task: str, request_id: str, kind: str, workspace_id: str,
                      session_id: str, current_model: str, explicit_model: str,
                      available_models: list[str], available_skills: list[str],
                      skill_metadata: list[dict], available_mcp_capabilities: list[str],
                      mcp_metadata: list[dict]) -> dict:
        return {"schema_version": "1.0", "request_id": request_id or __import__("uuid").uuid4().hex,
                "task": {"text": task, "source": "mcp", "kind": kind},
                "environment": {"workspace_id": workspace_id or None, "session_id": session_id or None,
                                "current_model": current_model or None, "explicit_model": explicit_model or None},
                "constraints": {"available_models": available_models, "available_skills": available_skills,
                                "skill_metadata": skill_metadata,
                                "available_mcp_capabilities": available_mcp_capabilities,
                                "mcp_metadata": mcp_metadata}}

    @mcp.tool()
    async def laya_route_task(task_summary: str, request_id: str = "", kind: str = "user_task",
                              workspace_id: str = "", session_id: str = "", current_model: str = "",
                              explicit_model: str = "", available_models: list[str] | None = None,
                              available_skills: list[str] | None = None,
                              skill_metadata: list[dict] | None = None,
                              available_mcp_capabilities: list[str] | None = None,
                              mcp_metadata: list[dict] | None = None) -> dict:
        """Return a deterministic advisory route for a coding task; does not execute it."""
        payload = route_payload(task_summary, request_id, kind, workspace_id, session_id, current_model,
                                explicit_model, available_models or [], available_skills or [],
                                skill_metadata or [], available_mcp_capabilities or [], mcp_metadata or [])
        return await request("/api/v1/routes", payload)

    @mcp.tool()
    async def laya_route_subtask(task_summary: str, parent_trace_id: str, request_id: str = "",
                                 workspace_id: str = "", available_skills: list[str] | None = None,
                                 skill_metadata: list[dict] | None = None) -> dict:
        """Route a bounded subtask and retain its parent trace reference."""
        payload = route_payload(task_summary, request_id, "subtask", workspace_id, parent_trace_id, "", "", [],
                                available_skills or [], skill_metadata or [], [], [])
        return await request("/api/v1/routes", payload)

    @mcp.tool()
    async def laya_capability_search(query: str, candidates: list[dict], limit: int = 8) -> dict:
        """Search only the skill/MCP candidates supplied in this MCP request."""
        try:
            return capability_search(query, candidates, limit)
        except ValueError as exc:
            raise ToolError(str(exc)) from exc

    @mcp.tool()
    async def laya_get_route(trace_id: str) -> dict:
        """Retrieve a previously recorded route using its route ID or request ID."""
        from urllib.parse import quote
        return await request(f"/api/v1/routes/{quote(trace_id, safe='')}")

    @mcp.tool()
    async def laya_report_execution(trace_id: str, status: str, details: dict | None = None) -> dict:
        """Record this MCP caller's unverified self-report against a known route trace."""
        if status not in {"started", "completed", "failed"}:
            raise ToolError("status must be started, completed, or failed")
        store = app.state.routing_store
        try:
            return store.report_execution(trace_id, status, details)
        except ValueError as exc:
            raise ToolError(str(exc)) from exc

    @mcp.tool()
    async def laya_get_routing_policy() -> dict:
        """Read the local advisory-routing policy."""
        return await request("/api/v1/config")

    @mcp.tool()
    async def laya_update_routing_policy(patch: dict) -> dict:
        """Update bounded route preferences only; permission escalation and prompt storage remain forbidden."""
        return await request("/api/v1/config", patch)

    transport = mcp.streamable_http_app(streamable_http_path="/mcp", stateless_http=True, json_response=True,
                                        max_request_body_size=65536)
    previous_lifespan = app.router.lifespan_context
    @asynccontextmanager
    async def lifespan(application):
        async with previous_lifespan(application):
            async with mcp.session_manager.run():
                yield
    app.router.lifespan_context = lifespan
    # Last route: preserve existing REST/Swagger routes, /mcp goes to SDK transport.
    app.mount("/", transport)
    return mcp
