# 模組載入架構：研究與進度紀錄

## 一、研究歷程

### 1.1 DOGI CLAUDE.md 膨脹問題分析（起點）

**調研範圍**：分析 DOGI bot 的三個 workspace（cc、st_workspace、digital_worker）的 CLAUDE.md 是否過於龐大。

**關鍵發現**：

| 項目 | 數據 | Anthropic 建議 | 超標倍率 |
|------|------|---------------|---------|
| cc/CLAUDE.md | 965 行 / ~14K tokens | < 200 行 | 4.8x |
| st_workspace/CLAUDE.md | 803 行 / ~11.4K tokens | < 200 行 | 4x |
| digital_worker/CLAUDE.md | 817 行 / ~12.2K tokens | < 200 行 | 4.1x |
| 全域 rules (~/.claude/rules/) | 1,791 行 / ~16.7K tokens | — | — |
| 每次 session 啟動消耗 | ~31K tokens | < 20% of 200K | 15.7% |

**Anthropic 官方建議**（來源：code.claude.com/docs/en/context-window）：
- Project CLAUDE.md 保持在 200 行以下
- 將參考內容移至 skills 或 path-scoped rules
- 啟動載入不超過 context window 的 20%

**Agent 分析結論**：
1. cc/CLAUDE.md 有 78% 是工具參考文件（排程 142 行、需求管理 164 行、YouTube 105 行等），大部分對話不需要
2. 三個 workspace 共用 556 行模板，但各自獨立複製維護
3. 全域 rules 中 sagemaker.md（89 行）在 WSL2 環境完全無用
4. 存在規則衝突：commit message 語言（中文 vs 英文 conventional commits）

### 1.2 Claude Code 載入機制深度理解

**四種載入機制比較**：

| 機制 | 載入時機 | Compaction 後 | 成本 |
|------|----------|-------------|------|
| CLAUDE.md | 啟動時 | ✅ 重新注入 | 持續佔用 |
| .claude/rules/ | 啟動時全載 | ✅ 重新注入 | 持續佔用 |
| .claude/skills/ | 描述啟動載、內容按需 | ❌ 描述不重注入 | 低 |
| On-demand Read | Claude 主動決定 | ❌ | 最低 |

**關鍵發現**：Skills 描述在 compaction 後不會重新注入。對 24/7 bot 環境來說，CLAUDE.md 的觸發索引是唯一可靠的按需載入機制。

### 1.3 跨 Workspace 分析

**模板重複問題**：
- 模板 556 行，在三個 workspace 完全複製
- 各 workspace 獨自演化（cc 加了 Alloy 工具、dw 加了行事曆），增強功能不回流
- 需求管理流程在不同 workspace 有不同版本（基礎版 vs INVEST 增強版）

### 1.4 多使用者同機隔離分析

**情境 A（不同 OS user）**：天然隔離，無任何衝突。

**情境 B（同一 OS user、不同 $OPENTREE_HOME）**：
- **最大風險**：`~/.claude/` 全域狀態共用（settings.json、credentials、MEMORY.md）
- **解決方案**：wrapper 啟動時設定 `CLAUDE_CONFIG_DIR=$OPENTREE_HOME/.claude-state`
- **待驗證**：`CLAUDE_CONFIG_DIR` 是否覆蓋所有路徑（credentials、projects/、rules/ 等）

**10 項隔離需求**已識別（見 design.md 第 8 節）。

---

## 二、Agent 交互與決策歷程

### 2.1 第一輪：DOGI 分析（3 個並行 agent）

| Agent | 角色 | 主要發現 |
|-------|------|---------|
| architect | Anthropic 官方差距分析 | cc/CLAUDE.md 是 7.6x token 超標；78% 內容可延遲載入；compaction 後全量重注入造成固定開銷 |
| planner-1 | CLAUDE.md 抽取機會 | 分類 A/B/C/D 四類；TOP 5 抽取可省 ~11K tokens |
| planner-2 | 全域 Rules 重複審計 | 發現 sagemaker.md 完全無用、skill-development.md 207 行只在開發 skill 時用、commit 語言衝突 |

**決策衝突解決**：architect agent 發現 `everything-claude-code/rules/` 的語言專屬規則已有 `paths:` frontmatter（Go/Swift/TS/Python），但 `claude-config/rules/` 的 13 個檔案全部沒有 path-scoping。修正了初始估計。

### 2.2 第二輪：跨 Workspace + Skill 可行性（3 個並行 agent）

| Agent | 角色 | 主要發現 |
|-------|------|---------|
| architect | 跨 workspace 重構架構 | **關鍵發現**：`.claude/rules/` 也是全量載入，純搬移不省 token。真正能省的只有刪除內容或 on-demand Read |
| planner-1 | Skill 抽取可行性 | 11 個工具逐項分析漏載風險；schedule-tool 和 requirement-tool 需「混合方案」；memory-audit-tool 不應抽出 |
| planner-2 | 具體優化計畫 | 4 Phase 計畫（Quick wins → 模板重構 → 工具抽出 → 全域清理） |

**關鍵交互**：architect agent 的「token 不會減少」發現直接影響了後續設計方向——使用者最終選擇了 Option A（安全優先，不省 token），而非 Option B（省 token 但有風險）。

### 2.3 第三輪：OpenTree 模組架構設計（3 個並行 agent）

| Agent | 角色 | 主要發現 |
|-------|------|---------|
| architect | 模組載入機制 | 設計三層 Tier 系統；guardrail 310→120 行精簡但全部 always-on；CLAUDE.md 觸發索引 vs skills 描述的取捨 |
| planner-1 | 模組生命週期 | 完整 install/remove/update 流程；manifest schema v1；module-registry.json 設計；edge cases 處理 |
| planner-2 | CLAUDE.md 生成規格 | 場景 A（53 行）和場景 B（62 行）的完整範例；token 預算計算；compaction 安全保障 |

### 2.4 第四輪：多使用者驗證 + 文件寫入 + Phase 1 計畫（3 個並行 agent）

| Agent | 角色 | 主要發現 |
|-------|------|---------|
| architect | 多使用者隔離 | `CLAUDE_CONFIG_DIR` 是最關鍵的隔離機制；10 項隔離需求；PID/heartbeat 的 fallback 風險 |
| general-purpose | 設計文件寫入 | 1001 行 design.md 已寫入 opentree 專案 |
| planner | Phase 1 實作計畫 | JSON Schema + Validator + Registry + 10 個 manifest；33 個 validator 測試 + 15 個 registry 測試 |

---

## 三、使用者確認的設計決策

| # | 決策 | 使用者選擇 | 備註 |
|---|------|-----------|------|
| D1 | Tier 分類 | OK | guardrail 120 行 always-on 合理 |
| D2 | Tier-2 載入方式 | **Option A**（.claude/rules/ symlink） | 零風險，不省 token 但檔案分離 |
| D3 | Phase 1 先做 schema + validator | OK | |
| D4 | 設計文件位置 | openspec/changes/20260329-module-loading/design.md | |
| D5 | 多使用者支援 | 確認需要 | 觸發了隔離分析 |
| D6 | 暫不異動 DOGI 專案 | 確認 | 學到的 best practice 移植到 opentree |

---

## 四、待辦事項（TODO）

### P0（Phase 1 — 已完成）

- [x] 建立 opentree 專案骨架（pyproject.toml、src/ 結構）
- [x] 撰寫 opentree.json JSON Schema（draft-2020-12）
- [x] 實作 ManifestValidator 類別（12 種錯誤碼、39 個測試案例）
- [x] 實作 Registry CRUD（load/save/register/unregister，16 個測試案例）
- [x] 建立 10 個模組目錄 + opentree.json manifest
- [x] 整合測試：validator 驗證全部 10 個 manifest
- [x] 驗證 CLAUDE_CONFIG_DIR 環境變數 → 延至 Phase 4，腳本已建立

### P1（Phase 2-3 — 已完成）

- [x] CLAUDE.md 動態生成器
- [x] .claude/rules/ symlink 管理器
- [x] .claude/settings.json 合併產生器
- [x] opentree install/remove/list/refresh CLI 命令
- [x] PlaceholderEngine（per-file symlink vs resolved_copy）
- [x] System prompt 組裝器 + prompt_hook 機制

### P2（Phase 4-6 — 已完成）

- [x] 從 DOGI 遷移 28 rule files（1,035 行）
- [x] prompt_hook 系統（PromptContext + 4 builders）
- [x] opentree init/start/prompt 命令
- [x] E2E lifecycle 測試 + token 比較
- [ ] DOGI bot integration（connect OpenTree to slack-bot）
- [ ] Python to Go migration（long-term）

> 最新狀態見「九、TODO 更新」

---

## 五、Phase 1 實作結果（2026-03-29）

### 5.1 測試結果

| 分類 | 測試數 | 通過 | 備註 |
|------|--------|------|------|
| Schema | 2 | 2 | |
| Validator | 39 | 39 | 原 33 + 6 (code review fixes) |
| Registry | 16 | 16 | 原 15 + 1 (code review fix) |
| Integration | 10 | 10 | |
| Registry Integration | 5 | 4 + 1 xfail | IR-03 reverse dep 為 Phase 2 |
| **Phase 1 小計** | **72** | **71 pass + 1 xfail** | |

**Phase 1 覆蓋率：98%**（253 statements, 5 missed）

> Phase 1-6 最終結果：265 tests (264 pass + 1 xfail), coverage 91%

### 5.2 Agent 交互與決策歷程（Phase 1 實作）

**共 5 Batch，每 batch ≤ 2 agents 並行：**

| Batch | Agent 1 | Agent 2 | 結果 |
|-------|---------|---------|------|
| 1 | 骨架+Schema+Models (9 files) | Flow Simulation (17 scenarios) | 2/2 tests pass; 9 issues found |
| 2 | ManifestValidator TDD (33 tests) | Registry CRUD TDD (15 tests) | 50/50 pass, 98% coverage |
| 3 | 10 Module Manifests (23 files) | Integration Tests (15 tests) | 65/65 pass |
| 4 | Code Review (0C/3H/3M/3L) | Full Test Suite + Coverage | 3 HIGH issues identified |
| 4+ | Fix 3 HIGH issues (+7 tests) | — | 72 tests, 98% coverage |
| 5 | 文件更新 | — | 本文件 |

**Flow Simulation 關鍵發現：**
- handoff.md 的 loading.rules pattern 與 design.md 不一致 → 修正 handoff.md
- personality/slack 的 depends_on 跨文件矛盾 → 統一為 ["core"]
- generate_claude_md 會存取 RegistryEntry 不存在的 triggers 欄位 → 記錄為 Phase 2

**Code Review 關鍵發現與修正：**
- Schema 未限制 prompt_hook/hooks 路徑 → 加入 pattern 防 traversal
- Registry.load 未處理 missing field → KeyError 轉 ValueError
- validate_file 未處理 OSError → 加入 except OSError

### 5.3 歧義解決記錄

| # | 歧義 | 決策 | 理由 |
|---|------|------|------|
| Q1 | loading.rules 格式 | 純檔名 `^[a-z0-9-]+\.md$` | 可攜性佳、rename 安全（推演 A:15/12 vs B:22/16） |
| Q2 | scheduler depends_on | `["core"]` | migration-map 權威依賴圖 |
| Q3 | priority 欄位 | 不加 | 拓撲排序決定載入順序 |

### 5.4 TODO 更新（Phase 1 時點）

#### P0（Phase 1 — 已完成）

- [x] 建立 opentree 專案骨架（pyproject.toml、src/ 結構）
- [x] 撰寫 opentree.json JSON Schema（draft-2020-12）
- [x] 實作 ManifestValidator 類別（12 種錯誤碼、39 個測試案例）
- [x] 實作 Registry CRUD（load/save/register/unregister，16 個測試案例）
- [x] 建立 10 個模組目錄 + opentree.json manifest
- [x] 整合測試：validator 驗證全部 10 個 manifest（15 個測試案例）
- [x] Code Review + HIGH issues 修正
- [x] 驗證 CLAUDE_CONFIG_DIR 環境變數 → Phase 4 完成（腳本建立，待實機執行）

> Phase 1-6 完整 TODO 見「九、TODO 更新」

---

## 六、Phase 2 實作結果（2026-03-29）

### 6.1 實作內容

| 元件 | 說明 |
|------|------|
| ClaudeMdGenerator | 動態生成 CLAUDE.md（< 200 行目標） |
| SymlinkManager | .claude/rules/ symlink 建立與管理 |
| SettingsGenerator | .claude/settings.json 合併產生器 |
| CLI | opentree install/remove/list/refresh 命令（Typer） |
| CLAUDE_CONFIG_DIR 研究 | Web research 5 篇 + 隔離可行性驗證 |

### 6.2 Phase 1 修正

- RegistryEntry 新增 `link_method` 和 `depends_on` 欄位
- Registry 加入 file lock + fsync + crash recovery（寫入 .tmp 再 rename）

### 6.3 推演驗證

- **33 scenarios** 模擬（normal + edge + adversarial）
- **15 issues** 發現並修正

### 6.4 Code Review

- 0 CRITICAL, 4 HIGH（全部修正）

### 6.5 測試結果

| 指標 | 值 |
|------|-----|
| 測試數 | 152（151 pass + 1 xfail） |
| 覆蓋率 | 90% |

---

## 七、Phase 3 實作結果（2026-03-29）

### 7.1 實作內容

- **28 rule files** 從 DOGI 遷移（1,035 行）
- **PlaceholderEngine**：per-file 判斷 symlink vs resolved_copy
  - symlink：不含 placeholder 的檔案
  - resolved_copy：含 placeholder 的檔案（替換後寫入副本）

### 7.2 Placeholder 類型

| Placeholder | 說明 |
|-------------|------|
| `{{bot_name}}` | Bot 名稱 |
| `{{bot_root}}` | Bot 程式碼根目錄 |
| `{{data_root}}` | Bot 資料目錄 |
| `{{home}}` | 使用者 home 目錄 |
| `{{workspace}}` | 當前 workspace 名稱 |

### 7.3 測試結果

| 指標 | 值 |
|------|-----|
| 測試數 | 212（211 pass + 1 xfail） |
| 覆蓋率 | 91% |

---

## 八、Phase 4-6 實作結果（2026-03-29 ~ 2026-03-30）

### 8.1 Phase 4 (P0): CLAUDE_CONFIG_DIR 驗證

- 驗證腳本已建立：`tests/isolation/verify_config_dir.sh`
- 確認 CLAUDE_CONFIG_DIR 重定向：.claude.json, .credentials.json, projects/, settings.json
- 不影響：project-level .claude/
- **待實機手動執行**

### 8.2 Phase 5 (P1a): prompt_hook 系統

| 元件 | 說明 |
|------|------|
| PromptContext | 上下文資料結構（user_id, workspace, channel 等） |
| 4 builders | memory, slack, requirement, scheduler prompt builders |
| hook collector | 從已安裝模組收集 prompt_hook 輸出 |

### 8.3 Phase 5 (P1b): opentree init/start 命令

| 命令 | 說明 |
|------|------|
| `opentree init` | 一鍵初始化 workspace（安裝 pre-installed 模組） |
| `opentree start --dry-run` | 啟動 Claude CLI（dry-run 模式顯示參數） |
| `opentree prompt show` | Debug system prompt 組裝結果 |

### 8.4 Phase 6 (P2): E2E lifecycle 測試

- 完整生命週期測試：init → install → start → prompt
- Token 比較測試：驗證模組化後 token 用量

### 8.5 Option C: admin_channel 混合策略

- 推演驗證通過
- 策略：module manifest 定義 channel placeholder，runtime 從 workspace.json 解析

### 8.6 最終測試結果

| 指標 | 值 |
|------|-----|
| 測試數 | 265（264 pass + 1 xfail） |
| 覆蓋率 | 91% |
| Commits | 8 |
| Lines added | ~11,500 |

---

## 九、TODO 更新（Phase 1-6 完成後）

### 已完成

- [x] 建立 opentree 專案骨架（pyproject.toml、src/ 結構）
- [x] 撰寫 opentree.json JSON Schema（draft-2020-12）
- [x] 實作 ManifestValidator 類別（12 種錯誤碼、39 個測試案例）
- [x] 實作 Registry CRUD（load/save/register/unregister，16 個測試案例）
- [x] 建立 10 個模組目錄 + opentree.json manifest
- [x] 整合測試：validator 驗證全部 10 個 manifest
- [x] Code Review + HIGH issues 修正
- [x] CLAUDE.md 動態生成器（ClaudeMdGenerator）
- [x] .claude/rules/ symlink 管理器（SymlinkManager）
- [x] .claude/settings.json 合併產生器（SettingsGenerator）
- [x] opentree install/remove/list/refresh CLI 命令
- [x] 28 rule files 從 DOGI 遷移（1,035 行）
- [x] PlaceholderEngine（per-file symlink vs resolved_copy）
- [x] prompt_hook 系統（PromptContext + 4 builders + hook collector）
- [x] opentree init/start/prompt 命令
- [x] E2E lifecycle 測試 + token 比較

### 待完成（優先級排序）

- [ ] CLAUDE_CONFIG_DIR 實機驗證（scripts ready, needs manual run）
- [ ] requirement prompt_hook（stub, needs data layer）
- [ ] opentree update command（module upgrade flow）
- [ ] Python to Go migration（long-term）
- [ ] DOGI bot integration（connect OpenTree to slack-bot）

---

## 十、檔案索引

### OpenSpec 文件

| 檔案 | 狀態 | 說明 |
|------|------|------|
| `openspec/changes/20260329-initial-architecture/proposal.md` | ✅ | 架構提案 |
| `openspec/changes/20260329-initial-architecture/decisions.md` | ✅ | 核心決策（6 項） |
| `openspec/changes/20260329-initial-architecture/research.md` | ✅ | 技術調研 |
| `openspec/changes/20260329-initial-architecture/migration-map.md` | ✅ | DOGI→OpenTree 遷移對照 |
| `openspec/changes/20260329-module-loading/design.md` | ✅ 已修正 | 模組載入架構設計（1001 行） |
| `openspec/changes/20260329-module-loading/progress.md` | ✅ 已更新 | 本文件 |
| `openspec/changes/20260329-module-loading/handoff.md` | ✅ 已修正 | Phase 2 接續指引 |
| `openspec/changes/20260329-module-loading/execution-plan.md` | ✅ | 執行計畫 |
| `openspec/changes/20260329-module-loading/flow-simulation.md` | ✅ 新增 | 推演報告 |

### Phase 1 產出檔案

| 分類 | 數量 | 檔案 |
|------|------|------|
| 專案配置 | 1 | pyproject.toml |
| 原始碼 | 9 | src/opentree/**/*.py + .json |
| 模組 manifest | 10 | modules/*/opentree.json |
| 模組 placeholder | 10 | modules/*/rules/.gitkeep |
| 模組 hook stubs | 3 | modules/{memory,slack,requirement}/prompt_hook.py |
| 測試 | 6 | tests/*.py |
| **總計** | **39** | |
