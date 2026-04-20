# Proposal: Receiver Liveness Probe Loop

**Date:** 2026-04-20
**Author:** walter
**Status:** approved

## 背景

Bot 執行長時間 Codex 任務（例如 30+ 分鐘的程式碼生成）時，watchdog 會因偵測到
heartbeat 停止更新而觸發 SIGTERM，強制重啟 bot，導致任務中斷。

## 問題根因

heartbeat 更新目前發生在兩個位置：

1. `Receiver._handle_message()`：每次收到 Slack 訊息時寫入
2. 無其他週期性更新機制

若使用者只發一則訊息然後等待 Codex 執行，`_handle_message` 不再被呼叫。
heartbeat 停止更新，watchdog 在 120 秒後觸發 SIGTERM。
而 Codex 任務可能正在正常執行中，被強制中斷純屬誤殺。

## 變更範圍

### receiver.py

1. 新增 `PROBE_INTERVAL: int = 15` class constant
2. 新增 `shutdown_event` 參數到 `__init__`（若未提供則自動建立）
3. 將 `start()` 從 `handler.start()`（blocking）改為：
   - `handler.connect()`（non-blocking，建立 WebSocket 連線）
   - 進入 probe loop，每 `PROBE_INTERVAL` 秒呼叫 `_liveness_probe()`
   - 當 `shutdown_event` 被 set 時退出 loop
4. 新增 `_liveness_probe()` 方法，僅呼叫 `_write_heartbeat()`

### bot.py

將 `self._shutdown_event` 傳入 `Receiver(...)` 建構子，確保 signal handler
設定 shutdown event 後，probe loop 能正確退出。

## 驗收標準

- heartbeat 每 15 秒更新一次，與 Slack 訊息流量無關
- watchdog timeout 120 秒 >> probe interval 15 秒，不會誤觸發
- 收到 SIGTERM 後，shutdown_event 被 set，probe loop 在下一個 wait() 返回時退出
- 現有測試全部通過，新增測試覆蓋 probe loop 行為

## 限制與假設

- 不修改 run.sh 的 WATCHDOG_TIMEOUT（維持 120 秒）
- 不新增 HTTP auth_test probe 或失敗計數器（保持最小侵入）
- `SocketModeHandler.connect()` 為 non-blocking，slack-bolt SDK 預期的呼叫方式
