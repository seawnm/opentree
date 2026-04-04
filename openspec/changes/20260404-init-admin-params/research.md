# Research: init 參數改造

## Background
opentree init 需要在 onboard 流程中一併設定管理者，且移除不再需要的 admin_channel。

## Candidates

### admin_users 設定方式
| 方案 | 評估 | 未採用原因 |
|------|------|------------|
| CLI 參數 --admin-users | ✅ 採用 | — |
| 互動式詢問 | 不適合 Claude Code 環境（無 stdin） | bot 環境不支援 AskUserQuestion |
| 環境變數 | 不直觀 | 使用者需要額外設定 |

### admin_channel 處理
| 方案 | 評估 | 未採用原因 |
|------|------|------------|
| 完全移除欄位 | 破壞向後相容 | 既有 user.json 含此欄位 |
| 保留欄位但不設定 | ✅ 採用 | — |
| Deprecated warning | 過度工程 | 不值得加 warning 邏輯 |

## Conclusion
--admin-users 作為必填 CLI 參數最適合 Claude Code onboard 場景。admin_channel 保留欄位但 guardrail 改為 optional。
