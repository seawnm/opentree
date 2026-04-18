# Proposal: Owner 識別規則修復 — LLM 誤判 Owner 身分與幻覺 user_id

## 需求背景

在 bot_DOGI 部署期間的 smoke test 中，非 Owner 使用者 Walter 詢問「who is your owner?」時，
LLM 錯誤回覆 Walter 就是 Owner，且進一步編造了一個不存在於系統提示中的 owner user_id。

根因不是程式碼層的 `is_owner()` 判斷錯誤，而是 LLM 缺少明確規則去理解 prompt 內
「權限等級：Owner / 一般使用者」才是唯一識別依據，導致它自行腦補 Owner 身分。

## 變更範圍

- `modules/personality/rules/character.md`
  - 在「Owner 概念」段落新增 4 條識別規則
  - 明確要求 LLM 只能依據系統提示中的「權限等級」判斷是否為 Owner
  - 禁止猜測非提示中出現的任何 user_id

## 影響分析

- 無程式碼變更
- 無權限模型或 prompt 組裝邏輯變更
- 僅改善 LLM 在 Owner 身分辨識與 user_id 引用上的行為一致性
