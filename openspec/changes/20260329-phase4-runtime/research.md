# Research: CLAUDE_CONFIG_DIR Isolation

## 調研背景

OpenTree 需要支援多使用者在同台機器同時運行獨立 bot 實例。核心問題是 `~/.claude/` 全域狀態共用（settings.json、credentials、MEMORY.md），會導致多實例互相干擾。需要找到可靠的隔離機制。

## 候選方案

| 方案 | 評估結果 | 未採用原因 |
|------|----------|------------|
| A: CLAUDE_CONFIG_DIR only | user-level 隔離 OK | project-level 需另外處理 |
| B: 不同 OS user | 完整隔離 | 運維成本高，每個 bot 實例需獨立 OS 帳號 |
| C: Docker 容器 | 完整隔離 | 太重，WSL2 環境下額外開銷大 |
| D: CLAUDE_CONFIG_DIR + 分離 workspace | 雙層隔離 | -- |

**採用方案 D**：CLAUDE_CONFIG_DIR 處理 user-level 隔離，workspace 目錄分離處理 project-level 隔離。

## 確認的行為（from web research）

### CLAUDE_CONFIG_DIR 重定向的範圍

| 項目 | 是否跟隨 CLAUDE_CONFIG_DIR | 說明 |
|------|---------------------------|------|
| .claude.json | 是 | 全域設定 |
| .credentials.json | 是 | 認證資訊 |
| projects/ | 是 | 專案 session 紀錄 |
| settings.json | 是 | 使用者設定（allowedTools 等） |
| MEMORY.md | 是 | 自動記憶 |

### 不受 CLAUDE_CONFIG_DIR 影響

| 項目 | 說明 |
|------|------|
| project-level .claude/ | 跟隨 cwd，不受環境變數影響 |
| .claude/rules/ | 專案目錄下，由 cwd 決定 |
| .claude/settings.json (project) | 專案目錄下 |

### Web Research 來源

5 篇 web research 報告（存放於 `openspec/changes/20260329-phase2-runtime/`）：
- `web-research-claude-code.md` — Claude Code 架構與載入機制
- `web-research-isolation.md` — 多實例隔離方案比較
- `web-research-settings-merge.md` — settings.json 合併策略
- `web-research-symlink.md` — WSL2 symlink 行為驗證
- `web-research-typer.md` — CLI 框架選型（Typer vs Click）

## 待驗證

- `~/.claude/rules/` 是否跟隨 CLAUDE_CONFIG_DIR？（全域 rules 目錄）
- 驗證腳本已建立：`tests/isolation/verify_config_dir.sh`
- 需要在有 Claude CLI 的實機上手動執行

## 調研結論

採用方案 D（CLAUDE_CONFIG_DIR + 分離 workspace）。wrapper 啟動時設定 `CLAUDE_CONFIG_DIR=$OPENTREE_HOME/.claude-state`，每個 bot 實例擁有獨立的認證、session、設定。project-level 隔離由 workspace 目錄結構保證。驗證腳本已就緒，待實機執行確認。
