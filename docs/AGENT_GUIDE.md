# Laya MCP Server: agent guide

Read this once per session when using the local service; no inference is required to fetch it.
Discovery: /llms.txt, /guide.md, /openapi.json, /integrations.json. MCP: laya_guide or resource laya://guide.

## Pick the right tool
- laya_status: check availability/device/revision, not before every successful call.
- laya_classify: backwards-compatible single classification; returns the upstream response.
- laya_decide: 1-3 typed questions sharing short state; normalized schema_version 1.0.
- choice: routing, intent, log category, relevance or selecting among known candidates.
- noul: probability of a yes/no proposition. Always advisory/review-required in this release.
- score: ordered descriptions, index expectation 0..N-1, not an exact number. Experimental and always review-required.

Not for open-ended answers, code generation, summaries, arithmetic, counting, reliable date comparisons,
large file analysis or multi-hop reasoning. Use deterministic code first where it suffices.
Installing MCP does not intercept shell commands or automatically switch the agent's primary model.

## Input contract
laya_decide(state, questions, caller, task). state: nonempty string, at most 4000 characters.
Each question has unique id, type and instructions. choice requires criteria object (2-10 labels).
score requires criteria list (2-5 distinct levels, low to high). noul has no criteria.
Maximum 3 questions; request one unless more are actually needed. Send relevant excerpts only.
Model is fixed multilingual, token budget 512; truncated responses are rejected, never silently trusted.
caller: actual client/app name. task: short purpose or issue ID, not invented identity.

## Output contract
laya_decide returns schema_version, model, routing, decisions, usage, duration_ms, trace_id, advisory=true.
Each decision contains id, type, value, probabilities if applicable, confidence if available,
margin for choice/score, needs_review and warnings. Fields are validated before returning success.
needs_review=false is NOT authorization, confidence calibration, or proof of correctness.
Choice review defaults (top probability <0.85, margin <0.25, or a known review label) are heuristics,
not calibrated thresholds. Include an unknown/review category when evidence can be insufficient.
No action is executed by this service. Tests and permission boundaries remain authoritative.

## Keep latency low
One resident CPU model; one inference admitted at a time. Three questions cost more than one.
Do not send every file or call after every agent step. Reuse a result only for identical inputs,
criteria and model revision; the service does not implement a result cache.
On overload/timeouts, report the condition and continue with the main agent when appropriate.
No automatic paid fallback and no unbounded retries. On invalid input, shorten or fix it once.

## Example: routing
{"state":"I was charged twice and need a refund.","questions":[{"id":"route","type":"choice","instructions":"Route this request by its main issue.","criteria":{"billing":"Payments, invoices, refunds","account":"Login and password","unknown":"Insufficient evidence or another issue"}}],"caller":"codex","task":"support-triage"}

## Deployment and privacy
Loopback only, trusted local user, no authentication. Setup registers user-global clients and shared skill.
Start a fresh agent session after config changes. In JSON debug mode, input/output go to Docker stdout with size limits;
free-form text may contain sensitive data. Do not submit credentials. Model judgments can be wrong.
