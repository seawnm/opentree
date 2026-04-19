# 排程工具（schedule-tool）

使用者提到排程（建立、修改、取消、查詢）時，使用以下 CLI 工具操作。**不需要二次確認**，直接根據語義判斷執行。

## Channel ID 自動偵測

`--channel` 參數可以省略，tool 會自動從 workspace.json 讀取 channel_id。也可從 system prompt 的「目前頻道 ID」取得，明確傳入。

## CRUD 指令

```bash
# 列出所有排程
uv run --directory {{opentree_home}} python -m scripts.tools.schedule_tool list

# 查看單一排程
uv run --directory {{opentree_home}} python -m scripts.tools.schedule_tool get <task_id>

# 建立排程 -- 相對時間（推薦，避免時區計算錯誤）
uv run --directory {{opentree_home}} python -m scripts.tools.schedule_tool create \
  --title "時間提醒" \
  --delay 2m46s \
  --task-type reminder \
  --prompt "時間到了" \
  --user <user_id> \
  --workspace <workspace> \
  --thread-ts <thread_ts>

# 建立排程 -- cron 週期
uv run --directory {{opentree_home}} python -m scripts.tools.schedule_tool create \
  --title "每日站會提醒" \
  --trigger-type cron \
  --trigger-value "15 13 * * *" \
  --task-type reminder \
  --prompt "記得參加站會" \
  --user <user_id> \
  --workspace <workspace> \
  --thread-ts <thread_ts>

# 建立排程 -- 絕對時間
uv run --directory {{opentree_home}} python -m scripts.tools.schedule_tool create \
  --title "會議提醒" \
  --trigger-type once \
  --trigger-value "2026-02-20T14:00:00+08:00" \
  --task-type reminder \
  --prompt "準備開會" \
  --user <user_id> \
  --workspace <workspace> \
  --thread-ts <thread_ts>

# 修改排程（只傳要改的欄位）
uv run --directory {{opentree_home}} python -m scripts.tools.schedule_tool update <task_id> \
  --trigger-value "0 9 * * *" \
  --prompt "新的提示文字"

# 刪除排程
uv run --directory {{opentree_home}} python -m scripts.tools.schedule_tool delete <task_id>

# 暫停/恢復
uv run --directory {{opentree_home}} python -m scripts.tools.schedule_tool pause <task_id>
uv run --directory {{opentree_home}} python -m scripts.tools.schedule_tool resume <task_id>

# 查看任務鏈
uv run --directory {{opentree_home}} python -m scripts.tools.schedule_tool chain <task_id>

# 建立鏈式任務（上游完成後自動觸發）
uv run --directory {{opentree_home}} python -m scripts.tools.schedule_tool chain-create \
  --upstream <upstream_task_id> \
  --title "Step 2: 分析" \
  --task-type ai_generate \
  --prompt "讀取上一步結果，整理成報告" \
  --user <user_id> \
  --workspace <workspace> \
  --thread-ts <thread_ts>
```

## 參數說明

| 參數 | 說明 | 範例 |
|------|------|------|
| delay | 相對延遲時間（與 trigger-value 互斥） | `30s` / `1m` / `2m46s` / `1h30m` |
| trigger-type | `cron`（週期）或 `once`（單次），使用 --delay 時可省略 | `cron` |
| trigger-value | cron 5 欄格式或 ISO datetime（與 delay 互斥） | `15 13 * * *` |
| task-type | `reminder` / `ai_generate` / `interactive` / `research` | `reminder` |
| channel | Slack channel ID（可省略，自動偵測） | 從 system prompt 取得 |
| workspace | 工作區名稱 | `beta-room` |
| thread-ts | 回覆目標 thread | `1739012345.123456` |

## 工具執行排錯指引（BUG-06 修正）

### 工具路徑失敗時的處理順序

遇到 `ModuleNotFoundError: No module named 'scripts'` 或類似錯誤時，**不可直接判定工具不存在**：

1. **確認執行方式**：
   - 正確：`uv run --directory {{opentree_home}} python -m scripts.tools.schedule_tool ...`
   - 若上述失敗，嘗試：`{{opentree_home}}/.venv/bin/python -m scripts.tools.schedule_tool ...`
2. **搜尋工具位置**：用 `find {{opentree_home}} -name "schedule_tool.py" 2>/dev/null` 確認檔案存在
3. **再嘗試不同模組路徑**（如 `opentree.tools.schedule_tool`）
4. 若以上都失敗，才告知使用者工具不可用並提供替代方案

### workspace 名稱

`--workspace` 參數必須使用系統 prompt 中「目前頻道工作區」的實際值（如 `ai-room`、`beta-room`），不可使用 `default`。

### 任務鏈中間結果路徑

每個鏈式步驟的 prompt 必須明確指定中間結果路徑：
- Step 1：`"搜尋後儲存到 /tmp/opentree/chains/{chain-name}/step1.md"`
- Step 2：`"先讀取 /tmp/opentree/chains/{chain-name}/step1.md，再整理成報告…"`
