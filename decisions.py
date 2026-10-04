"""Shared validated contract for REST and MCP bounded decisions."""
import asyncio
import json
import math
import time
import urllib.error
import urllib.request
from urllib.parse import quote
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator
from observability import trace_context, label

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]
Description = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]

class Question(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_-]{0,31}$")
    type: Literal["choice", "noul", "score"]
    instructions: str = Field(min_length=1, max_length=600)
    criteria: dict[str, Description] | list[Description] | None = None

    @model_validator(mode="after")
    def valid_criteria(self):
        if not self.instructions.strip(): raise ValueError("Instructions cannot be blank")
        if self.type == "choice":
            if not isinstance(self.criteria, dict) or not 2<=len(self.criteria)<=10:
                raise ValueError("choice needs 2-10 named criteria")
            if any(not k.strip() or len(k)>64 for k in self.criteria): raise ValueError("Invalid criterion ID")
        elif self.type == "score":
            if not isinstance(self.criteria,list) or not 2<=len(self.criteria)<=5 or len(set(self.criteria))!=len(self.criteria):
                raise ValueError("score needs 2-5 distinct ordered descriptions")
        elif self.criteria is not None:
            raise ValueError("noul accepts instructions only")
        return self

class DecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    state: Text
    questions: list[Question] = Field(min_length=1, max_length=3)
    caller: str = Field(default="", max_length=200)
    task: str = Field(default="", max_length=200)

    @model_validator(mode="after")
    def unique_ids(self):
        ids=[q.id for q in self.questions]
        if len(set(ids))!=len(ids): raise ValueError("Question IDs must be unique")
        return self

class Decision(BaseModel):
    id: str
    type: Literal["choice", "noul", "score"]
    value: str | float
    probabilities: dict[str,float] | None = None
    margin: float | None = None
    confidence: float | None = None
    needs_review: bool
    warnings: list[str]

class DecisionResponse(BaseModel):
    schema_version: Literal["1.0"] = "1.0"
    model: str
    routing: dict
    decisions: list[Decision]
    usage: dict
    duration_ms: float
    trace_id: str
    advisory: bool = True

class BackendError(Exception):
    def __init__(self,message,status=502): super().__init__(message); self.status=status

async def backend_request(backend,path,payload=None,caller="",task=""):
    context=trace_context.get()
    headers={"Content-Type":"application/json","X-Trace-Id":context.get("trace_id", ""),
             "X-Laya-Caller":quote(label(caller,context.get("caller","unknown")),safe=""),
             "X-Laya-Task":quote(label(task,context.get("task","unknown")),safe="")}
    def send():
        request=urllib.request.Request(backend+path,data=json.dumps(payload).encode() if payload is not None else None,headers=headers)
        try:
            with urllib.request.urlopen(request,timeout=30) as response:
                raw=response.read(1_000_001)
                if len(raw)>1_000_000: raise BackendError("Backend response exceeds limit")
                return json.loads(raw)
        except urllib.error.HTTPError as exc:
            # Keep backend diagnostics bounded; don't echo arbitrary input back to clients.
            status=exc.code if exc.code in {413,422,429,503} else 502
            raise BackendError(f"Local inference returned HTTP {exc.code}; shorten input or retry later",status) from exc
        except (urllib.error.URLError,TimeoutError) as exc:
            raise BackendError("Local inference unavailable or timed out; no cloud fallback",503) from exc
        except (ValueError,UnicodeDecodeError) as exc:
            raise BackendError("Invalid JSON from local inference") from exc
    return await asyncio.to_thread(send)

def number(value,low=0,high=1):
    if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or not low<=value<=high:
        raise BackendError("Invalid numeric field from model")
    return float(value)

def normalize(raw,request,duration_ms):
    if not isinstance(raw,dict) or not isinstance(raw.get("answers"),dict) or not isinstance(raw.get("usage"),dict):
        raise BackendError("Incomplete model response")
    if not isinstance(raw.get("model"),str) or not isinstance(raw.get("routing",{}),dict):
        raise BackendError("Invalid model metadata")
    for key in ["input_tokens","output_tokens"]:
        count=raw["usage"].get(key)
        if isinstance(count,bool) or not isinstance(count,int) or count<0: raise BackendError("Invalid token usage")
    if raw["usage"].get("truncated") or raw["usage"].get("state_tokens_dropped",0) or raw["usage"].get("truncated_questions"):
        raise BackendError("Input was truncated; shorten state and criteria",422)
    decisions=[]
    for question in request.questions:
        answer=raw["answers"].get(question.id)
        if not isinstance(answer,dict) or answer.get("type")!=question.type:
            raise BackendError("Missing or mismatched model answer")
        warnings=["uncalibrated_for_your_task"]
        probabilities=None; margin=None; confidence=None
        if question.type=="noul":
            value=number(answer.get("noul"))
            review=True
            warnings.append("boolean_judgment_requires_review")
        else:
            keys=list(question.criteria) if question.type=="choice" else [str(i) for i in range(len(question.criteria))]
            distribution=answer.get("probabilities")
            if not isinstance(distribution,dict) or set(distribution)!=set(keys): raise BackendError("Invalid probability labels")
            probabilities={k:number(v) for k,v in distribution.items()}
            if abs(sum(probabilities.values())-1)>0.02: raise BackendError("Probabilities do not sum to one")
            top=sorted(probabilities.values(),reverse=True);margin=round(top[0]-top[1],6)
            if answer.get("confidence") is not None:confidence=number(answer["confidence"])
            if question.type=="choice":
                value=answer.get("choice")
                if value not in probabilities or probabilities[value]+1e-4<max(probabilities.values()): raise BackendError("Invalid winning label")
                # Heuristics for review, never an authorization or correctness guarantee.
                review=top[0]<0.85 or margin<0.25 or value.lower() in {"unknown","other","review","uncertain"}
                if review:warnings.append("ambiguous_or_review_label")
            else:
                value=number(answer.get("score"),0,len(keys)-1)
                review=True;warnings.append("experimental_score_requires_review")
        decisions.append(Decision(id=question.id,type=question.type,value=value,probabilities=probabilities,
                                  margin=margin,confidence=confidence,needs_review=review,warnings=warnings))
    return DecisionResponse(model=str(raw.get("model","unknown")),routing=raw.get("routing") or {},decisions=decisions,
        usage=raw["usage"],duration_ms=round(duration_ms,3),trace_id=trace_context.get().get("trace_id",""))

async def evaluate(request,backend):
    started=time.perf_counter()
    payload={"model":"multilingual","state":request.state,"max_len":512,
             "questions":{q.id:q.model_dump(exclude={"id"},exclude_none=True) for q in request.questions}}
    raw=await backend_request(backend,"/v1/systemone",payload,request.caller,request.task)
    return normalize(raw,request,(time.perf_counter()-started)*1000)

def configure_decisions(app,backend="http://127.0.0.1:8000"):
    from fastapi import HTTPException
    @app.post("/v1/decide",response_model=DecisionResponse,tags=["Decisions"],summary="Choice, yes/no or experimental score")
    async def decide(request:DecisionRequest):
        try:return await evaluate(request,backend)
        except BackendError as exc:raise HTTPException(exc.status,str(exc)) from exc
