"""Deterministic MCP route recommendations over caller-supplied candidates."""
import json
import re
import urllib.error
import urllib.request
import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class TaskInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=4000)
    source: str = Field(default="mcp", max_length=80)
    kind: str = Field(default="user_task", max_length=40)


class EnvironmentInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workspace_id: str | None = Field(default=None, max_length=128)
    session_id: str | None = Field(default=None, max_length=128)
    current_model: str | None = Field(default=None, max_length=128)
    explicit_model: str | None = Field(default=None, max_length=128)
    max_parallel_agents: int = Field(default=1, ge=1, le=100)


class ConstraintsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    available_models: list[str] = Field(default_factory=list, max_length=100)
    available_skills: list[str] = Field(default_factory=list, max_length=1000)
    skill_metadata: list[dict[str, Any]] = Field(default_factory=list, max_length=1000)
    available_mcp_capabilities: list[str] = Field(default_factory=list, max_length=500)
    mcp_metadata: list[dict[str, Any]] = Field(default_factory=list, max_length=500)


class RouteInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: str = "1.0"
    request_id: str = Field(min_length=1, max_length=128)
    task: TaskInput
    environment: EnvironmentInput = Field(default_factory=EnvironmentInput)
    constraints: ConstraintsInput = Field(default_factory=ConstraintsInput)


def classify_unknown(text, timeout_ms=1200):
    safe_text = re.sub(r"(?i)(api[_-]?key|password|token|secret)\s*[:=]\s*\S+", r"\1=[REDACTED]", text)
    safe_text = re.sub(r"(?i)bearer\s+\S+", "Bearer [REDACTED]", safe_text)[:4000]
    payload = {"model": "multilingual", "state": safe_text, "max_len": 512, "questions": {
        "complexity": {"type": "choice", "instructions": "Choose task complexity based only on the short task summary.",
                       "criteria": {"light": "Lookup or simple extraction", "small": "Small isolated edits or docs",
                                    "mid": "Multi-file feature or debugging", "top": "Architecture or security-sensitive work"}}}}
    request = urllib.request.Request("http://127.0.0.1:8000/v1/systemone", data=json.dumps(payload).encode(),
                                     headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=max(0.1, min(timeout_ms, 5000) / 1000)) as response:
            raw = json.loads(response.read(1_000_000))
        if not isinstance(raw, dict):
            return None
        answer = raw.get("answers", {}).get("complexity", {})
        if not isinstance(answer, dict):
            return None
        probabilities = answer.get("probabilities", {})
        if not isinstance(probabilities, dict):
            return None
        choice = answer.get("choice")
        labels = {"light", "small", "mid", "top"}
        if choice not in labels or set(probabilities) != labels:
            return None
        values = probabilities.values()
        if any(isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 1 for value in values):
            return None
        if abs(sum(probabilities.values()) - 1) > 0.02 or probabilities[choice] != max(probabilities.values()):
            return None
        return choice, float(probabilities[choice])
    except (OSError, urllib.error.URLError, TimeoutError, ValueError, TypeError):
        return None


def capability_search(query, candidates, limit=8):
    needle = query.strip().casefold()
    if not needle:
        raise ValueError("query must not be blank")
    if not 1 <= limit <= 50:
        raise ValueError("limit must be between 1 and 50")
    results = []
    for item in candidates:
        haystack = json.dumps(item, ensure_ascii=False).casefold()
        if needle in haystack:
            results.append(item)
            if len(results) == limit:
                break
    return {"items": results, "total": len(results)}


def build_route(request, config):
    text = request.task.text.lower()
    if request.schema_version != "1.0":
        raise ValueError("unknown schema_version")
    available_models = set(request.constraints.available_models)
    requested_model = request.environment.explicit_model
    if requested_model and requested_model not in available_models:
        raise ValueError("explicit model must be included in the MCP caller's available_models")

    candidates = {str(item.get("id")): item for item in request.constraints.skill_metadata if item.get("id")}
    skills = []
    reasons = []
    if re.search(r"\b(security|vulnerability|exploit|credentials|bảo mật|lỗ hổng)\b", text):
        complexity, reason = "top", "SECURITY_SENSITIVE"
    elif re.search(r"\b(bug|error|crash|fix|debug|lỗi|sửa)\b", text):
        complexity, reason = "mid", "BUG_FIX"
    elif re.search(r"\b(architecture|design|threat|migration|kiến trúc)\b", text):
        complexity, reason = "top", "COMPLEX_OR_SENSITIVE"
    elif re.search(r"\b(test|tests|testing|pytest|unit test|kiểm thử)\b", text):
        complexity, reason = "small", "TESTS_REQUIRED"
    elif re.search(r"\b(document|docs|readme|documentation|tài liệu)\b", text):
        complexity, reason = "small", "DOCUMENTATION"
    else:
        complexity, reason = "small", "UNKNOWN_TASK"
    reasons.append(reason)

    decision_source = "rules"
    classified = None
    routing = config.get("routing", {})
    if reason == "UNKNOWN_TASK" and routing.get("enabled", True):
        classified = classify_unknown(text, routing.get("classifier_timeout_ms", 1200))
        if classified and classified[1] >= routing.get("confidence_threshold", 0.5):
            complexity = classified[0]
            reasons = ["CLASSIFIER_RECOMMENDATION"]
            decision_source = "classifier"
        else:
            reasons = ["CLASSIFIER_FALLBACK"]
    if re.search(r"\b(test|tests|testing|pytest|unit test|kiểm thử)\b", text) and reason != "TESTS_REQUIRED":
        reasons.append("TESTS_REQUIRED")

    recommendations = []
    for skill_id in request.constraints.available_skills:
        meta = candidates.get(skill_id, {"id": skill_id})
        if meta.get("routing_enabled", True) is False:
            continue
        searchable = " ".join([skill_id, str(meta.get("name", "")), str(meta.get("description", ""))]).casefold()
        score = sum(1 for word in set(re.findall(r"[a-z0-9_]+", text)) if len(word) > 2 and word in searchable)
        if score:
            recommendations.append({"id": skill_id, "reason_code": "SKILL_MATCH", "_score": score})
    skills = [{"id": row["id"], "reason_code": row["reason_code"]}
              for row in sorted(recommendations, key=lambda item: (-item["_score"], item["id"]))
              [:config.get("skills", {}).get("max_recommendations", 3)]]

    caps = request.constraints.available_mcp_capabilities
    meta_by_id = {str(item.get("id")): item for item in request.constraints.mcp_metadata if item.get("id")}
    selected_caps = []
    for capability in caps:
        meta = meta_by_id.get(capability, {"id": capability})
        searchable = " ".join([capability, str(meta.get("name", "")), str(meta.get("description", ""))]).casefold()
        if any(word in searchable for word in set(re.findall(r"[a-z0-9_]+", text)) if len(word) > 2):
            selected_caps.append(capability)

    mapped = config.get("models", {}).get("tiers", {}).get(complexity)
    if mapped and mapped not in available_models:
        reasons.append("MODEL_MAPPING_UNAVAILABLE")
        mapped = None
    fallback = "CLASSIFIER_FALLBACK" in reasons or "MODEL_MAPPING_UNAVAILABLE" in reasons
    recommended_model = requested_model or (mapped if not fallback else None)
    status = "disabled" if not routing.get("enabled", True) else "fallback" if fallback else "recommended"
    return {"schema_version": "1.0", "trace_id": str(uuid.uuid4()), "status": status,
            "route": {"complexity": complexity, "execution": "not_executed", "mode": "advisory",
                      "model": {"strategy": "explicit" if requested_model else "recommended" if recommended_model else "inherit",
                                "model_id": recommended_model, "applied": False},
                      "skills": skills, "mcp_capabilities": selected_caps,
                      "parallel_agents": min(request.environment.max_parallel_agents,
                                               config.get("execution", {}).get("max_parallel_agents", 3))},
            "decision": {"source": decision_source, "confidence": classified[1] if decision_source == "classifier" else None,
                         "reason_codes": reasons},
            "policy": {"requires_approval": False, "permission_escalation_allowed": False},
            "telemetry": {"routing_duration_ms": 0}}
