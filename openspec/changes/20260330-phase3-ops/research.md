# Research: Phase 3 Operations

> 建立日期：2026-03-30

## 調研背景

Phase 3 為 Bot Runner 新增運維能力：日誌系統和 process wrapper。需要調研 Python logging 最佳實踐、bash process supervision 模式。

## Web Research

原始調研資料（permanent records）：
- [web-research-watchdog.md](web-research-watchdog.md) — Bash 程序監督和 watchdog 模式

## 候選方案

### 類別 1：日誌系統

| 方案 | 評估結果 | 未採用原因 |
|------|----------|------------|
| A. Python stdlib logging + TimedRotatingFileHandler | ✅ 採用 | — |
| B. structlog（structured logging） | 過度設計 | 額外依賴，MVP 不需要 JSON 日誌 |
| C. loguru（第三方） | 不適用 | 避免非必要依賴 |

### 類別 2：Process Supervision

| 方案 | 評估結果 | 未採用原因 |
|------|----------|------------|
| A. Bash wrapper（run.sh） | ✅ 採用 | 零依賴，與 DOGI 經驗一致 |
| B. systemd service | 未採用 | 不跨平台（macOS/WSL2 不支援），且需 root 權限 |
| C. supervisord | 未採用 | 額外依賴，對單 process bot 過度 |
| D. PM2 | 未採用 | 需要 Node.js，不適合純 Python 專案 |

### 類別 3：Crash Loop Protection

| 方案 | 評估結果 | 未採用原因 |
|------|----------|------------|
| A. 固定視窗 + cooldown（N 次/M 秒 → 休眠 K 秒） | ✅ 採用 | 簡單有效 |
| B. Exponential backoff | 未採用 | 對 bot 場景過度，cooldown 後直接重置更合適 |

## 調研結論

- 日誌使用 Python stdlib + daily rotation（30 天保留），console + file 雙輸出
- Process supervision 使用 bash wrapper（零依賴、跨平台）
- Crash loop 保護：5 次/600 秒 → cooldown 300 秒
- Watchdog：heartbeat file 監控（120 秒超時 → SIGTERM → 40 秒 → SIGKILL）
