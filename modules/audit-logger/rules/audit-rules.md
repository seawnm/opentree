# 記憶修改審計工具

修改使用者的記憶後，呼叫此工具記錄審計日誌。被修改者下次互動時會自動收到通知。

## CLI 指令

```bash
# 記錄審計條目（修改記憶後必須呼叫）
uv run --directory {{opentree_home}} python -m scripts.tools.memory_audit_tool log \
  --modifier <admin_name> \
  --target <user_name> \
  --summary "修改摘要"

# 查看使用者的審計日誌
uv run --directory {{opentree_home}} python -m scripts.tools.memory_audit_tool list \
  --target <user_name> [--pending-only]

# 標記為已通知（系統自動處理，通常不需手動操作）
uv run --directory {{opentree_home}} python -m scripts.tools.memory_audit_tool mark-notified \
  --target <user_name>
```

## 參數說明

| 參數 | 說明 | 範例 |
|------|------|------|
| modifier | 修改者名稱 | `walter` |
| target | 被修改者名稱 | `th-yang` |
| summary | 修改摘要（一句話） | `新增新聞搜尋來源偏好` |
| target-file | 被修改的檔案（預設 memory.md） | `memory.md` |
| action | 動作類型（預設 modified） | `modified` / `created` / `deleted` |

## 運作機制

1. **記錄**：audit 條目寫入使用者目錄下的 `audit.jsonl`
2. **通知**：被修改者下次互動時，bot 自動在 system prompt 注入變更通知
3. **標記**：通知注入後自動標記為已通知，不重複提醒
