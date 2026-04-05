# Proposal: Module Completion & Project Polish

## Requirements (user's original words, verbatim)

> 幫我規劃底下任務：
> - `modules/` 目錄（7 個 bundled modules 的實際規則檔案尚未建立）
> - 各模組的 `prompt_hook.py`
> - 版本號不同步（pyproject.toml = 0.4.0，`__init__.py` = 0.1.0）
> - README 寫「尚未開始實作」但實際上已有完整程式碼

## Problem

經 planner agent 全面分析後發現：
1. `modules/` 目錄實際上已建立完成，但有 manifest 問題（permissions 路徑不一致、placeholder 宣告遺漏、殘留檔案）
2. prompt_hook 已有基礎版，但缺少 Thread 參與者提醒和訪談上下文偵測
3. 版本號確實分歧（0.4.0 vs 0.1.0），且無防止再發的機制
4. README 內容嚴重過時

## Solution

四項任務按優先級和依賴關係分三批執行：
- **Batch 1**（並行）：版本號同步 + README 更新 + Modules manifest 修正
- **Batch 2a**（前置）：PromptContext 擴充 + Dispatcher 修改
- **Batch 2b+2c**（並行）：slack hook 完善 + requirement hook 實作

## Change Scope

| 檔案 | 變更類型 | 說明 |
|------|----------|------|
| `src/opentree/__init__.py` | 修改 | importlib.metadata 動態版本讀取 |
| `src/opentree/runner/__init__.py` | 修改 | 版本 re-export |
| `src/opentree/core/prompt.py` | 修改 | PromptContext +2 欄位 |
| `src/opentree/runner/dispatcher.py` | 修改 | `_check_new_user` + context 傳入 + 未使用 import 清理 |
| `modules/slack/prompt_hook.py` | 修改 | Thread 參與者提醒 + sanitization |
| `modules/requirement/prompt_hook.py` | 重寫 | 完整訪談上下文偵測 |
| `modules/*/opentree.json` (7 files) | 修改 | permissions 路徑 + placeholder 補齊 |
| `README.md` | 重寫 | 完整英文文件 |
| `CHANGELOG.md` | 更新 | 新增 8 Added, 2 Changed, 1 Fixed |
| `tests/test_version.py` | 新增 | +3 版本一致性測試 |
| `tests/test_prompt.py` | 修改 | +2 新欄位測試 |
| `tests/test_dispatcher.py` | 修改 | +5 `_check_new_user` 測試 |
| `tests/test_prompt_hooks.py` | 修改 | +11 hook 測試 |

## Risk

- **LOW**：所有變更有完整測試覆蓋（1123 passed, 0 skipped, 89% coverage）
- ~~**MEDIUM**：requirement hook 的 pyyaml 依賴未加入 pyproject.toml~~ → 已解決：pyyaml>=6.0 加入主依賴
- ~~**KNOWN**：`thread_participants` 欄位已宣告但 Dispatcher 尚未填入~~ → 已解決：`_extract_thread_participants` 已實作
