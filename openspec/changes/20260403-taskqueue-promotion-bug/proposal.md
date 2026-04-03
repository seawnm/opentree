# Proposal: TaskQueue promotion worker thread bug

## Requirements (user's original words, verbatim)
E2E 測試在 concurrent test 之後全部 timeout（30 個 Slack thread 只有 6 個真正完成）

## Problem
TaskQueue._promote_next_locked() 將 pending task 標記為 RUNNING 狀態，但沒有通知 Dispatcher spawn worker thread。promoted task 永久佔用 running slot 但不做任何事，後續所有 task 卡在 pending queue。

觸發條件：2+ concurrent messages 同時處理時。

## Solution
- mark_completed/mark_failed 回傳 promoted tasks list（原本是 None）
- _promote_next_locked 回傳 list[Task]
- 新增 Dispatcher._spawn_promoted() 為每個 promoted task spawn daemon thread

## Change Scope
| File | Change Type | Description |
|------|-------------|-------------|
| task_queue.py | 修改 | mark_completed/mark_failed 回傳 list[Task]，_promote_next_locked 回傳 promoted list |
| dispatcher.py | 修改 | 新增 _spawn_promoted()，在 _process_task 結尾呼叫 |

## Risk
| Risk | Severity | Mitigation |
|------|----------|------------|
| 過多 thread spawn | LOW | 受 max_concurrent_tasks 限制 |
