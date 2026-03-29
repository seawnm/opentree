# Web Research: JSON Settings File Merging Patterns
Date: 2026-03-29
Keywords: ["JSON merge", "settings.json", "deep merge", "conflict resolution", "permission arrays", "atomic write", "Python"]

## Source 1: Claude Code Settings — Official Merge Behavior
- URL: https://code.claude.com/docs/en/settings
- Relevance: HIGH
### Key Excerpts
> When the same setting is configured in multiple scopes, more specific scopes take precedence: Managed (highest) > Command line > Local > Project > User (lowest).
> Array settings merge across scopes — arrays are concatenated and deduplicated, not replaced.
> Permission rules follow the format `Tool` or `Tool(specifier)`. Rules are evaluated in order: deny rules first, then ask, then allow. The first matching rule wins.
> For managed-settings, `managed-settings.json` is merged first as the base, then all `*.json` files in `managed-settings.d/` are sorted alphabetically and merged on top. Later files override earlier ones for scalar values; arrays are concatenated and de-duplicated; objects are deep-merged.
### Takeaways
- Claude Code 自身的合併策略：標量值覆蓋、陣列 concat + dedup、物件 deep-merge
- Permission 評估順序：deny > ask > allow（deny 優先）
- drop-in directory 支援數字前綴排序（如 `10-security.json`, `20-tools.json`）
- 這是 OpenTree 必須遵循的合併語義

## Source 2: Claude Code Permission Precedence
- URL: https://deepwiki.com/FlorianBruniaux/claude-code-ultimate-guide/4.2-settings-and-permissions-files
- Relevance: HIGH
### Key Excerpts
> If your user settings allow `Bash(npm run *)` but a project's shared settings deny it, the project setting takes precedence and the permission is blocked.
> Settings combine; they don't override. A project-level deny cannot be undone by a local allow.
### Takeaways
- **Deny 永遠優先**：不論 scope 高低，deny 規則不可被 allow 覆蓋
- 這是安全設計：高層級的 deny 是不可逆的
- OpenTree 合併 permission arrays 時必須尊重此語義

## Source 3: jsonmerge Library
- URL: https://pypi.org/project/jsonmerge/
- Relevance: MEDIUM
### Key Excerpts
> jsonmerge allows you to merge a series of JSON documents into a single one.
> Strategies: `overwrite` (replace), `discard` (keep base), `append` (combine arrays), `arrayMergeById` (merge by ID field), `objectMerge` (recursive dict merge).
> The `mergeStrategy` keyword in JSON Schema specifies which strategy applies to document sections.
> `arrayMergeById` identifies matching array items using ID fields and merges them hierarchically.
### Takeaways
- jsonmerge 提供 schema-driven 的合併策略
- `arrayMergeById` 對 permission rules 可能有用（但 Claude Code 的 rules 是字串不是物件）
- `objectMerge` 是物件的預設策略（遞迴合併）
- 可以用 JSON Schema 指定每個欄位的合併策略

## Source 4: Dynaconf — Configuration Merging
- URL: https://www.dynaconf.com/merging/
- Relevance: LOW
### Key Excerpts
> Dynaconf provides global and local tools to control if conflicting settings will be merged or override one another.
> Only container types (list and dict) can be merged by default.
### Takeaways
- Dynaconf 的做法：只有 list/dict 可合併，其他都覆蓋
- 與 Claude Code 的行為一致

## Source 5: Atomic Write Patterns for JSON Files
- URL: https://code.activestate.com/recipes/579097-safely-and-atomically-write-to-a-file/
- Relevance: HIGH
### Key Excerpts
> The core atomic write pattern: create a temporary file, write data, rename to target.
> Creating the temp file in the same directory as the target is critical — if on a different filesystem, os.rename performs a non-atomic copy-and-delete.
### Takeaways
- 原子寫入模式：tempfile + fsync + rename
- 必須在同一 filesystem 上建立 tempfile
- `os.replace()` 比 `os.rename()` 更安全（跨平台、自動覆蓋）

## Source 6: Python os.replace() and Atomic Operations
- URL: https://zetcode.com/python/os-replace/
- Relevance: HIGH
### Key Excerpts
> `os.replace()` is designed for atomic replacement on the same filesystem.
> Maps to atomic rename/replace semantics on POSIX.
### Takeaways
- `os.replace()` 是 Python 標準庫的原子替換方法
- POSIX 上是真正的原子操作
- Windows 上也可用但需注意跨磁碟機的情況

## Source 7: Crash-Safe JSON at Scale
- URL: https://dev.to/constanta/crash-safe-json-at-scale-atomic-writes-recovery-without-a-db-3aic
- Relevance: MEDIUM
### Key Excerpts
> Write to a temporary file, sync to disk with os.fsync, then atomic rename.
> The target is always in a consistent state: either completely preserved or completely replaced.
### Takeaways
- 完整的 crash-safe 流程：write → fsync → rename
- 確保目標檔案永遠是完整的

## Summary

### Claude Code settings.json 合併語義（OpenTree 必須遵循）

| 資料類型 | 合併行為 | 範例 |
|----------|----------|------|
| 標量（string, number, bool） | 後者覆蓋前者 | `model: "opus"` 覆蓋 `model: "sonnet"` |
| 陣列（array） | Concat + Dedup | `allow: ["A"]` + `allow: ["B"]` → `allow: ["A", "B"]` |
| 物件（object） | Deep merge（遞迴） | 巢狀物件遞迴合併 |

### Permission Arrays 合併策略

```
User:    allow: ["Bash(git *)"]          deny: []
Project: allow: ["Bash(npm run *)"]      deny: ["Bash(curl *)"]
Local:   allow: ["Bash(docker *)"]       deny: []

合併結果:
  allow: ["Bash(git *)", "Bash(npm run *)", "Bash(docker *)"]
  deny:  ["Bash(curl *)"]

評估順序: deny 先匹配 → ask → allow
```

### 推薦的 OpenTree 合併實作

```python
import json
from pathlib import Path
from typing import Any

def deep_merge(base: dict, overlay: dict) -> dict:
    """Deep merge following Claude Code semantics."""
    result = dict(base)  # immutable: create new dict
    for key, value in overlay.items():
        if key in result:
            base_val = result[key]
            if isinstance(base_val, dict) and isinstance(value, dict):
                result[key] = deep_merge(base_val, value)
            elif isinstance(base_val, list) and isinstance(value, list):
                # Concat + dedup (preserve order)
                seen = set()
                merged = []
                for item in base_val + value:
                    item_key = json.dumps(item, sort_keys=True) if isinstance(item, dict) else item
                    if item_key not in seen:
                        seen.add(item_key)
                        merged.append(item)
                result[key] = merged
            else:
                result[key] = value  # scalar: overlay wins
        else:
            result[key] = value
    return result

def atomic_write_json(path: Path, data: dict) -> None:
    """Atomic JSON write with fsync."""
    import os
    import tempfile

    content = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    dir_path = path.parent
    dir_path.mkdir(parents=True, exist_ok=True)

    # Create temp file in same directory (same filesystem)
    fd, tmp_path = tempfile.mkstemp(dir=str(dir_path), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, str(path))
    except:
        os.unlink(tmp_path)
        raise
```

### 衝突解決原則

1. **Deny 永遠優先**：合併 permission arrays 時，deny 規則從所有 scope 收集，不可被 allow 覆蓋
2. **陣列不取代**：永遠 concat + dedup，不能用 overlay 的 array 直接替換 base
3. **標量由高 scope 決定**：Local > Project > User
4. **原子寫入**：修改 settings.json 必須用 atomic write pattern，避免 crash 時檔案損壞
5. **備份**：Claude Code 自動保留 5 個 timestamped backups，OpenTree 也應保留修改前的備份
