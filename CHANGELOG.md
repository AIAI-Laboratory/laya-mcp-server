# Changelog

All notable changes are recorded here. Versions follow Semantic Versioning.
This pre-1.0 project may change its interface between minor releases.

## [Unreleased]

### Changed
- Application logging now writes only Docker stdout; compact by default, JSON opt-in.
- Consolidated English documentation and added README.vi.md.

### Simplified
- One shell entry point: setup.sh, including global-only registration.
- Consolidated operator/security/provenance notes in README; kept only runtime guide and shared skill separately.


### Added
- Shared typed decision contract for REST and MCP: choice, yes/no and experimental score.
- Validated normalized responses, truncation rejection and explicit review flags.
- Local documentation console with supplied logo, editable examples and copyable client settings/rules.
- Agent discovery endpoints and MCP guide tool/resource, without inference overhead.
- Primary sources and upstream attribution in README.

### Changed
- Consolidated startup around setup.sh and native Docker Compose commands.
- Removed duplicated client templates and usage/research/service documents.
- Moved validation-only dependencies under tests/; no dev/prod runtime profiles.
- Auto-detection with no installed agent leaves the standalone service usable.
- Runtime image copies only the smoke-test helper, not host installer scripts.

## [0.1.0] - 2026-10-04

### Added
- CPU-only Laya service with one resident multilingual checkpoint.
- Stateless Streamable HTTP MCP at `/mcp`: `laya_status` and `laya_classify`.
- REST inference, health endpoint and bundled, offline-capable Swagger UI.
- User-global MCP installation for Codex, Claude Code and OpenCode with backups,
  merge validation, rollback on configuration-write failures and a shared skill.
- Concise terminal logs plus bounded, rotating JSON input/output logs with trace IDs.
- Live MCP smoke test and a repeatable HTTP latency smoke benchmark.
- Docker restart policy, resource limits and guarded migration from the original container.

### Fixed
- Hugging Face Hub/tokenizers dependency conflict by pinning compatible versions.
- Unicode caller/task propagation between MCP and REST.
- Clean-clone initialization of environment and report directories.

### Known limitations
- Intended for a trusted, single-user Linux/systemd host; loopback only, no authentication.
- No independently established accuracy guarantee; six-case smoke tests are not an evaluation set.
- Base image and transitive dependencies are not fully locked; save the built image and package snapshot.
