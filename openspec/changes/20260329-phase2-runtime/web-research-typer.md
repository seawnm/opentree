# Web Research: Typer CLI Framework Best Practices
Date: 2026-03-29
Keywords: ["Typer", "CLI", "Python", "subcommand", "CliRunner", "testing", "architecture"]

## Source 1: Typer CLI Best Practices and Coding Standards
- URL: https://www.projectrules.ai/rules/typer
- Relevance: HIGH
### Key Excerpts
> Directory Layout: `my_cli/main.py` (entry point), `commands/` (subcommands), `utils/` (helpers), `models/` (data structures)
> Each module should have a single, well-defined purpose (Single Responsibility Principle).
> Organize subcommands into separate modules within a dedicated `commands/` directory.
> Use dependency injection to provide dependencies to command functions via type hinting.
> Commands should be intuitive, lowercase, meaningful, and avoid conflicts with existing commands.
> Design your CLI to read from stdin and write to stdout and stderr appropriately.
> Return 0 for success, non-zero values for failures.
### Takeaways
- 標準目錄結構：`commands/`、`utils/`、`models/`
- 每個模組單一職責
- 子命令拆分到獨立檔案
- 使用 dependency injection
- 遵循 Unix 慣例（stdin/stdout/stderr、exit codes）

## Source 2: Python Typer Subcommands and Modular CLI
- URL: https://pytutorial.com/python-typer-subcommands-and-modular-cli/
- Relevance: HIGH
### Key Excerpts
> Use `app.add_typer()` to integrate command modules.
> The recommended architecture separates commands into dedicated files.
> Structure enables hierarchical commands: `python app.py create user john`.
> Group related commands in modules and maintain consistent naming conventions.
### Takeaways
- `app.add_typer(sub_app, name="group")` 是組織子命令群的標準方式
- 每個子命令群一個檔案，每個檔案建立自己的 `typer.Typer()` 實例
- 支援巢狀子命令：`opentree install`, `opentree remove`, `opentree list`

## Source 3: Typer Official Testing Tutorial
- URL: https://typer.tiangolo.com/tutorial/testing/
- Relevance: HIGH
### Key Excerpts
> CliRunner is a utility from Click for testing CLI apps, and it works perfectly with Typer.
> Use `runner.invoke(app, ["arg1", "--option", "value"])` to invoke CLI with test arguments.
> Check exit code: `assert result.exit_code == 0`
> Check output: `assert "expected text" in result.output`
> Use the `input` parameter to simulate stdin input.
### Takeaways
- 使用 `typer.testing.CliRunner`（基於 Click 的 CliRunner）
- `runner.invoke(app, args)` 是基本測試模式
- 檢查 `result.exit_code` 和 `result.output`
- `input` 參數模擬 stdin
- `runner.isolated_filesystem()` 用於檔案操作測試

## Source 4: Testing Typer Apps with pytest
- URL: https://pytest-with-eric.com/pytest-advanced/pytest-argparse-typer/
- Relevance: HIGH
### Key Excerpts
> Create a runner object which will "invoke" your command line application.
> Inside the test function, add assert statements to ensure everything in the result is as expected.
> Parametrized testing: pytest parametrization allows running tests against a variety of input data.
### Takeaways
- pytest + CliRunner 是標準測試組合
- 使用 `@pytest.mark.parametrize` 進行多組輸入測試
- 測試檔案命名以 `test_` 開頭

## Source 5: Building CLI Tools with Python — Click, Typer, argparse
- URL: https://dasroot.net/posts/2025/12/building-cli-tools-python-click-typer-argparse/
- Relevance: MEDIUM
### Key Excerpts
> Typer is the modern standard for new Python CLI projects in 2025-2026.
> Typer's integration with typing and pydantic makes it ideal for projects that emphasize type safety.
> Typer supports multi-level subcommand trees without writing verbose code upfront.
### Takeaways
- Typer 是 2025-2026 的 Python CLI 首選
- 基於 type hints 自動產生 help 和驗證
- 支援 pydantic 整合（structured validation）

## Source 6: Python CLI Tools Guide — Click and Typer
- URL: https://devtoolbox.dedyn.io/blog/python-click-typer-cli-guide
- Relevance: MEDIUM
### Key Excerpts
> Typer's nested CLI structure and subcommand support are well-suited for complex CLIs like docker or git.
> 2025-2026 best practice emphasizes actionable error messages with suggestions.
> Adhere to standard exit codes for interoperability with CI/CD systems.
### Takeaways
- 錯誤訊息應包含建議動作
- Exit code 遵循標準：0=成功，1=一般錯誤，2=用法錯誤

## Summary

### 推薦的 OpenTree CLI 架構

```
opentree/
├── __init__.py
├── __main__.py          # entry point: python -m opentree
├── cli/
│   ├── __init__.py
│   ├── main.py          # app = typer.Typer(); register sub-apps
│   ├── install.py       # opentree install <source>
│   ├── remove.py        # opentree remove <target>
│   ├── list_cmd.py      # opentree list (避開 Python reserved word)
│   ├── refresh.py       # opentree refresh [--all | <target>]
│   └── status.py        # opentree status
├── core/
│   ├── __init__.py
│   ├── linker.py        # symlink/junction/copy 邏輯
│   ├── scanner.py       # 掃描 rules 目錄
│   ├── merger.py        # settings.json 合併
│   └── config.py        # opentree 自身設定
├── models/
│   ├── __init__.py
│   ├── rule.py          # Rule dataclass
│   └── manifest.py      # Manifest dataclass
└── tests/
    ├── test_install.py
    ├── test_remove.py
    ├── test_linker.py
    └── test_merger.py
```

### 子命令設計

| 命令 | 用途 | 範例 |
|------|------|------|
| `install` | 從 source 安裝 rules 到 target | `opentree install ~/my-rules --target ./project` |
| `remove` | 移除已安裝的 rules | `opentree remove ./project` |
| `list` | 列出已安裝的 rules 和狀態 | `opentree list` |
| `refresh` | 重新同步（symlink 斷裂修復） | `opentree refresh --all` |
| `status` | 檢查 rules 狀態 | `opentree status` |

### 測試策略

```python
from typer.testing import CliRunner
from opentree.cli.main import app

runner = CliRunner()

def test_install_creates_symlinks(tmp_path):
    source = tmp_path / "rules"
    source.mkdir()
    (source / "test.md").write_text("# Test Rule")

    target = tmp_path / "project" / ".claude" / "rules"

    result = runner.invoke(app, ["install", str(source), "--target", str(target)])
    assert result.exit_code == 0
    assert (target / "test.md").exists()
```

### 關鍵實作建議

1. 使用 `typer.Typer(help="...")` 提供 app 層級描述
2. 每個子命令用 docstring 提供 help
3. 使用 `typer.Option()` 和 `typer.Argument()` 提供參數描述
4. 錯誤時用 `typer.echo(msg, err=True)` 輸出到 stderr
5. 使用 `raise typer.Exit(code=1)` 設定 exit code
6. 避免使用 `list` 作為命令名（Python reserved word），用 `list_cmd` 模組名但 `@app.command("list")` 設定命令名
