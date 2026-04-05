# Research: System Prompt Context Gaps

## Background

Bot_Walter 的 system prompt 缺少多項 Claude 決策所需的上下文（is_admin、channel info 等），
導致 guardrail rules 無法正常運作。需參考 DOGI 的做法補齊。

## Candidates

### Admin 狀態偵測方式

| 方案 | 評估結果 | 未採用原因 |
|------|----------|------------|
| 比對 `RunnerConfig.admin_users` | ✅ 採用 | — |
| 查詢 Slack API `is_admin` 欄位 | 多一次 API 呼叫 | 已有 admin_users 設定，不需要查 Slack |
| 讀取 `_permissions/` 目錄 | 過度複雜 | DOGI 架構才需要 permission_manager |

### Channel 資訊注入方式

| 方案 | 評估結果 | 未採用原因 |
|------|----------|------------|
| 新增 `build_channel_block()` 函數 | ✅ 採用 | 與 DOGI 的 `build_channel_block()` 對齊 |
| 在 `build_identity_block()` 內一併輸出 | 職責混淆 | identity 是使用者資訊，channel 是環境資訊 |

### Thread Participants 提取方式

| 方案 | 評估結果 | 未採用原因 |
|------|----------|------------|
| 從 `get_thread_replies()` 提取 | ✅ 採用 | 與 DOGI 的 `thread_participants` 相同來源 |
| 從 `build_thread_context()` 副作用取得 | 耦合度高 | thread_context 是文字組裝，不應承擔 participant 提取 |

### Capability Summary（非 admin 使用者功能清單）

| 方案 | 評估結果 | 未採用原因 |
|------|----------|------------|
| 移植 DOGI 的 `permission_manager.get_capability_summary()` | 架構差異大 | Bot_Walter 無 permission_manager，guardrail rules 已覆蓋 |
| 在 guardrail module hook 實作 | 可行但非必要 | 留後續需求驅動 |

## Conclusion

1. `is_admin` 用 `RunnerConfig.admin_users` 比對，最簡單且與 admin command 判斷邏輯一致
2. Channel 資訊獨立為 `build_channel_block()`，與 DOGI 對齊
3. Thread participants 從 thread history API 提取，limit=50 控制效能
4. Capability summary 暫不實作（guardrail rules 已有權限描述）
