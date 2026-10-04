---
name: laya-mcp-server
description: Use the local Laya MCP for bounded text decisions: classification, routing, relevance, yes/no checks and experimental ordinal scoring. Use when the user requests Laya or when a narrow classification benefits from a separate local model.
---

# LOCAL LAYA DECISIONS

Read `laya_guide` or MCP resource `laya://guide` once when the task needs the service.
Use `laya_decide` for the normalized typed response; keep `laya_classify` for existing integrations.
Choice is the preferred default. Noul and score always need review; do not treat them as validated gates.
Docs and copyable client settings are also served at `/guide.md` and `/integrations.json`.

Use the registered `laya` MCP tools (`laya_status`, `laya_classify`, `laya_decide`, `laya_guide`; client prefixes vary).
No API key or Docker access is needed in the agent. The shared model runs locally on CPU.

- Call `laya_classify` with a short relevant `text`, 2–10 `labels` mapping IDs to clear descriptions,
  and focused `instructions`. Include an unknown/review label when the evidence can be insufficient.
- Set `caller` to the actual client name (codex, claude-code, opencode, etc.).
  Set `task` to the current task ID or a short purpose; do not invent user identity.
- Keep inputs short. The service uses multilingual with a 512-token budget and refuses truncated results.
  Avoid repeatedly sending whole files or calling it for every step.
- Treat the classification as advisory. High probability is not proof, and neither confidence nor
  act_probability authorizes editing, deleting, merging, or deploying. Use tests for deterministic claims.
- For connectivity problems, call `laya_status`. If unavailable or rejected, report it and continue
  using the main agent where appropriate; do not loop retries or switch to paid cloud providers.

Example arguments:
```json
{
  "text": "Tôi bị trừ tiền hai lần và muốn hoàn tiền.",
  "labels": {
    "billing": "Payments, invoices, refunds",
    "account": "Login, passwords, account access",
    "unknown": "Insufficient evidence or another category"
  },
  "instructions": "Classify the support request by its main issue.",
  "caller": "codex",
  "task": "support-triage"
}
```

Use the client-configured MCP endpoint. Do not create a second server or load another model.
Skill instructions alone do not register MCP: run the project's `./setup.sh --register-only` when installing.
