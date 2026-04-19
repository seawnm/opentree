# Research: Codex-First vs Claude CLI 支援策略

**日期**：2026-04-19

## 問題 1：為何 AI 預設提到 CLAUDE.md 而非 AGENTS.md？

### 根本原因

OpenTree 框架在設計時以 Claude CLI 為主，CLAUDE.md 是核心概念。AI 在讀取
`workspace/CLAUDE.md`（old）、模組說明文件時，所有文件都指向 `CLAUDE.md`，因此 AI 的
working assumption 是 Claude CLI 環境。

### 解決機制

COGI 使用 Codex CLI，bot runner 在 `runner/config.py` 中設定 `runner_type = "codex"`。
但目前沒有任何文件或 system prompt 明確告訴 AI「這個 bot 是 Codex-based」。

**方案 A（採用）**：在 `assemble_system_prompt()` 中加入 runner 型別說明
```
Runner 型別：Codex CLI
規則來源：AGENTS.md（動態寫入，來自 prompt_hook.py 注入）
注意：.claude/rules/ 對本 bot 無效，規則必須透過 prompt_hook.py 注入
```

**方案 B（棄用）**：在 AGENTS.md owner section 加說明 — 易被覆蓋，不穩定

## 問題 2：是否移除 Claude CLI 支援？

### 現狀評估

| 層面 | 現狀 | 移除後 |
|------|------|--------|
| COGI | 已全面使用 Codex CLI | 無影響 |
| 其他 bots | 可能仍用 Claude CLI（如 DOGI CC workspace） | 需確認 |
| 測試 | `tests/` 大量測試針對 ClaudeProcess | 需重寫或保留 |
| 維護成本 | 雙路徑（claude_process.py + codex_process.py）需同步維護 | 簡化 |

### 調研：Codex CLI vs Claude CLI 的核心差異

1. **認證**：Codex 用 `~/.codex/auth.json`（SSO），Claude 用 API key
2. **Session**：Codex 用 `session_id` resume，Claude 用 `--resume session_id`
3. **Rules**：Codex 讀 `AGENTS.md`，Claude 讀 `CLAUDE.md` + `.claude/rules/`
4. **Sandboxing**：Codex 有 `--full-auto` sandbox，Claude 用 bwrap
5. **Output**：兩者都輸出 JSONL stream，但格式略有差異

### 決策

**建議：保留雙路徑，但明確標記 Codex 為主路徑**

原因：
1. OpenTree 是通用框架，其他部署可能選擇 Claude CLI（cost 考量）
2. 移除 Claude CLI 支援是 breaking change，需要跨 bot 協調
3. 維護成本可以透過抽象層（介面統一）降低，而非刪除實作

短期行動：
- `core/prompt.py` 的 `assemble_system_prompt()` 加入 runner 型別說明 → 讓 AI 知道自己在哪個環境
- 新模組開發時，**一律先寫 `prompt_hook.py`**，然後才寫 rules/*.md（可選）

## 問題 3：BUG 修復實際上進了 AGENTS.md 嗎？

### 追蹤結果

| Bug | 修改位置 | Codex 可見？ | 說明 |
|-----|---------|------------|------|
| BUG-01 | dispatcher.py 程式碼 | N/A（runtime 邏輯）| ✅ 已修復 |
| BUG-02 | dispatcher.py 程式碼 | N/A（runtime 邏輯）| ✅ 已修復 |
| BUG-03 | personality/prompt_hook.py | ✅ 進入 AGENTS.md | ✅ 已修復 |
| BUG-04 | personality/prompt_hook.py | ✅ 進入 AGENTS.md | ✅ 已修復 |
| BUG-05 | tone-rules.md（靜態）+ prompt_hook.py | tone-rules.md ❌，prompt_hook ✅ | ✅ 有效 |
| BUG-06 | schedule-tool.md（靜態）only | ❌ **Codex 看不到** | ❌ 本次修復 |
| BUG-07 | design-principles.md（靜態）+ prompt_hook.py | md ❌，prompt_hook ✅ | ✅ 有效 |
| BUG-08 | message-format.md（靜態）+ prompt_hook.py | md ❌，prompt_hook ✅ | ✅ 有效 |

### 結論

BUG-06 是唯一一個**只在靜態 rules/*.md 中修復**而沒有對應 prompt_hook.py 的 bug。
本次新增 `scheduler/prompt_hook.py` 後，所有 8 個 bug 的修復都已正確注入 AGENTS.md。

## 最佳實務調研

Codex CLI（OpenAI Codex）使用 AGENTS.md 的最佳實務：
1. 規則應在 AGENTS.md 中直接列出，而非依賴外部符號連結
2. Runtime injection（prompt_hook）比靜態 AGENTS.md 更靈活（可動態包含使用者資訊）
3. 規則應盡量精簡、可操作（不超過 20-30 行），避免 context window 浪費
4. 使用 `<!-- OPENTREE:AUTO:BEGIN/END -->` 清楚區分自動內容與 owner 自訂內容

參考：Codex CLI 文件 - https://github.com/openai/codex
