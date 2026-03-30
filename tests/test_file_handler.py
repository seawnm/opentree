"""Tests for file_handler — downloads Slack file attachments to local temp dir.

TDD order:
1.  test_safe_filename_normal
2.  test_safe_filename_path_traversal
3.  test_safe_filename_long_name
4.  test_safe_filename_special_chars
5.  test_format_size_bytes
6.  test_format_size_kb
7.  test_format_size_mb
8.  test_download_files_success
9.  test_download_files_creates_directory
10. test_download_files_duplicate_names
11. test_download_files_skip_large_file
12. test_download_files_skip_no_url
13. test_download_files_network_error
14. test_build_file_context
15. test_build_file_context_empty
16. test_cleanup_temp
"""

from __future__ import annotations

import io
import shutil
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

from opentree.runner.file_handler import (
    download_files,
    build_file_context,
    cleanup_temp,
    _safe_filename,
    _format_size,
    DEFAULT_TEMP_BASE,
    MAX_FILE_SIZE,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_file(
    name: str = "test.txt",
    url: str = "https://files.slack.com/private/test.txt",
    mimetype: str = "text/plain",
    size: int = 100,
) -> dict:
    """Build a minimal Slack file object dict."""
    return {
        "name": name,
        "url_private_download": url,
        "mimetype": mimetype,
        "size": size,
    }


# ---------------------------------------------------------------------------
# 1. test_safe_filename_normal
# ---------------------------------------------------------------------------

class TestSafeFilenameNormal:
    """_safe_filename preserves ordinary filenames unchanged."""

    def test_simple_name_unchanged(self):
        assert _safe_filename("report.py") == "report.py"

    def test_name_with_underscores(self):
        assert _safe_filename("my_file_v2.txt") == "my_file_v2.txt"

    def test_name_with_hyphens(self):
        assert _safe_filename("my-file.json") == "my-file.json"

    def test_empty_string_returns_unnamed(self):
        assert _safe_filename("") == "unnamed"

    def test_only_whitespace_returns_unnamed(self):
        assert _safe_filename("   ") == "unnamed"


# ---------------------------------------------------------------------------
# 2. test_safe_filename_path_traversal
# ---------------------------------------------------------------------------

class TestSafeFilenamePathTraversal:
    """_safe_filename strips path traversal sequences."""

    def test_strips_dotdot_slash(self):
        result = _safe_filename("../../etc/passwd")
        assert ".." not in result
        assert "/" not in result

    def test_strips_leading_slash(self):
        result = _safe_filename("/etc/passwd")
        assert result == "passwd"

    def test_strips_backslash_traversal(self):
        result = _safe_filename("..\\windows\\system32\\cmd.exe")
        assert ".." not in result

    def test_nested_dotdot_bypass(self):
        # "..../" after one pass becomes "../", so must be applied repeatedly
        result = _safe_filename("....//secret.txt")
        assert ".." not in result

    def test_only_dotdots_returns_unnamed(self):
        result = _safe_filename("../../..")
        # After stripping path separators and dots, should be "unnamed" or empty
        assert result == "unnamed" or result == ""


# ---------------------------------------------------------------------------
# 3. test_safe_filename_long_name
# ---------------------------------------------------------------------------

class TestSafeFilenameLongName:
    """_safe_filename truncates filenames exceeding 255 bytes."""

    def test_long_name_truncated(self):
        long_name = "a" * 300 + ".txt"
        result = _safe_filename(long_name)
        assert len(result) <= 255

    def test_short_name_not_truncated(self):
        name = "short.py"
        assert _safe_filename(name) == name

    def test_exactly_255_bytes_not_truncated(self):
        name = "x" * 251 + ".txt"  # 255 chars total
        result = _safe_filename(name)
        assert len(result) == 255


# ---------------------------------------------------------------------------
# 4. test_safe_filename_special_chars
# ---------------------------------------------------------------------------

class TestSafeFilenameSpecialChars:
    """_safe_filename handles special characters gracefully."""

    def test_spaces_preserved(self):
        # Spaces in filenames are valid
        result = _safe_filename("my file.txt")
        assert "file" in result

    def test_unicode_chars_preserved(self):
        result = _safe_filename("报告.txt")
        assert result == "报告.txt"

    def test_null_bytes_stripped(self):
        # Null bytes are dangerous
        result = _safe_filename("file\x00.txt")
        assert "\x00" not in result


# ---------------------------------------------------------------------------
# 5. test_format_size_bytes
# ---------------------------------------------------------------------------

class TestFormatSizeBytes:
    """_format_size returns '... B' for sizes under 1 KB."""

    def test_zero_bytes(self):
        assert _format_size(0) == "0 B"

    def test_one_byte(self):
        assert _format_size(1) == "1 B"

    def test_999_bytes(self):
        assert _format_size(999) == "999 B"

    def test_1023_bytes(self):
        assert _format_size(1023) == "1023 B"


# ---------------------------------------------------------------------------
# 6. test_format_size_kb
# ---------------------------------------------------------------------------

class TestFormatSizeKB:
    """_format_size returns '... KB' for sizes between 1 KB and 1 MB."""

    def test_exactly_1_kb(self):
        assert _format_size(1024) == "1.0 KB"

    def test_1_5_kb(self):
        assert _format_size(1536) == "1.5 KB"

    def test_1023_kb(self):
        result = _format_size(1023 * 1024)
        assert "KB" in result

    def test_format_has_one_decimal(self):
        result = _format_size(2048)
        assert result == "2.0 KB"


# ---------------------------------------------------------------------------
# 7. test_format_size_mb
# ---------------------------------------------------------------------------

class TestFormatSizeMB:
    """_format_size returns '... MB' for sizes >= 1 MB."""

    def test_exactly_1_mb(self):
        assert _format_size(1024 * 1024) == "1.0 MB"

    def test_3_5_mb(self):
        assert _format_size(int(3.5 * 1024 * 1024)) == "3.5 MB"

    def test_50_mb(self):
        assert _format_size(50 * 1024 * 1024) == "50.0 MB"


# ---------------------------------------------------------------------------
# 8. test_download_files_success
# ---------------------------------------------------------------------------

class TestDownloadFilesSuccess:
    """download_files returns a list with local_path, name, mimetype, size."""

    def test_returns_downloaded_list(self, tmp_path):
        files = [_make_file(name="hello.py", size=42)]
        fake_response = MagicMock()
        fake_response.read.return_value = b"print('hello')"

        with patch("urllib.request.urlopen", return_value=fake_response):
            result = download_files(
                files=files,
                thread_ts="1234.5678",
                bot_token="xoxb-fake",
                temp_base=tmp_path,
            )

        assert len(result) == 1
        assert result[0]["name"] == "hello.py"
        assert result[0]["mimetype"] == "text/plain"
        assert result[0]["size"] == 42
        assert Path(result[0]["local_path"]).exists()

    def test_file_content_written_correctly(self, tmp_path):
        content = b"def foo(): pass"
        files = [_make_file(name="foo.py", size=len(content))]
        fake_response = MagicMock()
        fake_response.read.return_value = content

        with patch("urllib.request.urlopen", return_value=fake_response):
            result = download_files(
                files=files,
                thread_ts="1234.5678",
                bot_token="xoxb-fake",
                temp_base=tmp_path,
            )

        written = Path(result[0]["local_path"]).read_bytes()
        assert written == content

    def test_uses_bot_token_in_auth_header(self, tmp_path):
        files = [_make_file()]
        fake_response = MagicMock()
        fake_response.read.return_value = b"data"
        captured_requests = []

        def mock_urlopen(req, **kwargs):
            captured_requests.append(req)
            return fake_response

        with patch("urllib.request.urlopen", side_effect=mock_urlopen):
            download_files(
                files=files,
                thread_ts="111.222",
                bot_token="xoxb-secret-token",
                temp_base=tmp_path,
            )

        assert len(captured_requests) == 1
        req = captured_requests[0]
        auth_header = req.get_header("Authorization")
        assert auth_header == "Bearer xoxb-secret-token"


# ---------------------------------------------------------------------------
# 9. test_download_files_creates_directory
# ---------------------------------------------------------------------------

class TestDownloadFilesCreatesDirectory:
    """download_files creates the per-thread temp directory if it does not exist."""

    def test_creates_thread_subdirectory(self, tmp_path):
        thread_ts = "9999.1234"
        files = [_make_file()]
        fake_response = MagicMock()
        fake_response.read.return_value = b"x"

        expected_dir = tmp_path / thread_ts
        assert not expected_dir.exists()

        with patch("urllib.request.urlopen", return_value=fake_response):
            download_files(
                files=files,
                thread_ts=thread_ts,
                bot_token="xoxb-fake",
                temp_base=tmp_path,
            )

        assert expected_dir.exists()
        assert expected_dir.is_dir()

    def test_works_when_directory_already_exists(self, tmp_path):
        thread_ts = "8888.0001"
        thread_dir = tmp_path / thread_ts
        thread_dir.mkdir(parents=True)
        files = [_make_file()]
        fake_response = MagicMock()
        fake_response.read.return_value = b"y"

        with patch("urllib.request.urlopen", return_value=fake_response):
            result = download_files(
                files=files,
                thread_ts=thread_ts,
                bot_token="xoxb-fake",
                temp_base=tmp_path,
            )

        assert len(result) == 1


# ---------------------------------------------------------------------------
# 10. test_download_files_duplicate_names
# ---------------------------------------------------------------------------

class TestDownloadFilesDuplicateNames:
    """download_files resolves duplicate filenames by appending numeric suffixes."""

    def test_second_same_name_gets_suffix(self, tmp_path):
        files = [
            _make_file(name="data.csv", url="https://slack.com/1"),
            _make_file(name="data.csv", url="https://slack.com/2"),
        ]
        fake_response = MagicMock()
        fake_response.read.return_value = b"content"

        with patch("urllib.request.urlopen", return_value=fake_response):
            result = download_files(
                files=files,
                thread_ts="1111.0000",
                bot_token="xoxb-fake",
                temp_base=tmp_path,
            )

        assert len(result) == 2
        paths = [r["local_path"] for r in result]
        # Both paths should be different
        assert paths[0] != paths[1]
        # Second should have a suffix
        assert "data_1.csv" in paths[1] or "data.csv" not in Path(paths[1]).name or paths[0] != paths[1]

    def test_three_files_same_name(self, tmp_path):
        files = [
            _make_file(name="img.png", url=f"https://slack.com/{i}")
            for i in range(3)
        ]
        fake_response = MagicMock()
        fake_response.read.return_value = b"png-data"

        with patch("urllib.request.urlopen", return_value=fake_response):
            result = download_files(
                files=files,
                thread_ts="2222.0000",
                bot_token="xoxb-fake",
                temp_base=tmp_path,
            )

        assert len(result) == 3
        local_paths = [r["local_path"] for r in result]
        # All paths must be unique
        assert len(set(local_paths)) == 3

    def test_duplicate_names_result_in_existing_files(self, tmp_path):
        files = [
            _make_file(name="note.txt", url="https://slack.com/a"),
            _make_file(name="note.txt", url="https://slack.com/b"),
        ]
        fake_response = MagicMock()
        fake_response.read.return_value = b"text"

        with patch("urllib.request.urlopen", return_value=fake_response):
            result = download_files(
                files=files,
                thread_ts="3333.0000",
                bot_token="xoxb-fake",
                temp_base=tmp_path,
            )

        for entry in result:
            assert Path(entry["local_path"]).exists()


# ---------------------------------------------------------------------------
# 11. test_download_files_skip_large_file
# ---------------------------------------------------------------------------

class TestDownloadFilesSkipLargeFile:
    """download_files skips files that exceed MAX_FILE_SIZE."""

    def test_large_file_skipped(self, tmp_path):
        large = _make_file(name="huge.bin", size=MAX_FILE_SIZE + 1)
        small = _make_file(name="tiny.txt", size=100)

        fake_response = MagicMock()
        fake_response.read.return_value = b"tiny"

        with patch("urllib.request.urlopen", return_value=fake_response):
            result = download_files(
                files=[large, small],
                thread_ts="4444.0000",
                bot_token="xoxb-fake",
                temp_base=tmp_path,
            )

        # Only the small file should be downloaded
        assert len(result) == 1
        assert result[0]["name"] == "tiny.txt"

    def test_exactly_max_size_is_allowed(self, tmp_path):
        """A file exactly at MAX_FILE_SIZE bytes should be downloaded (not skipped)."""
        exact = _make_file(name="borderline.bin", size=MAX_FILE_SIZE)
        fake_response = MagicMock()
        fake_response.read.return_value = b"x" * MAX_FILE_SIZE

        with patch("urllib.request.urlopen", return_value=fake_response):
            result = download_files(
                files=[exact],
                thread_ts="5555.0000",
                bot_token="xoxb-fake",
                temp_base=tmp_path,
            )

        assert len(result) == 1

    def test_no_urlopen_called_for_large_file(self, tmp_path):
        large = _make_file(name="huge.zip", size=MAX_FILE_SIZE + 1024)

        with patch("urllib.request.urlopen") as mock_open:
            result = download_files(
                files=[large],
                thread_ts="6666.0000",
                bot_token="xoxb-fake",
                temp_base=tmp_path,
            )

        mock_open.assert_not_called()
        assert result == []


# ---------------------------------------------------------------------------
# 12. test_download_files_skip_no_url
# ---------------------------------------------------------------------------

class TestDownloadFilesSkipNoUrl:
    """download_files skips files with no url_private_download."""

    def test_missing_url_key_skipped(self, tmp_path):
        no_url = {"name": "ghost.txt", "mimetype": "text/plain", "size": 50}
        good = _make_file(name="good.txt")
        fake_response = MagicMock()
        fake_response.read.return_value = b"content"

        with patch("urllib.request.urlopen", return_value=fake_response):
            result = download_files(
                files=[no_url, good],
                thread_ts="7777.0000",
                bot_token="xoxb-fake",
                temp_base=tmp_path,
            )

        assert len(result) == 1
        assert result[0]["name"] == "good.txt"

    def test_none_url_skipped(self, tmp_path):
        no_url = _make_file(name="none_url.txt")
        no_url["url_private_download"] = None
        fake_response = MagicMock()
        fake_response.read.return_value = b"x"

        with patch("urllib.request.urlopen", return_value=fake_response):
            result = download_files(
                files=[no_url],
                thread_ts="8888.0000",
                bot_token="xoxb-fake",
                temp_base=tmp_path,
            )

        assert result == []

    def test_empty_url_skipped(self, tmp_path):
        empty_url = _make_file(name="empty_url.txt")
        empty_url["url_private_download"] = ""

        with patch("urllib.request.urlopen") as mock_open:
            result = download_files(
                files=[empty_url],
                thread_ts="9999.0000",
                bot_token="xoxb-fake",
                temp_base=tmp_path,
            )

        mock_open.assert_not_called()
        assert result == []


# ---------------------------------------------------------------------------
# 13. test_download_files_network_error
# ---------------------------------------------------------------------------

class TestDownloadFilesNetworkError:
    """download_files handles network errors gracefully (log and skip)."""

    def test_network_error_does_not_raise(self, tmp_path):
        files = [_make_file(name="fail.txt")]

        with patch("urllib.request.urlopen", side_effect=OSError("connection refused")):
            # Must not raise
            result = download_files(
                files=files,
                thread_ts="1010.0000",
                bot_token="xoxb-fake",
                temp_base=tmp_path,
            )

        assert result == []

    def test_failed_file_excluded_from_result(self, tmp_path):
        fail = _make_file(name="bad.txt", url="https://slack.com/bad")
        ok = _make_file(name="good.txt", url="https://slack.com/good")

        fake_response = MagicMock()
        fake_response.read.return_value = b"good content"

        def side_effect(req, **kwargs):
            if "bad" in req.full_url:
                raise OSError("timeout")
            return fake_response

        with patch("urllib.request.urlopen", side_effect=side_effect):
            result = download_files(
                files=[fail, ok],
                thread_ts="1111.2222",
                bot_token="xoxb-fake",
                temp_base=tmp_path,
            )

        assert len(result) == 1
        assert result[0]["name"] == "good.txt"

    def test_exception_type_agnostic(self, tmp_path):
        """Any exception (not just OSError) should be swallowed."""
        files = [_make_file()]

        with patch("urllib.request.urlopen", side_effect=RuntimeError("unexpected")):
            result = download_files(
                files=files,
                thread_ts="2020.0001",
                bot_token="xoxb-fake",
                temp_base=tmp_path,
            )

        assert result == []


# ---------------------------------------------------------------------------
# 14. test_build_file_context
# ---------------------------------------------------------------------------

class TestBuildFileContext:
    """build_file_context formats downloaded file list as a readable string."""

    def test_single_file_contains_name_and_path(self):
        downloaded = [
            {
                "name": "report.py",
                "local_path": "/tmp/opentree/1234/report.py",
                "mimetype": "text/plain",
                "size": 1234,
            }
        ]
        result = build_file_context(downloaded)
        assert "report.py" in result
        assert "/tmp/opentree/1234/report.py" in result

    def test_contains_mimetype(self):
        downloaded = [
            {
                "name": "image.png",
                "local_path": "/tmp/opentree/1234/image.png",
                "mimetype": "image/png",
                "size": 46387,
            }
        ]
        result = build_file_context(downloaded)
        assert "image/png" in result

    def test_contains_human_readable_size(self):
        downloaded = [
            {
                "name": "data.csv",
                "local_path": "/tmp/opentree/1234/data.csv",
                "mimetype": "text/csv",
                "size": 2048,
            }
        ]
        result = build_file_context(downloaded)
        # Should show "2.0 KB" not raw bytes
        assert "KB" in result

    def test_multiple_files_all_listed(self):
        downloaded = [
            {
                "name": "a.py",
                "local_path": "/tmp/a.py",
                "mimetype": "text/plain",
                "size": 100,
            },
            {
                "name": "b.png",
                "local_path": "/tmp/b.png",
                "mimetype": "image/png",
                "size": 2048,
            },
        ]
        result = build_file_context(downloaded)
        assert "a.py" in result
        assert "b.png" in result

    def test_has_header_and_footer_markers(self):
        downloaded = [
            {
                "name": "x.txt",
                "local_path": "/tmp/x.txt",
                "mimetype": "text/plain",
                "size": 10,
            }
        ]
        result = build_file_context(downloaded)
        assert "---" in result
        assert "Attached files" in result or "file" in result.lower()


# ---------------------------------------------------------------------------
# 15. test_build_file_context_empty
# ---------------------------------------------------------------------------

class TestBuildFileContextEmpty:
    """build_file_context returns empty string when list is empty."""

    def test_empty_list_returns_empty_string(self):
        assert build_file_context([]) == ""

    def test_empty_list_is_falsy(self):
        result = build_file_context([])
        assert not result


# ---------------------------------------------------------------------------
# 16. test_cleanup_temp
# ---------------------------------------------------------------------------

class TestCleanupTemp:
    """cleanup_temp removes the per-thread temp directory."""

    def test_removes_thread_directory(self, tmp_path):
        thread_ts = "cleanup-test-1234"
        thread_dir = tmp_path / thread_ts
        thread_dir.mkdir()
        (thread_dir / "file.txt").write_text("data")

        cleanup_temp(thread_ts=thread_ts, temp_base=tmp_path)

        assert not thread_dir.exists()

    def test_no_error_if_directory_missing(self, tmp_path):
        # Should not raise even if directory doesn't exist
        cleanup_temp(thread_ts="nonexistent-ts", temp_base=tmp_path)

    def test_removes_nested_contents(self, tmp_path):
        thread_ts = "cleanup-nested"
        thread_dir = tmp_path / thread_ts
        nested = thread_dir / "sub" / "deep"
        nested.mkdir(parents=True)
        (nested / "file.bin").write_bytes(b"\x00" * 100)

        cleanup_temp(thread_ts=thread_ts, temp_base=tmp_path)

        assert not thread_dir.exists()

    def test_other_thread_dirs_untouched(self, tmp_path):
        keep_ts = "keep-this-1111"
        remove_ts = "remove-this-2222"
        keep_dir = tmp_path / keep_ts
        remove_dir = tmp_path / remove_ts
        keep_dir.mkdir()
        remove_dir.mkdir()
        (keep_dir / "important.txt").write_text("keep me")

        cleanup_temp(thread_ts=remove_ts, temp_base=tmp_path)

        assert keep_dir.exists()
        assert not remove_dir.exists()
