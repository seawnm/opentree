# OpenTree Roadmap

> 最後更新：2026-04-24

---

## 近期

### Permission Remediation 後續（來自 2026-04-08 反思 + E2E 推演）

#### 🔴 必須做（v0.5.1 前）

- [x] **pyproject.toml 版本號更新** — `0.5.0` → `0.5.1` — ✅ 2026-04-11
- [x] **opentree.schema.json stale description 修正** — `allowedTools`/`denyTools` → `permissions.allow`/`permissions.deny` — ✅ 2026-04-11
- [x] **部署遷移指引** — CHANGELOG `[Unreleased] ### Security` 節已加入 ⚠️ 部署注意事項（需執行 `opentree module refresh`）— ✅ 2026-04-11

#### 🟡 應該做（品質 / 可靠性）

- [ ] **settings.json 格式自動遷移** — bot 啟動時偵測舊 `allowedTools` 格式自動 refresh。避免依賴人工記得執行 refresh（flow-simulation.md Edge 5 Option A）（~30 min）
- ~~[ ] **Dispatcher integration test: permission_mode 鏈路**~~ — ~~驗證 `is_owner` → `permission_mode` → `ClaudeProcess` 完整傳遞~~ **[已刪除 - obsolete]**：`permission_mode` 參數於 20260411 移除，傳遞鏈不復存在
- [ ] **Guardrail deny pattern scope 驗證** — `Read(config/.env*)` 相對路徑在 workspace cwd 下是否正確匹配。如不生效則 deny 規則形同虛設（~45 min）
- [ ] **記憶雙寫問題（E2E Issue #1）** — Claude Write + memory_extractor 可能雙寫。需決定權責：關 extractor 或 deny Write(**/memory.md)（~45 min）
- [x] **Owner deny bypass 研究（E2E Issue #4）** — `--dangerously-skip-permissions` 繞過 deny list。**✅ 2026-04-11 已修復**：改用 `--permission-mode dontAsk` 完全消除 bypass，詳見 [openspec/changes/20260411-owner-dontask-mode/](openspec/changes/20260411-owner-dontask-mode/)
- [ ] **`_build_claude_args` cwd 參數清理** — Code Review MEDIUM：cwd 傳入函數但未使用，僅供 docstring 文檔化。考慮移除或保留（~10 min）
- [x] **AGENTS.md ClaudeProcess 描述補充** — ✅ 2026-04-19：補充到 DEPLOYMENT.md「Codex Rules Injection Architecture」章節，說明 ClaudeProcess → 全員 `--permission-mode dontAsk`，以及 Codex 的 prompt_hook 注入路徑

### 開發流程改善（來自 2026-04-08 反思 · 六大遺漏模式）

- [ ] **Scope-Out Impact Assessment 規範** — 任何被 scope out 的項目，必須附帶「不做的後果」。答案若為「核心功能壞掉」→ blocker 不是 backlog。寫入 openspec template 或 CONTRIBUTING.md（~20 min）
- [ ] **部署驗收清單模板** — 標準 checklist = 新功能驗收 + 既有功能 smoke test（記憶、排程、搜尋、Slack 查詢、上傳…）+ E2E 通過（~30 min）
- [ ] **Integration Verifier agent 角色** — 多 agent 開發流程的最後一步：站在部署後使用者視角驗證端到端功能。下次大功能開發時試行（~30 min）
- [ ] **排程任務權限文檔化（E2E Issue #8）** — 排程任務繼承建立者權限等級（動態檢查，非建立時鎖定）。寫入 scheduler 模組文件（~15 min）
- [x] **README / DEPLOYMENT.md permission 說明** — 說明 Owner vs Restricted 權限模型、admin_users 設定、settings.json 格式 — ✅ 2026-04-13（DEPLOYMENT.md 新增 `## Permission Model` 章節）
- [ ] **E2E 測試：Permission 場景** — 新增 Owner/Restricted 權限行為的 E2E 測試，含：dontAsk 允許清單生效、deny 規則阻止 .env 讀取、Owner 與 Restricted 行為一致（~1-2 hr）

### Permission Remediation 已完成 ✅

- [x] **settings.json 格式修正** — `allowedTools` → `permissions.allow/deny`（Claude Code 規範格式）— ✅ 2026-04-08
- [x] **Permission mode 支援** — v0.5.0 試驗階段：Owner 用 `--dangerously-skip-permissions`，Restricted 用 `--permission-mode dontAsk`；**⚠️ 已由 20260411 安全修復取代，全員改為 `--permission-mode dontAsk`（見下方 Security Fix 節）** — ✅ 2026-04-08 → 2026-04-11
- [x] **Dispatcher 權限傳遞** — v0.5.0 實作 `is_owner` → `permission_mode` 推導；**⚠️ 已由 20260411 安全修復移除，`permission_mode` 參數已刪除，不再區分** — ✅ 2026-04-08 → 2026-04-11
- [x] **Core 基線工具** — 新增 Read/Write/Edit/Glob/Grep/WebSearch/WebFetch/Task — ✅ 2026-04-08
- [x] **Guardrail .env deny 加固** — `Read(config/.env*)` 等 deny pattern — ✅ 2026-04-08
- [x] **新用戶 memory 目錄預建** — dispatcher 為首次互動用戶預建目錄 — ✅ 2026-04-08
- [x] **permission_mode 驗證** — 未知值 warning log — ✅ 2026-04-08
- [x] **admin_users docstring 修正** — 空 tuple 語意從「全員 admin」修正為「無人有 owner 權限」— ✅ 2026-04-08
- [x] **回歸測試** — test_permission_completeness.py (8 tests) + test_settings_coverage.py (6 tests) — ✅ 2026-04-08

### Security Fix 已完成（2026-04-11）✅

- [x] **移除 `--dangerously-skip-permissions`** — 全員（含 Owner）改為 `--permission-mode dontAsk`，徹底消除 bypass — ✅ 2026-04-11
- [x] **Core 工具路徑限縮** — `modules/core/opentree.json`：裸 Read/Write/Edit → `$OPENTREE_HOME/**` 範圍限定 — ✅ 2026-04-11
- [x] **Guardrail 絕對路徑 deny 加固** — `modules/guardrail/opentree.json` 新增 `$OPENTREE_HOME/**/.env*` 絕對路徑 deny 規則 — ✅ 2026-04-11
- [x] **permissions.json + settings.json 重新產生** — `bot_walter` instance 已套用新限縮規則 — ✅ 2026-04-11
- [x] **版本號升至 v0.5.1** — ✅ 2026-04-11
- [x] **OpenSpec 文件** — `openspec/changes/20260411-owner-dontask-mode/`（proposal.md + research.md）— ✅ 2026-04-11
- [x] **CHANGELOG.md Security 節** — ⚠️ 部署注意：須執行 `opentree module refresh` — ✅ 2026-04-11
- [x] **Regression tests：`TestPermissionModeUniformity`** — `test_dispatcher.py` 新增 2 個 regression tests，驗證 Owner 不再獲得特殊 CLI 權限 — ✅ 2026-04-13
- [x] **Roadmap / DEPLOYMENT.md 文件補齊** — roadmap lines 38-39 更新為已取代狀態、新增 Security Fix 完成節、DEPLOYMENT.md Permission Model 章節 — ✅ 2026-04-13

### Bot 生命週期管理（來自 2026-04-08 reinstall 改善）

- [x] **`opentree stop` CLI 指令** — 安全停止 wrapper + bot（SIGTERM → 等待 → SIGKILL），/proc/cmdline 防 PID reuse — ✅ commit b652f34 (2026-04-08)
- [x] **run.sh wrapper.pid + stop flag** — wrapper 寫入 PID 供 stop 定位，.stop_requested 防止重啟 — ✅ commit b652f34 (2026-04-08)
- [x] **init 補齊 `data/logs/` 目錄** — nohup redirect 在 mkdir 之前執行導致靜默失敗 — ✅ commit 36615e2 (2026-04-08)
- [x] **legacy `.env` 自動遷移** — init --force 時偵測 legacy .env 含真實 token → 遷移到 .env.local — ✅ commit 36615e2 (2026-04-08)
- [x] **`_load_tokens` placeholder fallback** — 三層 merge 後若 token 仍為 placeholder，fallback 到 legacy .env — ✅ commit 36615e2 (2026-04-08)
- [x] **DEPLOYMENT.md `opentree stop` 文件** — 新增 Stopping the Bot 章節（用法、參數、範例、流程） — ✅ commit 930082f (2026-04-08)
- [ ] **`--force` SIGKILL orphan 清理** — wrapper 被 SIGKILL 後 watchdog 和 bot 子進程成為 orphan，lifecycle.py 需追殺 bot.pid（2026-04-08 驗證時發現）
- [ ] **PermissionError on SIGTERM 整合測試** — Code Review MEDIUM：非 root 用戶停止 root 啟動的 bot 場景（來自 thread 1775575876）
- [ ] **wrapper.pid identity fallback 測試** — Code Review MEDIUM：PID reuse 防護機制的 fallback 路徑（來自 thread 1775575876）
- [ ] **test_match dead code 清理** — Code Review LOW：tests/test_lifecycle.py 中有未使用的 mock block（來自 thread 1775575876）

### 版本發布

- [x] **v0.6.2 發布** — Silent failure fix：4 個無聲失敗路徑修補（no result event / empty response / circuit breaker / promoted tasks stuck）+ Codex finish 可觀測性 log — ✅ 2026-04-21
- [x] **v0.6.1 發布** — Receiver liveness probe loop：修復 Codex 長任務期間 heartbeat stale 導致 watchdog SIGKILL — ✅ 2026-04-20
- [x] **v0.6.0 發布** — Codex-first 架構：Codex migration + bwrap sandbox + AGENTS.md rules injection + 8 COGI bug fixes + permission remediation 完工 — ✅ 2026-04-19
- ~~[ ] **v0.5.1 發布**~~ — 已被 v0.6.0 取代（含原規劃的 reinstall 改善、pip install 解耦、instance decoupling、permission remediation）
- ~~[ ] **v0.3.1 發布**~~ — 已被 v0.5.0 取代

### 測試驗證

- [ ] **完整 E2E 全跑一次** — 目前 1310 unit/integration tests 通過（89% 覆蓋率），但 13 個 E2E tests 未跑（需要運行中的 bot instance）（來自 thread 1775069650）
- [ ] **完整 E2E 全跑驗證（含 TaskQueue bug fix）** — TaskQueue promotion bug 修復後的回歸測試

### 既有已完成

- [x] **flock DrvFs 修復** — WSL2 `/mnt/e/` 上 flock 不生效，改用 `/tmp/` — ✅ 2026-04-04
- [x] **remaining-tasks.md 更新** — ✅ 2026-04-04
- [x] **opentree init 加入 admin_users 必填設定** — ✅ commit 6c9cf5b (2026-04-04)
- [x] **onboarding 指令偵測修復** — ✅ commit 570c65c (2026-04-05)
- [x] **system prompt 資訊缺口修復** — ✅ commit aad02a9 (2026-04-05)

## 中期

### 部署與維運

- [ ] **Bot Walter rsync 部署自動化** — 每次 opentree commit 後手動 rsync runner 容易遺漏（來自 thread 1775069650）
- [ ] **`opentree stop` 預設 timeout 評估** — 測試發現 30s 不夠（wrapper cleanup 等待 bot drain 最多 40s），目前 CLI 預設 60s 但可能需調整文件建議值（來自 2026-04-08 驗證）

### 測試補強

- [ ] **9 個 xfail 測試持續觀察** — 部分可能在穩定環境下轉 XPASS 可升級（來自 thread 1775069650）
- [ ] **opentree module update 指令的測試補強** — 目前只有 version.py 的 21 個測試，update 指令本身缺整合測試（來自 thread 1775069650）

## 長期

- [ ] **DOGI 遷移評估** — 991 行 CLAUDE.md 遷移至 OpenTree 模組化（來自 thread 1775069650）
- [ ] **Python -> Go 遷移** — 啟動速度和資源效率（來自 thread 1775069650）
- [x] **requirement prompt_hook** — 需求訪談上下文注入 — ✅ commit 570c65c (2026-04-05)
- [ ] **跨 workspace 模板複用** — 多 workspace 共享模組（來自 thread 1775069650）

---

## 設計決策索引

| 日期 | 功能 | OpenSpec 路徑 |
|------|------|---------------|
| 2026-04-21 | Silent Failure Fix（4 路徑修補 + finish log） | `openspec/changes/20260421-silent-failure-fix/` |
| 2026-04-20 | Slack Task Visibility Parity（進行中） | `openspec/changes/20260420-slack-visibility-parity/` |
| 2026-04-19 | Codex-first Rules Injection + AGENTS.md marker fix | `openspec/changes/20260419-codex-rules-injection/` |
| 2026-04-11 | Owner dontAsk Mode（安全修復） | `openspec/changes/20260411-owner-dontask-mode/` |
| 2026-04-08 | Permission Remediation | `openspec/changes/20260408-permission-remediation/` |
| 2026-04-08 | Bot Reinstall Improvements | `openspec/changes/20260408-reinstall-improvements/` |
| 2026-04-08 | pip install 完全解耦 | `openspec/changes/20260408-full-decouple/` |
| 2026-04-07 | Instance Decoupling | `openspec/changes/20260407-decouple-instance/` |
| 2026-04-07 | Owner Freedom (v0.5.0) | `openspec/changes/20260407-owner-freedom/` |
| 2026-04-06 | AGENTS.md Codemap | `openspec/changes/20260406-agents-md-codemap/` |
| 2026-04-05 | 部署架構 | `openspec/changes/20260405-deployment-architecture/` |
| 2026-04-01 | E2E 全面測試 | `openspec/changes/20260401-e2e-comprehensive/` |
| 2026-03-31 | E2E 驗證 | `openspec/changes/20260331-e2e-verification/` |
| 2026-03-30 | Slack Bot Runner | `openspec/changes/20260330-slack-bot-runner/` |
| 2026-03-29 | Module Loading | `openspec/changes/20260329-module-loading/` |
| 2026-03-29 | Initial Architecture | `openspec/changes/20260329-initial-architecture/` |
