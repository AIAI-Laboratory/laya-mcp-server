<p align="center"><img src="assets/logo.png" alt="Laya MCP Server" width="128"></p>
<h1 align="center">Laya MCP Server</h1>
<p align="center">
  <img alt="Version 0.1.0" src="https://img.shields.io/badge/version-0.1.0-0d9488">
  <a href="LICENSE"><img alt="Apache 2.0 license" src="https://img.shields.io/badge/license-Apache--2.0-blue"></a>
  <img alt="Python 3.11" src="https://img.shields.io/badge/Python-3.11-3776AB?logo=python&amp;logoColor=white">
  <img alt="Docker Compose" src="https://img.shields.io/badge/Docker-Compose-2496ED?logo=docker&amp;logoColor=white">
  <img alt="MCP Streamable HTTP" src="https://img.shields.io/badge/MCP-Streamable_HTTP-334155">
</p>

**Local CPU decisions for AI agents.** One container, one model, one setup command.
MCP, REST, Swagger and a test console. No GPU, paid API, database or dev/prod profiles.

By **[htrnguyen](https://github.com/htrnguyen)** · [Tiếng Việt](README.vi.md)

## Start

Requires **Linux/systemd, Docker Compose v2+, Python 3 and [uv](https://docs.astral.sh/uv/getting-started/installation/)**.
Use a normal account with sudo access. First startup downloads dependencies/model weights.
Default container limits: 4 CPUs, 4 GiB RAM, no swap.

```bash
./setup.sh
```

Setup enables Docker at boot, starts the service, tests MCP inference and registers detected
**Claude Code, Codex and OpenCode** clients globally. Open a new agent session afterward.
Global means all projects of the same OS user on this machine. Clients need no Docker privileges.

| Open | URL |
|---|---|
| Test console + copy settings/rules | **http://127.0.0.1:30765/** |
| Swagger | http://127.0.0.1:30765/docs |
| MCP | http://127.0.0.1:30765/mcp |
| Health | http://127.0.0.1:30765/health |

Service already running? `./setup.sh --register-only`.
Select clients with `--targets codex,claude`; preview registration with `--dry-run`.
The installer backs up changed configs, preserves other entries and avoids duplicates.
The global skill links to this checkout: keep its location stable.

## Use

> Read laya_guide, then use laya_decide to classify “I was charged twice and need a refund.”
> Include caller/task and show the tool result.

| Tool | Purpose |
|---|---|
| `laya_guide` | Usage/schema/limits, no inference |
| `laya_status` | Loaded model, device, revision |
| `laya_decide` | 1–3 typed questions and normalized results |
| `laya_classify` | Compatible single-classification tool |

**Choice** selects among 2–10 labels. **Noul** estimates yes/no probability.
**Score** rates ordered descriptions and is experimental. Noul/score always require review.
Short input and one question are the best starting point for CPU latency.

REST: `POST /v1/decide` uses `state`, `questions`, `caller`, `task` and returns validated decisions,
review flags, usage, timing and trace ID. Raw `/v1/systemone` remains available.
Examples are in the console and Swagger. Agents can read `/llms.txt`, `/guide.md`, `/skill.md`,
`/rules.md`, `/integrations.json`, `/openapi.json`, or MCP resource `laya://guide`.

## Configure & operate

Edit `.env`, then rerun setup. Defaults are in [.env.example](.env.example).
Main settings: `LAYA_PORT=30765`, `LAYA_THREADS=4`, `LAYA_CPUS=4`, `LAYA_MEMORY=4g`.

```bash
sudo docker compose ps
sudo docker compose logs -f --tail 50
sudo docker compose stop
sudo docker compose start
sudo docker compose down       # keeps model files
```

Logs go **only to Docker stdout**. Default `LAYA_LOG_FORMAT=compact` shows result, caller/task,
latency and trace. Use `json` for bounded input/output details, then rerun setup.
Docker rotates at 10 MiB × 2 files; recreating a container may discard its old logs.
Successful health polls are hidden. Nested MCP/REST timings must not be added together.

Keep `data/models`: it avoids downloading weights again. Setup caches, optional reports and private
config backups are ignored by Git. No persistent application log folder is needed;
setup removes old request log files only after successful deployment.
`restart: always` needs an existing container; after `compose down`, run setup again.

## Limits & checks

This is a **trusted local-only service**, without authentication. Do not expose it directly to LAN/Internet.
Logs in JSON mode may contain private text. Structured credential keys are redacted; free-form secrets are not.
Model confidence is not proof or permission to act. Use tests/code for exact checks, and the main agent
for writing, planning or multi-step reasoning. Invalid/truncated normalized responses are rejected.

```bash
uv run --no-project --with-requirements tests/requirements.txt python -m unittest discover -s tests -v
sudo docker compose exec -T laya python /app/scripts/verify_mcp.py
python3 scripts/benchmark.py --runs 100
```

An earlier six-case repeated CPU smoke test measured p50 **103 ms**, p95 **116 ms** on Ryzen 5 5600H
(4 threads, 100 warm calls). Not an accuracy guarantee or a benchmark of the multi-question API.
Full container rebuild/reboot and browser interaction must be verified on the target host.

## Sources & license

- **[Laya / Convai Innovations](https://github.com/NandhaKishorM/laya)** — upstream runtime;
  [pinned commit](https://github.com/NandhaKishorM/laya/tree/2e4d9c87e8b1621deb344eac7de5c7258f32f849),
  [docs](https://nandhakishorm.github.io/laya/), [benchmarks](https://github.com/NandhaKishorM/laya/blob/main/BENCHMARKS.md).
- **[Laya weights](https://huggingface.co/convaiinnovations/laya)** — the pinned runtime uses its multilingual subfolder;
  see [multilingual limitations](https://huggingface.co/convaiinnovations/laya-multilingual) and [SOURCE.json](SOURCE.json).
  `/health` reports the actual loaded revision.
- **[MCP specification](https://modelcontextprotocol.io/specification/latest)** / [Python SDK](https://github.com/modelcontextprotocol/python-sdk).
- **[FastAPI](https://fastapi.tiangolo.com/)**, [Pydantic](https://docs.pydantic.dev/), [Uvicorn](https://www.uvicorn.org/),
  [PyTorch](https://pytorch.org/), [Transformers](https://huggingface.co/docs/transformers/).
- **[Swagger UI](https://github.com/swagger-api/swagger-ui)** — bundled 5.33.1; [asset provenance](static/swagger/SOURCE.json).
- **[Docker Compose](https://docs.docker.com/compose/)** / [uv](https://docs.astral.sh/uv/).
- **[TypeSafe / Jev](https://docs.typesafe.ai/introduction/coding-agents)** and
  [Jev, Clearly Explained — Avi Chawla](https://blog.dailydoseofds.com/p/jev-clearly-explained) — architectural reading only.

Integration author: **htrnguyen**. [Apache-2.0](LICENSE) · [NOTICE](NOTICE) · [CHANGELOG](CHANGELOG.md).
Original Laya/Swagger licenses remain with their code. Model weights are not committed.
This project is not affiliated with TypeSafe and does not claim equivalent quality to Jev.
Direct dependencies are pinned; base-image/transitive dependencies are not fully locked.

## Clean reinstall

`./setup.sh --reset` removes only this checkout's Laya containers/images, global MCP entries/skill links, model/cache data, reports and backups, then rebuilds without layer cache and runs setup again. Source and `.env` remain. Other Docker projects and shared Docker build cache are not pruned. Requires sudo in your terminal.
