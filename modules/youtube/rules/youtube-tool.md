# YouTube 影片資訊庫工具

使用 `alloy youtube` 搜尋、抓取和管理 YouTube 影片資訊（metadata + 字幕）。

資料存放於共享目錄，路徑由環境變數 `YOUTUBE_DATA_DIR` 指定。

## CLI 指令

```bash
# 抓取單一影片
alloy youtube fetch <url> --user-id <user_id> --user-name <user_name>

# 抓取頻道影片
alloy youtube fetch-channel <channel_url> --limit 10 \
  --user-id <user_id> --user-name <user_name>

# 搜尋影片標題、描述、頻道、tags
alloy youtube search "AI investment" --limit 20

# 搜尋字幕內容
alloy youtube search "machine learning" --in-subtitles --limit 20

# 列出影片（支援篩選）
alloy youtube list [--channel <channel_id>] [--tag <tag>] [--after <YYYYMMDD>] [--limit 20]

# 列出追蹤頻道
alloy youtube channels

# 新增追蹤頻道
alloy youtube channels-add <channel_url> --name "頻道名稱"

# 移除追蹤頻道
alloy youtube channels-remove <channel_id>

# 同步所有追蹤頻道
alloy youtube sync --user-id <user_id> --user-name <user_name> [--limit 10]

# 重試失敗的字幕下載
alloy youtube retry-subs [--limit 50]
```

## 子指令參考

| 子指令 | 用途 | 必要參數 | 選用參數 |
|--------|------|----------|----------|
| `fetch` | 抓取單一影片 | url, --user-id, --user-name | --langs |
| `fetch-channel` | 抓取頻道影片 | url, --user-id, --user-name | --limit(10) |
| `search` | 全文搜尋 | query | --in-subtitles, --limit(20) |
| `list` | 列出影片 | (無) | --channel, --tag, --after, --limit(20) |
| `channels` | 列出追蹤頻道 | (無) | -- |
| `channels-add` | 新增追蹤頻道 | url, --name | -- |
| `channels-remove` | 移除追蹤頻道 | channel_id | -- |
| `sync` | 同步所有頻道 | --user-id, --user-name | --limit(10) |
| `retry-subs` | 重試失敗的字幕 | (無) | --limit(50) |

## 字幕狀態說明

| 狀態 | 說明 | 會被 retry？ |
|------|------|-------------|
| `pending` | 初始（metadata 已寫入） | 否 |
| `fetched` | 有字幕 | 否 |
| `none` | 嘗試過但失敗 | 是 |
| `no_subs` | 確認影片無字幕 | 否 |
| `unavailable` | 影片已刪除/私人 | 否 |

所有子指令回傳 JSON（`{"success": true/false, ...}`）。
