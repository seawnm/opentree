# Proposal: Batch 4 — Extension Module E2E Tests

## Requirements (verbatim)
使用者原始需求：「補齊這個專案的E2E測試案例，目標是要讓opentree專案的功能都能達到dogi的功能。遵循所有功能都是擴充套件的設計原則，讓Opentree核心可以自由的增刪擴充套件。」

## Problem
OpenTree v0.2.0 的擴充模組（scheduler、requirement）缺乏 E2E 測試覆蓋。
DM 處理邏輯已有 unit test 但無 E2E 驗證（受限於測試框架）。

## Solution
撰寫 E2E 測試碼驗證：
1. D1 — 排程功能：使用者透過 bot 建立/查看/刪除排程
2. D2 — 需求收集：功能需求訊息自動觸發收集流程
3. D3 — DM 處理：標記為 skip（E2E 框架限制）

## Change Scope

| File | Change Type | Description |
|------|-------------|-------------|
| `tests/e2e/test_e2e_extensions.py` | **新增** | D1-D3 擴充模組 E2E 測試 |
| `openspec/.../batch-results.md` | 更新 | Batch 4 結果 |

## Risk

| Risk | Severity | Mitigation |
|------|----------|------------|
| 排程工具需要 bot 有可用的 schedule-tool | HIGH | 用 grep_log 驗證工具呼叫，非直接 CLI 測試 |
| AI 行為不可預測（需求觸發） | MEDIUM | xfail(strict=False) 包裹 |
| DM 無法 E2E 測試 | LOW | skip + 指向 unit test 覆蓋 |

## Design Decisions

### Decision 1: 排程測試策略
**問題**: E2E 測試應直接呼叫 schedule-tool CLI，還是透過 bot 間接測試？
**選擇**: 透過 bot 間接測試 — 發送自然語言指令，驗證 bot 正確呼叫工具。
**理由**: E2E 測試的目的是驗證端到端使用者體驗，不是驗證 CLI 工具本身。

### Decision 2: DM 測試 skip
**問題**: DM 無法透過 message-tool 測試怎麼辦？
**選擇**: skip + 文件說明 + 指向 unit test。
**理由**: 改造 E2E 框架支援 DM 的成本不值得（receiver.py unit test 已覆蓋）。
