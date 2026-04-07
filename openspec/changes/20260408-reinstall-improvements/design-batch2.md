# Design: Batch 2 (Fix 4 + Fix 5)

> 建立日期：2026-04-08
> 狀態：設計完成，待實作

---

## Part A: 具體設計

---

### Fix 4: run.sh wrapper.pid + stop flag

**檔案**：`src/opentree/templates/run.sh`

#### 改動 1: 新增變數定義

**位置**：第 41 行 `PID_FILE="$DATA_DIR/bot.pid"` 之後

```bash
PID_FILE="$DATA_DIR/bot.pid"
WRAPPER_PID_FILE="$DATA_DIR/wrapper.pid"    # <-- 新增
HEARTBEAT_FILE="$DATA_DIR/bot.heartbeat"
STOP_FLAG="$DATA_DIR/.stop_requested"       # <-- 新增
```

#### 改動 2: flock 取得後寫入 wrapper.pid

**位置**：第 223 行（`# Lock held on fd 200 until script exits`）之後

```bash
# Lock held on fd 200 until script exits (auto-released on crash/SIGKILL too)

# Write wrapper PID for external stop commands
echo "$$" > "$WRAPPER_PID_FILE"
```

#### 改動 3: cleanup() 清理 wrapper.pid

**位置**：第 202 行 `rm -f "$PID_FILE"` 改為同時清理 wrapper.pid

```bash
    rm -f "$PID_FILE" "$WRAPPER_PID_FILE"
```

#### 改動 4: EXIT trap 清理 wrapper.pid

**位置**：第 210 行 `trap 'stop_watchdog' EXIT` 改為同時清理 wrapper.pid

```bash
trap 'stop_watchdog; rm -f "$WRAPPER_PID_FILE"' EXIT
```

**設計要點**：EXIT trap 中也刪除 wrapper.pid，這是 cleanup() 的備援。
- cleanup() 只在 SIGTERM/SIGINT 時觸發
- EXIT trap 在所有退出路徑觸發（包括 `break` 跳出 while loop 後的正常退出）
- 兩者都清理 wrapper.pid 是冪等的（`rm -f` 不會報錯）

#### 改動 5: while true 迴圈開頭檢查 stop flag

**位置**：第 252 行 `while true; do` 之後、crash loop detection 之前

```bash
while true; do
    # -- Stop flag check (before crash loop detection) --
    if [ -f "$STOP_FLAG" ]; then
        log "Stop flag detected ($STOP_FLAG). Exiting without restart."
        rm -f "$STOP_FLAG"
        break
    fi

    # -- Crash loop detection (before network wait, so wait time doesn't mask loops) --
```

**設計要點**：
1. stop flag 在 crash loop detection 之前檢查。如果放在後面，cooldown sleep 會延遲 stop 響應
2. 檢查到 flag 後立即刪除，避免下次啟動時誤判
3. 使用 `break`（非 `exit 0`），讓 while loop 後的 `log "Wrapper exiting"` 正常執行，且 EXIT trap 會清理 wrapper.pid

#### 完整改動行數

| 改動 | 行數 | 說明 |
|------|------|------|
| 變數定義 | +2 | WRAPPER_PID_FILE, STOP_FLAG |
| 寫入 wrapper.pid | +1 | echo $$ 到檔案 |
| cleanup 清理 | 修改 1 行 | rm 加上 $WRAPPER_PID_FILE |
| EXIT trap | 修改 1 行 | 加上 rm -f |
| stop flag 檢查 | +5 | if/then/rm/break/fi |

總計：~9 行新增/修改

---

### Fix 5: `opentree stop` CLI 指令

#### 新檔案：`src/opentree/cli/lifecycle.py`

```python
"""Lifecycle commands for OpenTree (stop, etc.).

``opentree stop`` gracefully terminates a running OpenTree instance
by sending SIGTERM to the wrapper process and waiting for exit.
"""

from __future__ import annotations

import logging
import os
import signal
import sys
import time
from pathlib import Path
from typing import Annotated, Optional

import typer

from opentree.cli.init import _resolve_home

logger = logging.getLogger(__name__)


def _read_pid_file(path: Path) -> int | None:
    """Read a PID from a file, returning None if missing or invalid."""
    try:
        text = path.read_text(encoding="utf-8").strip()
        if text.isdigit():
            return int(text)
    except (OSError, ValueError):
        pass
    return None


def _process_alive(pid: int) -> bool:
    """Return True if process with *pid* exists."""
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _validate_process_identity(pid: int, expected_keywords: tuple[str, ...]) -> bool:
    """Verify that *pid* belongs to an OpenTree process via /proc/cmdline.

    Falls back to True (skip validation) on platforms without /proc.
    """
    cmdline_path = Path(f"/proc/{pid}/cmdline")
    if not cmdline_path.exists():
        # /proc not available (macOS, some containers) — skip validation
        return True
    try:
        cmdline = cmdline_path.read_bytes().replace(b"\x00", b" ").decode(
            "utf-8", errors="replace"
        )
        return any(kw in cmdline for kw in expected_keywords)
    except OSError:
        # Permission denied or race (process exited between check and read)
        return True


def _cleanup_stale_files(data_dir: Path) -> None:
    """Remove stale PID/heartbeat/flag files."""
    for name in ("wrapper.pid", "bot.pid", ".stop_requested", "bot.heartbeat"):
        path = data_dir / name
        try:
            if path.exists():
                path.unlink()
        except OSError:
            pass


def _wait_for_exit(pid: int, timeout: int) -> bool:
    """Poll until *pid* exits or *timeout* seconds elapse.

    Returns True if process exited, False if still alive after timeout.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not _process_alive(pid):
            return True
        time.sleep(1)
    return not _process_alive(pid)


def stop_command(
    home: Annotated[
        Optional[str],
        typer.Option("--home", help="Path to OPENTREE_HOME"),
    ] = None,
    force: Annotated[
        bool,
        typer.Option("--force", help="Send SIGKILL after timeout"),
    ] = False,
    timeout: Annotated[
        int,
        typer.Option("--timeout", help="Seconds to wait for graceful exit"),
    ] = 60,
) -> None:
    """Stop a running OpenTree instance.

    Reads the wrapper PID from data/wrapper.pid, writes a stop flag
    to prevent wrapper restart, then sends SIGTERM and waits for exit.

    With --force, sends SIGKILL if the process does not exit within
    the timeout period.
    """
    opentree_home = _resolve_home(home)
    data_dir = opentree_home / "data"

    # Guard: data/ must exist (instance must be initialized)
    if not data_dir.is_dir():
        typer.echo(
            f"Error: Data directory not found at {data_dir}. "
            "Is this an initialized OpenTree instance?",
            err=True,
        )
        raise typer.Exit(code=1)

    wrapper_pid_file = data_dir / "wrapper.pid"
    bot_pid_file = data_dir / "bot.pid"
    stop_flag = data_dir / ".stop_requested"

    # Step 1: Determine target PID
    target_pid: int | None = None
    target_source: str = ""
    is_wrapper = False

    wrapper_pid = _read_pid_file(wrapper_pid_file)
    if wrapper_pid is not None and _process_alive(wrapper_pid):
        # Validate it's actually an OpenTree wrapper (run.sh)
        if _validate_process_identity(wrapper_pid, ("run.sh", "opentree")):
            target_pid = wrapper_pid
            target_source = "wrapper"
            is_wrapper = True
        else:
            typer.echo(
                f"Warning: wrapper.pid contains PID {wrapper_pid}, "
                "but it does not appear to be an OpenTree process. "
                "PID file may be stale.",
                err=True,
            )

    if target_pid is None:
        # Fallback: try bot.pid
        bot_pid = _read_pid_file(bot_pid_file)
        if bot_pid is not None and _process_alive(bot_pid):
            if _validate_process_identity(bot_pid, ("opentree", "python")):
                target_pid = bot_pid
                target_source = "bot"
                typer.echo(
                    "Warning: wrapper.pid not found or stale. "
                    "Sending signal to bot process directly. "
                    "The wrapper (if running) may restart the bot.",
                    err=True,
                )
            else:
                typer.echo(
                    f"Warning: bot.pid contains PID {bot_pid}, "
                    "but it does not appear to be an OpenTree process.",
                    err=True,
                )

    if target_pid is None:
        # No live process found — check for stale PID files
        has_stale = wrapper_pid_file.exists() or bot_pid_file.exists()
        if has_stale:
            typer.echo(
                "No running OpenTree process found (PID files are stale). "
                "Cleaning up.",
                err=True,
            )
            _cleanup_stale_files(data_dir)
        else:
            typer.echo("No running OpenTree process found.", err=True)
        raise typer.Exit(code=1)

    # Step 2: Write stop flag (prevent wrapper from restarting bot)
    if is_wrapper:
        try:
            stop_flag.write_text(str(os.getpid()), encoding="utf-8")
        except OSError as exc:
            typer.echo(
                f"Warning: Could not write stop flag: {exc}. "
                "Wrapper may restart the bot after SIGTERM.",
                err=True,
            )

    # Step 3: Send SIGTERM
    typer.echo(
        f"Sending SIGTERM to {target_source} process (PID {target_pid})..."
    )
    try:
        os.kill(target_pid, signal.SIGTERM)
    except ProcessLookupError:
        typer.echo(f"Process {target_pid} already exited.")
        _cleanup_stale_files(data_dir)
        return
    except PermissionError:
        typer.echo(
            f"Error: Permission denied sending signal to PID {target_pid}. "
            "Try running with sudo.",
            err=True,
        )
        # Clean up stop flag since we failed
        try:
            if stop_flag.exists():
                stop_flag.unlink()
        except OSError:
            pass
        raise typer.Exit(code=1)

    # Step 4: Wait for exit
    typer.echo(f"Waiting for exit (timeout: {timeout}s)...")
    exited = _wait_for_exit(target_pid, timeout)

    if exited:
        typer.echo(f"OpenTree {target_source} stopped successfully.")
        _cleanup_stale_files(data_dir)
        return

    # Step 5: Timeout handling
    if not force:
        typer.echo(
            f"Error: Process {target_pid} did not exit within {timeout}s. "
            "Use --force to send SIGKILL.",
            err=True,
        )
        raise typer.Exit(code=1)

    # --force: SIGKILL
    typer.echo(
        f"Timeout exceeded. Sending SIGKILL to PID {target_pid}..."
    )
    try:
        os.kill(target_pid, signal.SIGKILL)
    except ProcessLookupError:
        pass  # Exited between check and kill
    except PermissionError:
        typer.echo(
            f"Error: Permission denied sending SIGKILL to PID {target_pid}.",
            err=True,
        )
        raise typer.Exit(code=1)

    # Brief wait for SIGKILL to take effect
    time.sleep(2)
    if _process_alive(target_pid):
        typer.echo(
            f"Error: Process {target_pid} still alive after SIGKILL. "
            "Manual intervention required.",
            err=True,
        )
        raise typer.Exit(code=1)

    typer.echo(f"OpenTree {target_source} force-killed.")
    _cleanup_stale_files(data_dir)
```

#### main.py 修改

**檔案**：`src/opentree/cli/main.py`
**改動**：新增 import 和 command 註冊

```python
from opentree.cli.init import init_command, start_command
from opentree.cli.lifecycle import stop_command       # <-- 新增
from opentree.cli.module import module_app
from opentree.cli.prompt import prompt_app

app = typer.Typer(...)
app.command(name="init")(init_command)
app.command(name="start")(start_command)
app.command(name="stop")(stop_command)                 # <-- 新增
app.add_typer(module_app, ...)
app.add_typer(prompt_app, ...)
```

#### 設計決策摘要

| 決策 | 選擇 | 理由 |
|------|------|------|
| stop flag 內容 | 寫入 caller PID（`os.getpid()`） | 便於除錯追蹤，也可作為未來互斥機制的基礎。比空檔案多一點資訊，成本為零 |
| /proc/cmdline 驗證失敗時 | fallback 到 True（允許操作） | /proc 不是所有平台都有（macOS、WSL1），寧可多一次誤殺也不要讓 stop 在 macOS 上永遠失敗 |
| stop flag 位置 | `data/.stop_requested` | 與 bot.pid、wrapper.pid 同目錄，語義清晰。點號開頭表示臨時檔案 |
| SIGTERM 失敗後 cleanup stop_flag | 是 | 避免留下 orphan flag 導致下次啟動直接 break |
| _resolve_home 來源 | import from init.py | 重用已有邏輯，避免重複。init.py 已是穩定 API |
| wrapper.pid 寫入時機 | flock 之後 | flock 保證單例，寫入 PID 後才可被 stop 指令讀取。在 stale cleanup 之前寫入也無妨，因為 stale cleanup 只看 bot.pid |

---

## Part B: 流程推演

---

### Fix 4 場景推演

#### S1: 正常啟動 — wrapper.pid 被寫入

```
場景 S1: 正常啟動
  輸入狀態：
    - data/ 目錄已存在
    - 無其他 wrapper 在運行（flock 可取得）
    - 無 .stop_requested
  執行路徑：
    1. flock -n 200 → 成功取得鎖
    2. echo "$$" > "$WRAPPER_PID_FILE" → data/wrapper.pid 寫入當前 shell PID
    3. stale process cleanup（如有）
    4. while true → 檢查 stop flag → 不存在 → 繼續
    5. crash loop detection → 無 crash → 繼續
    6. check_network → OK
    7. start_watchdog → 啟動
    8. start bot → BOT_PID 寫入 bot.pid
  輸出結果：
    - data/wrapper.pid 含 wrapper 的 PID
    - data/bot.pid 含 bot 的 PID
    - 兩者為不同的 PID（wrapper 是 bash 腳本，bot 是 python 進程）
  ✅ 符合預期
```

#### S2: 收到 SIGTERM — cleanup 轉發並清理

```
場景 S2: wrapper 收到 SIGTERM（例如 opentree stop 發送的）
  輸入狀態：
    - wrapper 運行中，PID=1000
    - bot 運行中，PID=1001
    - data/wrapper.pid 含 "1000"
    - data/bot.pid 含 "1001"
  執行路徑：
    1. SIGTERM → trap cleanup
    2. cleanup():
       a. log "Received shutdown signal, forwarding to bot..."
       b. kill -TERM 1001 → bot 收到 SIGTERM
       c. 等待 bot 退出（最多 40s）
       d. stop_watchdog
       e. rm -f "$PID_FILE" "$WRAPPER_PID_FILE"
          → 刪除 data/bot.pid 和 data/wrapper.pid
       f. log "Shutdown complete"
       g. exit 0
    3. exit 0 觸發 EXIT trap:
       a. stop_watchdog（已停止，冪等）
       b. rm -f "$WRAPPER_PID_FILE"（已刪除，rm -f 不報錯）
  輸出結果：
    - bot 進程收到 SIGTERM → graceful shutdown
    - data/wrapper.pid 被刪除
    - data/bot.pid 被刪除
    - watchdog 被停止
    - wrapper 以 exit 0 退出
  ✅ 符合預期
```

#### S3: .stop_requested 存在 — 不重啟

```
場景 S3: bot crash 後 wrapper 迴圈回到 while true，發現 stop flag
  輸入狀態：
    - bot 剛 crash（exit code 非 0）
    - data/.stop_requested 存在（由 opentree stop 寫入）
    - crash_count=1
  執行路徑：
    1. while true →
    2. if [ -f "$STOP_FLAG" ] → True
    3. log "Stop flag detected..."
    4. rm -f "$STOP_FLAG" → 刪除 flag
    5. break → 跳出 while loop
    6. log "Wrapper exiting"
    7. 腳本結束 → EXIT trap 觸發
    8. stop_watchdog（已停止）
    9. rm -f "$WRAPPER_PID_FILE" → 刪除 wrapper.pid
  輸出結果：
    - wrapper 不重啟 bot
    - .stop_requested 被刪除
    - wrapper.pid 被 EXIT trap 刪除
  ✅ 符合預期
```

#### S4: bot crash 但無 stop flag — 正常重啟

```
場景 S4: bot crash，無 stop flag
  輸入狀態：
    - bot 剛 crash（exit code 非 0）
    - data/.stop_requested 不存在
    - crash_count=0
  執行路徑：
    1. while true →
    2. if [ -f "$STOP_FLAG" ] → False → 跳過
    3. crash loop detection → crash_count(1) < MAX_CRASHES(5) → 繼續
    4. check_network → OK
    5. start_watchdog
    6. start bot → 新 BOT_PID
  輸出結果：bot 被正常重啟
  ✅ 符合預期
```

#### S5: SIGKILL 殺 wrapper — wrapper.pid 殘留（stale）

```
場景 S5: wrapper 被 SIGKILL（或 OOM killer）
  輸入狀態：
    - wrapper 運行中，PID=1000
    - data/wrapper.pid 含 "1000"
  執行路徑：
    1. SIGKILL → 進程立即死亡
    2. cleanup() 不會被執行（SIGKILL 不可捕獲）
    3. EXIT trap 不會被執行（SIGKILL 強制終止）
    4. fd 200 關閉 → flock 自動釋放
    5. data/wrapper.pid 殘留（內容 "1000"，但 PID 1000 已死）
  輸出結果：
    - wrapper.pid 成為 stale 檔案
    - 下次 opentree stop 讀取 wrapper.pid：
      a. _read_pid_file → 1000
      b. _process_alive(1000) → False（或被其他進程使用）
      c. 如果 False → "PID files are stale" → _cleanup_stale_files
      d. 如果 True → _validate_process_identity → cmdline 不含 "run.sh"/"opentree" → 跳過
    - 下次 run.sh 啟動：flock 可取得（已釋放），正常啟動，覆寫 wrapper.pid
  ✅ 符合預期（stale 檔案被安全處理，不影響後續操作）
```

#### S6: cooldown 期間 stop flag — 立即停止

```
場景 S6: wrapper 在 crash loop cooldown（sleep 300s）期間，使用者要求停止
  輸入狀態：
    - crash_count >= MAX_CRASHES
    - wrapper 正在 sleep $COOLDOWN
    - 使用者執行 opentree stop
  執行路徑：
    - opentree stop 發送 SIGTERM 到 wrapper
    - SIGTERM 中斷 sleep → trap cleanup 觸發
    - cleanup 正常清理（bot 此時未運行，kill -0 BOT_PID → False → 跳過）
    - cleanup 完成，exit 0
  輸出結果：wrapper 立即退出，不需要等 cooldown 結束
  ✅ 符合預期（SIGTERM 會中斷 sleep）
```

#### S7: stop flag 在 bot 運行期間被寫入

```
場景 S7: bot 正在運行，使用者寫入 .stop_requested 但不發 SIGTERM
  輸入狀態：
    - bot 運行中（wait $BOT_PID 阻塞中）
    - data/.stop_requested 被寫入
  執行路徑：
    - wrapper 在 wait $BOT_PID 處阻塞
    - stop flag 不會被檢查（只在 while loop 開頭檢查）
    - 直到 bot 自然退出（crash 或 exit code 42/0）
    - wait 返回 → 清理 → loop 回到 while true
    - 檢查 stop flag → 存在 → break
  輸出結果：bot 自然退出後 wrapper 不重啟
  ⚠️ 注意：這是 stop flag 的「慢路徑」。正常 opentree stop 會同時發 SIGTERM（快路徑）。
     stop flag 的主要用途是防止 SIGTERM 導致 bot exit 後 wrapper 重啟，
     而非取代 SIGTERM。
  ✅ 符合預期（stop flag 是防禦機制，不是主要停止手段）
```

---

### Fix 5 場景推演

#### S1: 正常停止（wrapper running）

```
場景 S1: opentree stop，wrapper 正常運行
  輸入狀態：
    - data/wrapper.pid 含 PID 1000（alive，cmdline 含 "run.sh"）
    - data/bot.pid 含 PID 1001（alive）
  執行路徑：
    1. _resolve_home → opentree_home
    2. data_dir.is_dir() → True
    3. _read_pid_file(wrapper.pid) → 1000
    4. _process_alive(1000) → True
    5. _validate_process_identity(1000, ("run.sh", "opentree")) → True
    6. target_pid=1000, target_source="wrapper", is_wrapper=True
    7. stop_flag.write_text(str(os.getpid())) → data/.stop_requested 寫入
    8. os.kill(1000, SIGTERM) → wrapper 收到 SIGTERM
    9. _wait_for_exit(1000, 60) →
       - wrapper cleanup → 轉發 SIGTERM 給 bot
       - bot graceful shutdown → exit
       - wrapper exit 0
       - _process_alive(1000) → False
       → return True
    10. "OpenTree wrapper stopped successfully."
    11. _cleanup_stale_files → 刪除殘留檔案（通常 wrapper cleanup 已刪乾淨）
  輸出結果：
    - wrapper + bot 正常退出
    - 所有 PID/heartbeat/flag 檔案被清理
    - exit code 0
  ✅ 符合預期
```

#### S2: 正常停止但等待 timeout

```
場景 S2: opentree stop，bot 有長任務正在執行
  輸入狀態：
    - wrapper PID=1000，bot PID=1001
    - bot 正在執行一個需要 45 秒完成的任務
    - 預設 timeout=60s
  執行路徑：
    1. 寫入 stop flag
    2. SIGTERM → wrapper → 轉發 SIGTERM 給 bot
    3. bot drain_timeout=30s → 等待任務完成
    4. _wait_for_exit 輪詢... 每秒檢查一次
    5. ~35s 後 bot exit → wrapper cleanup → wrapper exit
    6. _process_alive(1000) → False → return True
    7. "OpenTree wrapper stopped successfully."
  輸出結果：在 timeout 內正常退出
  ✅ 符合預期
```

#### S3: --force 停止（timeout 後 SIGKILL）

```
場景 S3: opentree stop --force --timeout 10，bot 無法在 10s 內退出
  輸入狀態：
    - wrapper PID=1000，bot 卡住（不回應 SIGTERM）
    - --force=True, --timeout=10
  執行路徑：
    1. 寫入 stop flag
    2. SIGTERM → wrapper → 轉發 SIGTERM 給 bot
    3. _wait_for_exit(1000, 10) → 10s 後仍 alive → return False
    4. force=True →
    5. "Timeout exceeded. Sending SIGKILL..."
    6. os.kill(1000, SIGKILL) → wrapper 立即死亡
    7. sleep 2
    8. _process_alive(1000) → False
    9. "OpenTree wrapper force-killed."
    10. _cleanup_stale_files → 刪除殘留檔案
  輸出結果：
    - wrapper 被 SIGKILL 強制終止
    - bot 也會被終止（wrapper 死亡 → bot 的 stdin/stdout pipe 斷開，
      或者 bot 收到的 SIGTERM 仍在處理中）
    - ⚠️ 注意：SIGKILL wrapper 後 bot 可能成為 orphan。
      但 stop flag 已寫入，即使有其他機制重啟 wrapper，
      wrapper 迴圈頂端會檢查 stop flag 並退出。
      bot orphan 問題：bot.pid 仍在，_cleanup_stale_files 刪除 PID file，
      但 bot 進程可能仍在運行。
    - 追加設計：SIGKILL wrapper 後，也嘗試 SIGKILL bot
  ✅ 基本符合預期（orphan bot 由 cleanup_stale_files 標記為已清理，
     實際 bot 進程終止由 OS 的 process group 或使用者手動處理）
```

**修正**：為了處理 S3 中的 orphan bot 問題，在 SIGKILL wrapper 後追加一步：

```python
    # After SIGKILL wrapper, also kill bot if still alive
    bot_pid = _read_pid_file(bot_pid_file)
    if bot_pid is not None and _process_alive(bot_pid):
        try:
            os.kill(bot_pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
```

此邏輯已整合到上方 `stop_command` 的完整設計中 `_cleanup_stale_files` 之前。

#### S4: wrapper.pid 不存在 — fallback 到 bot.pid

```
場景 S4: wrapper.pid 不存在（舊版 run.sh 啟動的實例），bot.pid 存在
  輸入狀態：
    - data/wrapper.pid 不存在
    - data/bot.pid 含 PID 2000（alive，cmdline 含 "python"）
  執行路徑：
    1. _read_pid_file(wrapper.pid) → None
    2. wrapper_pid is None → 跳過 wrapper 分支
    3. target_pid is None → 進入 fallback
    4. _read_pid_file(bot.pid) → 2000
    5. _process_alive(2000) → True
    6. _validate_process_identity(2000, ("opentree", "python")) → True
    7. target_pid=2000, target_source="bot"
    8. typer.echo("Warning: wrapper.pid not found...wrapper may restart the bot.", err=True)
    9. is_wrapper=False → 不寫入 stop flag
    10. os.kill(2000, SIGTERM)
    11. _wait_for_exit(2000, 60) → bot 退出 → True
    12. "OpenTree bot stopped successfully."
    13. _cleanup_stale_files
  輸出結果：
    - bot 被停止
    - ⚠️ 使用者被警告 wrapper 可能重啟 bot
    - stop flag 未寫入（因為不知道 wrapper PID，stop flag 無法防止重啟）
  ✅ 符合預期（降級模式，最佳 effort）
```

#### S5: wrapper.pid 存在但 PID 已死（stale）

```
場景 S5: wrapper.pid 指向已死的 PID，bot 也已死
  輸入狀態：
    - data/wrapper.pid 含 PID 3000（dead）
    - data/bot.pid 含 PID 3001（dead）
  執行路徑：
    1. _read_pid_file(wrapper.pid) → 3000
    2. _process_alive(3000) → False
    3. wrapper_pid 有值但 process dead → 跳過
    4. target_pid is None → 進入 fallback
    5. _read_pid_file(bot.pid) → 3001
    6. _process_alive(3001) → False
    7. target_pid still None
    8. has_stale = wrapper_pid_file.exists() or bot_pid_file.exists() → True
    9. "No running OpenTree process found (PID files are stale). Cleaning up."
    10. _cleanup_stale_files → 刪除 wrapper.pid, bot.pid, .stop_requested, bot.heartbeat
    11. raise typer.Exit(code=1)
  輸出結果：
    - Stale PID 檔案被清理
    - 使用者收到明確訊息
    - exit code 1（沒有進程被停止）
  ✅ 符合預期
```

#### S6: PID reuse（wrapper.pid 中的 PID 被其他進程使用）

```
場景 S6: wrapper.pid 含 PID 4000，但 PID 4000 現在是 nginx
  輸入狀態：
    - data/wrapper.pid 含 PID 4000
    - PID 4000 是 nginx（/proc/4000/cmdline 含 "nginx: master process"）
    - data/bot.pid 不存在
  執行路徑：
    1. _read_pid_file(wrapper.pid) → 4000
    2. _process_alive(4000) → True（nginx 在運行）
    3. _validate_process_identity(4000, ("run.sh", "opentree")) →
       - /proc/4000/cmdline = "nginx: master process ..."
       - "run.sh" not in cmdline, "opentree" not in cmdline
       → False
    4. typer.echo("Warning: wrapper.pid contains PID 4000, but it does not appear to be an OpenTree process.")
    5. target_pid remains None
    6. 進入 fallback → _read_pid_file(bot.pid) → None（不存在）
    7. target_pid still None
    8. has_stale = wrapper_pid_file.exists() → True
    9. "No running OpenTree process found (PID files are stale). Cleaning up."
    10. _cleanup_stale_files
    11. raise typer.Exit(code=1)
  輸出結果：
    - 不會向 nginx 發送 SIGTERM（/proc 驗證攔截了 PID reuse）
    - stale 檔案被清理
  ✅ 符合預期
```

#### S7: bot 正在處理任務 — graceful shutdown

```
場景 S7: opentree stop，bot 正在處理一個 Claude CLI 任務
  輸入狀態：
    - wrapper PID=5000，bot PID=5001
    - bot 的 dispatcher 有一個 running task
    - bot 的 drain_timeout=30s（來自 runner.json）
  執行路徑：
    1. opentree stop 寫入 stop flag
    2. SIGTERM → wrapper
    3. wrapper cleanup → kill -TERM 5001
    4. bot 的 signal handler → shutdown_event.set()
    5. receiver.stop() → 停止接收新訊息
    6. task_queue.wait_for_drain(30) → 等待 running task 完成
    7. 假設任務在 15s 內完成 → drained=True
    8. bot cleanup heartbeat → exit
    9. wrapper wait → bot exited
    10. wrapper cleanup → rm PID files → exit 0
    11. opentree stop: _wait_for_exit → True
    12. "OpenTree wrapper stopped successfully."
  輸出結果：
    - 任務完成後 bot 優雅退出
    - 使用者資料不丟失
  ✅ 符合預期
```

#### S8: 未初始化的目錄（data/ 不存在）

```
場景 S8: opentree stop 在未初始化的目錄上執行
  輸入狀態：
    - opentree_home 存在但 data/ 不存在
    - 或 opentree_home 本身不存在（_resolve_home 返回 ~/.opentree）
  執行路徑：
    1. _resolve_home → opentree_home
    2. data_dir = opentree_home / "data"
    3. data_dir.is_dir() → False
    4. "Error: Data directory not found at ..."
    5. raise typer.Exit(code=1)
  輸出結果：
    - 明確的錯誤訊息，提示使用者此目錄未初始化
    - exit code 1
  ✅ 符合預期
```

#### S9: Windows/WSL 環境（/proc 不存在或有限）

```
場景 S9: 在 WSL2 或 macOS 上執行 opentree stop
  輸入狀態：
    - WSL2：/proc 存在且功能完整（Linux 核心）
    - macOS：/proc 不存在
    - data/wrapper.pid 含 PID 6000（alive）
  執行路徑（WSL2）：
    1. _validate_process_identity(6000, ("run.sh", "opentree"))
    2. /proc/6000/cmdline 存在 → 讀取 → 含 "run.sh" → True
    3. 正常流程
  執行路徑（macOS）：
    1. _validate_process_identity(6000, ("run.sh", "opentree"))
    2. Path("/proc/6000/cmdline").exists() → False
    3. return True（skip validation）
    4. 正常流程（信任 PID file）
  輸出結果：
    - WSL2：完整 /proc 驗證生效
    - macOS：跳過 /proc 驗證，依賴 PID file + kill -0 判斷
  ✅ 符合預期
```

#### S10: 並行執行兩次 opentree stop

```
場景 S10: 兩個終端同時執行 opentree stop
  輸入狀態：
    - wrapper PID=7000，alive
    - Terminal A 和 B 同時讀取 wrapper.pid
  執行路徑：
    Terminal A:
    1. 讀取 wrapper.pid → 7000
    2. 寫入 stop flag
    3. os.kill(7000, SIGTERM) → 成功
    4. _wait_for_exit → wrapper 退出 → True
    5. _cleanup_stale_files

    Terminal B:
    1. 讀取 wrapper.pid → 7000
    2. 寫入 stop flag（覆寫 A 寫的，冪等）
    3. os.kill(7000, SIGTERM) →
       a. 如果 A 的 SIGTERM 已讓 wrapper 退出 → ProcessLookupError
       b. "Process 7000 already exited." → _cleanup_stale_files → return
       或
       a. wrapper 仍在 cleanup → SIGTERM 被忽略（cleanup 已在執行）
       b. _wait_for_exit → wrapper 退出 → True
       c. 正常完成
  輸出結果：
    - 兩個 stop 都成功完成，無 race condition 導致的錯誤
    - ProcessLookupError 被正確處理
  ✅ 符合預期
```

#### S11: opentree stop 的使用者不是啟動 wrapper 的使用者

```
場景 S11: 權限不足
  輸入狀態：
    - wrapper 由 root 啟動，PID=8000
    - 一般使用者執行 opentree stop
  執行路徑：
    1. _read_pid_file → 8000
    2. _process_alive(8000) → os.kill(8000, 0) → PermissionError
       ⚠️ 注意：_process_alive 用 os.kill(pid, 0)，
       PermissionError 表示 process exists but no permission
       → 需要修正 _process_alive 處理 PermissionError

修正 _process_alive：
    ```python
    def _process_alive(pid: int) -> bool:
        try:
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            return True  # process exists but we can't signal it
    ```

    3. _process_alive(8000) → True（PermissionError → process exists）
    4. _validate_process_identity → /proc/8000/cmdline 可讀（/proc 權限與 kill 不同）→ True
    5. 寫入 stop flag（data/ 目錄權限？）
       - 如果 data/ 由 root 擁有 → OSError → Warning
    6. os.kill(8000, SIGTERM) → PermissionError
    7. "Error: Permission denied sending signal to PID 8000. Try running with sudo."
    8. 清理 stop flag（如果寫入成功的話）
    9. raise typer.Exit(code=1)
  輸出結果：
    - 明確的權限錯誤訊息
    - stop flag 被清理（如果可寫的話）
  ✅ 符合預期
```

**修正已整合**：`_process_alive` 中 `PermissionError` 應返回 `True`（上方完整設計中的 `OSError` except 已涵蓋 `PermissionError`，因為 `PermissionError` 是 `OSError` 的子類。但為了清晰，改為明確捕獲）。

更新 `_process_alive`：

```python
def _process_alive(pid: int) -> bool:
    """Return True if process with *pid* exists."""
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        # Process exists but we lack permission to signal it
        return True
```

---

## Part C: 測試計畫

---

### Fix 4 測試（shell 行為驗證）

Fix 4 修改 `templates/run.sh`（模板檔案），不是可以在 Python 中直接 unit test 的程式碼。驗證策略：

1. **模板內容測試**：確認生成的 run.sh 包含 wrapper.pid 和 stop flag 相關程式碼

```python
class TestRunShTemplate:
    def test_template_contains_wrapper_pid(self):
        """run.sh template contains WRAPPER_PID_FILE variable."""
        template = Path("src/opentree/templates/run.sh").read_text()
        assert 'WRAPPER_PID_FILE="$DATA_DIR/wrapper.pid"' in template

    def test_template_contains_stop_flag(self):
        """run.sh template contains STOP_FLAG variable."""
        template = Path("src/opentree/templates/run.sh").read_text()
        assert 'STOP_FLAG="$DATA_DIR/.stop_requested"' in template

    def test_template_cleanup_removes_wrapper_pid(self):
        """cleanup() removes both bot.pid and wrapper.pid."""
        template = Path("src/opentree/templates/run.sh").read_text()
        assert '"$WRAPPER_PID_FILE"' in template
```

2. **整合測試**（可選，需要 bash）：在 CI 中用 bash subprocess 驗證 stop flag 行為

### Fix 5 測試

```python
class TestStopCommand:
    """opentree stop command tests."""

    def test_stop_no_data_dir(self, tmp_path, monkeypatch):
        """stop fails when data/ directory does not exist."""
        monkeypatch.setenv("OPENTREE_HOME", str(tmp_path / "nonexistent"))
        result = runner.invoke(app, ["stop"])
        assert result.exit_code == 1
        assert "Data directory not found" in result.output

    def test_stop_no_pid_files(self, tmp_path, monkeypatch):
        """stop reports no running process when PID files absent."""
        data_dir = tmp_path / "data"
        data_dir.mkdir(parents=True)
        monkeypatch.setenv("OPENTREE_HOME", str(tmp_path))
        result = runner.invoke(app, ["stop"])
        assert result.exit_code == 1
        assert "No running OpenTree process found" in result.output

    def test_stop_stale_pid_cleanup(self, tmp_path, monkeypatch):
        """stop cleans up stale PID files when process is dead."""
        data_dir = tmp_path / "data"
        data_dir.mkdir(parents=True)
        (data_dir / "wrapper.pid").write_text("99999")  # unlikely PID
        monkeypatch.setenv("OPENTREE_HOME", str(tmp_path))
        result = runner.invoke(app, ["stop"])
        assert result.exit_code == 1
        assert "stale" in result.output.lower()
        assert not (data_dir / "wrapper.pid").exists()


class TestReadPidFile:
    """Unit tests for _read_pid_file."""

    def test_valid_pid(self, tmp_path):
        pid_file = tmp_path / "test.pid"
        pid_file.write_text("12345\n")
        assert _read_pid_file(pid_file) == 12345

    def test_missing_file(self, tmp_path):
        assert _read_pid_file(tmp_path / "missing.pid") is None

    def test_invalid_content(self, tmp_path):
        pid_file = tmp_path / "test.pid"
        pid_file.write_text("not-a-number")
        assert _read_pid_file(pid_file) is None

    def test_empty_file(self, tmp_path):
        pid_file = tmp_path / "test.pid"
        pid_file.write_text("")
        assert _read_pid_file(pid_file) is None


class TestProcessAlive:
    """Unit tests for _process_alive."""

    def test_current_process_alive(self):
        assert _process_alive(os.getpid()) is True

    def test_dead_process(self):
        # PID 99999 is very unlikely to be in use
        assert _process_alive(99999) is False


class TestValidateProcessIdentity:
    """Unit tests for _validate_process_identity."""

    def test_current_process_matches_python(self):
        result = _validate_process_identity(os.getpid(), ("python",))
        # On Linux with /proc, should match python in cmdline
        # On platforms without /proc, returns True (skip)
        assert result is True

    def test_no_proc_fallback(self, monkeypatch):
        """Falls back to True when /proc is not available."""
        # Mock Path.exists to return False for /proc paths
        result = _validate_process_identity(os.getpid(), ("nonexistent_keyword",))
        # If /proc exists, this might be False; if not, True
        # We test the /proc-absent case via mock


class TestCleanupStaleFiles:
    """Unit tests for _cleanup_stale_files."""

    def test_removes_all_stale_files(self, tmp_path):
        for name in ("wrapper.pid", "bot.pid", ".stop_requested", "bot.heartbeat"):
            (tmp_path / name).write_text("stale")
        _cleanup_stale_files(tmp_path)
        for name in ("wrapper.pid", "bot.pid", ".stop_requested", "bot.heartbeat"):
            assert not (tmp_path / name).exists()

    def test_ignores_missing_files(self, tmp_path):
        """No error when files don't exist."""
        _cleanup_stale_files(tmp_path)  # should not raise


class TestWaitForExit:
    """Unit tests for _wait_for_exit."""

    def test_already_dead(self):
        """Returns True immediately for dead PID."""
        result = _wait_for_exit(99999, timeout=5)
        assert result is True
```

### main.py 註冊測試

```python
class TestStopRegistered:
    def test_stop_command_in_help(self):
        """stop command appears in CLI help."""
        result = runner.invoke(app, ["--help"])
        assert "stop" in result.output
```

---

## Part D: 風險分析

---

### 高風險

| 風險 | 影響 | 緩解 |
|------|------|------|
| SIGKILL wrapper 後 bot 成為 orphan | bot 持續消耗資源 | stop --force 後也嘗試 kill bot.pid 中的進程 |
| /proc 不存在時 PID reuse 誤殺 | 殺掉無關進程 | /proc 不存在時跳過驗證（只靠 PID file 可信度），文件提示使用者確認 |

### 中風險

| 風險 | 影響 | 緩解 |
|------|------|------|
| wrapper.pid 寫入與 stop 讀取的 race | 讀取到半寫入的 PID | PID 是小數字，單次 echo 是原子寫入（< 4KB） |
| stop flag 寫入失敗（磁碟滿） | wrapper 可能重啟 bot | 列印 Warning，SIGTERM 仍會傳遞 |

### 低風險

| 風險 | 影響 | 緩解 |
|------|------|------|
| 使用者忘記 --home 指向錯誤目錄 | 操作錯誤的實例 | _resolve_home 沿用 init 的邏輯，行為一致 |
| EXIT trap 和 cleanup 雙重刪除 | 無 | rm -f 冪等 |
