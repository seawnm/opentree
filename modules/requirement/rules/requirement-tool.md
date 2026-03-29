# 需求管理工具（requirement-tool）

使用者提出功能需求時，使用此 CLI 工具記錄和追蹤。

## CLI 指令

```bash
# 列出所有需求
uv run --directory {{opentree_home}} python -m scripts.tools.requirement_tool list

# 篩選（可組合）
uv run --directory {{opentree_home}} python -m scripts.tools.requirement_tool list \
  --status draft --priority must --type team

# 查看單一需求
uv run --directory {{opentree_home}} python -m scripts.tools.requirement_tool get <req_id>

# 建立需求
uv run --directory {{opentree_home}} python -m scripts.tools.requirement_tool create \
  --title "需求標題" \
  --requester <display_name> \
  --requester-id <user_id> \
  --raw-text "使用者原話（不可改寫）" \
  --type personal \
  --priority should \
  --source "Slack #channel-name" \
  --tags "tag1,tag2"

# 更新需求
uv run --directory {{opentree_home}} python -m scripts.tools.requirement_tool update <req_id> \
  --status confirmed

# 搜尋需求
uv run --directory {{opentree_home}} python -m scripts.tools.requirement_tool search "關鍵字"

# 追加討論歷程（含使用者原文保存）
uv run --directory {{opentree_home}} python -m scripts.tools.requirement_tool history <req_id> \
  --entry-type "訪談" \
  --content "訪談內容摘要" \
  --raw-input "使用者的完整原話（一字不改）" \
  --role BA

# 統計概覽
uv run --directory {{opentree_home}} python -m scripts.tools.requirement_tool stats
```

## 參數說明

| 參數 | 說明 | 範例 |
|------|------|------|
| `--title` | 需求標題 | `自動整理會議紀錄` |
| `--requester` | 提出者名稱 | 從 system prompt 取得 |
| `--requester-id` | 提出者 ID | 從 system prompt 取得 |
| `--raw-text` | 使用者原話（**不可改寫**） | 完整原文 |
| `--type` | `team`（影響多人）/ `personal`（個人工具） | `personal` |
| `--priority` | `must` / `should` / `could` / `wont` | `should` |
| `--source` | 來源頻道 | `Slack #general` |
| `--tags` | 標籤（逗號分隔） | `自動化,報告` |
| `--status` | 狀態（用於 update） | `confirmed` |
| `--role` | 記錄角色（用於 history） | `BA` / `SA` |

所有子指令回傳 JSON 格式。
