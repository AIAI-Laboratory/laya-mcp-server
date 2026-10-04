"""Bounded JSON request logs for REST/MCP; no request bodies are consumed early."""
import contextvars
import json
import logging
import os
import re
import sys
import time
import uuid
from urllib.parse import unquote
from datetime import datetime, timezone

trace_context = contextvars.ContextVar("laya_trace", default={})
LIMIT = max(256, int(os.environ.get("LAYA_LOG_BODY_LIMIT", "16384")))
SECRET = re.compile(r"^(authorization|password|passwd|secret|api[_-]?key|access[_-]?token|refresh[_-]?token|hf_token)$", re.I)
logger = logging.getLogger("laya.requests")

class ConsoleFilter(logging.Filter):
    def filter(self, record):
        row = json.loads(record.getMessage())
        if row.get("event") != "request.end":
            return False
        # Keep protocol errors, but successful MCP handshakes are hidden in compact mode.
        return not (row.get("transport") == "mcp" and not row.get("tool") and row.get("success"))

class CompactFormatter(logging.Formatter):
    def format(self, record):
        row = json.loads(record.getMessage())
        output = row.get("output") or {}
        if row.get("transport") == "mcp" and isinstance(output, dict):
            result = output.get("result") or {}
            output = result.get("structuredContent") or {} if isinstance(result, dict) else {}
            if not output and isinstance(result, dict):
                for block in result.get("content", []):
                    if block.get("type") == "text":
                        try:
                            output = json.loads(block["text"])
                        except (ValueError, KeyError):
                            pass
                        break
        answers = output.get("answers", {}) if isinstance(output, dict) else {}
        decision = answers.get("category", {}) if isinstance(answers, dict) else {}
        choice = decision.get("choice") if isinstance(decision, dict) else None
        if choice is None and isinstance(output,dict) and output.get("decisions"):
            choice = ", ".join(str(d.get("value")) for d in output["decisions"] if isinstance(d,dict))
        def short(value, limit=64):
            value = str(value or "unknown")
            return json.dumps(value[:limit] + ("…" if len(value)>limit else ""), ensure_ascii=False)
        stamp = str(row.get("timestamp", ""))[11:23] + "Z"
        name = row.get("tool") or row.get("path")
        line = (f"{stamp} {'OK' if row.get('success') else 'ERROR'} {row.get('transport')} {name} "
                f"status={row.get('status')} {row.get('duration_ms', 0):.1f}ms "
                f"caller={short(row.get('caller'),32)} task={short(row.get('task'))}")
        if choice is not None:
            line += f" result={short(choice)}"
        line += f" trace={str(row.get('trace_id',''))[:12]}"
        return line

class AccessFilter(logging.Filter):
    def filter(self, record):
        args = record.args
        if isinstance(args, tuple) and len(args)>=5:
            path, status = str(args[2]).split("?",1)[0], int(args[4])
            if path.startswith("/v1/systemone") or path=="/v1/decide" or path.rstrip("/")=="/mcp":
                return False  # request.end already covers these requests
            if path=="/health" and 200<=status<400:
                return False
        return True

def configure_logging():
    if logger.handlers:
        return
    logger.setLevel(logging.INFO)
    logger.propagate = False
    mode=os.environ.get("LAYA_LOG_FORMAT", "compact")
    if mode not in {"compact", "json"}:
        raise ValueError("LAYA_LOG_FORMAT must be compact or json")
    console = logging.StreamHandler(sys.stdout)
    if mode == "compact":
        console.addFilter(ConsoleFilter())
        console.setFormatter(CompactFormatter())
    else:
        console.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(console)

def emit(event, **fields):
    logger.info(json.dumps({"timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
                           "event": event, **fields}, ensure_ascii=False, default=str))

def clean(value):
    if isinstance(value, dict):
        return {k: "[REDACTED]" if SECRET.match(k) else clean(v) for k,v in value.items()}
    if isinstance(value, list):
        return [clean(v) for v in value]
    return value

def body_value(data, total):
    if total > LIMIT:
        # Never emit partial JSON: truncation could expose an unparsed credential field.
        return {"omitted": "body exceeds log limit", "bytes": total}
    try:
        return clean(json.loads(data)) if data else None
    except (ValueError, UnicodeDecodeError):
        return {"omitted": "non-JSON body", "bytes": total}

def label(value, fallback="unknown"):
    return str(value or fallback).replace("\r", " ").replace("\n", " ")[:200]

class RequestLogMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        path = scope.get("path", "")
        if scope["type"] != "http" or not (path.startswith("/v1/systemone") or path=="/v1/decide" or path.rstrip("/")=="/mcp"):
            return await self.app(scope, receive, send)
        headers = {k.decode().lower(): v.decode(errors="replace") for k,v in scope.get("headers", [])}
        request_id = uuid.uuid4().hex
        candidate = headers.get("x-trace-id", "")
        trace_id = candidate if re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", candidate) else request_id
        context = {"trace_id": trace_id, "request_id": request_id,
                   "caller": label(unquote(headers.get("x-laya-caller", ""))), "task": label(unquote(headers.get("x-laya-task", "")))}
        token = trace_context.set(context)
        common = {**context, "transport": "mcp" if path.rstrip("/")=="/mcp" else "rest",
                  "method": scope["method"], "path": path,
                  "peer_ip": (scope.get("client") or [None])[0],
                  "user_agent": label(headers.get("user-agent")), "identity_source": "client_supplied"}
        started = time.perf_counter()
        incoming, outgoing = bytearray(), bytearray()
        counts = [0,0]
        status = 0
        error = None
        emit("request.start", **common)

        async def observed_receive():
            message = await receive()
            if message["type"] == "http.request":
                data = message.get("body", b"")
                counts[0] += len(data)
                incoming.extend(data[:max(0,LIMIT-len(incoming))])
            return message

        async def observed_send(message):
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                message = dict(message)
                message["headers"] = list(message.get("headers", [])) + [(b"x-request-id", request_id.encode()), (b"x-trace-id", trace_id.encode())]
            elif message["type"] == "http.response.body":
                data = message.get("body", b"")
                counts[1] += len(data)
                outgoing.extend(data[:max(0,LIMIT-len(outgoing))])
            await send(message)
        try:
            await self.app(scope, observed_receive, observed_send)
        except BaseException as exc:
            error = type(exc).__name__
            raise
        finally:
            input_value, output_value = body_value(incoming, counts[0]), body_value(outgoing, counts[1])
            if isinstance(input_value, dict) and common["transport"]=="mcp":
                params = input_value.get("params") or {}
                params = params if isinstance(params, dict) else {}
                arguments = params.get("arguments") or {}
                arguments = arguments if isinstance(arguments, dict) else {}
                common.update(mcp_method=input_value.get("method"), tool=params.get("name"), rpc_id=input_value.get("id"))
                common["caller"] = label(arguments.get("caller"), common["caller"])
                common["task"] = label(arguments.get("task"), common["task"])
                if input_value.get("method")=="initialize":
                    common["client_info"] = clean(params.get("clientInfo"))
            if isinstance(input_value, dict) and path=="/v1/decide":
                common["caller"] = label(input_value.get("caller"), common["caller"])
                common["task"] = label(input_value.get("task"), common["task"])
            result = output_value.get("result", {}) if isinstance(output_value, dict) else {}
            tool_error = isinstance(result, dict) and bool(result.get("isError"))
            rpc_error = isinstance(output_value, dict) and "error" in output_value
            emit("request.end", **common, status=status, duration_ms=round((time.perf_counter()-started)*1000,3),
                 success=bool(200<=status<400 and not error and not tool_error and not rpc_error),
                 error_type=error, input=input_value, output=output_value, input_bytes=counts[0], output_bytes=counts[1])
            trace_context.reset(token)
