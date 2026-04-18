# OpenTree

Modular Codex CLI wrapper for building personal AI agent platforms.

OpenTree wraps Codex CLI with Owner-controlled security boundaries, a plug-and-play module system, and a built-in Slack bot runtime. Each user runs their own bot instance -- no multi-tenancy, no shared state. The core stays minimal; all features (personality, memory, scheduling, Slack connectivity) are delivered as modules that can be installed, removed, or replaced independently.

## Features

- **Security boundaries** -- Owner-configurable guardrails that users cannot bypass but can extend within scope
- **Module system** -- Folder-based modules with JSON manifests; install, remove, update, or create your own
- **Slack bot runtime** -- Socket Mode receiver, task queue, progress reporting, and crash recovery out of the box
- **Prompt assembly** -- Modules contribute rules and prompt hooks; OpenTree merges them into a single system prompt at startup
- **Placeholder engine** -- `{{bot_name}}`, `{{team_name}}`, and custom tokens resolved across all module files
- **Transactional init** -- Pre-flight validation and automatic rollback if any module fails to install

### Memory System

Four-section structured memory with semantic routing:

| Section | Purpose | Routing trigger |
|---------|---------|-----------------|
| Pinned | Explicitly remembered items | "remember this", "pin" |
| Core | Preferences, environment, habits | "I prefer", "my setup" |
| Episodes | Interaction experiences, lessons | Extracted from conversations |
| Active | Recent work context | Current tasks, projects |

Configurable via `memory_extraction_enabled` in `config/runner.json`.

### CLAUDE.md Customization

OpenTree generates `workspace/CLAUDE.md` with marker comments:

```
<!-- OPENTREE:AUTO:BEGIN -->
(auto-generated module rules -- do not edit)
<!-- OPENTREE:AUTO:END -->

Your custom content here (preserved across refresh/reinstall)
```

Owner content outside the markers is preserved during `opentree module refresh`, `opentree module update`, and `opentree init --force`.

## Requirements

- Python 3.11+
- [Codex CLI](https://github.com/openai/codex)（v0.120.0+）
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
  --owner "U0AJRPQ55PH"       # recommended
  # --admin-users "U0AJRPQ55PH"  # backward-compatible alias for --owner
```

Options:

| Flag | Default | Description |
|------|---------|-------------|
| `--owner` | (required) | Comma-separated Slack User IDs |
| `--admin-users` | — | Deprecated alias for `--owner` |
| `--bot-name` | (required) | Bot display name |
| `--cmd-mode` | `auto` | How to invoke opentree in run.sh (`auto`/`bare`/`uv-run`) |
| `--home` | `~/.opentree` | Path to OPENTREE_HOME |
| `--team-name` | — | Team name (optional) |
| `--force` | false | Re-initialize existing home |
| `--non-interactive` | false | Skip confirmation prompts |

This creates `~/.opentree/`, copies bundled modules, generates `.claude/settings.json` and `CLAUDE.md`, and produces `bin/run.sh` for daemon mode.

### 2. Configure

```bash
# .env.defaults is auto-generated with placeholder tokens -- edit it:
vim ~/.opentree/config/.env.defaults

# Copy the local example for Owner customizations:
cp ~/.opentree/config/.env.local.example ~/.opentree/config/.env.local
```

See [Instance Configuration](#instance-configuration-v050) for .env layering details.

### 3. Start

```bash
# Interactive mode (TUI)
opentree start

# Slack bot daemon
opentree start --mode slack
```

## Instance Configuration (v0.5.0)

### .env Three-Layer Loading

Environment variables are loaded in order, with later files overriding earlier ones:

| Layer | File | Purpose | Git-tracked |
|-------|------|---------|-------------|
| 1 | `.env.defaults` | Bot tokens (SLACK_BOT_TOKEN, SLACK_APP_TOKEN) | No |
| 2 | `.env.local` | Owner customizations (extra env vars, overrides) | No |
| 3 | `.env.secrets` | Optional sensitive keys (API keys, etc.) | No |

Legacy `.env` is loaded as fallback if none of the three-layer files exist.

### Command Mode (`--cmd-mode`)

Controls how `run.sh` invokes the `opentree` CLI:

| Mode | Command in run.sh | Use case |
|------|-------------------|----------|
| `auto` (default) | Detects `pyproject.toml` → `uv run`, else bare | Works in both dev and installed |
| `bare` | `opentree` | `pip install -e .` or system-wide install |
| `uv-run` | `uv run --directory <project> opentree` | Source checkout with uv |

### OPENTREE_CMD Override

Set `OPENTREE_CMD` in `.env.local` to override the baked-in command in `run.sh`:

```bash
# .env.local
OPENTREE_CMD=/usr/local/bin/opentree
```

This decouples the running instance from the source project location. Useful when the source directory moves or you switch between editable installs.

## Bot Commands

Owner-only commands sent via Slack `@BotName <command>`:

| Command | Description |
|---------|-------------|
| `reset-bot` | Soft reset -- regenerate settings, symlinks, CLAUDE.md auto block, clear sessions. Preserves `.env.local`, `data/`, Owner CLAUDE.md content |
| `reset-bot-all` | Hard reset -- clear all customizations and data, regenerate everything from scratch |
| `shutdown` | Permanent stop (no auto-restart) |

### Owner Identification

Owner detection is based only on the `権限等級：Owner` signal in the system prompt.
If the prompt shows `権限等級：一般使用者`, that user is not the Owner.
When asked who the Owner is, the bot answers from this signal only and does not guess or hallucinate user IDs.
The `admin_users` configuration is never exposed in the system prompt.

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

Security layer (Owner-locked, not modifiable)
  Sandbox | Settings Generator | Audit Logger

Codex CLI (runtime)
```

### Core Design Principles

1. **One user, one bot** -- No multi-tenancy; each bot instance serves a single user
2. **Minimal core** -- Wrapper + sandbox + onboarding; everything else is a module
3. **Everything is a module** -- Including Slack connectivity and personality
4. **Owner-defined boundaries** -- Users cannot weaken security, only extend within scope
5. **Codex CLI as runtime** -- Minimize custom logic; delegate to the CLI wherever possible

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
  generator/    CLAUDE.md (with marker preservation), settings.json, symlinks
  manifest/     Module manifest schema and validation
  registry/     Module registry (install state, locking)
  runner/       Slack bot runtime (receiver, dispatcher, progress, etc.)
    reset.py        Bot reset (soft/hard)
    memory_schema.py  Four-section structured memory
  schema/       JSON Schema definitions
  templates/    run.sh and other file templates

modules/        Bundled module definitions (manifests + rules)

tests/
  isolation/    Unit and integration tests
  e2e/          End-to-end Slack bot tests
```

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `OPENTREE_HOME` | Path to OpenTree home directory | `~/.opentree` |
| `OPENTREE_CMD` | Override the opentree command in run.sh | (baked-in at init) |
| `OPENTREE_E2E_DOGI_DIR` | Path to DOGI source for E2E tests | (unset = skip) |
| `OPENTREE_E2E_FOREIGN_PATH` | Path to foreign test bot for E2E | (unset = skip) |

## Design Documents

- [Architecture Proposal](openspec/changes/20260329-initial-architecture/proposal.md)
- [Architecture Research](openspec/changes/20260329-initial-architecture/research.md)
- [Architecture Decisions](openspec/changes/20260329-initial-architecture/decisions.md)
- [Slack Bot Runner (Phase 1)](openspec/changes/20260330-slack-bot-runner/)
- [UX Enhancements (Phase 2)](openspec/changes/20260330-phase2-ux/)
- [Operations (Phase 3)](openspec/changes/20260330-phase3-ops/)
- [E2E Verification](openspec/changes/20260331-e2e-verification/)
- [Owner Freedom (v0.5.0)](openspec/changes/20260407-owner-freedom/)

## Status

| Version | Date | Highlights |
|---------|------|------------|
| 0.1.0 | 2026-03-29 | Initial architecture -- module system, manifest validation, CLI, 10 bundled modules |
| 0.2.0 | 2026-03-31 | Slack bot runtime -- Socket Mode receiver, dispatcher, progress reporting, crash recovery |
| 0.3.0 | 2026-04-03 | Stability -- singleton lock, stale PID cleanup, 59 E2E tests, retry and circuit breaker |
| 0.4.0 | 2026-04-04 | Module update command, queued ack cleanup, E2E concurrency controls |
| 0.5.0 | 2026-04-07 | Owner Freedom -- Admin->Owner terminology, CLAUDE.md protection, .env three-layer, reset commands, structured memory |

See [CHANGELOG.md](CHANGELOG.md) for full details.

## License

Not yet specified.
