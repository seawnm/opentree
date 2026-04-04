# OpenTree Roadmap

> 最後更新：2026-04-04

---

## 近期

- [x] **flock DrvFs 修復** — WSL2 `/mnt/e/` 上 flock 不生效，需改用 `/tmp/` 路徑或 PID file lock（來自 thread 1775069650）— ✅ 2026-04-04
- [x] **remaining-tasks.md 更新** — module update、LOW issues 已完成但文件未標記 done（來自 thread 1775069650）— ✅ 2026-04-04
- [ ] **v0.3.1 發布** — post-v0.3.0 已有 12+ commits（含 P0 TaskQueue bug fix），應發版（來自 thread 1775069650）
- [ ] **完整 E2E 全跑一次** — 單 instance + bug fix 後需完成 75 tests 全跑驗證（來自 thread 1775069650）
- [ ] **完整 E2E 全跑驗證（含 TaskQueue bug fix）** — TaskQueue promotion bug 修復後的回歸測試
- [x] **opentree init 加入 admin_users 必填設定** — onboard 流程中一併設定管理者（來自 thread 1775069650）— ✅ commit 6c9cf5b (2026-04-04)

## 中期

- [ ] **9 個 xfail 測試持續觀察** — 部分可能在穩定環境下轉 XPASS 可升級（來自 thread 1775069650）
- [ ] **Bot Walter rsync 部署自動化** — 每次 opentree commit 後手動 rsync runner 容易遺漏（來自 thread 1775069650）
- [ ] **opentree module update 指令的測試補強** — 目前只有 version.py 的 21 個測試，update 指令本身缺整合測試（來自 thread 1775069650）

## 長期

- [ ] **DOGI 遷移評估** — 991 行 CLAUDE.md 遷移至 OpenTree 模組化（來自 thread 1775069650）
- [ ] **Python -> Go 遷移** — 啟動速度和資源效率（來自 thread 1775069650）
- [ ] **requirement prompt_hook** — 需求訪談上下文注入，stub 已建立（來自 thread 1775069650）
- [ ] **跨 workspace 模板複用** — 多 workspace 共享模組（來自 thread 1775069650）
