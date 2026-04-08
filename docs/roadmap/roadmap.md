# OpenTree Roadmap

> 最後更新：2026-04-08

---

## 近期

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

- [ ] **v0.5.1 發布** — 含 reinstall 改善（5 fixes）、pip install 解耦、instance decoupling。[Unreleased] 已有 9+ items
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
