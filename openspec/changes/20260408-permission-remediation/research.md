# Research: Permission Remediation

## 調研背景

OpenTree v0.5.0 部署後功能全面失敗，根因之一是 `SettingsGenerator.generate_settings()` 輸出的 settings.json 格式可能不正確。目前輸出 `{"allowedTools": [...], "denyTools": [...]}` 頂層 key，但 Claude Code 文檔和 JSON Schema 指定的是 `{"permissions": {"allow": [...], "deny": [...]}}`。需要確認正確格式、permission mode 選擇策略、以及 bot/headless 使用的最佳實踐。

## 候選方案

### 1. settings.json 權限格式

| 方案 | 評估結果 | 未採用原因 |
|------|----------|------------|
| `allowedTools` / `denyTools` 頂層 key | ❌ 不合法 | JSON Schema 無此 key；文檔無此格式；這是 CLI flag 名稱（`--allowedTools` / `--disallowedTools`），不是 settings.json key |
| `permissions.allow` / `permissions.deny` | ✅ 採用 | 官方文檔、JSON Schema、所有範例一致使用此格式 |
| 混合使用（兩者都寫） | ❌ 不可行 | Schema 會報 validation error；Claude Code 只讀 `permissions` 物件 |

**確認的正確格式**：

```json
{
  "permissions": {
    "allow": ["Bash(npm run *)", "Read", "Edit"],
    "deny": ["Bash(curl *)", "Read(./.env)"],
    "ask": ["Bash(git push *)"],
    "defaultMode": "dontAsk",
    "additionalDirectories": ["../docs/"],
    "disableBypassPermissionsMode": "disable"
  }
}
```

**`permissions` 物件的完整 key 清單**（來自 JSON Schema）：
- `allow`: array of permission rules — 自動允許
- `deny`: array of permission rules — 自動拒絕（最高優先）
- `ask`: array of permission rules — 需確認（headless 模式下等同 deny）
- `defaultMode`: enum — 權限模式預設值
- `additionalDirectories`: array of strings — 額外工作目錄
- `disableBypassPermissionsMode`: `"disable"` — 禁止使用 bypass 模式
- `skipDangerousModePermissionPrompt`: boolean — 跳過 bypass 模式的確認提示

**Rule 評估順序**：deny → ask → allow，第一個匹配的規則生效。

### 2. Permission Mode（headless/bot 使用）

| 方案 | 評估結果 | 未採用原因 |
|------|----------|------------|
| 無 `--permission-mode`（預設 `default`） | ❌ 不適用 bot | 會暫停等待使用者確認，headless 模式下無人可確認 |
| `--permission-mode acceptEdits` | ❌ 部分解決 | 檔案編輯免確認，但 Bash 和網路仍需確認，headless 下會失敗 |
| `--permission-mode plan` | ❌ 不適用 | 只分析不執行，bot 需要實際操作 |
| `--permission-mode auto` | ❌ 限制太多 | 僅 Team/Enterprise + Sonnet 4.6/Opus 4.6 + Anthropic API；背景安全分類器會擋住未知操作；headless 下連續被擋 3 次會 abort |
| `--permission-mode dontAsk` | ✅ 採用（restricted user） | 只允許 `permissions.allow` 中明確列出的工具，其他全部靜默拒絕，完全非互動 |
| `--permission-mode bypassPermissions` | ✅ 採用（owner/admin） | 跳過所有權限提示（protected paths 除外），等同 `--dangerously-skip-permissions` |

**關鍵發現**：

1. **`--dangerously-skip-permissions` 等同 `--permission-mode bypassPermissions`**：文檔明確說明兩者等價。
2. **`dontAsk` 是 CI/bot 的推薦模式**：文檔原文 "useful for locked-down CI runs"。只有 `permissions.allow` 中明確列出的工具可執行；`ask` 規則也會被拒絕（非提示）。
3. **`bypassPermissions` 僅建議用於隔離環境**：文檔原文 "Only use this mode in isolated environments like containers or VMs"。但對於 owner/admin 用戶且環境可控的情況下可接受使用。
4. **Protected paths 在所有模式下都受保護**：`.git`、`.vscode`、`.idea`、`.husky`、`.claude`（部分子目錄除外）。

### 3. CLI Flag vs settings.json 的關係

| CLI Flag | settings.json 對應 | 說明 |
|----------|-------------------|------|
| `--allowedTools "Read,Edit,Bash"` | `permissions.allow` | CLI flag 是單次覆蓋，settings.json 是持久設定 |
| `--disallowedTools "WebFetch"` | `permissions.deny` | 同上 |
| `--permission-mode dontAsk` | `permissions.defaultMode` | CLI flag 覆蓋 settings.json 設定 |
| `--dangerously-skip-permissions` | `permissions.defaultMode: "bypassPermissions"` | 等價 |

**合併規則**：
- Array 設定（allow/deny）跨 scope **串接去重**（managed + user + project + local 全部合併）
- 任何層級的 deny 都不可被其他層級的 allow 覆蓋
- CLI flag 優先級高於 settings.json，但低於 managed settings

## 調研結論

### 格式修正（必要）

`SettingsGenerator` 必須改為輸出 `permissions.allow` / `permissions.deny` 格式。`allowedTools` / `denyTools` 是 CLI flag 名稱，不是 settings.json 的合法 key。

### Permission Mode 策略（建議）

| 使用者類型 | Permission Mode | 搭配 settings.json |
|-----------|----------------|-------------------|
| Owner/Admin | `bypassPermissions` | `permissions.deny` 仍可限制危險操作 |
| Restricted User | `dontAsk` | `permissions.allow` 白名單控制可用工具 |

### Bot/Headless 最佳實踐

1. **使用 `-p` flag**（non-interactive mode）搭配 `--permission-mode`
2. **Restricted user 用 `dontAsk`**：只執行 allow 清單中的工具，安全且可預測
3. **Owner 用 `bypassPermissions`**：跳過確認，最大靈活性
4. **`--allowedTools` 可作為 CLI 層的額外 allow**：會與 settings.json 的 allow 合併
5. **使用 `--bare` 加速**：跳過 hooks/skills/plugins/MCP 載入，適合 CI
6. **settings.json 中設定基線工具**（Read/Write/Edit/Glob/Grep 等），模組專用工具由各模組追加

## 資料來源

- [Claude Code Settings](https://code.claude.com/docs/en/settings) — settings.json 完整格式、Available settings 表、Permission settings 表
- [Configure permissions](https://code.claude.com/docs/en/permissions) — 權限規則語法、managed settings、precedence
- [Choose a permission mode](https://code.claude.com/docs/en/permission-modes) — 所有 mode 的說明、dontAsk/bypassPermissions 行為
- [Run Claude Code programmatically](https://code.claude.com/docs/en/headless) — `-p` flag 用法、`--allowedTools` / `--permission-mode` CLI 範例
- [JSON Schema](https://json.schemastore.org/claude-code-settings.json) — 確認 `permissions` 物件結構、無 `allowedTools` 頂層 key
- [GitHub Issue #18973](https://github.com/anthropics/claude-code/issues/18973) — `--allowedTools` CLI flag 與 `permissions.allow` 的對應關係
