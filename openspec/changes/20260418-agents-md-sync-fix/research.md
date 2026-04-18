# Research: AGENTS.md / CLAUDE.md Post-Mutation Regeneration Gap

## 調研背景

OpenTree 同時維護兩份給不同 CLI runtime 使用的 prompt 載體：

- `AGENTS.md` 給 Codex CLI 使用
- `CLAUDE.md` 給 Claude CLI 使用

兩者承載的內容本質相同，但 marker 格式不同。`generate_agents_md()` 目前只在 `opentree init`
期間呼叫；後來加入的共用 helper `_regenerate_claude_md()` 負責 module mutation 後的重新生成，
但當時只納入 `CLAUDE.md`，沒有把 `AGENTS.md` 併入同一條更新路徑。

## 候選方案

| 方案 | 說明 | 結論 | 未採用原因 |
|------|------|------|------------|
| A | 新增獨立 `_regenerate_agents_md()` helper，並在 4 個 command site 各自呼叫 | ❌ | 重複邏輯過多，兩個 function 會做幾乎相同的 regeneration orchestration |
| B | 擴充 `_regenerate_claude_md()`，讓它同時處理 `AGENTS.md` | ✅ | 單一 helper、單一呼叫路徑變更，且與既有 `CLAUDE.md` preservation flow 對稱 |
| C | 只在 `refresh` 加入 `AGENTS.md` regeneration | ❌ | 行為不一致，`install/update/remove` 仍會留下過時狀態 |

## 最終選擇

採用方案 B。

理由：
- 單一 helper 擴充，4 個呼叫點自動受益
- 與 CLAUDE.md 的 owner-content preservation pattern 完全對稱
- 最小改動（1 個 import + ~15 行），副作用為零
