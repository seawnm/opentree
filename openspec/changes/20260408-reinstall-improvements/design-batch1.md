# Design: Batch 1 (Fix 1 + Fix 2 + Fix 3)

> 建立日期：2026-04-08
> 狀態：設計完成，待實作

---

## Part A: 具體設計

---

### Fix 1: init 補齊 `data/logs/`

**檔案**：`src/opentree/cli/init.py`
**位置**：第 382-387 行，`for subdir in (...)` tuple
**改動**：在 `"data/memory"` 後加入 `"data/logs"`

```python
    # 1. Create directory structure
    for subdir in (
        "modules",
        "workspace/.claude/rules",
        "data/memory",
        "data/logs",       # <-- 新增
        "config",
    ):
        (opentree_home / subdir).mkdir(parents=True, exist_ok=True)
```

**新增 import**：無

---

### Fix 2: init 自動遷移 legacy `.env` → `.env.local`

**檔案**：`src/opentree/cli/init.py`
**位置**：第 591 行（`_ensure_slack_deps` 區塊結束後）與第 592 行（`# Generate config/.env.defaults`）之間插入
**新增 import**：無（已有 `shutil`, `Path`, `typer`）

#### 新增模組層級輔助函式（插入在 `_PLACEHOLDER_PREFIXES` 附近，或 init.py 的 helpers 區塊）

在 `init.py` 的 helpers 區塊（約第 46 行 `# Helpers` 之後）新增：

```python
# Prefixes indicating a .env placeholder (mirrors bot.py _PLACEHOLDER_PREFIXES).
_PLACEHOLDER_PREFIXES = (
    "xoxb-your-",
    "xapp-your-",
    "your-",
    "xoxb-xxx",
    "xapp-xxx",
)


def _env_has_real_tokens(path: Path) -> bool:
    """Return True if *path* contains at least one non-placeholder token value.

    Reads the file line by line, looking for KEY=VALUE lines where the
    value does NOT start with any known placeholder prefix.
    Only checks SLACK_BOT_TOKEN and SLACK_APP_TOKEN.
    """
    target_keys = {"SLACK_BOT_TOKEN", "SLACK_APP_TOKEN"}
    try:
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip()
            # Strip surrounding quotes
            if len(value) >= 2 and value[0] in ('"', "'") and value[0] == value[-1]:
                value = value[1:-1]
            if key not in target_keys:
                continue
            if not value:
                continue
            is_placeholder = any(value.startswith(p) for p in _PLACEHOLDER_PREFIXES)
            if not is_placeholder:
                return True
    except (OSError, UnicodeDecodeError):
        return False
    return False
```

#### 遷移邏輯（插入位置：第 591 行之後、第 592 行 `# Generate config/.env.defaults` 之前）

```python
    # Migrate legacy config/.env -> config/.env.local (if real tokens present)
    legacy_env = opentree_home / "config" / ".env"
    env_local = opentree_home / "config" / ".env.local"
    if legacy_env.exists() and _env_has_real_tokens(legacy_env):
        if env_local.exists():
            typer.echo(
                "  WARNING: Legacy config/.env contains real tokens, "
                "but config/.env.local already exists.\n"
                "  Please manually merge config/.env into config/.env.local, "
                "then remove config/.env.",
                err=True,
            )
        else:
            shutil.copy2(legacy_env, env_local)
            try:
                env_local.chmod(0o600)
            except OSError:
                pass
            typer.echo("  Migrated config/.env -> config/.env.local")
```

**設計要點**：
1. 遷移在 `.env.defaults` 生成之前執行，確保 `.env.local` 已就位，後續 bot 啟動時三層 merge 可正常讀到 token
2. 只在 legacy `.env` 含真實 token 時才遷移（`_env_has_real_tokens`）
3. `.env.local` 已存在時不覆寫，輸出 stderr 指引
4. `_PLACEHOLDER_PREFIXES` 在 init.py 中複製一份（非 import），避免 init.py 對 runner 模組的依賴

---

### Fix 3: `_load_tokens` placeholder fallback

**檔案**：`src/opentree/runner/bot.py`
**改動 1**：提取 `_is_placeholder()` 為模組層級函式（第 31 行附近）
**改動 2**：在 `_load_tokens` 的三層 merge 後（第 213 行之後），加入 placeholder fallback 邏輯

#### 改動 1：提取 `_is_placeholder()`

將現有的 `_validate_not_placeholder` 重構為兩個函式：

```python
def _is_placeholder(value: str) -> bool:
    """Return True if *value* looks like a .env.example placeholder."""
    return any(value.startswith(prefix) for prefix in _PLACEHOLDER_PREFIXES)


def _validate_not_placeholder(value: str, name: str) -> None:
    """Raise RuntimeError if *value* looks like a .env.example placeholder."""
    if _is_placeholder(value):
        # Find which prefix matched for the error message
        for prefix in _PLACEHOLDER_PREFIXES:
            if value.startswith(prefix):
                raise RuntimeError(
                    f"{name} appears to be a placeholder (starts with '{prefix}'). "
                    "Update your .env file."
                )
```

#### 改動 2：placeholder fallback（在 `_load_tokens` 的第 213 行 `if secrets_path.exists()` 區塊之後）

修改 `_load_tokens` 方法，在三層 merge 完成後、驗證 token 之前，加入 fallback：

```python
        if defaults_path.exists():
            tokens.update(self._parse_env_file(defaults_path))
            loaded_any = True
            if local_path.exists():
                tokens.update(self._parse_env_file(local_path))
            if secrets_path.exists():
                tokens.update(self._parse_env_file(secrets_path))

            # Fallback: if tokens are still placeholders and legacy .env exists,
            # try loading from legacy .env (handles --force re-init scenario).
            bot_val = tokens.get("SLACK_BOT_TOKEN", "")
            app_val = tokens.get("SLACK_APP_TOKEN", "")
            if (
                legacy_path.exists()
                and (_is_placeholder(bot_val) or _is_placeholder(app_val))
            ):
                logger.warning(
                    "Tokens in .env.defaults are placeholders; "
                    "falling back to legacy config/.env at %s. "
                    "Run 'opentree init --force' to migrate.",
                    legacy_path,
                )
                legacy_tokens = self._parse_env_file(legacy_path)
                # Only override placeholder values, preserve real tokens
                for key in ("SLACK_BOT_TOKEN", "SLACK_APP_TOKEN"):
                    if _is_placeholder(tokens.get(key, "")) and key in legacy_tokens:
                        tokens[key] = legacy_tokens[key]

        elif legacy_path.exists():
            # ... (existing legacy branch unchanged)
```

**新增 import**：無

**設計要點**：
1. Fallback 只在 `.env.defaults` 存在但 token 為 placeholder 時觸發
2. 不是全量覆蓋，而是逐 key 判斷：只覆蓋仍為 placeholder 的 key
3. 保留 `_validate_not_placeholder` 在最後的驗證（如果 fallback 後仍為 placeholder 會正常報錯）
4. 發出 WARNING 提示使用者執行遷移

---

## Part B: 流程推演

---

### Fix 1 場景推演

#### S1: 全新安裝（data/logs/ 不存在）

```
場景 S1: 全新安裝
  輸入狀態：opentree_home 不存在或空目錄
  執行路徑：for subdir in (...) → "data/logs" → mkdir(parents=True, exist_ok=True)
  輸出結果：data/logs/ 被建立
  ✅ 符合預期
```

#### S2: --force 重裝（data/logs/ 已存在但為空）

```
場景 S2: --force 重裝，data/logs/ 已存在（空目錄）
  輸入狀態：data/logs/ 存在且為空
  執行路徑：mkdir(parents=True, exist_ok=True) → exist_ok=True 跳過
  輸出結果：目錄保持不變，無錯誤
  ✅ 符合預期
```

#### S3: --force 重裝（data/logs/ 下有舊日誌）

```
場景 S3: --force 重裝，data/logs/ 含舊 .log 檔案
  輸入狀態：data/logs/2026-04-07.log 等日誌檔存在
  執行路徑：mkdir(parents=True, exist_ok=True) → exist_ok=True 跳過
  輸出結果：目錄和日誌檔都保持不變，無錯誤
  ✅ 符合預期（init 不刪除 data/ 下的使用者資料）
```

---

### Fix 2 場景推演

#### S1: 全新安裝（無 legacy .env）

```
場景 S1: 全新安裝
  輸入狀態：config/.env 不存在，config/.env.local 不存在
  執行路徑：legacy_env.exists() → False → 跳過整個遷移區塊
  輸出結果：不遷移，繼續正常生成 .env.defaults
  ✅ 符合預期
```

#### S2: --force 重裝（legacy .env 有真實 token，無 .env.local）

```
場景 S2: --force 重裝，config/.env 含 xoxb-1234/xapp-5678
  輸入狀態：
    - config/.env 存在，含 SLACK_BOT_TOKEN=xoxb-1234..., SLACK_APP_TOKEN=xapp-5678...
    - config/.env.local 不存在
  執行路徑：
    1. legacy_env.exists() → True
    2. _env_has_real_tokens(legacy_env) → True（xoxb-1234 不匹配任何 placeholder prefix）
    3. env_local.exists() → False
    4. shutil.copy2(legacy_env, env_local)
    5. chmod 0o600
    6. typer.echo("  Migrated config/.env -> config/.env.local")
    7. 接續生成 .env.defaults（帶 placeholder token）
  輸出結果：
    - config/.env.local 建立，內容等於原 config/.env
    - config/.env.defaults 建立（帶 placeholder）
    - bot 啟動時三層 merge：.env.defaults(placeholder) + .env.local(真實) → 真實 token 生效
  ✅ 符合預期
```

#### S3: --force 重裝（legacy .env 有真實 token，.env.local 已存在）

```
場景 S3: --force 重裝，.env 有真實 token，.env.local 已存在
  輸入狀態：
    - config/.env 存在，含真實 token
    - config/.env.local 存在（可能是先前的遷移結果或使用者自建）
  執行路徑：
    1. legacy_env.exists() → True
    2. _env_has_real_tokens(legacy_env) → True
    3. env_local.exists() → True
    4. typer.echo("  WARNING: ...please manually merge...", err=True)
  輸出結果：
    - 不覆寫 .env.local
    - stderr 輸出手動遷移指引
  ✅ 符合預期（保護使用者已編輯的 .env.local）
```

#### S4: --force 重裝（legacy .env 只有 placeholder token）

```
場景 S4: --force 重裝，config/.env 含 xoxb-your-bot-token/xapp-your-app-token
  輸入狀態：
    - config/.env 存在，含 SLACK_BOT_TOKEN=xoxb-your-bot-token
  執行路徑：
    1. legacy_env.exists() → True
    2. _env_has_real_tokens(legacy_env) → False
       （xoxb-your- 匹配 _PLACEHOLDER_PREFIXES，xapp-your- 也匹配）
    3. 跳過遷移區塊
  輸出結果：不遷移（placeholder .env 沒有遷移價值）
  ✅ 符合預期
```

#### S5: --force 重裝（legacy .env 格式異常/空檔案）

```
場景 S5: config/.env 存在但內容為空或格式不正確
  輸入狀態：config/.env 存在，內容為 "" 或 "malformed=\n\n#only comments"
  執行路徑：
    1. legacy_env.exists() → True
    2. _env_has_real_tokens(legacy_env):
       - 空檔案：splitlines() → []，for loop 不進入 → return False
       - 只有 comment：line.startswith("#") → continue → return False
       - malformed（無 SLACK_BOT_TOKEN/SLACK_APP_TOKEN key）：key not in target_keys → continue → return False
    3. 條件不成立 → 跳過遷移區塊
  輸出結果：不遷移
  ✅ 符合預期
```

#### S6: force=False 時不走到遷移邏輯

```
場景 S6: 非 --force 模式（首次 init 或 registry 不存在）
  輸入狀態：config/.env 存在（含真實 token），registry.json 不存在
  執行路徑：
    1. reg_path.exists() → False → 跳過「already initialized」檢查
    2. 正常走 init 流程
    3. 遷移邏輯：legacy_env.exists() → True，_env_has_real_tokens() → True
    4. env_local.exists() → False → shutil.copy2 → 遷移成功
  輸出結果：即使 force=False，遷移邏輯仍會執行
  ⚠️ 注意：這是正確行為。遷移邏輯在 step 6（.env.defaults 生成段），此段落的守衛是
     `if not env_defaults.exists() or force`（第 594 行），但遷移邏輯本身在這個
     if 之前，不受 force 條件保護。
     
     分析：首次 init 時 config/.env 存在代表使用者先手動放了 .env，遷移為 .env.local
     是合理行為（確保使用者的 token 不會被 .env.defaults 的 placeholder 遮蓋）。
  ✅ 符合預期（遷移對首次安裝也是安全的）
```

---

### Fix 3 場景推演

#### S1: .env.defaults 有真實 token → 正常載入

```
場景 S1: 正常三層 merge 成功
  輸入狀態：
    - config/.env.defaults: SLACK_BOT_TOKEN=xoxb-real, SLACK_APP_TOKEN=xapp-real
    - 無 .env.local, 無 .env.secrets, 無 legacy .env
  執行路徑：
    1. defaults_path.exists() → True → tokens = {bot: xoxb-real, app: xapp-real}
    2. local_path.exists() → False
    3. secrets_path.exists() → False
    4. bot_val = "xoxb-real", app_val = "xapp-real"
    5. _is_placeholder("xoxb-real") → False, _is_placeholder("xapp-real") → False
    6. fallback 條件不成立 → 跳過
    7. _validate_not_placeholder → 通過
  輸出結果：正常返回 (xoxb-real, xapp-real)
  ✅ 符合預期
```

#### S2: .env.defaults 有 placeholder + legacy .env 有真實 token → fallback 載入

```
場景 S2: --force 重裝後，.env.defaults 為 placeholder，legacy .env 有真實 token
  輸入狀態：
    - config/.env.defaults: SLACK_BOT_TOKEN=xoxb-your-bot-token, SLACK_APP_TOKEN=xapp-your-app-token
    - config/.env（legacy）: SLACK_BOT_TOKEN=xoxb-real, SLACK_APP_TOKEN=xapp-real
    - 無 .env.local
  執行路徑：
    1. defaults_path.exists() → True → tokens = {bot: xoxb-your-bot-token, app: xapp-your-app-token}
    2. local_path.exists() → False
    3. secrets_path.exists() → False
    4. bot_val = "xoxb-your-bot-token", app_val = "xapp-your-app-token"
    5. legacy_path.exists() → True
    6. _is_placeholder("xoxb-your-bot-token") → True
    7. fallback 條件成立！
    8. logger.warning("Tokens in .env.defaults are placeholders; falling back...")
    9. legacy_tokens = parse(legacy .env) → {bot: xoxb-real, app: xapp-real}
    10. tokens["SLACK_BOT_TOKEN"] = "xoxb-real"（placeholder 被覆蓋）
    11. tokens["SLACK_APP_TOKEN"] = "xapp-real"（placeholder 被覆蓋）
    12. _validate_not_placeholder → 通過
  輸出結果：返回 (xoxb-real, xapp-real)，附帶 WARNING 日誌
  ✅ 符合預期
```

#### S3: .env.defaults 有 placeholder + 無 legacy .env → 正常報錯

```
場景 S3: --force 重裝後，.env.defaults 為 placeholder，無 legacy .env 可 fallback
  輸入狀態：
    - config/.env.defaults: SLACK_BOT_TOKEN=xoxb-your-bot-token, SLACK_APP_TOKEN=xapp-your-app-token
    - config/.env 不存在
    - 無 .env.local
  執行路徑：
    1. defaults_path.exists() → True → tokens = {bot: xoxb-your-bot-token, app: xapp-your-app-token}
    2. local_path.exists() → False
    3. secrets_path.exists() → False
    4. bot_val = "xoxb-your-bot-token"
    5. legacy_path.exists() → False
    6. fallback 條件不成立（legacy 不存在）
    7. _validate_not_placeholder("xoxb-your-bot-token", ...) → RuntimeError
  輸出結果：正常拋出 RuntimeError，提示更新 .env
  ✅ 符合預期
```

#### S4: .env.defaults 有 placeholder + .env.local 有真實 token → .env.local 覆蓋

```
場景 S4: .env.defaults placeholder + .env.local 有真實 token（正常遷移後的狀態）
  輸入狀態：
    - config/.env.defaults: SLACK_BOT_TOKEN=xoxb-your-bot-token, SLACK_APP_TOKEN=xapp-your-app-token
    - config/.env.local: SLACK_BOT_TOKEN=xoxb-real, SLACK_APP_TOKEN=xapp-real
    - config/.env（legacy）存在且含真實 token
  執行路徑：
    1. defaults_path.exists() → True → tokens = {bot: xoxb-your-bot-token, app: xapp-your-app-token}
    2. local_path.exists() → True → tokens.update → {bot: xoxb-real, app: xapp-real}
    3. secrets_path.exists() → False
    4. bot_val = "xoxb-real", app_val = "xapp-real"
    5. _is_placeholder("xoxb-real") → False
    6. fallback 條件不成立 → 跳過
    7. _validate_not_placeholder → 通過
  輸出結果：返回 (xoxb-real, xapp-real)，不觸發 fallback
  ✅ 符合預期（.env.local 已覆蓋 placeholder，不需要 fallback）
```

#### S5: 無 .env.defaults + legacy .env 有真實 token → 走原有 elif 分支

```
場景 S5: 尚未 init（或手動刪除 .env.defaults），只有 legacy .env
  輸入狀態：
    - config/.env.defaults 不存在
    - config/.env: SLACK_BOT_TOKEN=xoxb-real, SLACK_APP_TOKEN=xapp-real
  執行路徑：
    1. defaults_path.exists() → False
    2. elif legacy_path.exists() → True
    3. logger.warning("Legacy config/.env detected...")
    4. tokens.update(parse(legacy .env))
    5. loaded_any = True
    6. _validate_not_placeholder → 通過
  輸出結果：返回 (xoxb-real, xapp-real)，附帶 legacy WARNING
  ✅ 符合預期（原有行為不變）
```

---

### 組合場景推演（Fix 2 + Fix 3 聯合）

#### 最佳路徑：--force 重裝完整流程

```
場景：使用者執行 opentree init --force --bot-name DOGI --owner U123

Step 1 (init.py): 建立 data/logs/ → ✅ (Fix 1)
Step 2 (init.py): 偵測 config/.env 含真實 token → 複製為 config/.env.local → ✅ (Fix 2)
Step 3 (init.py): 生成 config/.env.defaults（placeholder token）
Step 4 (bot.py):  bot start → _load_tokens:
  - .env.defaults 載入 → placeholder
  - .env.local 覆蓋 → 真實 token
  - 驗證通過
  → ✅ 正常啟動
```

#### 防禦路徑：Fix 2 遷移未觸發（新安裝），Fix 3 防禦 placeholder

```
場景：使用者首次安裝，手動編輯 .env.defaults 前就啟動 bot

Step 1 (init.py): 建立 data/logs/ → ✅ (Fix 1)
Step 2 (init.py): 無 legacy .env → 遷移跳過 (Fix 2 不觸發)
Step 3 (init.py): 生成 config/.env.defaults（placeholder）
Step 4 (bot.py):  bot start → _load_tokens:
  - .env.defaults 載入 → placeholder
  - 無 .env.local
  - 無 legacy .env → fallback 不觸發
  - _validate_not_placeholder → RuntimeError
  → ✅ 正確報錯，提示更新 .env
```

#### 二重防禦：Fix 2 遷移失敗（.env.local 已存在），Fix 3 fallback 生效

```
場景：使用者二次 --force 重裝，.env.local 已存在但 token 過期/錯誤

Step 1 (init.py): 偵測 config/.env 有真實 token，但 .env.local 已存在 → WARNING（Fix 2 不覆寫）
Step 2 (init.py): 重新生成 .env.defaults（placeholder）
Step 3 (bot.py):  bot start → _load_tokens:
  - .env.defaults → placeholder
  - .env.local → 過期/錯誤 token（但格式正確，不是 placeholder）
  - 驗證通過（不是 placeholder 前綴）
  → ⚠️ 可能 auth_test 失敗，但這是使用者的 token 問題，不是程式 bug
  → ✅ 符合預期（程式層面正確，token 有效性由 Slack API 驗證）
```

---

## 測試計畫

### Fix 1 測試

```python
class TestInitDataLogs:
    def test_init_creates_data_logs_dir(self, ...):
        """init creates data/logs/ directory."""
        # invoke init → assert (home / "data" / "logs").is_dir()

    def test_init_force_preserves_existing_logs(self, ...):
        """--force re-init does not delete existing log files."""
        # create data/logs/old.log → invoke init --force → assert old.log still exists
```

### Fix 2 測試

```python
class TestInitLegacyEnvMigration:
    def test_migrate_legacy_env_to_env_local(self, ...):
        """Legacy .env with real tokens is copied to .env.local."""
    
    def test_no_migrate_when_placeholder_env(self, ...):
        """Legacy .env with placeholder tokens is not migrated."""
    
    def test_no_migrate_when_no_legacy_env(self, ...):
        """No migration when legacy .env does not exist."""
    
    def test_no_overwrite_existing_env_local(self, ...):
        """Existing .env.local is not overwritten; warning printed."""
    
    def test_no_migrate_empty_env(self, ...):
        """Empty legacy .env is not migrated."""

class TestEnvHasRealTokens:
    def test_real_tokens_returns_true(self):
    def test_placeholder_tokens_returns_false(self):
    def test_empty_file_returns_false(self):
    def test_comments_only_returns_false(self):
    def test_missing_file_returns_false(self):
    def test_mixed_real_and_placeholder(self):
        """One real + one placeholder → True (at least one real)."""
```

### Fix 3 測試

```python
class TestIsPlaceholder:
    def test_placeholder_prefixes(self):
        """All known placeholder prefixes return True."""
    def test_real_token_returns_false(self):
    def test_empty_string_returns_false(self):

class TestLoadTokensPlaceholderFallback:
    def test_fallback_from_legacy_env(self, ...):
        """Placeholder in .env.defaults + real tokens in legacy .env → fallback loads."""
    
    def test_no_fallback_when_real_tokens(self, ...):
        """Real tokens in .env.defaults → no fallback."""
    
    def test_no_fallback_when_no_legacy_env(self, ...):
        """Placeholder + no legacy .env → RuntimeError."""
    
    def test_no_fallback_when_env_local_overrides(self, ...):
        """.env.local overrides placeholder → no fallback."""
    
    def test_partial_fallback(self, ...):
        """Only bot_token is placeholder; app_token is real → only bot_token falls back."""
```
