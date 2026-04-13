# Proposal: Replace bypassPermissions with dontAsk for Owner Users

## 需求背景

OpenTree 目前的 owner/admin 使用者，在每次 Claude CLI 呼叫時都帶上
`--dangerously-skip-permissions` 旗標，導致 `workspace/.claude/settings.json`
中定義的所有 allow/deny 規則對 owner 完全無效。

實際觀察到的問題：
- Owner 可以讀取 `/`（根目錄）、`/etc`、`~/.ssh` 等系統路徑
- Owner 可以在工作區以外建立檔案（如 `/tmp/test.txt`）
- settings.json 的 deny 規則（如阻擋 `.env`）對 owner 無任何效果
- subagent 透過 Task 工具啟動時不繼承 bypassPermissions，在非互動模式下卡住

## 變更範圍

| 檔案 | 改動 |
|------|------|
| `src/opentree/runner/claude_process.py` | 移除 `owner` 分支，統一用 `--permission-mode dontAsk` |
| `src/opentree/runner/dispatcher.py` | 移除 `permission_mode` 賦值與傳遞 |
| `src/opentree/runner/config.py` | 更新 `admin_users` docstring |
| `modules/core/opentree.json` | `Read/Write/Edit` 加路徑限制 |
| `modules/guardrail/opentree.json` | 補充絕對路徑 `.env` deny 規則 |
| `tests/test_claude_process.py` | 更新 3 個測試（不再預期 bypass flag） |
| `tests/test_settings_coverage.py` | 精確比對改為前綴比對 |
| `tests/test_permission_completeness.py` | 同上，移除過時的設計假設說明 |

## 影響分析

**安全性提升**：
- Owner 存取範圍限制在 `$OPENTREE_HOME/**` + `/tmp/**`
- Write/Edit 限縮到 `$OPENTREE_HOME/workspace/**` + `$OPENTREE_HOME/data/**`
- settings.json deny 規則對所有使用者一視同仁

**行為變化**：
- Owner 無法再 `ls /`、`cat /etc/passwd` 等
- Owner 仍可使用 WebSearch/WebFetch/Playwright MCP
- Owner 仍可執行 `Bash(alloy *)` 等白名單指令（由模組 permissions.allow 控制）

**破壞性變更**：None（API 介面保持相容）
