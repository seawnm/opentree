# Web Research: Claude Code CLAUDE.md and rules/ Loading Behavior
Date: 2026-03-29
Keywords: ["Claude Code", "CLAUDE.md", "rules directory", "context window", "conditional loading", "path-scoped rules"]

## Source 1: Best Practices for Claude Code (Official Docs)
- URL: https://code.claude.com/docs/en/best-practices
- Relevance: HIGH
### Key Excerpts
> CLAUDE.md is a special file that Claude reads at the start of every conversation. Include Bash commands, code style, and workflow rules. This gives Claude persistent context it can't infer from code alone.
> There's no required format for CLAUDE.md files, but keep it short and human-readable.
> For each line, ask: "Would removing this cause Claude to make mistakes?" If not, cut it. Bloated CLAUDE.md files cause Claude to ignore your actual instructions!
> CLAUDE.md is loaded every session, so only include things that apply broadly. For domain knowledge or workflows that are only relevant sometimes, use skills instead.
> CLAUDE.md files can import additional files using `@path/to/import` syntax.
### Takeaways
- CLAUDE.md 是永遠載入的，所以必須精簡
- 使用 `@path/to/import` 語法可以引用其他檔案
- Skills（`.claude/skills/`）是 on-demand 載入的替代方案，不會膨脹每次對話
- 可以放在多個位置：`~/.claude/CLAUDE.md`（全域）、`./CLAUDE.md`（專案）、parent/child 目錄
- Child directory 的 CLAUDE.md 是 on-demand 載入（Claude 在該目錄工作時才拉入）

## Source 2: Claude Code Rules Directory Guide
- URL: https://claudefa.st/blog/guide/mechanics/rules-directory
- Relevance: HIGH
### Key Excerpts
> Every `.md` file in `.claude/rules/` automatically becomes part of your project context. No configuration needed.
> Rules files load with the same high priority as CLAUDE.md.
> User-level rules (`~/.claude/rules/`) load before project-specific rules, establishing a cascade where project rules override personal defaults.
> Rules support conditional activation through YAML frontmatter with `paths:` field supporting glob patterns.
> The system resolves symlinks and detects circular references gracefully, enabling rule sharing across projects through symbolic links.
### Takeaways
- `.claude/rules/` 下的所有 `.md` 檔案自動載入，不需額外設定
- 支援 path-scoped rules（YAML frontmatter `paths:` 欄位），只在處理符合 glob 的檔案時才啟用
- **支援 symlink**：可以用符號連結跨專案共用 rules，且能偵測循環引用
- User-level rules 先載入，Project rules 後載入可覆蓋
- 支援 brace expansion：`"src/**/*.{ts,tsx}"`
- 子目錄是遞迴探索的，所有深度的 `.md` 檔都會被載入

## Source 3: Claude Code Context Window Management
- URL: https://claudefa.st/blog/guide/mechanics/context-management
- Relevance: HIGH
### Key Excerpts
> Every token in CLAUDE.md is a token you can't use for conversation.
> The critical threshold occurs when your context fills to 80% capacity. At that point, complex multi-file operations should cease.
> The system reserves approximately 33K tokens as a compaction buffer.
> The `/compact` command summarizes conversation history while maintaining session memory.
### Takeaways
- CLAUDE.md 的每個 token 都佔用對話可用空間
- 80% 是效能臨界點
- 33K tokens 保留給 compaction buffer
- `/compact` 可以手動壓縮，也會自動觸發
- 建議：完成主要功能後、研究轉實作前、Claude 開始重複問題時進行 compact

## Source 4: Claude Code Settings (Official Docs) - Scope System
- URL: https://code.claude.com/docs/en/settings
- Relevance: HIGH
### Key Excerpts
> When the same setting is configured in multiple scopes, more specific scopes take precedence: Managed (highest) > Command line > Local > Project > User (lowest).
> Array settings merge across scopes — arrays are concatenated and deduplicated, not replaced.
> For managed-settings, `managed-settings.json` is merged first as the base, then all `*.json` files in the drop-in directory are sorted alphabetically and merged on top. Later files override earlier ones for scalar values; arrays are concatenated and de-duplicated; objects are deep-merged.
### Takeaways
- 設定有 5 層 scope 優先順序：Managed > CLI args > Local > Project > User
- **Array 是合併（concat + dedup）而非取代** — 這對 permission rules 很重要
- Managed settings 支援 drop-in directory（`managed-settings.d/`），用數字前綴控制合併順序
- 標量值後來的覆蓋前面的，陣列 concat + dedup，物件 deep-merge

## Source 5: Context Optimization — 54% Reduction Case Study
- URL: https://gist.github.com/johnlindquist/849b813e76039a908d962b2f0923dc9a
- Relevance: MEDIUM
### Key Excerpts
> Claude Code Context Optimization: 54% reduction in initial tokens while maintaining full tool access.
> Claude only needs to know when to invoke a skill. The skill's SKILL.md file contains the detailed protocol, loaded on-demand.
### Takeaways
- 把詳細指令移到 Skills 可大幅減少初始 context（54% 減少案例）
- CLAUDE.md 只放「觸發條件」，Skills 放「詳細協議」
- 這是 OpenTree 可以採用的關鍵模式

## Source 6: Claude Code CLAUDE.md — Stop Stuffing Everything
- URL: https://medium.com/@richardhightower/claude-code-rules-stop-stuffing-everything-into-one-claude-md-0b3732bca433
- Relevance: MEDIUM
### Key Excerpts
> If your CLAUDE.md is too long, Claude ignores half of it because important rules get lost in the noise.
> Fix: Ruthlessly prune. For each line, ask: "Would removing this cause Claude to make mistakes?" If not, cut it.
### Takeaways
- 過長的 CLAUDE.md 會導致指令被忽略
- 應該積極裁剪，只保留「移除後會導致錯誤」的內容
- 將 domain knowledge 移到 rules/ 或 skills/

## Summary

Claude Code 的 CLAUDE.md 和 rules/ 載入機制已經相當成熟：

1. **CLAUDE.md 載入規則**：
   - `~/.claude/CLAUDE.md`（全域，每次載入）
   - `./CLAUDE.md` 或 `.claude/CLAUDE.md`（專案，每次載入）
   - Parent 目錄 CLAUDE.md（monorepo，自動載入）
   - Child 目錄 CLAUDE.md（on-demand，工作到該目錄時才載入）
   - 支援 `@path/to/import` 引用語法

2. **rules/ 載入規則**：
   - `~/.claude/rules/*.md`（全域，User scope）
   - `.claude/rules/*.md`（專案，Project scope）
   - 遞迴掃描子目錄
   - **支援 path-scoped conditional loading**（YAML frontmatter `paths:` 欄位）
   - **支援 symlink**（可跨專案共用 rules）

3. **Context 最佳化策略**：
   - CLAUDE.md 精簡至 200 行以下
   - 詳細指令移到 Skills（on-demand 載入）
   - 利用 path-scoped rules 減少無關 context
   - Array 設定跨 scope 是合併而非覆蓋

4. **對 OpenTree 的啟示**：
   - 可以利用 symlink 將共用 rules 連結到各專案
   - 利用 path-scoped rules 實現條件載入
   - Settings merge 是 deep-merge + array concat，需要注意合併邏輯
   - `CLAUDE_CONFIG_DIR` 可控制全域設定目錄位置
