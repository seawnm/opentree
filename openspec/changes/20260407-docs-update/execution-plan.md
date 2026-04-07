# Execution Plan: Documentation & Developer Guide Update

> 基於文件審計結果，補齊 v0.5.0 所有缺失文件。

## 批次規劃

### Batch 1: README.md + docs/DEPLOYMENT.md ✅ DONE
- [x] README.md — 術語 admin→Owner、Quick Start、.env / --cmd-mode / reset / memory / CLAUDE.md 說明
- [x] docs/DEPLOYMENT.md — 新建 11 章節完整部署指南

### Batch 2: AGENTS.md + run.sh + init.py ✅ DONE
- [x] AGENTS.md — v0.5.0 版本更新、新增 reset.py / memory_schema.py / --cmd-mode 等
- [x] run.sh template — 強化 operator 註釋（Instance Decoupling、timeout 說明）
- [x] init.py — 改善 --cmd-mode help text + init_command docstring

## Agent 互動紀錄

### Batch 1
- **Agent A (README.md)**: 術語修正 5 處、新增 6 個段落（Instance Config、Bot Commands、Memory System、CLAUDE.md Customization、Environment Variables、Status table）
- **Agent B (DEPLOYMENT.md)**: 新建 11 章節，全部從源碼推導（init.py、bot.py、reset.py、run.sh）

### Batch 2
- **Agent C (AGENTS.md)**: 版本 v0.4.0→v0.5.0、新增 3 組件（reset.py、memory_schema.py、_resolve_opentree_cmd）、更新 5 既有組件描述、新增 4 設計模式、更新 Known Technical Debt
- **Agent D (run.sh + init.py)**: run.sh 新增 Instance Decoupling 註釋區塊 + 9 個 timeout 註釋；init.py 更新 --cmd-mode help text + init_command docstring。44/44 init tests passed

## 測試結果
- 1250 passed, 0 failed, 1 xfailed
- 無功能性程式碼變更（純文件更新），不影響覆蓋率
