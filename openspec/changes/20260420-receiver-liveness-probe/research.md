# Research: Receiver Liveness Probe Loop

**Date:** 2026-04-20

## 背景

Watchdog 設計預期 heartbeat 每 15 秒更新，逾時 120 秒則觸發 SIGTERM。
目前 heartbeat 只在收到 Slack 訊息時寫入（`_handle_message` 頂端）。
長時間任務期間若沒有新訊息，heartbeat 停更 120 秒就會被誤殺。

## 候選方案

### 方案 A：在更多呼叫點寫入 heartbeat

做法：
- 在 Dispatcher 任務執行迴圈、Codex runner 等位置額外呼叫 `_write_heartbeat()`

優點：
- 不需要改動 `start()` 的控制流

缺點：
- heartbeat 散落多處，邏輯不集中
- Dispatcher / runner 需持有 heartbeat_path 引用，違反單一責任
- 仍有死角：若執行路徑未覆蓋某段等待，問題依然存在
- 難以測試：需要覆蓋每個新增呼叫點

未採用原因：
- 治標不治本，root cause 是「heartbeat 更新依賴 Slack 訊息流量」

### 方案 B：Receiver probe loop（採用）

做法：
- 將 `handler.start()`（blocking）改為 `handler.connect()`（non-blocking）
- 在 `start()` 中進入 while loop，每 15 秒呼叫 `_write_heartbeat()`
- 透過 `shutdown_event.wait(timeout=PROBE_INTERVAL)` 實作等待與退出

優點：
- heartbeat 更新邏輯集中在 Receiver，責任清晰
- probe loop 與 Slack 訊息流量完全解耦
- 利用既有 `shutdown_event` 機制，退出路徑清晰
- 符合 DOGI bot 的既有 pattern（`socket_receiver.py` 的 liveness probe 同樣在 receiver 層）
- 測試容易：pre-set shutdown_event 讓 loop 立即退出，不需 sleep 或 mock time

缺點：
- 需要理解 `handler.connect()` vs `handler.start()` 的差異（見下方分析）

採用原因：
- 最小侵入，只改 Receiver 本身
- 解決 root cause 而非繞過

### 方案 C：Daemon thread 定期寫 heartbeat

做法：
- 在 `start()` 啟動一個 daemon thread，每 15 秒呼叫 `_write_heartbeat()`
- `start()` 仍呼叫 `handler.start()`（blocking）

優點：
- 不改動 `handler.start()` 呼叫方式

缺點：
- 多一個 thread 需要管理生命週期
- 停止機制需要額外 event 或 flag 協調
- daemon thread 在 Python 中若主 thread 異常退出，行為不保證乾淨

未採用原因：
- 方案 B 已達成相同目標，且不需引入額外 thread

## SocketModeHandler connect() vs start() 行為

`slack-bolt` SDK 中：
- `start()`：建立 WebSocket 連線並 block 直到 `close()` 被呼叫（blocking）
- `connect()`：建立 WebSocket 連線後立即返回（non-blocking）；
  事件透過背景 thread 持續接收

兩者都能接收 Slack 事件；差別只在是否阻塞呼叫端。
改用 `connect()` 後，`Receiver.start()` 可以自行掌控 blocking 行為（probe loop）。

## Shutdown 時序分析

```
SIGTERM
  → Bot._handle_signal()
      → shutdown_event.set()          # probe loop 在下個 wait() 返回
      → receiver.stop()               # close WebSocket
  → probe loop 退出（wait() 返回 True）
  → receiver.start() 返回
  → Bot.start() 進入 finally
  → Bot._shutdown()（drain tasks, cleanup）
```

關鍵：`shutdown_event.wait(timeout=15)` 在 event 被 set 後立即返回 `True`，
不需等滿 15 秒。最大額外延遲為接近 0（signal 到達時 wait() 立刻解除阻塞）。

## 決策

採用方案 B。

- Root cause 是「heartbeat 只在 Slack 訊息到達時更新」
- 方案 B 讓 heartbeat 成為週期性、與流量無關的行為
- 利用既有 shutdown_event 整合 graceful shutdown，不引入新機制
- 實作最小，測試容易，與現有架構一致
