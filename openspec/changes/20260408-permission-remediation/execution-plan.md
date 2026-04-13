# Execution Plan: Permission Remediation & Deployment Safety Net

> **狀態**：✅ Batch 1-3 全部完成
> **最後更新**：2026-04-08T17:00 (Asia/Taipei)

## 問題摘要

OpenTree v0.5.0 部署到 Bot_Walter 後，幾乎所有功能失敗。根因分析發現六大遺漏模式：

1. **Scope Boundary Blindness** — 每個 agent 只看自己 scope，無人負責端到端
2. **Mock Trap** — 1279 tests 全部 mock subprocess，未測真實 Claude CLI 行為
3. **Scope-Out Without Impact** — scripts.tools.* 移植被 scope out，未評估「不做的後果」
4. **New Feature Bias** — 驗收只涵蓋新功能，零項既有功能回歸
5. **Simulation-Reality Gap** — Flow Sim 只推框架內部邏輯，未模擬使用者操作路徑
6. **Environment-Dependent Tests** — E2E 依賴開發環境，無法反映部署後環境

## 技術根因（確認）

### 根因 1：settings.json 格式錯誤
- `allowedTools`/`denyTools` 不是 settings.json 的合法 key（JSON Schema 無此 key）
- 正確格式：`{"permissions": {"allow": [...], "deny": [...]}}`

### 根因 2：缺少 permission-mode CLI flag
- Owner 應用 `--dangerously-skip-permissions`
- Restricted 應用 `--permission-mode dontAsk`

### 根因 3：core 模組基線權限為空
- `modules/core/opentree.json` 的 `permissions.allow: []`

## 實施的變更

| # | 變更 | 檔案 | 狀態 |
|---|------|------|------|
| 1 | settings.json 格式修正 | `settings.py` | ✅ |
| 2 | permission_mode 參數 | `claude_process.py` | ✅ |
| 3 | Dispatcher 傳遞 permission_mode | `dispatcher.py` | ✅ |
| 4 | Core 基線工具 (8 項) | `core/opentree.json` | ✅ |
| 5 | Guardrail .env deny 加固 | `guardrail/opentree.json` | ✅ |
| 6 | 新用戶 memory 目錄預建 | `dispatcher.py` | ✅ |
| 7 | permission_mode 驗證 + warning | `claude_process.py` | ✅ |
| 8 | admin_users docstring 修正 | `config.py` | ✅ |

## E2E 推演結果

### 推演場景（25 個）

| 類別 | 場景數 | 通過 | 問題 |
|------|--------|------|------|
| Owner 正常流程 (1-6) | 6 | 6 | 0 |
| Restricted 正常流程 (7-13) | 7 | 6 | 1 (Issue #2 guardrail) |
| Session & 並發 (14-16) | 3 | 3 | 0 |
| Memory & 檔案 (17-19) | 3 | 2 | 1 (Issue #3 mkdir) |
| 模組工具 (20-22) | 3 | 3 | 0 |
| Edge Cases (23-25) | 3 | 2 | 1 (Issue #4 deny bypass) |

### 發現的 8 個問題及處置

| Issue | 嚴重度 | 狀態 | 處置 |
|-------|--------|------|------|
| #1 記憶雙寫 | LOW | ⏳ 後續 | 需決定 memory 寫入權責 |
| #2 .env 路徑 deny | HIGH | ✅ 已修 | guardrail deny pattern |
| #3 新用戶 mkdir | MEDIUM | ✅ 已修 | dispatcher 預建目錄 |
| #4 Owner MCP deny bypass | HIGH | ⚠️ 已知 | 受限於 CLI 設計，prompt 層處理 |
| #5 is_owner 單一來源 | CRITICAL | ✅ 已修 | 用 context.is_owner |
| #6 原子部署 | CRITICAL | ✅ 已修 | 同 commit 部署 |
| #7 is_owner 重複推導 | MEDIUM | ✅ 已修 | 同 #5 |
| #8 排程任務權限 | MEDIUM | ⏳ 後續 | 需文檔化 |

## 測試結果

### 測試涵蓋

| 測試類別 | 檔案 | 測試數 | 結果 |
|----------|------|--------|------|
| settings 格式 | test_settings.py | 14 | ✅ 全過 |
| claude_process permission | test_claude_process.py | 63 | ✅ 全過 |
| 權限完整性 (NEW) | test_permission_completeness.py | 8 | ✅ 全過 |
| settings 涵蓋度 (NEW) | test_settings_coverage.py | 6 | ✅ 全過 |
| dispatcher | test_dispatcher.py | 145 | ✅ 全過 |
| runner_config | test_runner_config.py | 16 | ✅ 全過 |
| **合計** | | **252** | **✅ 全過** |

### 全量測試

- **1157 passed, 1 xfailed** (排除 jsonschema 缺失的 pre-existing 問題)
- **0 regressions**

### 關鍵覆蓋率

| 模組 | 覆蓋率 |
|------|--------|
| claude_process.py | 93% |
| settings.py | 89% |
| dispatcher.py | 90-92% |
| config.py | 97% (docstring 更新不影響) |

## Code Review 結果

| 嚴重度 | 數量 | 狀態 |
|--------|------|------|
| CRITICAL | 0 | ✅ |
| HIGH | 2 | ✅ 已修（permission_mode 驗證 + docstring） |
| MEDIUM | 3 | ⚠️ 已知（deny pattern scope、integration test gap） |
| LOW | 5 | ✅ 已修（stale comments 清理） |

## 進度追蹤

| 批次 | 狀態 | 開始時間 | 完成時間 | 備註 |
|------|------|---------|---------|------|
| Batch 1 | ✅ 完成 | 15:30 | 16:20 | 研究+設計+E2E推演+TDD RED |
| Batch 2 | ✅ 完成 | 16:30 | 16:50 | TDD GREEN 實作 |
| Batch 3 | ✅ 完成 | 16:50 | 17:00 | Code Review + 修正 + 收尾 |

## Agent 交互歷程

### Batch 1（研究 + 設計 + 推演 + TDD RED）

**Agent A（Research, 2.5min）**：
- WebFetch Claude Code permissions/settings/headless 文檔
- 確認 `allowedTools` 不是 settings.json 合法 key（JSON Schema 驗證）
- 確認 `--dangerously-skip-permissions` ≡ `bypassPermissions`
- 確認 `dontAsk` 是 CI/bot 推薦模式
- 決策：Owner 用 bypass，Restricted 用 dontAsk

**Agent B（Design + Internal Simulation, 3.3min）**：
- 讀取 6 個核心原始檔設計 5 個變更
- 內部推演 10 場景（5 正常 + 5 edge case），全部通過
- 發現 auto-migration 需求

**Agent C（E2E Flow Simulation, 9.5min）**：
- 推演 25 個 Slack 使用者互動場景，全鏈路追蹤
- 發現 8 個問題（2 CRITICAL, 2 HIGH, 3 MEDIUM, 1 LOW）
- CRITICAL #5：`is_owner` 不應重複推導 → 改用 `context.is_owner`
- CRITICAL #6：5 個變更須原子部署
- HIGH #2：.env 路徑應在 tool 層 deny，不只 prompt 層
- 修正後重新推演全部通過

**Agent D（TDD RED, 4.5min）**：
- 寫入 30 個 failing tests（4 個測試檔）
- Group A：9 個 settings 格式測試
- Group B：10 個 permission_mode 測試
- Group C：8+6 個 completeness + coverage 回歸測試
- 既有 53 個 claude_process 測試未受影響

### Batch 2（TDD GREEN 實作）

**Agent A（Layer 1a+1b, 3min）**：
- 修正 `settings.py` generate_settings() 輸出格式
- 新增 `claude_process.py` permission_mode 參數
- 修改 `dispatcher.py` 傳遞 context.is_owner → permission_mode
- 1083 tests 通過，零回歸

**Agent B（Layer 1c + 2, 2.5min）**：
- 修改 `core/opentree.json` 新增 8 個基線工具
- 修改 `guardrail/opentree.json` 新增 4 個 .env deny pattern
- 修改 `dispatcher.py` 新用戶 memory 目錄預建
- 1082 tests 通過，零回歸

### Batch 3（Code Review + 收尾）

**Agent（Code Review, 2.2min）**：
- 審查 9 個檔案，0 CRITICAL / 2 HIGH / 3 MEDIUM / 5 LOW
- HIGH #1：permission_mode 未知值靜默 fallback → 加 warning log
- HIGH #2：admin_users docstring 與實際行為矛盾 → 更新 docstring
- LOW：stale "EXPECTED: FAIL" comments → 清理

**收尾**：
- 修正 2 個 HIGH issue（claude_process.py + config.py）
- 清理所有 stale comments
- 更新 CHANGELOG.md
- 更新 execution-plan.md

## 後續待辦

1. **Dispatcher integration test**：新增測試驗證 `_process_task()` 的 `is_owner` → `permission_mode` → `ClaudeProcess` 完整鏈路
2. **Guardrail deny pattern scope**：驗證 `Read(config/.env*)` 相對路徑在 workspace cwd 下是否正確匹配
3. **記憶雙寫問題（Issue #1）**：決定 memory 寫入權責（Claude Write vs memory_extractor）
4. **排程任務權限文檔（Issue #8）**：文檔化排程任務繼承建立者權限等級的行為
5. **部署後驗證**：`opentree module refresh` 重生成 settings.json，驗證功能恢復

## 相關文件

| 文件 | 內容 |
|------|------|
| [research.md](research.md) | Claude CLI 權限格式調研（settings.json + permission modes + 最佳實踐） |
| [proposal.md](proposal.md) | 5 個核心變更的技術設計 |
| [flow-simulation.md](flow-simulation.md) | 內部推演（10 場景） |
| [e2e-flow-simulation.md](e2e-flow-simulation.md) | E2E Slack 互動推演（25 場景 + 8 issues） |
