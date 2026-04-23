# Research: Silent Failure Fix

**Date:** 2026-04-21

## 事件記錄

### 時序

```
2026-04-21 07:02 UTC  Thread 1：使用者觸發任務
2026-04-21 07:02 UTC  Codex CLI spawn（pid=XXXX）
2026-04-21 07:02 UTC  Codex CLI exit_code=1（無 turn.completed 事件）
2026-04-21 07:02 UTC  OpenTree：WARNING has_result_event=False（僅記錄，未標記 is_error）
2026-04-21 07:02 UTC  progress.py complete()：response_text="" → 靜默返回
2026-04-21 07:02 UTC  使用者收到「✅ 處理完成」，無任何回覆內容

2026-04-21 07:04 UTC  Thread 2：同一問題重演
```

### Log 證據

```
WARNING codex_process: Codex exited without turn.completed event
WARNING codex_process: Codex exited with non-zero exit code: 1
```

兩個 WARNING 僅寫入 log，pipeline 繼續以 `is_error=False` 執行。

## Pipeline 追蹤

問題沿著以下路徑傳播：

```
codex_stream_parser.py
  → 解析 Codex JSONL 輸出
  → 未收到 turn.completed → has_result_event = False

codex_process.py
  → exit_code = 1
  → 兩個條件均僅記錄 WARNING
  → 回傳 ClaudeResult(is_error=False, response_text="")  ← 錯誤在此產生

dispatcher.py
  → 收到 is_error=False 的結果
  → circuit breaker 計為成功

progress.py
  → complete(response_text="", is_error=False)
  → response_text 為空 → 靜默 return  ← 使用者看不到任何回覆
```

## Codex CLI stdin 行為調查

Log 中出現 `Reading additional input from stdin...` 訊息。

**結論**：此訊息在成功和失敗執行中均會出現，是 Codex 的正常行為（等待可能的 stdin 輸入），
不是失敗的原因。`stdin=subprocess.DEVNULL` 已設定，不影響此行為。

## 預先存在的 Bug：mark_failed() 回傳值

**發現時機**：調查靜默失敗時，發現 `dispatcher.py` 的 timeout 和 error 路徑有以下模式：

```python
# 錯誤寫法（兩個路徑均如此）
self._task_queue.mark_failed(task)      # 回傳值被丟棄
self._spawn_promoted(None)              # 傳入 None，promoted tasks 未被接手
```

**影響**：當某個任務失敗後，佇列中的 promoted task 雖然標記為 RUNNING，但沒有
worker thread 接手，最長會卡 30 分鐘（直到下次 queue watchdog 掃描）。

**正確寫法**：
```python
promoted = self._task_queue.mark_failed(task)
self._spawn_promoted(promoted)
```

## 候選方案比較

### 方案 A：在 codex_process.py 設定 is_error（採用）

**做法**：`has_result_event=False` 或 `exit_code!=0` 時，設 `is_error=True` 並附上
描述性錯誤訊息。

優點：
- 在源頭修復，所有下游邏輯（dispatcher circuit breaker、progress.py 錯誤路徑）自動正確
- 不需修改 dispatcher 或 progress 的主邏輯
- 單一修復點，容易測試

缺點：
- 需確認 `ClaudeResult` dataclass 支援自訂 `message` 欄位

採用原因：根本修復，下游邏輯不需感知這個特殊條件。

### 方案 B：在 progress.py 攔截空回應（部分採用，作為 defense-in-depth）

**做法**：`complete()` 收到空 `response_text` 且 `is_error=False` 時，發送 fallback 警告。

優點：
- 不依賴 codex_process 的判斷，單獨也能保護使用者體驗

缺點：
- 僅是 UX 補丁；circuit breaker 仍計為成功（需搭配方案 C）
- 不能區分「正常空回覆」和「錯誤空回覆」（但後者在正常流程中不應發生）

採用為 defense-in-depth：即使未來 pipeline 有其他回歸導致空回應，使用者仍有警告。

### 方案 C：在 dispatcher.py 防禦（部分採用，作為 defense-in-depth）

**做法**：空 `response_text` 且 `is_error=False` 時，circuit breaker 計為 failure。

優點：
- 防止靜默失敗連續累積被計為健康，保護 circuit breaker 的準確性

缺點：
- 比方案 A 更晚介入，不能產生使用者可見的錯誤訊息

採用為 defense-in-depth：方案 A 若失效，方案 C 仍能讓 circuit breaker 正確計數。

## 決策：三層 Layered Defense

所有三個方案均實施，互不依賴：

```
Layer 1 (codex_process.py)：正確標記 is_error，根本修復
Layer 2 (progress.py)：空回應發 fallback 警告，保護使用者體驗
Layer 3 (dispatcher.py)：空回應計為 failure，保護 circuit breaker 準確性
```

同時修復預先存在的 `mark_failed()` 回傳值 bug（timeout 和 error 兩個路徑）。

## Observability 改善

調查過程發現現有 log 不足以快速定位問題（需要手動追蹤多個 WARNING）。

新增兩類結構化 log：

**codex_process.py — Spawn log（INFO）**：
```json
{"event": "codex_spawn", "cmd": "...", "cwd": "...", "sandboxed": true,
 "session_id": "...", "message_len": 1234}
```

**codex_process.py — Completion log（INFO）**：
```json
{"event": "codex_complete", "pid": 12345, "exit_code": 1, "elapsed": 3.2,
 "has_result_event": false, "response_len": 0, "is_error": true,
 "session_id": "...", "input_tokens": 800, "output_tokens": 0, "timed_out": false}
```

**dispatcher.py — Task result summary（INFO）**：
任務結果進入 circuit breaker 前記錄摘要，讓 circuit breaker 決策可追溯。
