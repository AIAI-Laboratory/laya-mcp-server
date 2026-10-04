import os
from observability import configure_logging, RequestLogMiddleware
configure_logging()
import torch
# One resident model; deterministic resource bounds, no torch.compile cold start.
torch.set_num_threads(int(os.environ.get("LAYA_THREADS", "4")))
torch.set_num_interop_threads(1)
from laya.serve import create_app
import uvicorn
app = create_app()
from decisions import configure_decisions
configure_decisions(app)
from web_docs import configure_docs
configure_docs(app)
# Reject automatic routing to a second checkpoint to avoid CPU reload thrashing.
from fastapi import Request
from fastapi.responses import JSONResponse
@app.middleware("http")
async def pin_model(request: Request, call_next):
    if request.method == "POST" and request.url.path.startswith("/v1/systemone"):
        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"error": "Invalid JSON"}, status_code=400)
        if request.url.path != "/v1/systemone" or not isinstance(body, dict) or body.get("model") != "multilingual":
            return JSONResponse({"error": "This CPU profile accepts /v1/systemone with model=multilingual only"}, status_code=422)
    return await call_next(request)
from mcp_http import attach_mcp
attach_mcp(app)
app.add_middleware(RequestLogMiddleware)

if __name__ == "__main__":
    from copy import deepcopy
    config = deepcopy(uvicorn.config.LOGGING_CONFIG)
    config["filters"] = {"laya_access": {"()": "observability.AccessFilter"}}
    config["handlers"]["access"]["filters"] = ["laya_access"]
    uvicorn.run(app, host="0.0.0.0", port=8000, workers=1, log_config=config)
