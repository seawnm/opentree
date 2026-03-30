# Research: Phase 2 UX Enhancement

> 建立日期：2026-03-30

## 調研背景

Phase 2 為 Bot Runner 新增三個 UX 元件：進度回報、thread 上下文、附件處理。需要調研 Slack Block Kit 最佳實踐、檔案下載安全性、和 thread 上下文注入策略。

## Web Research

原始調研資料（permanent records）：
- [web-research-slack-progress.md](web-research-slack-progress.md) — Slack Block Kit 進度更新模式
- [web-research-file-security.md](web-research-file-security.md) — 檔案下載安全（SSRF 防護、temp 管理）

## 候選方案

### 類別 1：進度回報機制

| 方案 | 評估結果 | 未採用原因 |
|------|----------|------------|
| A. chat.update + Block Kit（定期更新） | ✅ 採用 | — |
| B. chat.startStream（Slack streaming API） | 不適用 | 2025年10月新 API，Python SDK 支援不完整，且需 chat:write.stream scope |
| C. Emoji reaction 表示進度 | 不適用 | 表達力不足，無法顯示 phase/elapsed |

### 類別 2：Thread 上下文策略

| 方案 | 評估結果 | 未採用原因 |
|------|----------|------------|
| A. 滑動視窗（最近 N 則 + 字數上限） | ✅ 採用 | — |
| B. 全量注入（整個 thread） | 不適用 | 長 thread（>100 則）會超出 prompt token 預算 |
| C. 摘要注入（AI 先摘要再注入） | 過度設計 | 增加一次 API 呼叫延遲，MVP 不需要 |

### 類別 3：附件下載安全

| 方案 | 評估結果 | 未採用原因 |
|------|----------|------------|
| A. URL hostname whitelist + streaming size limit | ✅ 採用 | — |
| B. 不下載，只傳 URL 給 Claude | 不可行 | Claude CLI 無法存取 Slack 私有 URL |
| C. 下載後掃毒 | 過度設計 | 單使用者環境，由 Claude CLI sandbox 隔離 |

## 調研結論

- 進度回報使用 chat.update + Block Kit，背景 thread 定期更新（10s interval）
- Thread 上下文使用滑動視窗（20 則、8000 字），排除 bot 訊息和觸發訊息
- 附件下載使用 hostname whitelist（files.slack.com only）+ streaming size limit（50MB）+ 路徑 sanitization
