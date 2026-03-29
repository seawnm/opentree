# Slack 查詢工具

使用 Bot Token（xoxb-）查詢 Slack 資訊。**所有 Slack 讀取操作應優先使用此工具**，不要使用 MCP Slack 的唯讀工具。

## slack-query-tool CLI

```bash
# 讀取 thread（最常用）
uv run --directory {{opentree_home}} python -m scripts.tools.slack_query_tool read-thread \
  --channel <channel_id> \
  --thread-ts <thread_ts> \
  --limit 100

# 讀取頻道訊息
uv run --directory {{opentree_home}} python -m scripts.tools.slack_query_tool read-channel \
  --channel <channel_id> \
  --limit 20 \
  --oldest <unix_ts> --latest <unix_ts>

# 查詢頻道資訊
uv run --directory {{opentree_home}} python -m scripts.tools.slack_query_tool channel-info \
  --channel <channel_id>

# 列出頻道
uv run --directory {{opentree_home}} python -m scripts.tools.slack_query_tool list-channels \
  --types "public_channel,private_channel" \
  --limit 100

# 查詢使用者資訊
uv run --directory {{opentree_home}} python -m scripts.tools.slack_query_tool user-info \
  --user <user_id>

# 搜尋使用者
uv run --directory {{opentree_home}} python -m scripts.tools.slack_query_tool search-users \
  --query "關鍵字"

# 查詢 workspace 資訊
uv run --directory {{opentree_home}} python -m scripts.tools.slack_query_tool team-info
```

## 子指令參考

| 子指令 | 用途 | 必要參數 | 選用參數 |
|--------|------|----------|----------|
| `read-thread` | 讀取 thread 全部回覆 | `--channel`, `--thread-ts` | `--limit`(預設100), `--profile` |
| `read-channel` | 讀取頻道訊息 | `--channel` | `--limit`(預設20), `--oldest`, `--latest`, `--profile` |
| `channel-info` | 頻道詳細資訊 | `--channel` | `--profile` |
| `list-channels` | 列出頻道清單 | (無) | `--types`, `--limit`(預設100), `--include-archived`, `--profile` |
| `user-info` | 使用者資訊 | `--user` | `--profile` |
| `search-users` | 搜尋使用者 | `--query` | `--profile` |
| `team-info` | workspace 資訊 | (無) | `--profile` |

## alloy slack user — 快速搜尋使用者

```bash
alloy slack user <搜尋關鍵字>
```

- 以 `display_name`、`real_name`、`name` 做 substring 比對
- 回傳 JSON：`{"results": [{"user_id": "U...", "display_name": "...", "real_name": "..."}], "query": "..."}`

## 使用指引

1. **channel 和 thread-ts** 從 system prompt 中的「目前頻道 ID」和「目前 Thread TS」取得
2. **輸出格式**：所有子指令回傳 JSON（`{"success": true, ...}` 或 `{"success": false, "error": "..."}`）
3. **Token 來源**：自動從 `.env` 載入 `SLACK_BOT_TOKEN`
4. **與 MCP Slack 的差異**：使用 Bot Token（xoxb-），無 workspace 限制，可存取所有 bot 已加入的頻道
