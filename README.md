# OpenTree

Modular Claude Code CLI wrapper for building personal AI agent platforms.

OpenTree wraps Claude Code CLI with admin-controlled security boundaries, a plug-and-play module system, and a built-in Slack bot runtime. Each user runs their own bot instance -- no multi-tenancy, no shared state. The core stays minimal; all features (personality, memory, scheduling, Slack connectivity) are delivered as modules that can be installed, removed, or replaced independently.

## Features

- **Security boundaries** -- Admin-defined guardrails that users cannot bypass but can extend within scope
- **Module system** -- Folder-based modules with JSON manifests; install, remove, update, or create your own
- **Slack bot runtime** -- Socket Mode receiver, task queue, progress reporting, and crash recovery out of the box
- **Prompt assembly** -- Modules contribute rules and prompt hooks; OpenTree merges them into a single system prompt at startup
- **Placeholder engine** -- `{{bot_name}}`, `{{team_name}}`, and custom tokens resolved across all module files
- **Transactional init** -- Pre-flight validation and automatic rollback if any module fails to install

## Requirements

- Python 3.11+
- [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code)
- [uv](https://docs.astral.sh/uv/) (recommended)

## Installation

```bash
# From source (editable)
git clone https://github.com/anthropics/opentree.git
cd opentree
pip install -e ".[dev,slack]"
```

## Quick Start

### 1. Initialize

```bash
opentree init \
  --bot-name "MyBot" \
  --admin-users "U0AJRPQ55PH"
```

This creates the `~/.opentree/` home directory, copies bundled modules, generates `.claude/settings.json` and `CLAUDE.md`, and produces `bin/run.sh` for daemon mode.

### 2. Configure

```bash
cp ~/.opentree/config/.env.example ~/.opentree/config/.env
# Edit .env with your Slack tokens:
#   SLACK_BOT_TOKEN=xoxb-...
#   SLACK_APP_TOKEN=xapp-...
```

### 3. Start

```bash
# Interactive mode (TUI)
opentree start

# Slack bot daemon
opentree start --mode slack
```

## Module System

### Pre-installed Modules

| Module | Description |
|--------|-------------|
| core | Routing, path conventions, environment constraints |
| personality | Bot identity, speaking style, self-introduction rules |
| guardrail | Permission checks, safety rules, progressive denial guidance |
| memory | Remember, forget, and cross-thread memory management |
| scheduler | Scheduled task CRUD, watchers, task chains |
| slack | Slack connectivity -- message rules, queries, file uploads |
| audit-logger | Memory modification auditing -- tracking, notification, logging |

### Optional Modules

| Module | Description |
|--------|-------------|
| requirement | Requirement management -- collection, interview, assessment, tracking |
| stt | Speech-to-text -- audio transcription, quota management |
| youtube | YouTube video library -- search, fetch, subtitle management |

### Module Management

```bash
# List installed modules
opentree module list

# Install an optional module
opentree module install requirement

# Remove a module
opentree module remove stt

# Update modules to latest bundled versions
opentree module update --all

# Refresh generated files (CLAUDE.md, settings.json)
opentree module refresh
```

## Architecture

```
User-extensible area
  youtube | stt | requirement | ...        (optional modules)

Pre-installed modules
  personality | guardrail | memory | scheduler | slack | ...

OpenTree Core
  CLI Wrapper | Onboard (init) | Module Manager

Security layer (admin-locked, not modifiable)
  Sandbox | Settings Generator | Audit Logger

Claude Code CLI (runtime)
```

### Core Design Principles

1. **One user, one bot** -- No multi-tenancy; each bot instance serves a single user
2. **Minimal core** -- Wrapper + sandbox + onboarding; everything else is a module
3. **Everything is a module** -- Including Slack connectivity and personality
4. **Admin-defined boundaries** -- Users cannot weaken security, only extend within scope
5. **Claude Code CLI as runtime** -- Minimize custom logic; delegate to the CLI wherever possible

## Development

### Running Tests

```bash
# Unit and integration tests
pytest tests/

# With coverage
pytest tests/ --cov=opentree --cov-report=term-missing

# E2E tests (requires a running bot instance)
pytest tests/e2e/ -m "not slow and not destructive"
```

### Project Structure

```
src/opentree/
  cli/          CLI commands (init, start, module, prompt)
  core/         Config, placeholder engine, prompt assembly, version
  generator/    CLAUDE.md, settings.json, and symlink generation
  manifest/     Module manifest schema and validation
  registry/     Module registry (install state, locking)
  runner/       Slack bot runtime (receiver, dispatcher, progress, etc.)
  schema/       JSON Schema definitions
  templates/    run.sh and other file templates

modules/        Bundled module definitions (manifests + rules)

tests/
  isolation/    Unit and integration tests
  e2e/          End-to-end Slack bot tests
```

## Design Documents

- [Architecture Proposal](openspec/changes/20260329-initial-architecture/proposal.md)
- [Architecture Research](openspec/changes/20260329-initial-architecture/research.md)
- [Architecture Decisions](openspec/changes/20260329-initial-architecture/decisions.md)
- [Slack Bot Runner (Phase 1)](openspec/changes/20260330-slack-bot-runner/)
- [UX Enhancements (Phase 2)](openspec/changes/20260330-phase2-ux/)
- [Operations (Phase 3)](openspec/changes/20260330-phase3-ops/)
- [E2E Verification](openspec/changes/20260331-e2e-verification/)

## Status

| Version | Date | Highlights |
|---------|------|------------|
| 0.1.0 | 2026-03-29 | Initial architecture -- module system, manifest validation, CLI, 10 bundled modules |
| 0.2.0 | 2026-03-31 | Slack bot runtime -- Socket Mode receiver, dispatcher, progress reporting, crash recovery |
| 0.3.0 | 2026-04-03 | Stability -- singleton lock, stale PID cleanup, 59 E2E tests, retry and circuit breaker |
| 0.4.0 | 2026-04-04 | Module update command, queued ack cleanup, E2E concurrency controls |

See [CHANGELOG.md](CHANGELOG.md) for full details.

## License

Not yet specified.
