# Research: Claude Code CLI Permission Modes for Subprocess Use

## 六種 Permission Mode

| Mode | 行為 | 適用場景 |
|------|------|----------|
| `default` | 只有 Read 免確認，其他逐一問 | 互動式開發 |
| `acceptEdits` | 自動接受檔案編輯 | 快速迭代 |
| `plan` | 只讀，不修改 | 探索架構 |
| `auto` | 背景分類器自動判斷（需 Team/Enterprise/API） | 長任務 |
| **`dontAsk`** | **僅允許 `permissions.allow` 中的工具，其餘全拒** | **CI/subprocess** ✅ |
| `bypassPermissions` | 跳過所有檢查（已由 dontAsk 取代） | 容器/VM 隔離 |

官方文檔：
> `dontAsk` mode auto-denies every tool that is not explicitly allowed. This makes the mode
> fully non-interactive for CI pipelines or restricted environments.

## 為何 dontAsk 優於 bypassPermissions

### 問題 1：bypass 讓 settings.json 失效

GitHub Issue #12232：`--allowedTools` 在 `bypassPermissions` 模式下被忽略。
根源：`bypassPermissions` 在 permission 評估 pipeline 的最前段短路，tool-level 的
allow/deny 規則從未被評估。

### 問題 2：bypass 不傳遞給 subagent

GitHub Issue #11934：透過 Task/Agent tool 啟動的 subagent 不繼承 `bypassPermissions`，
在非互動模式下（`--print`）會卡在 permission prompt 上。

`dontAsk` 模式的 allow list 由 settings.json 繼承，subagent 行為一致。

### 問題 3：deny 規則歷史上有 bug

GitHub Issues #6699, #6631, #7246, #27040：`permissions.deny` 被忽略的報告。

最佳實踐：以 `dontAsk` + **allowlist 為主**，deny 作為額外防線。
不能只靠 deny blacklist 做隔離。

## 路徑語法（gitignore 規範）

| Pattern | 意義 | 範例 |
|---------|------|------|
| `//path` | 絕對路徑 | `Read(//tmp/**)` |
| `~/path` | 相對 HOME | `Read(~/.zshrc)` |
| `/path` | 相對專案根目錄 | `Edit(/src/**)` |
| `path` 或 `./path` | 相對 cwd | `Read(*.env)` |
| `$OPENTREE_HOME` | 佔位符（由 SettingsGenerator 展開） | `Read($OPENTREE_HOME/**)` |

注意：`Read` deny 規則只影響 Claude 的內建 Read tool，不影響 Bash 子程序。
若要真正阻止 `cat .env`，需要同時 deny `Bash(cat *)` 或使用 sandbox。

## 選用方案比較

| | 方案 A：dontAsk | 方案 B：bypassPermissions（現況） | 方案 C：dontAsk + Sandbox |
|--|--|--|--|
| settings.json 效果 | ✅ 完全生效 | ❌ 被跳過 | ✅ 完全生效 |
| subagent 相容 | ✅ | ❌ 卡住 | ✅ |
| OS 級別隔離 | ❌ | ❌ | ✅ (bubblewrap) |
| 實作複雜度 | 低 | 最低 | 中 |

**決定：採用方案 A**。Sandbox 可作為未來升級方向（見 openspec/changes/future-sandbox/）。

## 來源

- https://code.claude.com/docs/en/permission-modes
- https://code.claude.com/docs/en/permissions
- https://code.claude.com/docs/en/sandboxing
- https://github.com/anthropics/claude-code/issues/12232
- https://github.com/anthropics/claude-code/issues/11934
- https://github.com/anthropics/claude-code/issues/27040
