# Research: Slack Task Visibility Parity with DOGI

**Date:** 2026-04-20

## 研究目標

本研究要回答兩件事：

1. `OpenTree` 若要把 Slack 任務歷程顯示細度提升到和 DOGI（`slack-bot`）一致，缺的是哪些資料來源與結構
2. 哪些不確定點可以先用實測縮小，再回寫到 proposal

## 現況分析

### DOGI 的顯示資料流

DOGI 的 Slack 顯示不是只靠一條主 stream。

它同時使用兩層資料來源：

1. 主 stream
   - phase
   - tool events
   - thinking
   - compaction
   - assistant text decision cue
2. session JSONL side-channel
   - subagent live entries
   - subagent completion summary
   - thinking excerpt

因此 DOGI 才能做到：

- live progress 有 timeline、work phase、decision、subagent insertion
- completion summary 有 task 明細、thinking excerpt、compaction、工具聚合

### OpenTree 的顯示資料流

`OpenTree` 目前主要只有：

`Codex stdout -> codex_stream_parser -> dispatcher callback -> ToolTracker -> ProgressReporter`

這意味著：

- 任何 parser 沒抽出的欄位，後面全部看不到
- tracker 沒有 side-channel 輔助
- completion summary 只能依賴本地工具紀錄

## 已完成的實測

### 1. 跑現有測試

實際執行：

```bash
pytest -q /mnt/e/develop/mydev/opentree/tests/test_codex_stream_parser.py \
  /mnt/e/develop/mydev/opentree/tests/test_progress.py \
  /mnt/e/develop/mydev/opentree/tests/test_tool_tracker.py
```

結果：

- `96 passed in 3.69s`

結論：

- 目前 parser/progress/tracker 的既有行為是穩定的
- 任何 parity 改動都應保留這批測試的核心行為，再增補新案例

### 2. 合成事件餵 `codex_stream_parser`

實際執行：

```bash
PYTHONPATH=/mnt/e/develop/mydev/opentree/src python - <<'PY'
import json
from opentree.runner.codex_stream_parser import StreamParser
samples = [
    {"type":"item.started","item":{"type":"web_search","query":"latest slack api docs"}},
    {"type":"item.started","item":{"type":"collab_tool_call","description":"research parser gap"}},
    {"type":"item.started","item":{"type":"mcp_tool_call","server":"github","name":"search","arguments":{"query":"tool tracker"}}},
    {"type":"item.started","item":{"type":"command_execution","command":"rg foo src/"}},
]
for sample in samples:
    p = StreamParser()
    p.parse_line(json.dumps(sample))
    print({
        "item_type": sample["item"]["type"],
        "tool_name": p.state.tool_name,
        "tool_preview": p.state.tool_input_preview,
        "tool_category": p.state.tool_category,
    })
PY
```

結果摘要：

- `web_search` → `tool_category = web`
- `collab_tool_call` → `tool_category = task`
- `mcp_tool_call` → `tool_category = mcp`
- `command_execution` → `tool_category = bash`

結論：

- 目前 parser 的粗分類是穩定的
- 但 `read/edit/search` 不存在於現有 category model

### 3. 真實 `codex exec --json`：讀檔

實際執行：

```bash
codex exec --json -C /mnt/e/develop/mydev/opentree \
  --skip-git-repo-check --full-auto \
  "Read README.md and reply with only the first word of the file."
```

觀察到的關鍵事件：

```json
{"type":"item.started","item":{"type":"command_execution","command":"/bin/bash -lc 'head -n 1 README.md'"}}
{"type":"item.completed","item":{"type":"command_execution","aggregated_output":"# OpenTree\n","exit_code":0}}
```

結論：

- 真實「讀檔」行為在目前 Codex 任務中，可能實際表現成 `command_execution`
- 若要在 Slack 上把這類行為顯示成 `📖 讀取檔案`，必須加一層顯示層 normalization
- 不能假設 raw stream 會天然給你 `read_file` 類事件

### 4. 真實 `codex exec --json`：搜尋程式碼

實際執行：

```bash
codex exec --json -C /mnt/e/develop/mydev/opentree \
  --skip-git-repo-check --full-auto \
  "Search this repository for the string 'class ProgressReporter' and reply with only the matching file path."
```

觀察到的關鍵事件：

```json
{"type":"item.started","item":{"type":"command_execution","command":"/bin/bash -lc 'rg -l \"class ProgressReporter\" .'"}} 
{"type":"item.completed","item":{"type":"command_execution","aggregated_output":"./src/opentree/runner/progress.py\n","exit_code":0}}
```

結論：

- 真實「搜尋程式碼」也可能實際表現成 `command_execution`
- 若要做 DOGI 細度 parity，`search` 不能只靠 `item.type`
- 需要從 shell command 再做 heuristic normalization

### 5. 真實 `codex exec --json`：subagent / task

實際執行：

```bash
codex exec --json -C /mnt/e/develop/mydev/opentree \
  --skip-git-repo-check --full-auto \
  "Use a subagent to inspect README.md and report only the first word of the file."
```

觀察到的關鍵事件：

```json
{"type":"item.started","item":{"type":"collab_tool_call","tool":"spawn_agent","prompt":"Read the repository's README.md ...","status":"in_progress"}}
{"type":"item.completed","item":{"type":"collab_tool_call","tool":"spawn_agent","receiver_thread_ids":["..."],"agents_states":{"...":{"status":"pending_init","message":null}},"status":"completed"}}
{"type":"item.started","item":{"type":"collab_tool_call","tool":"wait","receiver_thread_ids":["..."],"status":"in_progress"}}
{"type":"item.completed","item":{"type":"collab_tool_call","tool":"wait","receiver_thread_ids":["..."],"agents_states":{"...":{"status":"completed","message":"#"}},"status":"completed"}}
```

結論：

- 真實 raw stream 的確有 `collab_tool_call`
- 也的確帶有 `receiver_thread_ids`、`agents_states.status`、`agents_states.message`
- 但在父執行緒 stream 中，我沒有看到 subagent 內部的讀檔/搜尋/修改事件
- 這表示：
  - 最低限度的 task 狀態顯示可直接從 raw stream 擷取
  - DOGI 等級的 subagent 內部明細，多半仍需要 side-channel

## 已證實的事

### A. `OpenTree` 目前能穩定做到的分類

- `bash`
- `web`
- `task`
- `mcp`

這些都能直接從現有 parser 穩定得到。

### B. `OpenTree` 目前做不到的細分類

- `read`
- `edit`
- `search`

原因不是單純沒顯示，而是：

- parser 沒有這些 category
- tracker 沒有這些聚合規則
- 真實 raw stream 中，這些行為有時本來就只會表現成 `command_execution`

### C. subagent parity 的真實限制

已證實目前父 stream 可以拿到：

- spawn/wait 類型
- receiver thread id
- agents state status
- 最後 message

但尚未證實目前父 stream 能拿到：

- subagent 內部逐步工具事件
- nested child timeline
- child thinking / compaction

因此完整 DOGI parity 不應假設「只改 parser 就能拿到 subagent 內部明細」。

## 2026-04-20 實作後驗證

### 6. 真實 Slack smoke：`bot_walter` 細分類顯示

完成第一、二輪修改後，直接在 ai-room 對 `bot_walter` 做人工 smoke。

驗證方法：

1. 前台啟動 `bot_walter/.venv/bin/opentree start --mode slack --home ...`
2. 用 DOGI `message_tool` 發送真實 Slack 訊息
3. 用 `slack_sdk.WebClient.conversations_replies()` 直接讀 thread raw blocks

實際觀察：

- `status` 指令可正常回覆
- 讀檔 + 搜尋任務的 live progress 會顯示 `🔍 搜尋內容中`
- completion summary 實際出現：
  - `:mag:` 對應搜尋類項目
  - `:book:` 對應讀取類項目
- edit-only 任務的 live progress 會顯示 `✏️ 編輯內容中`
- completion summary 實際出現：
  - `:pencil2:` 對應編輯類項目

結論：

- `read/search/edit` 細分類已不只停留在單元測試層
- 在真實 Slack thread 中，`bot_walter` 已可將這些類別渲染到 progress / completion block

### 8. 真實 ai-room thread：為何沒有顯示網路搜尋關鍵字

針對使用者回報的 ai-room thread，直接用 `slack_sdk.WebClient.conversations_replies()` 讀取 raw blocks。

實際看到的 completion block 為：

```text
✅ 處理完成
🧠 思考 21 秒 + 思考 19 秒
🌐 搜尋網路 8 次
```

當下沒有 query，證明問題不是 Slack render 掉，而是 `OpenTree` 在 completion summary 階段沒有拿到可用的 query preview。

### 9. 真實 `codex exec --json`：web_search query 出現在 completed 事件

實際執行：

```bash
codex exec --json -C /mnt/e/develop/mydev/opentree \
  --skip-git-repo-check --full-auto \
  "Search the web for today's IMF global growth forecast headline and reply with only the title."
```

觀察到的關鍵差異：

```json
{"type":"item.started","item":{"type":"web_search","query":"","action":{"type":"search","query":""}}}
{"type":"item.completed","item":{"type":"web_search","query":"site:imf.org April 21 2026 IMF global growth forecast headline","action":{"query":"site:imf.org April 21 2026 IMF global growth forecast headline","queries":["site:imf.org April 21 2026 IMF global growth forecast headline","IMF World Economic Outlook April 2026 growth headline"]}}}
```

結論：

- `item.started` 可能是空 query
- 真正有價值的 query 常在 `item.completed.action.query` 或 `item.completed.action.queries[]`
- 若 dispatcher 只保留 started preview，completion summary 就會退化成 `搜尋網路 N 次`

### 10. 2026-04-21 小迭代：web query parity 補強

本輪已完成 3 個直接對應使用者回報的修正：

1. `dispatcher` 在 `tool_completed` 先用完成事件的 preview 回填目前工具，再 `end_tool()`
2. `codex_stream_parser` 的 `web_search` 改為優先讀 `action.query / action.queries[]`
3. `mcp_tool_call` 的分類順序改為先判斷 `web_search / web_fetch / fetch_url`，再判斷 generic `search`

另外補了一個 DOGI 接近度修正：

- grouped `search` timeline 現在會顯示第一個 query，而不是只寫 `搜尋 2 次`

對應 targeted tests：

```bash
pytest -q tests/test_codex_stream_parser.py tests/test_tool_tracker.py tests/test_dispatcher.py \
  -k 'web_search_completed_prefers_action_query_when_started_query_is_empty or mcp_web_search_tool_maps_to_web_category or update_current_tool_replaces_preview_before_end or two_search_commands_grouped or uses_completed_web_query_for_completion_summary'
```

結果：

- `5 passed`

### 11. 2026-04-21 ai-room smoke：`🌐` 與 `🔍` query 顯示

本輪用 ai-room 真實 thread 再做兩個 smoke：

1. web search smoke
   - prompt: `請務必使用 web search 找出 IMF World Economic Outlook April 2026 的官方頁面 URL，最後只回覆 URL，不可憑記憶回答。`
   - thread: `1776726797.651099`
   - completion block 實際出現：
     - `🌐 搜尋 "site:imf.org "World Economic O..."`
   - 最終回覆為官方 IMF URL
2. repo search smoke
   - prompt: `請在目前 repo 搜尋字串 'class ProgressReporter'，最後只回答第一個符合的檔案路徑。`
   - thread: `1776726683.353279`
   - completion block 實際出現：
     - `🔍 \`/usr/bin/bash -lc 'rg -n --no-heading "c...\`, \`/usr/bin/bash -lc 'rg -uu -n --no-headin...\` 等 3 次`

結論：

- 使用者回報的核心缺口 `🌐 只顯示搜尋網路 N 次、沒有 query` 已在真實 ai-room thread 修正
- `🔍` 路徑也能在 completion summary 中保留 query / command preview

### 12. 部署殘留：wrapper / stdin 問題

這輪部署後另觀察到兩個與功能本身分離的營運問題：

1. `scripts/deploy.sh --target bot_walter` 會留下 stale `wrapper.pid` / `bot.pid`
   - deploy script 回報成功，但實際 process 已不存在
   - 這表示 `bot_walter` 的 wrapper 啟動鏈仍不穩定，需另案處理
2. 前台 TTY 啟動 bot 時，Codex CLI 可能報：
   - `Reading additional input from stdin...`
   - 接著以 `No result event received from Codex CLI stream` 結束

因此本輪功能 smoke 的可信樣本採用：

- 實際 `bot_walter` instance
- 非互動式啟動條件
- 直接以 Slack API 讀 thread raw blocks 驗證

### 7. shell wrapper 是真實顯示差異的主要來源

第一次 smoke 仍只出現 `💻`，原因是 Codex 真實送出的 `command_execution` 形式是：

```text
/usr/bin/bash -lc "sed ..."
/usr/bin/bash -lc "rg ..."
/usr/bin/bash -lc "mkdir ..."
```

若直接用整個 command string 做分類，很多關鍵詞會被 shell wrapper 稀釋掉。

修正後做法：

- 先 unwrap `bash -lc '...'` / `bash -lc "..."` 的內層命令
- 再對內層命令做 `read/edit/search` heuristic normalization

結論：

- 這一步是 OpenTree 要達成 DOGI 顯示細度 parity 的必要條件

### 8. `bot_walter` wrapper/watchdog 仍有現場風險

雖然前台直接啟動可正常做 smoke，但 `bot_walter/bin/run.sh` 的 watchdog 在現場仍觀察到 idle heartbeat stale 後將 bot 殺掉的情況。

已確認：

- 前台直接啟動可穩定連上 Slack 並完成 smoke
- `run.sh` 路徑在現場曾出現 `WATCHDOG_TIMEOUT=120s` 後 stale kill

結論：

- 本次 Slack 任務歷程細分類功能已可驗證
- 但 `bot_walter` 的 wrapper/watchdog 健康度仍建議另立 follow-up 處理，不應與本次 visibility parity 混為同一個功能缺陷

## 方案比較

### 方案 A：只改 Slack Block Kit 文案

優點：

- 改動小

缺點：

- 無法補足資料來源缺口
- `read/edit/search` 仍無法穩定顯示
- subagent 明細仍不存在

結論：

- 不採用

### 方案 B：先補 parser 與 tracker，不做 side-channel

優點：

- 能快速提升大部分 timeline 與 completion summary 品質
- 可先達成 `bash/web/task/mcp` → `bash/web/task/mcp/read/edit/search` 的顯示層 parity

缺點：

- 無法達到 DOGI 等級的 subagent live 明細
- thinking excerpt 來源依然薄弱

結論：

- 作為第一階段可採用

### 方案 C：補 parser/tracker，再加 session JSONL side-channel

優點：

- 最接近 DOGI 的完整設計
- 能把 subagent 與 completion summary 補完整

缺點：

- 複雜度較高
- 必須先證實 session 資料源足夠穩定

結論：

- 作為最終方案採用
- 但應分階段落地，不應一次全部重寫

## 決策

採用「兩層資料流 parity」方案：

1. 先補主 stream 的 parser/tracker/normalization
2. 再補 session side-channel，專門解 subagent 與 completion summary 補充資料

### 為什麼不是一次直接追 UI parity

因為真實 raw stream 已證明：

- 讀檔與搜尋很常以 `command_execution` 出現
- subagent 在父 stream 中只有粗粒度 task 狀態

如果先不補資料層，只做 UI，很快會卡在：

- 類別永遠不夠細
- subagent 永遠只能平面顯示

## 回寫到 proposal 的調整

基於實測，proposal 應明確寫入以下修正：

1. `read/edit/search` parity 需要顯示層 normalization，不能假設 raw stream 天然提供
2. `subagent live 明細` 分成兩級：
   - Level 1: task status parity，可從 raw `collab_tool_call` 先做
   - Level 2: nested subagent timeline parity，需要 side-channel
3. `Phase 0` 必須先建立 raw capture fixture，而不是直接改 production code
4. `degraded mode` 必須是正式設計，不是 fallback 備註

## 最終結論

實測後，我的結論比一開始更明確：

- `OpenTree` 做到「大部分 DOGI 顯示細度」是可行的
- 其中 `read/edit/search` 需要 normalization，不是直接讀 parser category
- `subagent 完整內部明細` 目前不能假設從父 stream 直接取得，必須補 side-channel
- 因此最合理的 OpenSpec 應該是：
  - 先把 parser/tracker/progress builder 做成可擴充的 parity 架構
  - 再把 subagent side-channel 作為第二層能力補進去

這樣做，計畫才是可落地、可測試、也不會高估目前 Codex raw stream 能力的。

## 2026-04-21 增補：Level 1 task status parity

這一輪先不碰 session side-channel，只補 parent stream 已可見的 `collab_tool_call` 狀態卡。

已證實：

- parser 可從 `collab_tool_call` 穩定萃取並保留：
  - `description`
  - `agents_states.status`
  - `agents_states.message`
  - `receiver_thread_ids`
- 這些欄位足以支撐 Level 1 顯示：
  - live progress：`inspect README.md（等待中）`
  - completion summary：`inspect README.md（已完成） README 第一個字是 #`

本輪設計決策：

1. parser 持續保留 `_opentree_task` 結構化 metadata
2. dispatcher 直接把 `_opentree_task` 傳進 tracker
3. tracker 以 metadata 為主、preview fallback 為輔
4. 不假裝支援 nested child timeline；該能力仍視為 side-channel 範圍

結論：

- `Level 1 task status parity` 可直接從現有 parent stream 落地
- `Level 2 nested child parity` 仍需 side-channel，不能在這一輪硬做

## 2026-04-21 增補：collab task metadata 回放驗證

針對 ai-room smoke 中仍只看到 `spawn_agent / wait` 的問題，這一輪做了更小的 raw 驗證。

### 實際 `codex exec --json` 回放結果

用真實 `codex exec --json` 跑：

- `Use a subagent to read README.md and reply with only the first character.`

得到的關鍵事件是：

- `item.started collab_tool_call tool=spawn_agent`
- `item.completed collab_tool_call tool=spawn_agent`
- `item.started collab_tool_call tool=wait`
- `item.completed collab_tool_call tool=wait`

但 payload 形狀不是原本測試假設的簡單結構：

- `spawn_agent` 的描述主要在 `prompt`
- `spawn_agent completed` 的 `agents_states` 是 `{thread_id: {...}}` map，不是 list
- `wait completed` 沒有自己的 `prompt`，但 `agents_states[thread_id].message` 帶有子代理最終結果

### 新確認的根因

不是父 stream 缺少 `collab_tool_call`，而是 parser 對 `collab_tool_call` 的 metadata 萃取還不完整：

1. `description` 沒有讀 `prompt`
2. `_pick_collab_state()` 對 `agents_states` map 判斷錯誤，導致：
   - `pending_init` 被錯看成 top-level `completed`
   - `wait completed` 的 child `message` 沒有被抓到
3. `wait` 事件沒有 `prompt`，若不沿用前一個 `receiver_thread_id -> description` 映射，就會退回 generic `wait`

### 本輪設計修正

1. `collab_tool_call.description` 缺省時，改從 `prompt` 取第一句作為 task description
2. parser 對 `agents_states` 同時支援：
   - 直接 state dict
   - list of state dicts
   - `{thread_id: state_dict}` map
3. parser 緩存 `receiver_thread_id -> description`，讓 `wait` 可沿用 `spawn_agent` 的任務描述
4. `pending_init` 正規化為 `建立中`

### 實測後的預期顯示

原本：

- `📋 子任務 spawn_agent（已完成）`
- `📋 子任務 wait（已完成）`

修正後預期至少變成：

- `📋 Read README.md in the current workspace and report back only its first character.（建立中）`
- `📋 Read README.md in the current workspace and report back only its first character.（已完成：#）`

結論：

- 這是一個 parser metadata bug，不是 tracker bug
- 下一輪若 smoke 還有缺口，再看是否需要額外對 `mcp_tool_call` 形式的 task 做第二層補齊

### 2026-04-21 第二輪 smoke 補充

第二次 ai-room smoke 證實：

- `spawn_agent` 已成功顯示為真實子任務 prompt，而不是 generic `spawn_agent`
- 但部分 `wait` 事件仍可能缺少 `receiver_thread_ids`，導致沿用映射失敗，退回 generic `wait`

因此再補一條更小的 fallback：

1. parser 額外記住最近一次非空 task description
2. 當 `tool in {wait, wait_agent}` 且沒有 `receiver_thread_ids` 可對應時，先沿用最近一次 task description

這個 fallback 的目的是補真實 stream 的不完整欄位，而不是改變正常資料流優先順序。
