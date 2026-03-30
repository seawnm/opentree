"""File handler for OpenTree bot runner.

Downloads Slack file attachments to a local temporary directory so
Claude CLI can access them via the filesystem.
"""
from __future__ import annotations

import logging
import shutil
import urllib.request
from pathlib import Path

logger = logging.getLogger(__name__)

# Default temp directory base
DEFAULT_TEMP_BASE = Path("/tmp/opentree")

# Maximum file size (50 MB)
MAX_FILE_SIZE = 50 * 1024 * 1024


def download_files(
    files: list[dict],
    thread_ts: str,
    bot_token: str,
    temp_base: Path = DEFAULT_TEMP_BASE,
) -> list[dict]:
    """Download Slack file attachments to local temp directory.

    Args:
        files: List of Slack file objects (from event payload)
        thread_ts: Thread timestamp (used for directory naming)
        bot_token: Slack bot token (for auth header)
        temp_base: Base temp directory

    Returns:
        List of dicts with download info:
        [{"name": "file.py", "local_path": "/tmp/opentree/.../file.py",
          "mimetype": "text/plain", "size": 1234}]

        Each file is downloaded to: {temp_base}/{thread_ts}/{filename}
        Duplicate filenames get a numeric suffix: file.py, file_1.py, etc.
    """
    thread_dir = temp_base / thread_ts
    thread_dir.mkdir(parents=True, exist_ok=True)

    downloaded: list[dict] = []

    for file in files:
        url = file.get("url_private_download")
        if not url:
            logger.debug("Skipping file with no url_private_download: %s", file.get("name"))
            continue

        size = file.get("size", 0)
        if size > MAX_FILE_SIZE:
            logger.warning(
                "Skipping file %s: size %d exceeds MAX_FILE_SIZE %d",
                file.get("name"),
                size,
                MAX_FILE_SIZE,
            )
            continue

        safe_name = _safe_filename(file.get("name") or "unnamed")
        local_path = thread_dir / safe_name

        # Resolve duplicate filenames
        if local_path.exists():
            stem = local_path.stem
            suffix = local_path.suffix
            counter = 1
            while local_path.exists():
                local_path = thread_dir / f"{stem}_{counter}{suffix}"
                counter += 1

        try:
            req = urllib.request.Request(
                url,
                headers={"Authorization": f"Bearer {bot_token}"},
            )
            response = urllib.request.urlopen(req)
            data = response.read()
            local_path.write_bytes(data)
            downloaded.append(
                {
                    "name": file.get("name", safe_name),
                    "local_path": str(local_path),
                    "mimetype": file.get("mimetype", "application/octet-stream"),
                    "size": size,
                }
            )
            logger.info("Downloaded %s -> %s", file.get("name"), local_path)
        except Exception as exc:
            logger.warning("Failed to download %s: %s", file.get("name"), exc)

    return downloaded


def build_file_context(downloaded: list[dict]) -> str:
    """Build a context string describing downloaded files.

    Format::

        ---
        Attached files:
        - file.py (text/plain, 1.2 KB): /tmp/opentree/.../file.py
        - image.png (image/png, 45.3 KB): /tmp/opentree/.../image.png
        ---

    Returns empty string if no files were downloaded.
    """
    if not downloaded:
        return ""

    lines = ["---", "Attached files:"]
    for entry in downloaded:
        human_size = _format_size(entry.get("size", 0))
        lines.append(
            f"- {entry['name']} ({entry.get('mimetype', '')}, {human_size}):"
            f" {entry['local_path']}"
        )
    lines.append("---")
    return "\n".join(lines)


def _safe_filename(name: str) -> str:
    """Sanitize filename: remove path separators, limit length.

    Args:
        name: Raw filename from Slack file object.

    Returns:
        A safe filename string, or ``"unnamed"`` when nothing valid remains.
    """
    if not name:
        return "unnamed"

    # Strip null bytes
    name = name.replace("\x00", "")

    # Extract only the final path component (handles / and \\)
    # Use str operations to handle both separators
    for sep in ("/", "\\"):
        name = name.split(sep)[-1]

    # Repeatedly remove ".." sequences until stable (prevents "..../" bypass)
    prev = None
    while prev != name:
        prev = name
        name = name.replace("..", "")

    name = name.strip()
    if not name or name == ".":
        return "unnamed"

    # Enforce maximum filename length (255 bytes is common OS limit)
    if len(name) > 255:
        name = name[:255]

    return name


def _format_size(size_bytes: int) -> str:
    """Format bytes as human-readable: '1.2 KB', '3.4 MB'.

    Args:
        size_bytes: File size in bytes.

    Returns:
        Human-readable size string.
    """
    if size_bytes < 1024:
        return f"{size_bytes} B"
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    return f"{size_bytes / (1024 * 1024):.1f} MB"


def cleanup_temp(thread_ts: str, temp_base: Path = DEFAULT_TEMP_BASE) -> None:
    """Remove temp directory for a thread.

    Args:
        thread_ts: Thread timestamp identifying the directory to remove.
        temp_base: Base temp directory (default: DEFAULT_TEMP_BASE).
    """
    thread_dir = temp_base / thread_ts
    if thread_dir.exists():
        shutil.rmtree(thread_dir)
        logger.debug("Cleaned up temp directory: %s", thread_dir)
    else:
        logger.debug("Cleanup: directory not found (already removed?): %s", thread_dir)
