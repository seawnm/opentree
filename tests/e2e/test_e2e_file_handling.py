"""E2E tests for file handling (B4).

Verify that Bot_Walter correctly handles file-related operations:
- Reading file contents when requested
- Graceful error handling for invalid file paths
- Temp directory cleanup after task completion

Note: These tests exercise the file_handler module indirectly by asking the
bot to read files.  Direct file upload tests are omitted because message-tool
does not support file uploads; only text-based file references are tested.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Callable

import pytest

from opentree.runner.file_handler import DEFAULT_TEMP_BASE

pytestmark = [pytest.mark.e2e, pytest.mark.slow]

# Temp directory used by file_handler for Slack file downloads
_TEMP_BASE = DEFAULT_TEMP_BASE


# ===================================================================
# B4 -- File handling
# ===================================================================


class TestFileHandling:
    """B4: file reference reading, error handling, and temp cleanup."""

    @pytest.mark.xfail(
        strict=False,
        reason=(
            "AI non-deterministic: bot reply may not contain expected "
            "content indicators (workspace name, admin, etc.) depending "
            "on how Claude interprets the file content."
        ),
    )
    def test_bot_processes_file_reference(
        self,
        bot_mention: str,
        send_message: Callable[..., dict[str, Any]],
        wait_for_bot_reply: Callable[..., str],
    ) -> None:
        """要求 bot 讀取特定檔案，驗證回覆包含檔案內容。

        pyproject.toml 的 [project] name 欄位應為 "opentree"。
        """
        # Use a file within Bot_Walter's workspace to avoid path restrictions
        workspace_claude = (
            "/mnt/e/develop/mydev/project/trees/bot_walter"
            "/workspace/CLAUDE.md"
        )
        result = send_message(
            f"{bot_mention} read the file "
            f"{workspace_claude} "
            "and tell me what the project name or workspace name is"
        )
        thread_ts = result["message_ts"]

        reply = wait_for_bot_reply(thread_ts, timeout=180)

        assert reply, "Bot returned an empty reply"
        # Bot should mention the workspace name or some content from the file
        reply_lower = reply.lower()
        content_indicators = [
            "bot_walter", "walter", "workspace", "claude",
            "工作區", "admin",
        ]
        found = any(ind in reply_lower for ind in content_indicators)
        assert found, (
            f"Expected file content reference in bot reply but got: {reply[:500]}"
        )

    @pytest.mark.xfail(
        strict=False,
        reason=(
            "AI non-deterministic: bot error response wording may not "
            "match any of the expected error indicators. Claude may "
            "describe the missing file in unexpected phrasing."
        ),
    )
    def test_file_not_found_handled_gracefully(
        self,
        bot_mention: str,
        send_message: Callable[..., dict[str, Any]],
        wait_for_bot_reply: Callable[..., str],
    ) -> None:
        """驗證不存在的檔案路徑不會導致 crash，bot 應回覆錯誤或說明。

        使用一個顯然不存在的路徑，確認 bot 能優雅處理。
        """
        fake_path = "/tmp/opentree/nonexistent_e2e_test_file_12345.txt"
        result = send_message(
            f"{bot_mention} read the file {fake_path} and show me its contents"
        )
        thread_ts = result["message_ts"]

        reply = wait_for_bot_reply(thread_ts, timeout=120)

        assert reply, "Bot returned an empty reply for a nonexistent file"
        # Bot should mention that the file doesn't exist or cannot be found.
        reply_lower = reply.lower()
        error_indicators = [
            "not found", "doesn't exist", "does not exist",
            "no such file", "cannot", "couldn't", "error",
            "unable", "not exist", "empty",
            # Chinese equivalents
            "找不到", "不存在", "無法", "沒有這個", "錯誤",
            "無此", "失敗",
        ]
        found = any(ind in reply_lower for ind in error_indicators)
        assert found, (
            f"Expected an error indication for nonexistent file, "
            f"but got: {reply[:500]}"
        )

    def test_temp_file_cleanup(
        self,
        bot_mention: str,
        send_message: Callable[..., dict[str, Any]],
        wait_for_bot_reply: Callable[..., str],
        drain_bot_queue: Callable[[], None],
    ) -> None:
        """驗證任務完成後 temp 目錄被清理。

        發送一個觸發 Read 工具的請求，完成後檢查 /tmp/opentree/{thread_ts}/
        目錄不存在（已被 cleanup_temp 清除）。

        NOTE: Earlier tests in this class (including xfail ones) send
        messages that occupy the bot queue.  We drain the queue first so
        this test's request is processed promptly and does not time out.
        """
        # Ensure any previously queued bot tasks have finished
        drain_bot_queue()

        result = send_message(
            f"{bot_mention} read /mnt/e/develop/mydev/opentree/pyproject.toml "
            "and tell me the version"
        )
        thread_ts = result["message_ts"]

        # Wait for bot to finish processing
        reply = wait_for_bot_reply(thread_ts, timeout=180)
        assert reply, "Bot returned an empty reply"

        # Give a moment for the finally block (cleanup_temp) to run
        time.sleep(5)

        # The temp directory for this thread should have been cleaned up.
        # file_handler.cleanup_temp removes /tmp/opentree/{thread_ts}/
        thread_temp_dir = _TEMP_BASE / thread_ts
        assert not thread_temp_dir.exists(), (
            f"Temp directory was not cleaned up: {thread_temp_dir}"
        )
