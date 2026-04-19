# Research: Pending Task Shutdown Notify

**Date:** 2026-04-19

## 背景

目前 graceful shutdown 只保證 running task 有機會完成，對 pending task 沒有任何處理。
結果是：使用者先收到「已排隊」ack，但 bot 在真正開始執行前若收到 SIGTERM，這些 task 會直接從記憶體消失。

## Root Cause 分析

問題不是單一 bug，而是三個設計點疊加：

1. `TaskQueue._pending` 是純記憶體 `list[Task]`
2. `TaskQueue.wait_for_drain()` 只等待 `_running` 清空，不會處理 `_pending`
3. `Bot._shutdown()` 原本只呼叫 `wait_for_drain()`，沒有對 pending 使用者發任何 Slack 訊息

因此，pending task 既沒有持久化，也沒有在 shutdown 路徑中被顯式取消或通知。

## 候選方案

### 方案 A：Shutdown 時通知 pending 使用者（採用）

做法：
- shutdown 時先原子取出所有 pending task
- 刪除既有 queue ack
- 在原 thread 發取消通知，請使用者重啟後重新發送

優點：
- 實作最小
- 不引入持久化與 replay 複雜度
- 使用者得到立即且明確的反饋

缺點：
- 任務仍然需要手動重送

### 方案 B：Pending 持久化到磁碟

做法：
- 將 pending queue 序列化到 JSON / state file
- bot 重啟後載入並恢復

優點：
- 任務理論上不會因重啟而消失

缺點：
- 需要處理去重、過期、格式升級、損毀恢復
- Slack event / thread context 並非天然可安全重播
- 會把 queue 從記憶體結構升級成 durable state，範圍擴大很多

未採用原因：
- 超出本次問題範圍；為了修正「靜默丟失」而引入 persistence 並不划算

### 方案 C：重啟後自動 re-queue

做法：
- 不完整持久化 task 執行狀態，只保存必要欄位
- bot 啟動後重新塞回 queue

優點：
- 比完整持久化略簡單
- 使用者不必手動重送

缺點：
- 仍要處理 task idempotency、thread context 是否過期、附件是否還可下載
- 若 Slack 事件本身被重播，可能出現重複執行

未採用原因：
- 複雜度仍高，而且比起 persistence 只少了一部分工程量

## 決策

採用方案 A。

理由：
- 這個問題的核心不是「一定要保住 pending 任務」，而是「不能讓使用者毫無反饋地等不到結果」
- 方案 A 直接消除 silent drop，並維持目前 queue / shutdown 設計簡單
- 若未來真的需要跨重啟保留任務，應作為獨立 feature 設計 durable queue，而不是在這次修補中半套實作

## 實作方式

### `TaskQueue.drain_pending()`

- 在持有 `_lock` 的情況下複製 `self._pending`
- 立即清空原 queue
- 回傳 drained snapshot 給 caller

設計重點：
- 「取出 + 清空」必須是同一個臨界區，避免 shutdown 與其他 queue 操作競態
- Slack API I/O 不在 lock 內執行，避免長時間持鎖

### `Dispatcher.cancel_pending_tasks()`

- 呼叫 `task_queue.drain_pending()`
- 對每個 task best-effort 執行：
  - 若有 `queued_ack_ts`，先刪除原先的「queued」提示
  - 再在原 thread 發送取消通知
- 回傳取消數量供 `_shutdown()` 記錄

### `Bot._shutdown()`

- 在 `wait_for_drain()` 之前先呼叫 `cancel_pending_tasks()`
- 先處理尚未開始的任務，再等待已經 running 的任務自然完成

## 關鍵取捨

- **不做 persistence**：避免把單一 UX 問題升級成 durable queue 專案
- **best-effort Slack 通知**：通知失敗不阻斷 shutdown，仍以安全退出為優先
- **刪除 queued ack 再發取消訊息**：避免 thread 同時出現「已排隊」與「已取消」造成混淆

## 結論

這次變更修正的是「pending task 在 shutdown 時被靜默丟棄」的可見性問題。

使用者現在至少會收到明確取消通知，知道 bot 正在重啟、需要重新送出請求；而系統端則維持現有 in-memory queue 模型，不引入不必要的持久化複雜度。
