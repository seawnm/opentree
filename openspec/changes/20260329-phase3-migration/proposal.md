# Proposal: Module Content Migration + Placeholder Engine

> 建立日期：2026-03-29
> 狀態：待確認

## Requirements（使用者原話）

「下一步建議...P1: 從 DOGI 遷移 module rules 內容 + Placeholder 替換引擎」

## Problem

10 個模組目錄只有 opentree.json manifest 和 rules/.gitkeep，實際 rule 檔案為空。
ClaudeMdGenerator 和 SymlinkManager 無法產生有意義的 .claude/rules/ 內容。
28 個 rule 檔案需從 DOGI.md (430行) + cc/CLAUDE.md (992行) 提取並通用化。
其中 16 個檔案含 {{placeholder}}，需在安裝時替換為實際值。

## Solution

1. PlaceholderEngine：讀取 template rules → 替換 {{...}} → 寫入 resolved copy
2. 28 個 rule .md 檔案：從 DOGI 源碼提取、通用化、加入 placeholder
3. SymlinkManager 整合：per-file 判斷 symlink vs resolved_copy
4. CLI 整合：install/refresh 時自動解析 placeholder

## Change Scope

| 分類 | 數量 | 說明 |
|------|------|------|
| 新增 rule .md | 28 | 10 模組的實際規則內容 |
| 新增 source | 1 | core/placeholders.py |
| 修改 source | 4 | config.py, symlinks.py, claude_md.py, cli/module.py |
| 新增 tests | 3 | test_placeholders.py, test_migration_integration.py, test_e2e_phase3.py |
| 修改 tests | 4 | test_config/symlinks/claude_md/cli.py |
| 預估新增 tests | ~61 | 總計 ~213 tests |

## Batch Schedule

| Batch | Agent 1 | Agent 2 | ~min |
|-------|---------|---------|------|
| 1 | PlaceholderEngine TDD (20 tests) | UserConfig + ClaudeMdGenerator 委託 | 20 |
| 2 | SymlinkManager per-file resolution (7 tests) | CLI install/refresh 整合 (4 tests) | 25 |
| 3 | core+personality+guardrail rules (11 files) | memory+slack+audit-logger rules (7 files) | 25 |
| 4 | scheduler rules (3 files) + integration tests | requirement+stt+youtube rules (7 files) | 25 |
| 5 | E2E test + Code Review | Documentation + Commit | 20 |

## Key Design Decision

含 {{placeholder}} 的 rule → **resolved_copy**（安裝時複製+替換）
不含 placeholder 的 rule → **symlink**（零成本，上游更新即時反映）
16 files resolved_copy + 12 files symlink

## Risk

| 風險 | 嚴重度 | 緩解 |
|------|--------|------|
| resolved_copy 與原始脫鉤 | MEDIUM | refresh 重新解析 |
| 遷移遺漏 DOGI 內容 | MEDIUM | extraction-map 逐行對照 |
| WSL2 symlink 不穩定 | LOW | fallback chain 已建 |
