# Proposal: Slack Task Visibility Parity with DOGI

**Date:** 2026-04-20
**Author:** walter
**Status:** in_progress

## 背景

`OpenTree` 目前在 Slack thread 中已具備基本進度更新能力：

- 先發一則 `⏳ 收到！正在處理...` 的進度訊息
- 任務執行中持續更新同一則訊息
- 完成時將進度訊息改成 `✅ 處理完成`
- 再另外發送最終回覆

但相較於 DOGI（`slack-bot`），`OpenTree` 的任務歷程仍明顯偏粗：

- 工具分類只有 `bash/web/task/mcp/other`
- `read/edit/search` 無法穩定區分
- subagent 只顯示平面 task 行，沒有內部明細
- completion summary 缺少 `session_summary` 類補充資料
- thinking / compaction / decision 的資料鏈不完整

因此使用者雖然知道 bot 正在處理任務，仍無法像 DOGI 那樣清楚理解：

- bot 目前主要在做哪一類工作
- 做了哪些高訊號動作
- 哪些子任務已完成、花了多久
- 是否出現重新規劃、深度思考、壓縮上下文等關鍵轉折

## 問題根因

問題不是單一 UI 元件不足，而是 `OpenTree` 缺少與 DOGI 同級的「資料來源層」。

目前 `OpenTree` 的 Slack 顯示主要依賴單一路徑：

`Codex stdout -> codex_stream_parser -> dispatcher callback -> ToolTracker -> ProgressReporter`

這條路徑有 4 個結構性限制：

1. `codex_stream_parser.py` 只輸出粗粒度欄位，無法支撐 `read/edit/search` 細分類
2. `dispatcher.py` 只消費 `last_event/tool_name/tool_input_preview/tool_category/response_text`
3. `ToolTracker` 目前只支援本地簡化摘要，沒有 `session_summary` 或 side-channel 輔助
4. `progress.py` 只渲染平面 timeline + decision，沒有 DOGI 的 subagent 插槽與 completion 聚合規則

DOGI 則同時依賴兩條資料流：

1. 主 stream：phase、tool events、thinking、compaction、decision
2. session JSONL side-channel：subagent live 明細、subagent completion summary、thinking excerpt

若 `OpenTree` 不先補這兩層資料來源，即使複製 Block Kit 文案，也只會做出外觀相似、資訊密度仍不足的半成品。

## 目標

本變更的目標不是「文案接近 DOGI」，而是讓 `OpenTree` 在 Slack thread 中達成與 DOGI 同等級的任務歷程可見性。

具體目標：

1. Live progress card 能顯示更細的 timeline 與穩定的 work phase
2. Completion summary 能聚合高訊號行為，而不只顯示粗粒度計數
3. 能區分 `read/edit/search/web/task/mcp/bash` 類別，至少在顯示層達成穩定分類
4. 能顯示 subagent 相關資訊，至少包含 task 狀態；進階目標是接上內部明細
5. 能顯示 decision cue、thinking excerpt、compaction event
6. 所有新增顯示規則都由可測試的資料模型驅動，而非散落在 dispatcher 或 progress builder 的臨時字串邏輯

## 非目標

本次不做：

- 重新設計整個 Slack bot 對話骨架
- 變更最終回覆內容生成策略
- 大規模改寫 `CodexProcess` 的執行模型
- 引入新的外部服務或資料庫
- 為所有 MCP server 建立永久、完美的工具語義映射

## 變更範圍

### 1. `codex_stream_parser.py`

擴充 parser 與對外 state，讓 progress callback 能取得足夠訊號。

變更方向：

1. 保留現有 phase 流程
2. 新增更完整的 event-normalized 欄位，例如：
   - `tool_raw_type`
   - `tool_server`
   - `tool_arguments`
   - `tool_command`
   - `tool_normalized_category`
   - `task_agent_ids`
   - `task_status_snapshot`
   - `assistant_text_delta`
3. 對 `mcp_tool_call` 與 `command_execution` 增加 normalization hook
4. 明確保留 raw fields，避免 display 層只能吃截斷過的 preview

### 2. 新增顯示事件模型

在 runner 層引入 DOGI 同型的顯示事件概念，區分：

- tool events
- status events
- decision events
- subagent events

建議資料模型至少包含：

- `TimelineEntry`
- `StatusEvent`
- `DecisionPoint`
- `SubagentEntry`

原則：

- tracker 負責累積與壓縮
- builder 負責渲染
- dispatcher 不直接拼接顯示字串

### 3. `tool_tracker.py`

從現行簡化實作升級為 parity-oriented tracker。

必做項目：

1. 新增 `record_status_event()` 類機制，處理 thinking / compaction / response generation
2. 對 `bash` 命令做顯示層 heuristic normalization
   - `head/cat/sed` 類讀檔命令 → `read`
   - `rg/grep/find` 類搜尋命令 → `search`
   - `apply_patch/git diff patch` 類修改命令 → `edit`
3. 對 `mcp_tool_call` 做 server/name-based normalization
   - `filesystem.read_*` → `read`
   - `filesystem.edit_*` / `write_*` → `edit`
   - `search_*` / `grep_*` → `search`
   - 未命中者才保留 `mcp`
4. timeline 支援：
   - same-type grouping ±1s
   - head/tail folding
   - in-progress duration
   - work phase 多數決
5. completion summary 支援：
   - 優先級聚合
   - task 明細展開
   - thinking excerpt
   - compaction

### 4. side-channel：session JSONL 補充資料

新增一條 DOGI 同型的補充資料流，用來取得主 stream 看不到的資訊。

至少要支援兩件事：

1. subagent live 狀態
2. completion summary 的補充資訊

規劃做法：

1. 先實作最小版 raw session reader，確認 `Codex` session JSONL 是否可穩定提供：
   - subagent progress
   - child thread state
   - thinking text
2. 若可行，再補：
   - `session_poller.py`
   - `session_reader.py`
3. 若不可行，退而求其次：
   - live 只顯示平面 task
   - completion summary 從 `agents_states` 或 wait-result 萃取可見資訊

### 5. `progress.py`

把目前簡化版 Block Kit builder 升級成 parity builder。

必做項目：

1. live progress blocks 支援：
   - timeline
   - subagent insertion
   - decision block
   - work phase
2. completion blocks 支援：
   - completion items 多行聚合
   - task/subagent 顯示
   - thinking excerpt
   - compaction
3. 加入 block 上限保護與折衷策略，避免超過 Slack Block Kit 限制

### 6. `dispatcher.py`

調整 `_tracking_callback()`，改為餵標準化事件，而不是直接手動操作簡化版 tracker。

原則：

1. dispatcher 只做接線，不承載顯示規則
2. `response_started` 不應是唯一 decision 偵測點
3. `assistant_text_delta` 若存在，應持續送入 tracker 做 decision 偵測
4. `completion_items` 的生成需能結合 side-channel 補充資料

## 分階段執行計畫

### Phase 0: Raw Feasibility Capture

目標：先用真實 `codex exec --json` 樣本確認可取得哪些訊號。

工作：

1. 建立 raw sample capture 腳本或測試 fixture
2. 至少保留 4 類真實樣本：
   - 純讀檔
   - 純搜尋程式碼
   - MCP 工具
   - Task/subagent
3. 確認 `collab_tool_call` 是否能提供足夠 subagent 狀態
4. 確認 `mcp_tool_call` 的 name/server/arguments 是否足以細分類

完成條件：

- `proposal` 中所有關鍵假設都有對應 raw evidence 或明確 fallback

### Phase 1: Category Parity

目標：先把 `bash/web/task/mcp` 提升到 DOGI 接近的可讀性與細分類。

工作：

1. parser 保留 raw metadata
2. tracker 新增 normalization layer
3. completion summary 新增 `read/edit/search` 聚合規則
4. live timeline 改成細分類顯示

完成條件：

- 在沒有 side-channel 的前提下，使用者已能看到 `read/edit/search/web/task/bash/mcp`

目前狀態（2026-04-20）：

- 已完成 parser raw metadata 保留
- 已完成 `command_execution` / `mcp_tool_call` 的 `read/edit/search` 顯示層 normalization
- 已完成 `ToolTracker` 的 `📖 / ✏️ / 🔍` timeline / work phase / completion summary 顯示
- 已以真實 Slack smoke 驗證 `🔍`、`📖`、`✏️` 會出現在 `bot_walter` 的 completion summary
- 已補 `web_search item.completed` query backfill，避免 `item.started` 空 query 造成 completion summary 只剩 `搜尋網路 N 次`
- 已修正 MCP web search 分類優先順序，`mcp__...web_search...` 不再先被 generic `search` 吃掉
- 已讓 grouped `search` timeline 顯示首個 query，行為更接近 DOGI 的高訊號顯示
- 已完成 `collab_tool_call` 的 Level 1 task status parity 基礎：
  - parser 保留 `_opentree_task`
  - dispatcher 會把 task metadata 傳進 tracker
  - live/completion 可顯示 `等待中 / 已完成 + child message preview`
  - 仍未嘗試 nested child timeline，該部分保留給 side-channel 階段

### Phase 2: Event Parity

目標：補 thinking / compaction / decision 的完整資料鏈。

工作：

1. 新增 status event 記錄
2. 接上 thinking excerpt 資料來源
3. decision 不再只靠 final response text
4. compaction 事件納入 timeline 與 completion summary

完成條件：

- live 與 completion 都能看到 DOGI 同等級的高訊號狀態事件

### Phase 3: Subagent Parity

目標：讓 task 不再只是平面列表，而是能顯示與 DOGI 接近的 subagent 視圖。

工作：

1. 若 session JSONL 可行，導入 poller + reader
2. 若不可行，建立 degraded mode：
   - live 只顯示 task status
   - completion 顯示 task 結果與耗時
3. progress builder 支援 subagent insertion

完成條件：

- 至少有可預期、可測試的 subagent 顯示模式
- 若做不到 DOGI 完整內部明細，需在文件中清楚記錄限制與退化策略

目前狀態（2026-04-21）：

- 已完成 Level 1 subagent/task status parity
- 目前 Slack thread 可辨識 parent-stream 可見的 `spawn/wait/completed` 類狀態
- 已補 `collab_tool_call.prompt -> description`、`agents_states map` 支援、以及 `receiver_thread_id -> description` 沿用，避免 ai-room smoke 退回 generic `spawn_agent / wait`
- 已補 `wait / wait_agent` 在缺少 `receiver_thread_ids` 時沿用最近一次 task description 的 degraded fallback，避免真實 stream 欄位不完整時退回 generic `wait`
- 尚未完成 DOGI 等級的 nested child timeline；這仍依賴 session/side-channel

### Phase 4: Integration Hardening

目標：確保新的顯示資料流可長期維護。

工作：

1. 補 parser / tracker / progress / dispatcher 整合測試
2. 補 raw sample fixture 測試
3. 補 block limit / truncation / overflow 測試
4. 驗證既有 progress UX 不回退

完成條件：

- 重要顯示規則皆有測試保護
- 未來新增工具類別時，不需回頭修改多處分散邏輯

## 驗收標準

### 使用者可見行為

- Slack thread 中仍維持單一進度訊息更新，不改互動骨架
- live progress 至少能穩定顯示：
  - header
  - elapsed
  - work phase
  - timeline
  - decision
- completion progress 至少能顯示：
  - task 明細
  - `read/edit/search/web/bash` 聚合
  - thinking excerpt
  - compaction
- 搜尋程式碼與讀檔不再都只顯示成 `bash`

### 資料流與結構

- parser 對外 state 不再只有粗粒度 `tool_category`
- tracker 有明確的 normalization 層與 status event 層
- side-channel 若採用，必須有獨立測試與 fallback 行為

### 測試

- 現有 `test_codex_stream_parser.py`、`test_progress.py`、`test_tool_tracker.py` 持續通過
- 新增 raw capture fixture 測試
- 新增 dispatcher progress callback integration test
- 新增 subagent 顯示測試

## 限制與假設

- 真實 `Codex` raw JSON 事件可能比目前 parser 看見的更多，也可能沒有 DOGI 同等級的內部訊號
- `read/edit/search` 的一部分可能只能透過顯示層 heuristic 判斷，不能保證 100% 語義準確
- 若 session JSONL 無法穩定提供 subagent 內部明細，本次應交付明確的 degraded mode，而不是硬做脆弱實作
- 本 proposal 的 priority 是「資料流 parity 優先於文案 parity」
