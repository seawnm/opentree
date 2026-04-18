# Proposal: AGENTS.md 同步修復 — module 操作後 Codex CLI bot 收到過時指令

## 需求背景

在 bot_DOGI 部署期間發現：執行 `module refresh` 後，只有 `CLAUDE.md` 會更新，
`AGENTS.md` 仍停留在 `opentree init` 當時的快照。

對 Codex CLI runtime 而言，這代表任何 module 規則變更
（例如 Owner identification fix）都不會反映到實際 system prompt，
使 bot 持續使用過時指令。

## 變更範圍

- 僅修改 `src/opentree/cli/module.py`
  - 擴充 `_regenerate_claude_md()`，在既有 `CLAUDE.md` 重新生成流程後追加 `generate_agents_md()`
  - 新增 1 個 import：`generate_agents_md` from `opentree.generator.claude_md`

## 影響分析

- `module refresh/install/update/remove` 這 4 個會改動 module 狀態的指令，現在都會同步重新生成 `AGENTS.md`
