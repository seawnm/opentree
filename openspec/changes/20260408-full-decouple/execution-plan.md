# Execution Plan: 完全解耦 — 刪除 opentree source 後 instance 繼續運行

## Batch 1: pip install . 打包完整性 ✅ DONE

### 問題分析
- modules/ 不在 wheel 裡（pyproject.toml 只打包 src/opentree/）
- _bundled_modules_dir() 用 4 層 __file__ 回溯，安裝後找不到
- _resolve_opentree_cmd("auto") 安裝後會撞到不相關的 pyproject.toml

### 實作
- [x] pyproject.toml: force-include modules → opentree/bundled_modules
- [x] pyproject.toml: exclude __pycache__ from build
- [x] _bundled_modules_dir() 雙路徑 fallback（init.py + module.py 同步）
- [x] _resolve_opentree_cmd("auto") 偵測 bundled_modules/ 存在 → bare command
- [x] Slack 依賴提示（bare mode 下缺 slack_bolt 時 warning）
- [x] 6 個新測試（TestBundledModulesDir + TestResolveCmdAutoInstalled）
- [x] Wheel 驗證：91 files, 41 bundled_modules, 0 __pycache__

### Flow Simulation
33 scenarios, 26 PASS, 7 issues found:
- Issue #4 (HIGH): schema/templates 在 wheel — 實際驗證已在 ✅
- Issue #5 (MEDIUM): auto mode installed 偵測 — 已修（bundled_modules check）
- Issue #1 (MEDIUM): module.py 同步 — 已修（identical logic）

### Code Review
APPROVE — 0 CRITICAL, 0 HIGH, 3 MEDIUM（docstring 已更新）

### 測試
1279 passed, 0 failed, 1 xfailed

## Backlog: 階段 B（另開任務）
- scripts.tools.* 移植（6 個工具從 DOGI 移植到 opentree）
- schedule_tool 是最大工程（3-5 days, APScheduler + SQLite）
