# Research: OpenTree Deployment Architecture

## Background

Bot_Walter 部署依賴 opentree source repo 路徑（`bin/run.sh` 硬編碼），
需要重新設計部署架構，讓 bot instance 可以獨立運行、安全更新。

使用者期望的流程：安裝套件 → onboard → 更新時不影響資料和記憶。

## 候選方案

### 方案 A：PyPI 發布（Claude Code CLI 模式）

| 方面 | 說明 |
|------|------|
| 安裝 | `uv tool install opentree` |
| Code | `~/.local/share/uv/tools/opentree/`（isolated venv） |
| Data | `~/.opentree/`（完全分離） |
| Modules | wheel 內 `opentree/_bundled_modules/`（via hatch force-include） |
| 更新 | `uv tool upgrade opentree` + `opentree module update --all` |
| 優點 | 使用者體驗最佳、完全解耦、多機器部署容易 |
| 缺點 | 需 CI/CD 發布流程、每次改 module 要發版 |
| 複雜度 | 高 |

### 方案 B：Clone & Instance（Flask Instance Folder 模式）

| 方面 | 說明 |
|------|------|
| 安裝 | `git clone` → `cd opentree` → `uv run opentree init` |
| Code | repo 內 `src/` + `modules/`（git tracked） |
| Data | repo 內 `instance/`（.gitignored） |
| 更新 | `git pull` + `opentree module update --all` |
| 優點 | 最快落地、Source 可見、開發迭代快 |
| 缺點 | 需 .gitignore 紀律、`git clean -fd` 危險 |
| 複雜度 | 低 |

### 方案 C：混合模式（Clone + Local venv Install）

| 方面 | 說明 |
|------|------|
| 安裝 | `git clone` → `uv pip install -e .` → `opentree init` |
| Code | repo 內但透過 editable install |
| Data | 外部 `~/.opentree/` 或指定路徑 |
| 更新 | `git pull`（editable 自動生效） |
| 複雜度 | 中 |

## 關鍵技術發現

### Claude Code CLI 架構

- Binary: `~/.local/share/claude/versions/X.Y.Z`（~230MB ELF）
- Symlink: `~/.local/bin/claude` → 最新版
- Data: `~/.claude/`（完全獨立，更新不觸碰）
- 三層 config: global(`~/.claude/`) > project(`.claude/`) > local(`.claude/local/`)

### Modules 打包進 Wheel（hatchling）

```toml
[tool.hatch.build.targets.wheel.force-include]
"modules" = "opentree/_bundled_modules"
```

Runtime 用 `importlib.resources.files("opentree").joinpath("_bundled_modules")` 存取。
Python 3.11 需自訂 `_copy_traversable()` helper（`as_file()` 對目錄支援需 3.12+）。

### Module Resolution 分層

```
1. ~/.opentree/modules/     使用者自訂（override）
2. wheel 內 _bundled_modules  隨版本發布（default）
```

### uv tool install 是現代 Python 的 npm install -g

- Isolated venv per tool
- `uv tool upgrade` 完整替換
- 3 秒安裝、零依賴衝突

## 調研結論

**推薦演進路線：Phase 1 → Phase 2**

| 階段 | 模式 | 適用時機 |
|------|------|----------|
| Phase 1 | B. Clone & Instance | 現在（開發期、快速驗證） |
| Phase 2 | A. PyPI 發布 | 穩定後（有外部使用者時） |

Phase 1 → Phase 2 遷移成本低（改 pyproject.toml + `_resolve_home()` + `_bundled_modules_dir()`）。

## 參考資料

- Claude Code 本地 storage 設計分析
- Flask Instance Folder 模式
- platformdirs (Python XDG 目錄庫)
- hatchling force-include 文件
- importlib.resources.files() 用法
- uv tool install 文件

（完整來源清單見 `/tmp/opentree-research-claude-cli-model.md` 和 `/tmp/opentree-research-deployment.md`）
