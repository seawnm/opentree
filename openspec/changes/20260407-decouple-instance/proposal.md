# Proposal: Decouple Instance from Source Project

## Requirements (user's original words, verbatim)

> 幫我全面檢查
> - opentree 是否有任何使用到 slackbot, slackbot data 程式的地方
> - Opentree instance 是否有使用到 opentree 專案程式的地方
> 我要完全解耦合

## Problem

OpenTree instance (bot_walter) 無法脫離 opentree source project 獨立運行。
6 個耦合點：

| # | 位置 | 耦合內容 | 嚴重度 |
|---|------|----------|--------|
| 1 | `bot_walter/bin/run.sh:24` | `uv run --directory '/mnt/e/.../opentree'` 硬編碼 | CRITICAL |
| 2 | `tests/e2e/conftest.py:43` | `DOGI_DIR = Path("/mnt/e/.../slack-bot")` | MEDIUM |
| 3 | `tests/e2e/test_e2e_extensions.py:32` | `_DOGI_DIR` + subprocess calls | MEDIUM |
| 4 | `tests/e2e/test_e2e_security.py:713` | 硬編碼 `slack-bot-data` 路徑 | MEDIUM |
| 5 | `modules/core/rules/environment.md:25` | `/tmp/slack-bot/` 臨時路徑 | MEDIUM |
| 6 | `modules/scheduler/rules/task-split-guide.md:34` | `/tmp/slack-bot/chains/` 路徑 | MEDIUM |

## Solution

### run.sh 解耦 (CRITICAL)
- `_resolve_opentree_cmd()` 新增第三層偵測：`shutil.which("opentree")` → bare command
- `opentree init` 新增 `--cmd-mode` 參數（`auto`/`bare`/`uv-run`）
- run.sh 模板新增 `OPENTREE_CMD` 環境變數覆蓋機制

### E2E 測試解耦 (MEDIUM)
- DOGI_DIR 改為環境變數 `OPENTREE_E2E_DOGI_DIR`
- 缺少環境變數時 skip 相關測試

### Module rules 解耦 (MEDIUM)
- `/tmp/slack-bot/` → `/tmp/opentree/`

## Change Scope

| 檔案 | 變更類型 | 說明 |
|------|----------|------|
| `src/opentree/cli/init.py` | 修改 | `_resolve_opentree_cmd()` + `--cmd-mode` 參數 |
| `src/opentree/templates/run.sh` | 修改 | OPENTREE_CMD 環境變數覆蓋 |
| `tests/e2e/conftest.py` | 修改 | DOGI_DIR → env var |
| `tests/e2e/test_e2e_extensions.py` | 修改 | _DOGI_DIR → env var |
| `tests/e2e/test_e2e_security.py` | 修改 | 硬編碼路徑 → env var |
| `modules/core/rules/environment.md` | 修改 | `/tmp/slack-bot/` → `/tmp/opentree/` |
| `modules/scheduler/rules/task-split-guide.md` | 修改 | `/tmp/slack-bot/` → `/tmp/opentree/` |

## Risk

- LOW: `--cmd-mode` 預設 `auto` 保持向後相容
- LOW: E2E 測試 skip 不影響 CI（E2E 本就需要 live bot）
- LOW: `/tmp/opentree/` 路徑變更不影響既有 instance（module refresh 時更新）
