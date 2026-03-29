# 路徑慣例

所有模組 rules 中使用以下佔位符，由 wrapper 在合併時替換：

| 路徑 | 說明 |
|------|------|
| `{{opentree_home}}` | OpenTree 安裝根目錄（`$OPENTREE_HOME`） |
| `{{opentree_home}}/modules/` | 模組目錄 |
| `{{opentree_home}}/workspace/` | 使用者工作區 |
| `{{opentree_home}}/data/` | 持久化資料 |
| `{{opentree_home}}/config/` | 設定檔 |

CLI 工具一律使用完整路徑：

```bash
uv run --directory {{opentree_home}} python -m <tool_module> <command>
```
