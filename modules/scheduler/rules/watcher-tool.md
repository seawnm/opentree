# 監看器工具（watcher-tool）

## CRUD 指令

```bash
# 列出所有 watcher
uv run --directory {{opentree_home}} python -m scripts.tools.watcher_tool list

# 建立 watcher
uv run --directory {{opentree_home}} python -m scripts.tools.watcher_tool create \
  --title "監看某 thread" \
  --channel <channel_id> \
  --thread-ts <thread_ts> \
  --task-type interactive \
  --prompt "有新訊息時摘要" \
  --user <user_id> \
  --workspace <workspace>

# 刪除 watcher
uv run --directory {{opentree_home}} python -m scripts.tools.watcher_tool delete <task_id>

# 檢查 watcher 狀態
uv run --directory {{opentree_home}} python -m scripts.tools.watcher_tool check <channel_id> <thread_ts>
```

## 使用時機

- 使用者想追蹤某個 thread 的後續動態
- 需要在特定事件發生時主動通知使用者
- 所有子指令回傳 JSON 格式
