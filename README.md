# OpenTree

安全限制的 Claude Code CLI wrapper + 模組化個人 AI agent 平台。

## 狀態

🏗️ **架構規劃中** — 尚未開始實作。

## 文件

- [架構提案](openspec/changes/20260329-initial-architecture/proposal.md)
- [調研記錄](openspec/changes/20260329-initial-architecture/research.md)
- [決策記錄](openspec/changes/20260329-initial-architecture/decisions.md)

## 核心概念

- 每個使用者擁有獨立的 bot 實例
- 所有功能皆為模組（包含 Slack 連線）
- Admin 預設安全邊界，使用者不可突破但可在範圍內擴充
- 底層調用 Claude Code CLI，最小化自建邏輯
