"""Versioned local routing endpoints used by the MCP tools."""
import json
import os
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse

from .router import RouteInput, build_route
from .store import DEFAULT_CONFIG, Store


def _merge(target, patch):
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _merge(target[key], value)
        else:
            target[key] = value
    return target


def _validate_config(config):
    if set(config) - set(DEFAULT_CONFIG):
        raise ValueError("unknown configuration section")
    routing = config.get("routing", {})
    if not isinstance(routing.get("enabled", True), bool):
        raise ValueError("routing.enabled must be a boolean")
    timeout = routing.get("classifier_timeout_ms", 1200)
    threshold = routing.get("confidence_threshold", 0.5)
    if isinstance(timeout, bool) or not isinstance(timeout, int) or not 100 <= timeout <= 5000:
        raise ValueError("classifier_timeout_ms must be between 100 and 5000")
    if isinstance(threshold, bool) or not isinstance(threshold, (int, float)) or not 0 <= threshold <= 1:
        raise ValueError("confidence_threshold must be between 0 and 1")
    execution = config.get("execution", {})
    parallel = execution.get("max_parallel_agents", 3)
    if isinstance(parallel, bool) or not isinstance(parallel, int) or not 1 <= parallel <= 16:
        raise ValueError("max_parallel_agents must be between 1 and 16")
    if execution.get("permission_escalation", "forbidden") != "forbidden":
        raise ValueError("permission escalation is forbidden")
    tiers = config.get("models", {}).get("tiers", {})
    if not isinstance(tiers, dict) or set(tiers) - {"light", "small", "mid", "top"}:
        raise ValueError("models.tiers contains an unknown tier")
    if any(value is not None and (not isinstance(value, str) or not value.strip()) for value in tiers.values()):
        raise ValueError("model tier IDs must be nonempty strings or null")
    recommendations = config.get("skills", {}).get("max_recommendations", 3)
    if isinstance(recommendations, bool) or not isinstance(recommendations, int) or not 0 <= recommendations <= 8:
        raise ValueError("skills.max_recommendations must be between 0 and 8")
    if config.get("telemetry", {}).get("store_prompt_content", False) is not False:
        raise ValueError("prompt content storage is disabled")


def configure_routing(app: FastAPI, database_path=None):
    store = Store(Path(database_path or os.environ.get("LAYA_ROUTING_DB", "/data/laya-routing.sqlite3")))
    app.state.routing_store = store

    @app.middleware("http")
    async def local_host_only(request, call_next):
        if request.url.hostname not in {"127.0.0.1", "localhost", "::1"}:
            return JSONResponse({"detail": "This service only accepts loopback Host headers."}, status_code=421)
        return await call_next(request)

    @app.get("/api/v1/health")
    def health():
        return {"status": "ok", "schema_version": "1.0"}

    def make_route(request, persist):
        if request.schema_version != "1.0":
            raise HTTPException(422, "unknown schema_version")
        if persist:
            previous = store.route_by_request(request.request_id)
            if previous:
                return previous
        try:
            route = build_route(request, store.config())
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        if persist:
            route_id = uuid.uuid4().hex
            route.update(route_id=route_id, request_id=request.request_id)
            events = [("route.requested", {"request_id": request.request_id})]
            if route["status"] == "fallback":
                events.append(("route.fallback", {"reason_codes": route["decision"]["reason_codes"]}))
            events.append(("route.completed", {"status": route["status"], "source": route["decision"]["source"]}))
            route, created = store.save_route(request.request_id, route_id, route["trace_id"], route, events)
            if not created:
                return route
        return route

    @app.post("/api/v1/routes")
    def route_task(request: RouteInput):
        return make_route(request, True)

    @app.post("/api/v1/routes/simulate")
    def simulate_route(request: RouteInput):
        return make_route(request, False)

    @app.get("/api/v1/routes/{route_id}")
    def get_route(route_id: str):
        route = store.route_by_request(route_id)
        if not route:
            raise HTTPException(404, "Route not found")
        return route

    @app.get("/api/v1/config")
    def get_config():
        return store.config()

    @app.post("/api/v1/config")
    @app.patch("/api/v1/config")
    def update_config(patch: dict[str, Any]):
        config = _merge(store.config(), patch)
        try:
            _validate_config(config)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        store.save_config(config)
        store.add_event("configuration", "config.updated", {"keys": sorted(patch)})
        return config

    @app.get("/api/v1/traces")
    def traces(limit: int = 100):
        if not 1 <= limit <= 500:
            raise HTTPException(422, "limit must be between 1 and 500")
        return {"items": store.traces(limit)}

    @app.get("/api/v1/traces/{trace_id}")
    def trace(trace_id: str):
        events = store.events(trace_id=trace_id)
        if not events:
            raise HTTPException(404, "Trace not found")
        return {"trace_id": trace_id, "events": events}
