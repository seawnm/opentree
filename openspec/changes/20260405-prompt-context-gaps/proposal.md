# Proposal: System Prompt Context Gaps

## Requirements (user's original words, verbatim)

> 為什麼他看不出我是admin?
> 幫我一併檢查其他地方是否有類似問題，一併規劃修復
> 改善做法請參考 dogi 作法，一併納入 low 問題修正

## Problem

Bot_Walter 的 system prompt 缺少多項 Claude 決策所需的關鍵上下文，導致：
- Claude 不知道使用者是否為 Admin → guardrail rules 權限分級形同虛設
- thread_participants 永遠空 → slack hook 的多人 thread 警告永不觸發
- channel_id/thread_ts 不在 prompt 輸出 → Claude 無法提供給工具使用
- workspace 硬編碼 "default"
- 缺少記憶讀取提示

## Solution

參考 DOGI 的 `task_processor.py` + `prompt_parts.py`，在 opentree 模組化架構下補齊：
1. PromptContext 加 `is_admin` 欄位
2. `build_identity_block()` 輸出權限等級 + 記憶讀取提示
3. 新增 `build_channel_block()` 輸出 channel_id, thread_ts, workspace
4. Dispatcher 計算 is_admin、提取 thread_participants、修正 workspace
5. Memory hook 加入記憶讀取提示

## Change Scope

| File | Change Type | Description |
|------|-------------|-------------|
| `src/opentree/core/prompt.py` | Modify | +is_admin 欄位, +build_channel_block(), identity 增強 |
| `src/opentree/runner/dispatcher.py` | Modify | is_admin 計算, thread_participants 提取, workspace 修正 |
| `modules/memory/prompt_hook.py` | Modify | 記憶讀取提示 |
| `tests/test_prompt.py` | Modify | 新增測試 |
| `tests/test_dispatcher.py` | Modify | 新增測試 |
