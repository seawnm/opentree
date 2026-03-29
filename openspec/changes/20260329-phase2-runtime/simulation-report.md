# Phase 2 Flow Simulation Report

> 日期：2026-03-29
> 範圍：Normal 8 + Edge 25 = 33 scenarios

## 摘要

| 嚴重度 | 數量 | 需處理 |
|--------|------|--------|
| CRITICAL | 4 | 實作前必須解決 |
| HIGH | 5 | 實作前必須納入設計 |
| MEDIUM | 4 | 實作時處理 |
| LOW | 2 | 記錄，延後 |

## CRITICAL Issues（阻擋實作）

### C1. Registry 無寫入鎖（E20/E22）
**問題**：兩個 CLI 指令同時 load→modify→save registry.json，last writer wins，另一個的變更靜默丟失。
**修正**：加 `fcntl.flock()` context manager，從 load 到 save 持鎖。

### C2. Link Method 未持久化（E6）
**問題**：symlink fallback 到 copy 後，update/remove 仍假設 symlink → `IsADirectoryError`。
**修正**：RegistryEntry 加 `link_method: str`（"symlink"|"junction"|"copy"）。

### C3. Registry.save 缺 fsync + 無 crash recovery（E14）
**問題**：斷電時 .tmp 存在但 registry.json 遺失，下次啟動視為空 registry。
**修正**：save 加 `os.fsync()`；load 加 `.tmp` recovery 邏輯。

### C4. CLAUDE_CONFIG_DIR 共享無保護（E25）
**問題**：兩個 OPENTREE_HOME 共用同一 CLAUDE_CONFIG_DIR → permissions 互相覆蓋。
**修正**：project-level settings.json 管理 permissions（不依賴 CLAUDE_CONFIG_DIR），或加 binding 檢查。

## HIGH Issues（需納入設計）

### H1. Permission 無歸屬追蹤（E4/E15）
**問題**：settings.json 的 allowedTools 無法區分哪些 pattern 來自哪個模組。remove 時無法只移除該模組的 permissions。
**修正**：加 `config/permissions.json` 作為 source of truth，settings.json 從此檔案重新生成。

### H2. 無 Reverse Dependency Check（E12）
**問題**：remove slack 時未檢查 requirement depends_on slack。
**修正**：RegistryEntry 加 `depends_on` 或 remove 時重新讀 manifest 檢查。

### H3. Pre-installed Module Remove 無保護（E13）
**問題**：可以 remove core/guardrail 等必要模組。
**修正**：CLI 層 check module_type，pre-installed 拒絕 remove（除非 --force）。

### H4. Generator Crash on Missing Triggers（E3）
**問題**：validator 允許無 triggers 的模組安裝（warning），但 generator 存取 triggers 時 crash。
**修正**：generator 加 guard；或升級 MISSING_TRIGGERS 為 error。

### H5. 使用者手動檔案被 Remove 刪除（E9）
**問題**：rules 目錄下使用者新增的非 symlink 檔案在 remove 時被 rmtree 刪除。
**修正**：remove 前掃描非 symlink 檔案，移至 .trash/ 保留。

## MEDIUM Issues（實作時處理）

- **M1**：空 registry 生成空 CLAUDE.md（E1）→ 加 assert
- **M2**：Windows backslash 在 placeholder 替換中 crash（E5）→ 用 str.replace + 正規化
- **M3**：install 已安裝模組無版本檢查（E11）→ 路由到 update
- **M4**：CLAUDE_CONFIG_DIR 目錄不存在（E24）→ 啟動時 mkdir -p

## 設計修正方案

### RegistryEntry 需新增欄位

```python
@dataclass(frozen=True)
class RegistryEntry:
    name: str
    version: str
    module_type: str
    installed_at: str
    source: str
    link_method: str = "symlink"    # NEW: "symlink"|"junction"|"copy"
    depends_on: tuple[str, ...] = () # NEW: for reverse dep check
```

### 新增檔案

| 檔案 | 用途 |
|------|------|
| config/permissions.json | 模組 permissions 歸屬追蹤 |
| config/registry.lock | 寫入鎖 |

### Settings.json 生成策略

```
安裝/移除時：
1. 更新 permissions.json（per-module 歸屬）
2. 從 permissions.json 重新聚合所有 permissions
3. 合併使用者自訂 settings
4. 原子寫入 settings.json
```
