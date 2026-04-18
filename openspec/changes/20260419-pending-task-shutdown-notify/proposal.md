# Proposal: Notify Pending Tasks on Shutdown

**Date:** 2026-04-19
**Author:** walter
**Status:** approved

## 背景

bot_walter 在 2026-04-18 21:51 收到一個任務時，佇列已有 `pending=10, running=2`。
任務進入 pending queue 並回覆 "Your request is queued and will be processed shortly."。
但約 5 分鐘後（21:56:40）bot 收到 SIGTERM，`_shutdown()` 只等 running 任務完成，
pending 清單直接隨記憶體消失。Slack Socket Mode 不重播舊事件，使用者永遠等不到回覆。

## 問題根因

1. `TaskQueue._pending` 是純記憶體 `list[Task]`，無持久化
2. `wait_for_drain()` 只等 `_running` 清空，不處理 `_pending`
3. `bot._shutdown()` 未通知 pending 任務使用者

## 變更範圍

### task_queue.py
新增 `drain_pending() -> list[Task]`：
- 取出並清空所有 pending 任務
- 返回清單供呼叫者處理（發通知、記錄等）

### dispatcher.py
新增 `cancel_pending_tasks() -> int`：
- 呼叫 `task_queue.drain_pending()` 取得清單
- 對每個 pending task 的 `thread_ts` 發 Slack 通知
- 清理 `queued_ack_ts` 訊息（刪除 "queued" ack）
- 返回被取消的任務數

### bot.py (`_shutdown`)
在 `wait_for_drain()` 之前新增：
```python
cancelled = self._dispatcher.cancel_pending_tasks()
if cancelled > 0:
    logger.info("Cancelled %d pending tasks with user notification", cancelled)
```

## 驗收標準

- shutdown 時，所有 pending 任務的 thread 都會收到通知訊息
- 通知訊息清楚告知使用者「bot 重啟中，請稍後重新發送」
- `queued_ack_ts` 的 "queued" 訊息會被刪除，替換為取消通知
- 不影響 running 任務的正常完成流程

## 限制與假設

- 不實作 pending 持久化（範圍外，複雜度高）
- 若 Slack API 呼叫失敗（網路中斷），通知是 best-effort，不中斷 shutdown
- 通知文字固定，不支援客製化
