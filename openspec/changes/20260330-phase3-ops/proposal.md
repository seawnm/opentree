# Proposal: Phase 3 Operations — Logging + run.sh Wrapper + Init Integration

> 建立日期：2026-03-30
> 狀態：已完成

## Requirements（使用者原話）

> 請繼續

（承接 Phase 2 完成後，使用者確認繼續 Phase 3 運維層。）

## Problem

Phase 1+2 的 bot 可以運行，但缺少生產環境必要的運維能力：
1. 無結構化日誌（只有 print 輸出，無法事後查詢）
2. 無自動重啟（crash 後需手動重啟）
3. 無 watchdog（bot hang 住時無人知道）
4. `opentree init` 不生成啟動腳本（使用者需自行撰寫）

## Solution

### logging_config.py — 日誌系統
- Console handler (INFO) + File handler (DEBUG, daily rotation)
- 日誌目錄：`$OPENTREE_HOME/data/logs/YYYY-MM-DD.log`
- 保留天數可設定（預設 30 天）

### templates/run.sh — Bash Wrapper
- 自動重啟（非零退出碼 → 5s 後重啟）
- Watchdog（heartbeat 超時 120s → SIGTERM → 40s → SIGKILL）
- Crash loop 保護（5 次/600s → cooldown 300s）
- 網路檢查（DNS resolution 失敗 → 等待最多 60s）
- PID file + signal 轉發（SIGTERM/SIGINT → bot process）

### Init 整合
- `opentree init` 產生 `bin/run.sh`（placeholder 替換 + chmod +x）
- `opentree init` 產生 `config/.env.example`（token 模板）

### bot.py 整合
- `Bot.start()` 開頭呼叫 `setup_logging(log_dir)`

## Change Scope

| 檔案 | 變更類型 | 說明 |
|------|----------|------|
| `runner/logging_config.py` | **新增** | 日誌設定（64 行） |
| `templates/run.sh` | **新增** | Bash wrapper（246 行） |
| `runner/bot.py` | 修改 | start() 加入 setup_logging |
| `cli/init.py` | 修改 | 產生 run.sh + .env.example |
| `tests/test_logging_config.py` | **新增** | 19 tests |

## Risk

| 風險 | 嚴重度 | 緩解 |
|------|--------|------|
| run.sh 假設 `host` 指令可用 | MEDIUM | 容器環境可能缺少，可改用 ping |
| Watchdog PID 在 wrapper 異常退出時遺失 | MEDIUM | Watchdog 是 background subshell |
| 日誌檔案累積佔滿磁碟 | LOW | TimedRotatingFileHandler 保留 30 天 |
| .env.example 被誤當 .env 使用 | LOW | 檔案內有「Copy this file」提示 |
