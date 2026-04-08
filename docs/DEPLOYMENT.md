# Deployment Guide

Practical guide for setting up, configuring, and running an OpenTree bot instance.

## Prerequisites

- **Python 3.11+**
- **[uv](https://docs.astral.sh/uv/)** (recommended) or pip
- **[Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code)** installed and authenticated
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
| `--cmd-mode` | No | How run.sh invokes opentree: `auto`, `bare`, `uv-run` |
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
    CLAUDE.md                 # Generated system prompt
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
| `bare` | Always `opentree` | Production; requires `pip install` |
| `uv-run` | Always `uv run --directory ...` | Explicit source checkout binding |

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

## Updating

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

## Environment Variables Reference

| Variable | Description | Default |
|----------|-------------|---------|
| `OPENTREE_HOME` | Instance root directory | Set by `run.sh` from init |
| `OPENTREE_CMD` | Override the opentree command in run.sh | Baked at init time |
| `SLACK_BOT_TOKEN` | Slack Bot Token (`xoxb-...`) | Set in `.env.defaults` |
| `SLACK_APP_TOKEN` | Slack App-Level Token (`xapp-...`) | Set in `.env.defaults` |

## Troubleshooting

### Bot not starting

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

- Bot is stuck on a long Claude CLI call -- increase `WATCHDOG_TIMEOUT` in `bin/run.sh`
- Bot startup is slow -- increase `WATCHDOG_INIT_DELAY`

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
