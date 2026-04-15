# Proposal：移除 memory-sop.md 的 Bash 依賴

**日期**：2026-04-14  
**狀態**：Implementing  
**作者**：Walter  

## 背景

OpenTree bot 在 dontAsk permission mode 下，記憶讀寫功能失敗。
根本原因是 memory-sop.md 第 N 步要求執行 `Bash("mkdir -p ...")` 建立目錄，
而 `Bash` 工具未在 settings.json 的 allow 清單中，導致靜默失敗。

## 變更範圍

- `modules/memory/rules/memory-sop.md`：移除 Bash mkdir 前置步驟
- `modules/personality/rules/character.md`：能力宣告加入前提語氣
- `modules/personality/rules/tone-rules.md`：首次互動範本調整
- `modules/guardrail/rules/denial-escalation.md`：移除絕對性能力宣告

## 影響分析

| 影響項目 | 說明 |
|---------|------|
| 向後相容性 | ✅ 完全相容，只改 rule 文字 |
| 已部署實例 | 需執行 `opentree module refresh` 套用新規則 |
| 功能行為 | 記憶讀寫改用原生 Write 工具（更可靠） |
