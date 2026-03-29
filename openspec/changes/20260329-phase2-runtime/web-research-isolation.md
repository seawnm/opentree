# Web Research: CLAUDE_CONFIG_DIR Isolation
Date: 2026-03-29
Keywords: ["CLAUDE_CONFIG_DIR", "Claude Code", "multi-user isolation", "multi-instance", "environment variables", "settings.json"]

## Source 1: Claude Code Environment Variables (Official Docs)
- URL: https://code.claude.com/docs/en/env-vars
- Relevance: HIGH
### Key Excerpts
> `CLAUDE_CONFIG_DIR` — Customize where Claude Code stores its configuration and data files.
### Takeaways
- 官方確認 `CLAUDE_CONFIG_DIR` 存在且可用
- 文檔描述非常簡短，只有一行
- 沒有詳細說明哪些東西會被重定向、哪些不會

## Source 2: Claude Code Settings — Scope System (Official Docs)
- URL: https://code.claude.com/docs/en/settings
- Relevance: HIGH
### Key Excerpts
> User settings are defined in `~/.claude/settings.json` and apply to all projects.
> Project settings are saved in `.claude/settings.json` (shared) and `.claude/settings.local.json` (personal).
> When the same setting is configured in multiple scopes, more specific scopes take precedence: Managed > CLI args > Local > Project > User.
### Takeaways
- User scope 的設定在 `~/.claude/`，這是 `CLAUDE_CONFIG_DIR` 可以重定向的
- Project scope 的設定在工作目錄的 `.claude/`，這**不受** `CLAUDE_CONFIG_DIR` 影響
- Local scope 的 `.claude/settings.local.json` 也在工作目錄，不受影響

## Source 3: GitHub Issue #25762 — CLAUDE_CONFIG_DIR Feature Request
- URL: https://github.com/anthropics/claude-code/issues/25762
- Relevance: HIGH
### Key Excerpts
> `CLAUDE_CONFIG_DIR` already exists and works.
> A CLI tool called "cloak" manages multiple profiles using this environment variable.
> Multiple duplicate/related issues filed (#27477, #28808, #30633, #33131, #33430, #33857).
> The feature may not be officially documented. Users continue to request it, unaware it already exists.
> `~/.claude.json` configurability is still missing.
### Takeaways
- 功能已存在但文檔不完善
- 社群已有工具（cloak）利用此功能管理多帳號
- `~/.claude.json`（OAuth session、MCP configs、per-project state）的位置可能**不受** CLAUDE_CONFIG_DIR 控制
- 20+ thumbs up 顯示高需求

## Source 4: GitHub Issue #3833 — CLAUDE_CONFIG_DIR Behavior Issues
- URL: https://github.com/anthropics/claude-code/issues/3833
- Relevance: HIGH
### Key Excerpts
> Files redirected by CLAUDE_CONFIG_DIR: `.claude.json`, `.claude.json.backup`, `.credentials.json`, `projects/`, `shell-snapshots/`, `statsig/`, `todos/`, `settings.json`
> Files NOT redirected: project-local `.claude/settings.local.json`, IDE-specific `.claude/ide` folder
> Issue closed as "NOT_PLANNED" on December 26, 2025
> Community proposed renaming to CLAUDE_STATE_DIR to better reflect actual function (runtime state, not config)
> IDE integration doesn't respect CLAUDE_CONFIG_DIR (issue #4739)
### Takeaways
- **被重定向的**：`.claude.json`、`.credentials.json`、`projects/`、`settings.json`、`shell-snapshots/`、`statsig/`、`todos/`
- **不被重定向的**：project-local `.claude/`、IDE 整合檔案
- 行為在不同版本間有變化（v2.0.42-74+ 行為不同）
- 本質上是「state directory」而非「config directory」
- Anthropic 選擇 NOT_PLANNED 關閉此 issue，顯示他們認為目前行為足夠

## Source 5: GitHub Issue #15334 — Per-Instance Config Directory
- URL: https://github.com/anthropics/claude-code/issues/15334
- Relevance: MEDIUM
### Key Excerpts
> Running multiple Claude Code instances in parallel causes crashes due to lock file contention on shared ~/.claude/ directory.
> The `~/.claude` directory contains `history.jsonl`, `history.jsonl.lock`, `settings.json`, `.credentials.json`, and `projects/`.
### Takeaways
- 多實例並行時會因 lock file 衝突而 crash
- `CLAUDE_CONFIG_DIR` 可以解決此問題（每個實例用不同目錄）
- 這正是 OpenTree bot 多用戶場景需要解決的問題

## Source 6: Multiple Claude Code Accounts Setup Guide
- URL: https://medium.com/@buwanekasumanasekara/setting-up-multiple-claude-code-accounts-on-your-local-machine-f8769a36d1b1
- Relevance: MEDIUM
### Key Excerpts
> The CLAUDE_CONFIG_DIR environment variable tells Claude where to store its config, keeping accounts completely separate.
> Create shell aliases: `alias claude-work='CLAUDE_CONFIG_DIR=~/.claude-work claude'`
### Takeaways
- 實際可用的多帳號隔離方案
- 透過 shell alias 或環境變數設定即可

## Source 7: Claude Squad — Multi-Agent Management
- URL: https://github.com/smtg-ai/claude-squad
- Relevance: LOW
### Key Excerpts
> Claude Squad uses tmux to create isolated terminal sessions for each agent and git worktrees to isolate codebases.
### Takeaways
- 另一種隔離策略：tmux + git worktree
- 適合開發場景，但對 bot 多用戶場景不太適用

## Summary

`CLAUDE_CONFIG_DIR` 的現狀和 OpenTree 的啟示：

### 功能現狀

| 項目 | 狀態 |
|------|------|
| 環境變數存在 | YES（官方文件有列出） |
| 官方詳細文檔 | NO（僅一行描述） |
| 重定向 settings.json | YES |
| 重定向 credentials | YES |
| 重定向 projects/ | YES |
| 重定向 project-local .claude/ | NO（by design） |
| 重定向 ~/.claude.json | 版本相依（v2.0.42-74+ 有變化） |
| 多實例安全 | YES（解決 lock file 衝突） |

### 對 OpenTree Phase 2 的影響

1. **可行性確認**：`CLAUDE_CONFIG_DIR` 可以用來隔離多用戶的 Claude Code 實例
2. **限制**：project-local `.claude/` 目錄不受影響，這是 by design（project 設定應該跟著專案走）
3. **風險**：行為在版本間有變化，需要在目標版本上實測
4. **建議**：
   - OpenTree 的 `install` 命令可以設定 `CLAUDE_CONFIG_DIR` 指向用戶專屬目錄
   - 但 **不應依賴** `CLAUDE_CONFIG_DIR` 來管理 project-level rules — 那些應該用 symlink/copy 放在 `.claude/rules/`
   - User-level settings（`settings.json`）和 rules（`~/.claude/rules/`）才是 `CLAUDE_CONFIG_DIR` 能控制的
5. **OpenTree 的分層策略**：
   - User-level rules → 透過 `CLAUDE_CONFIG_DIR` 指向共享 rules 目錄
   - Project-level rules → 透過 symlink/copy 放在 `.claude/rules/`
   - 兩者互補，不衝突
