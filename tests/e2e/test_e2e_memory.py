"""E2E tests for memory extraction and persistence (B5).

Verify that Bot_Walter can:
- Persist explicit "remember" commands to memory.md
- Reference stored memories in later conversation turns
- (xfail) Automatically extract memories from conversation

The memory file is located at:
  bot_walter/data/memory/{user}/memory.md

Cleanup: Each test that writes to memory.md restores the original content
after assertion to avoid polluting the user's actual memory store.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Callable

import pytest

pytestmark = [pytest.mark.e2e, pytest.mark.slow]

# Bot_Walter data directory
_BOT_DATA_DIR = Path("/mnt/e/develop/mydev/project/trees/bot_walter/data")

# The user whose messages are sent via message-tool.
# message-tool sends as the DOGI operator; Bot_Walter resolves the Slack
# user_id to a display_name for the memory path.  Since we can't predict
# the exact resolved name, we search all subdirectories under memory/.
_MEMORY_BASE = _BOT_DATA_DIR / "memory"

# Unique marker to identify test-written memory entries for cleanup.
_TEST_MARKER = "E2E_MEMORY_TEST"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _find_memory_files() -> list[Path]:
    """Return all memory.md files under the bot's memory directory."""
    if not _MEMORY_BASE.exists():
        return []
    return list(_MEMORY_BASE.rglob("memory.md"))


def _cleanup_test_memories() -> None:
    """Remove test memory entries from all memory files."""
    try:
        for memory_path in _find_memory_files():
            try:
                content = memory_path.read_text(encoding="utf-8")
                if _TEST_MARKER in content:
                    lines = content.splitlines(keepends=True)
                    cleaned = [l for l in lines if _TEST_MARKER not in l]
                    memory_path.write_text("".join(cleaned), encoding="utf-8")
            except Exception:  # Broad catch for cleanup — must not fail tests
                pass
    except Exception:
        pass


def _memory_contains(text: str) -> bool:
    """Check if any memory.md under the bot's memory dir contains *text*."""
    for mem_file in _find_memory_files():
        try:
            content = mem_file.read_text(encoding="utf-8")
        except OSError:
            continue
        if text in content:
            return True
    return False


# ===================================================================
# B5 -- Memory extraction
# ===================================================================


class TestMemoryExtractor:
    """B5: explicit remember command, memory recall, and heuristic extraction."""

    @pytest.mark.xfail(
        strict=False,
        reason=(
            "Memory write path depends on user_id resolution (message-tool "
            "sends as DOGI bot, not as a human user) and on Claude interpreting "
            "the 'remember' command correctly via memory-sop rules."
        ),
    )
    def test_remember_command_persists(
        self,
        bot_mention: str,
        send_message: Callable[..., dict[str, Any]],
        wait_for_bot_reply: Callable[..., str],
    ) -> None:
        """發送「記住 X」指令，驗證 bot 回覆確認並且 memory.md 更新。

        MemoryExtractor 的 _REMEMBER_PATTERNS 會捕捉「記住」開頭的文字，
        萃取後 append_to_memory_file 寫入 data/memory/{user}/memory.md。
        """
        remember_text = f"{_TEST_MARKER} I prefer dark mode for coding"

        try:
            result = send_message(
                f"{bot_mention} remember {remember_text}"
            )
            thread_ts = result["message_ts"]

            reply = wait_for_bot_reply(thread_ts, timeout=120)
            assert reply, "Bot returned an empty reply to remember command"

            # Poll for memory update instead of fixed sleep
            deadline = time.monotonic() + 30
            memory_found = False
            while time.monotonic() < deadline:
                if _memory_contains("dark mode") or _memory_contains(_TEST_MARKER):
                    memory_found = True
                    break
                time.sleep(2)

            # Verify the memory file contains the test content.
            # The memory_extractor captures the text after "remember",
            # so we check for the distinctive marker and preference text.
            assert memory_found, (
                f"Expected memory.md to contain test memory after 'remember' "
                f"command. Memory files found: {_find_memory_files()}"
            )
        finally:
            _cleanup_test_memories()

    @pytest.mark.xfail(
        strict=False,
        reason=(
            "Memory recall depends on session resume + Claude non-deterministic "
            "behavior. The bot may not repeat the exact name verbatim."
        ),
    )
    def test_memory_referenced_in_conversation(
        self,
        bot_mention: str,
        send_message: Callable[..., dict[str, Any]],
        wait_for_bot_reply: Callable[..., str],
        wait_for_nth_bot_reply: Callable[..., str],
    ) -> None:
        """記住偏好後，同一 thread 後續對話應能引用記憶。

        Step 1: 記住名字
        Step 2: 在同一 thread 問「你還記得我的名字嗎？」
        驗證: 回覆包含記住的名字

        注意: 這同時測試了 session 的上下文保持和記憶系統。
        即使 memory_extractor 沒有將名字寫入 memory.md，
        session 的上下文保持（thread context）也應能回答這個問題。
        """
        unique_name = f"{_TEST_MARKER}-Tester"

        try:
            # Step 1: Tell the bot a name
            result = send_message(
                f"{bot_mention} remember my name is {unique_name}"
            )
            thread_ts = result["message_ts"]

            first_reply = wait_for_bot_reply(thread_ts, timeout=120)
            assert first_reply, "Bot did not reply to the remember command"

            # Allow time for session persistence
            time.sleep(10)

            # Step 2: Ask in the same thread
            send_message(
                f"{bot_mention} what is my name? Please repeat it exactly.",
                thread_ts=thread_ts,
            )

            # Wait for the second bot reply
            second_reply = wait_for_nth_bot_reply(thread_ts, n=2, timeout=120)

            # The reply should contain the test name (or part of it)
            assert _TEST_MARKER in second_reply or "Tester" in second_reply, (
                f"Expected bot to recall '{unique_name}' but got: "
                f"{second_reply[:500]}"
            )
        finally:
            _cleanup_test_memories()

    @pytest.mark.xfail(
        reason=(
            "Heuristic memory extraction depends on Claude's response "
            "containing specific patterns like 'I'll remember that...' "
            "which is not deterministic."
        ),
        strict=False,
    )
    def test_memory_heuristic_extraction(
        self,
        bot_mention: str,
        send_message: Callable[..., dict[str, Any]],
        wait_for_bot_reply: Callable[..., str],
    ) -> None:
        """驗證自動記憶萃取（非明確「記住」指令）。

        MemoryExtractor 在 Claude 回覆中偵測 preference 模式
        (如 "I prefer..." "I always..." 等)。由於 Claude 回覆內容
        不可預測，此測試標記為 xfail。

        觸發方式: 告訴 bot 一個偏好，但不用「記住」關鍵字，
        看 memory_extractor 能否從使用者的原始訊息中萃取。
        """
        preference = f"{_TEST_MARKER} I always use vim keybindings"

        try:
            result = send_message(
                f"{bot_mention} {preference}"
            )
            thread_ts = result["message_ts"]

            reply = wait_for_bot_reply(thread_ts, timeout=120)
            assert reply, "Bot returned an empty reply"

            # Wait for memory extraction pipeline
            time.sleep(10)

            # Check if the heuristic extractor picked up "always use vim keybindings"
            found = (
                _memory_contains("vim keybindings")
                or _memory_contains("vim")
                or _memory_contains(_TEST_MARKER)
            )
            assert found, (
                f"Heuristic extraction did not capture preference. "
                f"Memory files: {_find_memory_files()}"
            )
        finally:
            _cleanup_test_memories()
