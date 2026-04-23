# Proposal: Silent Failure Fix

**Date:** 2026-04-21
**Author:** walter
**Status:** approved

## 背景

2026-04-21 07:02-07:05 UTC，COGI bot 發生兩次靜默失敗事件。使用者收到「✅ 處理完成」
的成功通知，但 Slack thread 中沒有任何回覆內容。

兩個受影響的 thread_ts 均記錄到 Codex CLI exit code=1，且沒有 `turn.completed` 事件。
OpenTree pipeline 因缺乏正確的錯誤標記，將這兩次執行視為成功並觸發 ✅ 通知。

## 問題根因

Codex CLI 在特定條件下（例如：認證問題、stdin 競爭、內部錯誤）會以 exit_code=1 退出，
但不發出 `turn.completed` JSONL 事件。這兩個條件在 `codex_process.py` 中僅被記錄為
WARNING，並未標記 `is_error=True`，導致：

1. `CodexProcess.run()` 回傳 `ClaudeResult(is_error=False, response_text="")`
2. `progress.py` 的 `ProgressReporter.complete()` 收到空 `response_text` 後靜默返回
3. Circuit breaker 將空回應計為成功，不影響健康度
4. 使用者看到 ✅ 但沒有回覆

此外，發現一個預先存在的 bug：`dispatcher.py` 的 timeout 和 error 路徑呼叫
`self._task_queue.mark_failed(task)` 但丟棄回傳值，導致 promoted tasks 無法被
`_spawn_promoted()` 接手，永久卡在佇列（最長等待 30 分鐘）。

## 變更範圍

| File | Change Type | Description |
|------|-------------|-------------|
| `codex_process.py` | 修改 | `has_result_event=False` 和 `exit_code!=0` 時設為 `is_error=True`；新增結構化 INFO log |
| `progress.py` | 修改 | 空 `response_text` 改發 fallback 警告訊息，不再靜默返回 |
| `dispatcher.py` | 修改 | 空回應計為 circuit breaker failure；修復 `mark_failed()` 回傳值未傳給 `_spawn_promoted()` |

## 影響分析

- 原本靜默失敗的任務，使用者將收到 ❌ 明確錯誤通知
- Circuit breaker 能正確反映空回應的健康狀態，觸發保護機制
- Promoted tasks 不再卡佇列，worker thread 能正確接手

## 驗收標準

- Codex CLI exit_code=1 時，使用者收到 ❌ 錯誤通知（而非 ✅ 無回覆）
- `codex_process.py` 的結構化 log 包含 `exit_code`, `has_result_event`, `is_error` 欄位
- 並行任務完成後，promoted tasks 能在下個 worker cycle 立即被接手（不再等 30 分鐘）

## 限制與假設

- 不修改 Codex CLI 本身的行為
- `progress.py` 的 fallback 訊息為繁中，與現有錯誤訊息風格一致
- 三層修復（codex_process + progress + dispatcher）採 layered defense 策略，互不依賴
