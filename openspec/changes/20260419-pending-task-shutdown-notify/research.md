# Research: Pending Task Shutdown Options

**Date:** 2026-04-19

## 候選方案

### 方案 A：shutdown 時通知 pending 使用者（本次選擇）
**優點：** 實作簡單，使用者體驗明顯改善，不改資料結構
**缺點：** 任務仍然丟失，使用者需手動重試
**實作工時：** ~2 小時

### 方案 B：Pending 持久化到 JSON，重啟後 re-submit
**優點：** 任務不丟失，完全透明
**缺點：** 實作複雜（去重、過期清理、Slack event replay 衝突）、重啟後任務 context 可能過期
**淘汰原因：** Slack 不保證事件不重播，可能造成重複執行；task 的 Slack event context 不可序列化

### 方案 C：wait_for_drain 改為等 pending 清空
**優點：** 不丟任務
**缺點：** shutdown 時間不可預期（pending=10 個任務可能需要幾小時），watchdog 會強制 kill
**淘汰原因：** 根本上無法解決問題，反而讓 shutdown 卡住

## 決策

選方案 A：通知優先，簡單可靠。後續若需要持久化可作為獨立 feature。

## 實作細節

`TaskQueue.drain_pending()` 需要 hold `_lock` 才能安全清空 `_pending`，
並回傳 snapshot 讓 caller 在鎖外做 Slack 通知（避免持鎖時做 I/O）。

通知訊息設計：
- 刪除原有的 "Your request is queued..." ack（避免混淆）
- 發新訊息：「⚠️ Bot 正在重啟，你的請求已取消。重啟完成後請重新發送。」
