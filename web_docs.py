"""Self-hosted Swagger and editable examples for the local CPU profile."""
import json
import os
from pathlib import Path
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles


def configure_docs(app):
    root = Path(__file__).parent
    # Replace CDN-backed framework defaults.
    app.router.routes[:] = [r for r in app.router.routes if getattr(r, "path", None) not in {"/docs", "/docs/oauth2-redirect", "/redoc"}]
    app.mount("/static", StaticFiles(directory=root / "static"), name="static")
    app.mount("/assets", StaticFiles(directory=root / "assets"), name="assets")
    public_url = os.environ.get("LAYA_PUBLIC_URL", "http://127.0.0.1:30765").rstrip("/")


    @app.get("/", include_in_schema=False)
    def home():
        return FileResponse(root / "static/console.html", media_type="text/html")

    @app.get("/guide.md", response_class=PlainTextResponse, include_in_schema=False)
    def guide():
        return (root / "docs/AGENT_GUIDE.md").read_text()

    @app.get("/skill.md", response_class=PlainTextResponse, include_in_schema=False)
    def skill():
        return (root / "skills/laya-mcp-server/SKILL.md").read_text()

    @app.get("/rules.md", response_class=PlainTextResponse, include_in_schema=False)
    def rules():
        return ("# Local Laya rule\nUse the laya MCP only for short bounded semantic decisions. "
                "Read laya_guide once. Prefer laya_decide with explicit choices and an unknown/review option. "
                "Pass the real caller and task. Treat outputs as advisory; score and noul need review. "
                "Use tests/code for exact checks. Avoid repeated or unnecessary calls. "
                "If unavailable, report it; no paid fallback or retry loop.\n")

    @app.get("/integrations.json", tags=["Discovery"])
    def integrations():
        url=public_url+"/mcp"
        return {"scope":"user-global on this machine", "mcp_url":url,
            "claude":{"mcpServers":{"laya":{"type":"http","url":url,"headers":{"X-Laya-Caller":"claude-code"}}}},
            "codex_toml":'[mcp_servers.laya]\nurl = '+json.dumps(url)+'\nstartup_timeout_sec = 30\ntool_timeout_sec = 60\n[mcp_servers.laya.http_headers]\nX-Laya-Caller = "codex"\n',
            "opencode":{"mcp":{"laya":{"type":"remote","url":url,"enabled":True,"oauth":False,"headers":{"X-Laya-Caller":"opencode"}}}},
            "install":"./setup.sh", "register_only":"./setup.sh --register-only",
            "note":"Merge the laya entry; do not overwrite unrelated configuration. Never expose unauthenticated service publicly."}

    @app.get("/llms.txt", response_class=PlainTextResponse, include_in_schema=False)
    def llms():
        return ("# Laya MCP Server\nLocal CPU decisions; not a generative LLM.\n"
                f"- Guide: {public_url}/guide.md\n- Agent rule: {public_url}/rules.md\n"
                f"- Skill: {public_url}/skill.md\n- Client settings: {public_url}/integrations.json\n"
                f"- Schema: {public_url}/openapi.json\n- MCP: {public_url}/mcp\n"
                "Tools: laya_guide, laya_status, laya_classify (legacy raw response), laya_decide (normalized).\n"
                "POST /v1/decide: state, questions [{id,type,instructions,criteria}], caller, task.\n"
                "type=choice|noul|score. Max 3 questions; prefer one. Score is experimental.\n")

    @app.get("/docs", include_in_schema=False)
    def docs():
        return get_swagger_ui_html(
            openapi_url="/openapi.json", title="Laya MCP Server — Test API",
            swagger_js_url="/static/swagger/swagger-ui-bundle.js",
            swagger_css_url="/static/swagger/swagger-ui.css",
            swagger_favicon_url="/assets/logo.png",
            swagger_ui_parameters={"tryItOutEnabled": True, "displayRequestDuration": True,
                                   "defaultModelsExpandDepth": -1, "validatorUrl": None})

    original_openapi = app.openapi
    def openapi():
        schema = original_openapi()
        schema["info"].update(title="Laya MCP Server · CPU", version=(root / "VERSION").read_text().strip(), description=(
            "Run locally with no cloud API. Use /v1/decide for normalized decisions or /v1/systemone for the raw contract. "
            "Choose an example, edit the state and select Execute. Keep model=multilingual for raw requests. "
            "Check /health for the actual model/device. High probability is not proof of correctness."))
        schema["paths"].pop("/v1/systemone/batch", None)
        op = schema["paths"]["/v1/systemone"]["post"]
        sample = json.loads((root / "examples/request.json").read_text())
        sentiment = {"model": "multilingual", "state": "Sản phẩm rất tốt, giao hàng nhanh, tôi rất hài lòng.", "max_len": 512,
                     "questions": {"category": {"type": "choice", "instructions": "Classify the sentiment of this review.",
                        "criteria": {"positive": "Happy or satisfied", "negative": "Unhappy or dissatisfied", "neutral": "Neutral or unclear"}}}}
        op.update(summary="Raw upstream decision API", description="Edit a sample state. This profile uses one CPU model; the maximum budget is 1024 tokens.")
        op["parameters"] = [x for x in op.get("parameters", []) if x.get("name") not in {"X-Laya-Caller", "X-Laya-Task", "X-Trace-Id"}] + [
            {"name": name, "in": "header", "required": False, "schema": {"type": "string", "default": default}}
            for name, default in [("X-Laya-Caller", "swagger"), ("X-Laya-Task", "manual-test")]]
        op["requestBody"] = {"required": True, "content": {"application/json": {
            "schema": {"type": "object", "required": ["model", "state", "questions"], "properties": {
                "model": {"type": "string", "enum": ["multilingual"], "default": "multilingual"},
                "state": {"description": "Text or structured evidence to evaluate", "anyOf": [{"type": "string"}, {"type": "object"}, {"type": "array", "items": {}}]},
                "max_len": {"type": "integer", "minimum": 1, "maximum": 1024, "default": 512},
                "questions": {"type": "object", "additionalProperties": True}}},
            "examples": {"support": {"summary": "Support request classification", "value": sample},
                         "sentiment": {"summary": "Review sentiment", "value": sentiment}}}}}
        return schema
    app.openapi = openapi
