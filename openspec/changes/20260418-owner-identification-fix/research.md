# Research: Owner Identification Rules in Two-Layer Architecture

## 調研背景

OpenTree 的 Owner 判斷分成兩層：

1. 程式碼層：`is_owner()` 與 `build_identity_block()` 已正確將當前使用者標記為 `權限等級：Owner` 或 `權限等級：一般使用者`
2. LLM 推理層：`character.md` 尚未明確規定要以該欄位作為唯一判斷依據，導致模型在回答「誰是你的 Owner」時自行推論並幻覺 user_id

問題本質是提示規則缺口，而非 runtime identity signal 缺失。

## 候選方案

| 方案 | 說明 | 結論 | 未採用原因 |
|------|------|------|------------|
| A | 將 `admin_users` 的 user_id 注入 system prompt | ❌ | 會暴露隱私配置，違反 `admin_users` 不進 prompt 的既有設計 |
| B | 在 `build_identity_block()` / `prompt.py` 追加更細的識別說明 | ❌ | 規則埋在核心 prompt 組裝層，維護成本較高，且不如 personality module 直觀 |
| C | 在 `modules/personality/rules/character.md` 加入 Owner 識別規則 | ✅ | 最小改動、module-level 可維護、無需程式碼變更 |

## 最終選擇

採用方案 C。

理由：
- 直接修補 LLM 行為規則缺口
- 不改動隱私邊界，不暴露 `admin_users`
- 不影響現有程式碼層的 Owner 判斷與 prompt 組裝流程

最終 patch 經 Codex code review 驗證：第 4 條規則初版說「系統提示中沒有 owner user_id」，
但在 Owner session 中 `build_identity_block()` 確實注入了 `使用者 ID：{context.user_id}`，
因此修正為「不可捏造**不在系統提示中**的任何人的 user_id」，保留 Owner 可引用自身 ID 的能力。
