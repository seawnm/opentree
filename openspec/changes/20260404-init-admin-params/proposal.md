# Proposal: opentree init 參數改造

## Requirements (user's original words, verbatim)
- 「一律要設定admin」「透過 claude code cli來做 on board」
- 「取消管理頻道，不需要設定這個參數了」
- 「bot_name 也要改成必填」

## Problem
1. admin_users 不在 init 流程中，事後容易遺忘 → 預設所有人都是 admin
2. admin_channel 已不需要（管理員通知改用其他機制）
3. bot_name 有預設值 "OpenTree" 但實際部署都需要自訂名稱

## Solution
1. `--admin-users` 新增為必填（逗號分隔 Slack User ID）→ 產生 runner.json
2. `--bot-name` 改為必填（移除預設值）
3. `--admin-channel` 移除
4. guardrail 模組的 admin_channel placeholder 改為 optional
5. guardrail rules 中的 `{{admin_channel}}` 引用改寫

## Change Scope

| File | Change Type | Description |
|------|-------------|-------------|
| `src/opentree/cli/init.py` | 修改 | +admin_users 必填、bot_name 必填、-admin_channel |
| `src/opentree/runner/config.py` | 修改 | start 時驗證 admin_users 非空 |
| `src/opentree/core/config.py` | 保留 | admin_channel 欄位保留（向後相容），預設空 |
| `modules/guardrail/opentree.json` | 修改 | admin_channel: required → optional |
| `modules/guardrail/rules/permission-check.md` | 修改 | 移除 {{admin_channel}} 引用 |
| `modules/guardrail/rules/security-rules.md` | 修改 | 移除 {{admin_channel}} 引用 |
| `tests/test_init.py` | 修改 | 更新測試 |

## Risk
| Risk | Severity | Mitigation |
|------|----------|------------|
| 既有 Bot Walter user.json 有 admin_channel | LOW | config.py 仍讀取，只是不再寫入 |
| guardrail rules 功能降級 | LOW | 權限申請改為通知 admin_users 而非頻道 |
