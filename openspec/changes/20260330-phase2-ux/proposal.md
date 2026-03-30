# Proposal: Phase 2 UX Enhancement — Progress Reporter + Thread Context + File Handler

> 建立日期：2026-03-30
> 狀態：已完成

## Requirements（使用者原話）

> 我希望 opentree 有自己獨立的 slackbot 模組，不要直接引用目前的 dogi 程式。

Phase 2 是 Bot Runner 的 UX 強化層，讓 bot 回覆不只是最終結果，還包含即時進度、thread 上下文、和附件處理。

## Problem

Phase 1 核心循環只能：收到訊息 → 呼叫 Claude → 回覆結果。缺少：
1. 使用者等待時看不到進度（不知 bot 是否還在處理）
2. Claude 無法看到 thread 中先前的對話（失去上下文）
3. 使用者上傳的附件無法傳遞給 Claude（無法處理檔案）

## Solution

新增 3 個模組並整合到 Dispatcher：

### progress.py — Block Kit 進度回報
- 背景 thread 每 N 秒更新 Slack 訊息（phase emoji + spinner + elapsed time）
- 完成時替換為最終回覆（含 token 統計）

### thread_context.py — Thread 歷史讀取
- 滑動視窗取最近 20 則訊息，上限 8000 字元
- 排除 bot 自己的訊息和當前觸發訊息
- 格式化為 `user_name: text` 注入 Claude 的 message

### file_handler.py — Slack 附件下載
- 下載到 `/tmp/opentree/{thread_ts}/`
- SSRF 防護（URL whitelist: files.slack.com）
- Path traversal 防護（_safe_filename + _safe_thread_dir）
- 50 MB 大小限制（streaming download）
- 任務完成後 cleanup

### Dispatcher 整合
- _process_task 新流程：progress.start → download → context → Claude(callback) → progress.complete → cleanup

## Change Scope

| 檔案 | 變更類型 | 說明 |
|------|----------|------|
| `runner/progress.py` | **新增** | Block Kit 進度回報（268 行） |
| `runner/thread_context.py` | **新增** | Thread 歷史讀取（129 行） |
| `runner/file_handler.py` | **新增** | 附件下載 + 安全防護（260 行） |
| `runner/dispatcher.py` | 修改 | 整合 progress + context + files |
| `runner/slack_api.py` | 修改 | 新增 bot_token property |
| `tests/test_progress.py` | **新增** | 36 tests |
| `tests/test_thread_context.py` | **新增** | 34 tests |
| `tests/test_file_handler.py` | **新增** | 55 tests |
| `tests/test_dispatcher.py` | 修改 | 新增 5 integration tests |

## Risk

| 風險 | 嚴重度 | 緩解 |
|------|--------|------|
| SSRF via file download URL | HIGH | URL whitelist (files.slack.com only) |
| Memory DoS via large file | HIGH | Streaming download + runtime size limit |
| thread_ts path traversal | HIGH | 格式驗證 + SHA-256 fallback |
| Progress thread leak | MEDIUM | reporter.stop() 在 finally block |
| Block Kit text > 3000 chars | LOW | 截斷至 3000 字元 |
