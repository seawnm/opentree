# Deployment Guide

Practical guide for setting up, configuring, and running an OpenTree bot instance.

## Prerequisites

- **Python 3.11+**
- **[uv](https://docs.astral.sh/uv/)** (recommended) or pip
- **[Codex CLI](https://github.com/openai/codex)** (`codex`) installed and authenticated
- **[bubblewrap](https://github.com/containers/bubblewrap)** (`bwrap`) — kernel namespace sandbox; **required at bot startup**
  ```bash
  # Debian / Ubuntu / WSL2
  sudo apt-get install bubblewrap

  # Verify installation
  bwrap --version
  ```
- **Slack App** with:
  - Socket Mode enabled
  - Bot Token (`xoxb-...`) with required scopes
  - App-Level Token (`xapp-...`) with `connections:write` scope
  - Event subscriptions: `app_mention`, `message.im`

## Installation Methods

| Method | Command | Best for |
|--------|---------|----------|
| Source checkout | `git clone` + `uv sync --extra slack` | Development, contributing |
| Editable install | `pip install -e ".[slack]"` | Production instances |
| Package install | `pip install opentree[slack]` | Future (not yet on PyPI) |

### Source checkout

```bash
git clone https://github.com/anthropics/opentree.git
cd opentree
uv sync --extra slack
```

The `opentree` command is available via `uv run opentree`.

### Editable install

```bash
git clone https://github.com/anthropics/opentree.git
cd opentree
pip install -e ".[slack]"
```

The `opentree` command is available directly on PATH.

## Instance Setup

```bash
# From source checkout
uv run opentree init --bot-name "MyBot" --owner U12345

# From editable/package install
opentree init --bot-name "MyBot" --owner U12345 --cmd-mode bare
```

### Init options

| Option | Required | Description |
|--------|----------|-------------|
| `--bot-name` | Yes | Bot display name |
| `--owner` | Yes | Comma-separated Slack User IDs (e.g. `U123,U456`) |
| `--home` | No | Instance root directory (default: `~/.opentree/`) |
| `--team-name` | No | Team name for placeholder resolution |
| `--cmd-mode` | No | How run.sh invokes opentree: `auto`, `bare`, `uv-run`, `venv` |
| `--force` | No | Re-initialize an existing instance |

### What init creates

```
~/.opentree/                  # OPENTREE_HOME (default)
  bin/
    run.sh                    # Wrapper: auto-restart, watchdog, crash protection
  config/
    .env.defaults             # Bot tokens (chmod 600)
    .env.local.example        # Owner customization template
    user.json                 # Bot name, team name
    runner.json               # Owner user IDs, runtime settings
    registry.json             # Installed module state
  modules/                    # 10 bundled modules (symlinked rules)
  workspace/
    .claude/
      rules/                  # Symlinked module rules
      settings.json           # Merged permissions from all modules
    CLAUDE.md                 # Generated system prompt (Claude Code; preserved across refresh)
    AGENTS.md                 # Generated system prompt (Codex CLI; HTML-comment markers, runtime-rewritten)
  data/
    logs/                     # Daily rotated log files
    memory/                   # User memory files
```

## .env Configuration

Three-layer loading with later files overriding earlier ones:

| File | Purpose | Created by | Permissions |
|------|---------|-----------|-------------|
| `config/.env.defaults` | Bot tokens (secrets) | `opentree init` | `chmod 600` (owner-only) |
| `config/.env.local` | Owner API keys, overrides | Owner (copy from `.env.local.example`) | Owner-readable |
| `config/.env.secrets` | Deployment-specific overrides | Operator | Owner-readable |

**Load order:** `.env.defaults` -> `.env.local` -> `.env.secrets`

**Legacy support:** A single `config/.env` file is still recognized with a deprecation warning. Migrate to the three-layer scheme when convenient.

### Required tokens

Add these to `config/.env.defaults`:

```bash
SLACK_BOT_TOKEN=xoxb-your-bot-token
SLACK_APP_TOKEN=xapp-your-app-token
```

### Owner customization

Copy the example and add your keys to `config/.env.local`:

```bash
cp config/.env.local.example config/.env.local
# Edit .env.local:
#   OPENAI_API_KEY=sk-your-key-here
```

Keys in `.env.local` override `.env.defaults`. This separation keeps bot secrets invisible to the owner while allowing custom API keys.

## Starting the Bot

### Foreground (development)

```bash
# Source checkout
uv run opentree start --mode slack --home ~/.opentree

# Installed
opentree start --mode slack --home ~/.opentree
```

### Background (production)

```bash
nohup bash ~/.opentree/bin/run.sh >> ~/.opentree/data/logs/wrapper.log 2>&1 &
```

### Verify it's running

```bash
pgrep -af "opentree start --mode slack" && echo "Running" || echo "Not running"
```

### Logs

```bash
# Today's log
tail -f ~/.opentree/data/logs/$(date +%Y-%m-%d).log

# Errors only
grep ERROR ~/.opentree/data/logs/$(date +%Y-%m-%d).log
```

## Stopping the Bot

### 停止方式比較

| 方式 | 指令 | 適用情境 | 備註 |
|------|------|----------|------|
| `opentree stop` CLI | `opentree stop --home ~/.opentree` | **推薦**。從終端安全停止 | 寫入 stop flag 防止 wrapper 重啟 |
| `@Bot shutdown` | 在 Slack 發送 `@MyBot shutdown` | 從 Slack 遠端停止 | Exit code 42，wrapper 不重啟 |
| `pkill -f` | `pkill -f "run.sh"` | 最後手段 | ⚠️ 有誤殺其他進程風險，無 stop flag 保護 |

### `opentree stop` 用法

```bash
opentree stop [--home PATH] [--force] [--timeout SECONDS]
```

| 參數 | 必要 | 預設值 | 說明 |
|------|------|--------|------|
| `--home` | No | `~/.opentree/` 或 `OPENTREE_HOME` 環境變數 | Instance 根目錄路徑 |
| `--force` | No | False | 逾時後發送 SIGKILL 強制終止 |
| `--timeout` | No | 60 | 等待 graceful shutdown 的秒數 |

#### 基本範例

```bash
# 使用預設 home 路徑停止
opentree stop

# 指定 home 路徑
opentree stop --home ~/.opentree

# Source checkout 模式
uv run opentree stop --home ~/.opentree
```

#### 強制停止範例

```bash
# 等待 30 秒後強制 SIGKILL
opentree stop --force --timeout 30
```

### 停止流程

1. **讀取 PID**：從 `data/wrapper.pid` 讀取 wrapper 進程 PID（fallback 到 `data/bot.pid`）
2. **驗證進程**：透過 `/proc/cmdline` 確認 PID 屬於 OpenTree，避免誤殺
3. **寫入 stop flag**：在 `data/.stop_requested` 寫入標記，防止 wrapper 重啟 bot
4. **發送 SIGTERM**：通知進程開始 graceful shutdown
5. **等待退出**：輪詢進程狀態，最多等待 `--timeout` 秒
6. **逾時處理**：若加了 `--force`，發送 SIGKILL 強制終止；否則提示使用者加 `--force`

### 前置條件

- Instance 必須已初始化（`data/` 目錄存在）
- `data/wrapper.pid` 必須存在且記錄正確的 wrapper PID。舊版 `run.sh` 可能未寫入此檔案，執行 `opentree init --force` 可重新產生含 `wrapper.pid` 支援的 `run.sh`
- 若 `wrapper.pid` 不存在或過期，會 fallback 到 `bot.pid`，但此時 wrapper（若仍在執行）可能會重新啟動 bot

## Instance Decoupling (--cmd-mode)

The `--cmd-mode` option controls how `run.sh` invokes the `opentree` command. This determines whether an instance is tied to a source checkout or runs independently.

### Modes

| Mode | run.sh command | Use case |
|------|---------------|----------|
| `auto` (default) | Source checkout -> `uv run --directory ...`; installed -> bare `opentree` | Most users |
| `bare` | Always `opentree` | Requires `pip install` and `opentree` on PATH |
| `uv-run` | Always `uv run --directory ...` | Explicit source checkout binding |
| `venv` | `<home>/.venv/bin/opentree` | **Recommended for production**: instance-local venv, fully isolated from source |

**`venv` mode** is the recommended mode for running multiple production instances. Each instance has its own `.venv` containing a pinned version of opentree. Source code changes do **not** affect running instances until you explicitly redeploy via `scripts/deploy.sh`.

```bash
# Set up venv mode for a new instance
python3 -m venv /path/to/instance/.venv
/path/to/instance/.venv/bin/pip install '/path/to/opentree[slack]'
opentree init --home /path/to/instance --bot-name MyBot --owner U123 --cmd-mode venv
```

### Detection logic (auto mode)

1. `pyproject.toml` found at project root -> `uv run --directory <root> opentree`
2. `shutil.which("opentree")` succeeds -> bare `opentree`
3. Fallback -> bare `opentree`

### Runtime override

Override the baked-in command without re-running init:

```bash
# Use an installed package instead of uv run
export OPENTREE_CMD=opentree
bash ~/.opentree/bin/run.sh
```

The `OPENTREE_CMD` environment variable takes precedence over whatever was written into `run.sh` at init time.

## run.sh Wrapper Features

The generated `bin/run.sh` is a Bash wrapper that keeps the bot alive and healthy.

| Feature | Default | Description |
|---------|---------|-------------|
| Auto-restart | On any non-zero exit | Restarts the bot after a 5-second delay |
| Watchdog | 120s timeout | Kills the bot (SIGTERM, then SIGKILL after 40s) if heartbeat goes stale |
| Crash loop protection | 5 crashes / 600s | Enters 300s cooldown, then resets the counter |
| Network check | DNS `slack.com` | Waits up to 60s for connectivity before each (re)start |
| Singleton lock | `/tmp/opentree-wrapper-*.lock` | Prevents duplicate wrapper instances via `flock` |
| Stale PID cleanup | On startup | Kills orphaned bot processes from a previous run |
| Permanent stop | Exit code 42 | The `shutdown` command exits with 42; wrapper does not restart |
| Clean exit | Exit code 0 | Wrapper exits without restarting |

### Watchdog tuning

The watchdog expects the bot to keep `data/bot.heartbeat` fresh. Before v0.6.1, `receiver.py` only wrote heartbeat from `_handle_message()`, so a long 3-5 minute Codex task with no incoming Slack traffic could leave the heartbeat stale even though the bot was still healthy. `run.sh` would then see `WATCHDOG_TIMEOUT=120` exceeded and kill the bot.

This was fixed in v0.6.1 with a liveness probe loop in `Receiver.start()`: the receiver now uses `handler.connect()` (non-blocking), writes an initial heartbeat, then runs `shutdown_event.wait(timeout=15)` in a loop and calls `_liveness_probe()` every 15 seconds. Heartbeats are now independent of Slack traffic, which gives an 8x safety margin against the 120-second watchdog timeout.

Edit the variables at the top of `bin/run.sh`:

```bash
WATCHDOG_TIMEOUT=120          # seconds without heartbeat -> kill
WATCHDOG_INTERVAL=30          # check frequency
WATCHDOG_INIT_DELAY=30        # grace period for bot startup
WATCHDOG_SIGKILL_WAIT=40      # seconds after SIGTERM before SIGKILL
```

### Crash loop tuning

```bash
MAX_CRASHES=5                 # max crashes within window
CRASH_WINDOW=600              # detection window (seconds)
COOLDOWN=300                  # cooldown after crash loop detected
```

## Bot Commands (Owner Only)

These commands are sent via Slack (e.g. `@MyBot shutdown`):

| Command | Description |
|---------|-------------|
| `reset-bot` | Soft reset: regenerate settings.json, symlinks, CLAUDE.md auto block. Preserves `.env.local`, `.env.secrets`, `data/`, and owner CLAUDE.md content |
| `reset-bot-all` | Hard reset: delete `.env.local`, `.env.secrets`, clear `data/` contents, regenerate everything from scratch. Preserves `.env.defaults` and module source |
| `shutdown` | Permanent stop (exit code 42). Wrapper will not restart |
| `restart` | Graceful restart (SIGTERM -> wrapper auto-restarts) |
| `status` | Bot health information |

### Reset comparison

| What happens | `reset-bot` | `reset-bot-all` |
|-------------|:-----------:|:---------------:|
| Regenerate settings.json | Yes | Yes |
| Regenerate symlinks | Yes | Yes |
| Regenerate CLAUDE.md auto block | Yes | Yes |
| Preserve owner CLAUDE.md content | Yes | No |
| Preserve .env.local | Yes | No |
| Preserve .env.secrets | Yes | No |
| Preserve data/ (logs, memory, sessions) | Yes | No |
| Preserve .env.defaults | Yes | Yes |
| Preserve modules/ source | Yes | Yes |

## Permission Model

### How Permissions Work

All users — including Owners — run Claude Code CLI with `--permission-mode dontAsk`. This mode:

- **Only allows** tools explicitly listed in `workspace/.claude/settings.json` under `permissions.allow`
- **Automatically denies** every other tool without prompting
- **Cannot be bypassed** by Owner users at the CLI level

Permissions are compiled from installed modules (`modules/*/opentree.json`) into `config/permissions.json`, then generated into `workspace/.claude/settings.json` at init / refresh time.

### Default Security Boundaries

**Allow list** (from `core` module, scoped to instance home):

| Pattern | Scope |
|---------|-------|
| `Read($OPENTREE_HOME/**)` | Read any file in instance tree |
| `Read(//tmp/**)` | Read `/tmp/` |
| `Write($OPENTREE_HOME/workspace/**)` | Write workspace files only |
| `Write($OPENTREE_HOME/data/**)` | Write data dir (logs, memory) |
| `Write(//tmp/**)` | Write `/tmp/` |
| `Edit($OPENTREE_HOME/workspace/**)` | Edit workspace files |
| `Edit($OPENTREE_HOME/data/**)` | Edit data dir |
| `Edit(//tmp/**)` | Edit `/tmp/` |
| `Glob`, `Grep`, `WebSearch`, `WebFetch`, `Task` | Unrestricted |

**Deny list** (from `guardrail` module):

| Pattern | Blocks |
|---------|--------|
| `Read($OPENTREE_HOME/config/.env*)` | Config secrets |
| `Read($OPENTREE_HOME/**/.env)` | All nested `.env` files |
| `Read($OPENTREE_HOME/**/.env.*)` | All nested `.env.*` variants |

Additional modules (e.g. `slack`, `scheduler`) may add Bash-scoped tool patterns via their `opentree.json`.

### Owner Privileges

Owners have **no Claude CLI permission elevation**. They are distinguished only at the application layer:

- **Slack commands**: `reset-bot`, `reset-bot-all`, `shutdown`, `restart`, `status`
- **Config files**: `.env.local`, `.env.secrets`, `config/runner.json`
- **CLAUDE.md / AGENTS.md**: Editable content outside the `<!-- OPENTREE:AUTO:BEGIN -->` / `<!-- OPENTREE:AUTO:END -->` markers

## Sandbox (bubblewrap)

All Codex CLI subprocesses run inside a **bubblewrap kernel namespace sandbox**. This provides an additional security layer independent of `settings.json` permissions.

### What the sandbox does

| Aspect | Behavior |
|--------|----------|
| Filesystem | Only `/workspace` (instance home) and `~/.codex` are visible inside the sandbox |
| Blocked paths | `/mnt/e/` (Windows FS), `~/.ssh`, other host paths are excluded |
| Network | Open — Codex CLI needs to reach the OpenAI API |
| User scope | **All users including Owner** are sandboxed; no config toggle |
| Startup check | Bot refuses to start if `bwrap` is not found on PATH |

### Owner vs. non-owner filesystem access

| User type | Workspace bind | Effect |
|-----------|---------------|--------|
| Owner | `--bind` (read-write) | Full read/write to instance workspace |
| Non-owner | `--ro-bind` (read-only) | Read-only inside sandbox; writes to `/tmp/opentree/` still allowed |

### Fail-fast on missing bwrap

If `bwrap` is not installed, the bot logs an error and **refuses to start**:

```
RuntimeError: bubblewrap (bwrap) is not available. Install it with:
  sudo apt-get install bubblewrap
```

This is intentional — running without a sandbox is not a supported fallback.

### Upgrading (v0.5.0 → v0.5.1+)

If upgrading from v0.5.0, regenerate `settings.json` to apply the new path-scoped rules:

```bash
opentree module refresh
```

Without this step, the old unrestricted `Read`/`Write`/`Edit` entries remain in effect and the security fix is not activated.

## Codex Rules Injection Architecture

> **Critical for module authors.** This section explains the only correct way to deliver behavioral rules to Codex-based bots.

### The Two Rule Paths

OpenTree has two rule delivery mechanisms, and they serve **different runtimes**:

| Mechanism | Written to | Read by | Effective for |
|-----------|------------|---------|---------------|
| `modules/*/rules/*.md` → `.claude/rules/` symlinks | `workspace/.claude/rules/` | **Claude CLI only** | Claude Code bots |
| `modules/*/prompt_hook.py` → `assemble_system_prompt()` | `workspace/AGENTS.md` | **Codex CLI** | Codex-based bots |

**Codex bots never read `.claude/rules/`.** They only read `workspace/AGENTS.md`, which is rewritten atomically before every Codex subprocess call by `codex_process._write_agents_md()`.

### How AGENTS.md Gets Its Content

```
Each incoming message
    │
    ▼
assemble_system_prompt()          ← core/prompt.py
    ├── build_date_block()
    ├── build_identity_block()    ← sets "権限等級：Owner / 一般使用者"
    ├── build_channel_block()
    └── collect_module_prompts()  ← calls each module's prompt_hook.py
            ├── memory/prompt_hook.py
            ├── personality/prompt_hook.py   ← behavioral rules live here
            ├── scheduler/prompt_hook.py     ← scheduler rules live here
            ├── slack/prompt_hook.py
            └── requirement/prompt_hook.py
    │
    ▼
system_prompt (assembled string)
    │
    ▼
_write_agents_md()                ← codex_process.py
    └── workspace/AGENTS.md       ← Codex reads this before every turn
```

### Writing Rules for Codex Bots

**If you add behavioral rules to `rules/*.md` only, Codex bots will never see them.**

Always add critical rules to a `prompt_hook.py` in your module:

```python
# modules/mymodule/prompt_hook.py
def prompt_hook(context: dict) -> list[str]:
    return [
        "## My Module Rules",
        "",
        "**Rule 1**: ...",
        "**Rule 2**: ...",
    ]
```

Then register it in `opentree.json`:
```json
{ "prompt_hook": "prompt_hook.py" }
```

Static `rules/*.md` files are still useful for:
- Claude Code bots (via `.claude/rules/` symlinks)
- Human-readable documentation of the rules
- Reference material that prompt_hooks can summarize

### AGENTS.md Marker Format

Both the init-time generator (`generate_agents_md()`) and the runtime writer (`_write_agents_md()`) use identical HTML-comment markers:

```
<!-- OPENTREE:AUTO:BEGIN -->
... auto-generated content (rewritten on every message) ...
<!-- OPENTREE:AUTO:END -->

<!-- 以下為 Owner 自訂區塊，module 安裝/更新/refresh 不會覆蓋 -->
... owner custom content (preserved across rewrites) ...
```

> **Why HTML comments, not `# markdown` headers?** Codex CLI parses AGENTS.md as markdown. Using `# OPENTREE:AUTO:BEGIN` as a marker would render as a visible heading inside the system prompt. HTML comment markers are invisible to the LLM while still being parseable by the Python string search in `_merge_with_preservation()`.

## Updating

### Automated deployment (recommended for venv-mode instances)

Use `scripts/deploy.sh` to update one or all instances atomically. The script safely stops the wrapper (not just the bot), updates the package, re-initializes, and restarts — preventing zombie processes.

```bash
# Deploy all instances in instances.conf
bash /path/to/opentree/scripts/deploy.sh --all

# Deploy a specific instance
bash /path/to/opentree/scripts/deploy.sh --target bot_COGI

# Preview what would happen (dry-run)
bash /path/to/opentree/scripts/deploy.sh --dry-run --all

# Update package only, skip module re-init
bash /path/to/opentree/scripts/deploy.sh --all --skip-init
```

Register instances in `instances.conf` at the opentree project root:

```
# Format: name:home_path:bot_name
bot_COGI:/mnt/e/develop/mydev/project/trees/bot_COGI:COGI
bot_DOGI:/mnt/e/develop/mydev/project/trees/bot_DOGI:DOGI
```

> **Why kill the wrapper, not the bot?** The wrapper runs a cleanup trap (`trap cleanup SIGTERM`) that cascades SIGTERM to the bot and watchdog, then waits for clean exit. Killing only the bot causes the wrapper to detect a crash (non-zero exit) and restart the old version — creating zombie processes. Always SIGTERM the wrapper first.

### Source checkout

```bash
cd /path/to/opentree
git pull
# If using editable install, changes take effect immediately
# If using uv, the next `uv run opentree` picks up changes
```

### Refresh modules to latest bundled versions

```bash
opentree module update --all
```

This compares installed module versions against bundled versions and updates any that are outdated.

### Re-initialize (preserves owner content)

```bash
opentree init --force --home ~/.opentree --bot-name "MyBot" --owner U12345
```

`--force` re-runs init but preserves owner content outside `<!-- OPENTREE:AUTO:BEGIN -->` / `<!-- OPENTREE:AUTO:END -->` marker comments in CLAUDE.md.

### Refresh generated files only

```bash
opentree module refresh
```

Regenerates `settings.json`, symlinks, and CLAUDE.md without touching module source.

## Runtime Configuration (`config/runner.json`)

Optional JSON file for tuning bot behavior. All fields are optional — missing fields use defaults.

| Field | Default | Description |
|-------|---------|-------------|
| `codex_command` | `"codex"` | Path to the Codex CLI binary (e.g. `"/usr/local/bin/codex"`) |
| `task_timeout` | `1800` | Max seconds per task |
| `heartbeat_timeout` | `900` | Seconds without heartbeat before task is considered hung |
| `max_concurrent_tasks` | `2` | Max simultaneous Codex subprocess tasks |
| `progress_interval` | `10` | Seconds between progress Slack updates |
| `session_expiry_days` | `180` | Days before a session context is expired |
| `drain_timeout` | `30` | Seconds to wait for tasks to finish on graceful shutdown |
| `admin_users` | `[]` | List of Slack User IDs with owner privileges |
| `memory_extraction_enabled` | `true` | Enable/disable automatic memory extraction |

> **Legacy alias**: The JSON key `claude_command` is still accepted as a fallback for `codex_command`.

## Environment Variables Reference

| Variable | Description | Default |
|----------|-------------|---------|
| `OPENTREE_HOME` | Instance root directory | Set by `run.sh` from init |
| `OPENTREE_CMD` | Override the opentree command in run.sh | Baked at init time |
| `SLACK_BOT_TOKEN` | Slack Bot Token (`xoxb-...`) | Set in `.env.defaults` |
| `SLACK_APP_TOKEN` | Slack App-Level Token (`xapp-...`) | Set in `.env.defaults` |

## Troubleshooting

### Bot not starting

0. **`bubblewrap (bwrap) is not available`** — Install bubblewrap:
   ```bash
   sudo apt-get install bubblewrap
   bwrap --version   # should print a version number
   ```

1. Check tokens are set and not placeholder values:
   ```bash
   grep -c "your-" ~/.opentree/config/.env.defaults
   # Should output 0 (no placeholders remaining)
   ```
2. Verify `opentree` is on PATH (for `--cmd-mode bare`):
   ```bash
   which opentree
   ```
3. Check the wrapper log:
   ```bash
   tail -20 ~/.opentree/data/logs/wrapper.log
   ```

### Watchdog keeps killing the bot

The watchdog kills the bot if no heartbeat is written within 120 seconds. Possible causes:

- Running a version older than v0.6.1 during a long Codex task -- before the liveness probe fix, heartbeat was only refreshed when Slack messages arrived, so a 3-5 minute task with no incoming traffic could trigger the watchdog
- Bot is stuck or deadlocked in Python code
- Receiver thread crashed or failed to start (check logs for exceptions in `opentree.runner.receiver`)
- Disk full or permission error prevented writing `data/bot.heartbeat`
- Bot startup is slow -- increase `WATCHDOG_INIT_DELAY`

### Bot killed mid-task (watchdog SIGKILL)

**Symptom:** Bot gets SIGKILL (exit code 137) during long Codex tasks. Logs show `WATCHDOG: Heartbeat stale (>120s)`.

**Root cause (fixed in v0.6.1):** Prior to the liveness probe fix, heartbeat was only updated when Slack messages arrived. Long tasks with no incoming messages would exhaust the 120s watchdog timeout.

**Status:** Fixed. `receiver.py` now writes heartbeat every 15s in the probe loop.

**If still occurring:** Check that your instance is running the latest version (`python -c "import opentree; print(opentree.__version__)"`). If using venv mode, redeploy with `scripts/deploy.sh`.

### .env not loading

1. Check file exists and has correct name (`.env.defaults`, not `.env.default`)
2. Check permissions: `.env.defaults` should be readable by the bot process
3. Verify load order: `.env.secrets` overrides `.env.local` overrides `.env.defaults`
4. Legacy `config/.env` is only used when `.env.defaults` does not exist

### Reset not working

- `reset-bot` requires `config/registry.json` to exist. If missing, run `opentree init` first
- If `reset-bot` leaves the bot in a bad state, use `reset-bot-all` as a nuclear option
- `reset-bot-all` preserves `.env.defaults` (real tokens) so the bot can still authenticate after reset

### Singleton lock conflict

If the bot won't start with "Another wrapper is already running":

```bash
# Check for existing wrapper processes
pgrep -af "run.sh"

# If no process exists, the lock file is stale -- remove it
rm /tmp/opentree-wrapper-*.lock
```

### WSL2-specific issues

- `flock` does not work on DrvFs (`/mnt/` paths). Lock files are stored in `/tmp/` (native Linux fs) to work around this
- File permission commands like `chmod 600` may silently fail on DrvFs. Tokens are still loaded correctly but without filesystem-level protection
- **Watchdog kills after system sleep/suspend** — WSL2 suspends when the Windows host sleeps. The bot process is frozen during this time and cannot write heartbeats. When WSL2 resumes, the watchdog sees a stale heartbeat (e.g. 120-140s old) and kills/restarts the bot. This is expected behavior — run.sh recovers correctly. If you want to reduce spurious restarts, increase `WATCHDOG_TIMEOUT` in `bin/run.sh`:

  ```bash
  # bin/run.sh — increase from default 120 to accommodate WSL2 sleep cycles
  WATCHDOG_TIMEOUT=300
  ```

### Process manager (PM2 / systemd)

opentree's `run.sh` is a self-contained daemon with auto-restart, watchdog, crash loop protection, and singleton lock — it does not require a separate process manager.

**PM2 is redundant for opentree** and introduces unnecessary complexity:
- run.sh already handles restarts better (watchdog + crash loop protection vs. simple restart count)
- Exit code 42 semantics (permanent stop) are not honored by PM2 by default, causing it to restart the bot after a `shutdown` command
- Double-layered restart logic can cause hard-to-debug behavior

**Recommendation**: Use `nohup` directly as described in the [Starting the Bot](#starting-the-bot) section. If you need boot persistence, configure a minimal systemd unit that wraps `run.sh` — but avoid using PM2 for opentree.

If you already have PM2 installed and want to clean up:

```bash
pm2 delete bot-name     # remove from PM2 list
pm2 save                # persist the removal
# optionally: npm uninstall -g pm2 && rm -rf ~/.pm2
```
