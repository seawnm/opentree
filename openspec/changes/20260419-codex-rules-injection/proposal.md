# Proposal: Codex-First Rules Injection

**日期**：2026-04-19
**提案者**：walter（COGI bug fix 期間發現）

## 問題背景

COGI bot 已遷移到 Codex CLI，但 OpenTree 的模組規則系統存在架構性盲點：

1. **靜態 rules/*.md 對 Codex 無效**：
   - `modules/*/rules/*.md` 只透過 `.claude/rules/` 符號連結注入 Claude CLI
   - Codex CLI 不讀取 `.claude/rules/`，只讀取 `workspace/AGENTS.md`
   - AGENTS.md 的內容由 `_write_agents_md()` 在每次呼叫前動態寫入
   - 動態內容來源：`assemble_system_prompt()` → `collect_module_prompts()` → 各模組 `prompt_hook.py`

2. **只有 prompt_hook.py 的規則能到達 Codex**：
   - `personality/prompt_hook.py` → AGENTS.md ✅
   - `slack/prompt_hook.py` → AGENTS.md ✅
   - `memory/prompt_hook.py` → AGENTS.md ✅
   - `requirement/prompt_hook.py` → AGENTS.md ✅
   - `scheduler/rules/*.md` → `.claude/rules/` 只 → **Codex 看不到** ❌
   - `core/rules/*.md` → `.claude/rules/` 只 → **Codex 看不到** ❌

3. **COGI bug fix 期間的錯誤**：
   - BUG-04/05/07/08 最初只修改了 static rules/*.md，無效
   - 後來移到 `personality/prompt_hook.py` 才生效
   - BUG-06（scheduler 工具路徑排錯）只在 `schedule-tool.md` 裡，Codex 從未讀到

## 變更範圍

### 本次修復（2026-04-19）

1. 新增 `scheduler/prompt_hook.py` — 注入 BUG-06 規則：
   - 工具路徑失敗時的處理順序（不可第一步失敗就放棄）
   - `--workspace default` 禁止規則
   - 鏈式任務中間結果路徑慣例

2. 更新 `scheduler/opentree.json` — 從 `"prompt_hook": null` 改為 `"prompt_hook": "prompt_hook.py"`

3. 清理 `bot_COGI/workspace/AGENTS.md` 的 owner section — 移除錯誤的 CLAUDE.md 舊內容（「.claude/rules/ 自動載入」說明）

### 架構層面回答的三個使用者問題

**Q1: 為何之前總是提到 CLAUDE.md？**
- OpenTree 原設計以 Claude CLI 為主，CLAUDE.md 是文件中心概念
- 建議：在 `generate_agents_md()` 中加入 Codex 模式標記，讓未來 AI 一眼識別 bot 型別

**Q2: 是否移除 Claude CLI 支援？**
- 評估見 research.md

**Q3: 規則實際上修改了 AGENTS.md 嗎？**
- 部分生效（透過 prompt_hook.py），部分無效（純 rules/*.md）
- 本次 BUG-06 補充 scheduler prompt_hook 後，所有 8 個 bug 的修復都已透過正確路徑注入

## 影響分析

- `scheduler/prompt_hook.py` 新增：低風險，只注入文字說明
- `scheduler/opentree.json` 更新：觸發模組重裝時重新載入 prompt_hook
- AGENTS.md owner section 清理：低風險，移除錯誤說明，AUTO section 由 runtime 每次重寫
