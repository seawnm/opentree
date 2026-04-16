"""bubblewrap sandbox launcher helpers for OpenTree runner."""

from __future__ import annotations

import shutil
from pathlib import Path

BLOCKED_DOMAINS: list[str] = []


def is_bwrap_available() -> bool:
    """Return True when ``bwrap`` is available on PATH."""
    return shutil.which("bwrap") is not None


def check_bwrap_or_raise() -> None:
    """Raise when bubblewrap is unavailable."""
    if not is_bwrap_available():
        raise RuntimeError(
            "bubblewrap (bwrap) is required but not installed. "
            "Install with: sudo apt-get install -y bubblewrap"
        )


def _resolve_tool_binds(home: str, command: str) -> list[str]:
    """Return narrow RO binds for ~/.local or ~/.nvm tool installations only."""
    home_path = Path(home).resolve()
    allowed_roots = [home_path / ".local", home_path / ".nvm"]
    binds: list[str] = []
    seen: set[str] = set()

    for tool_name in (command, "node"):
        if not tool_name:
            continue
        tool_path = shutil.which(tool_name)
        if tool_path is None:
            continue

        resolved = Path(tool_path).resolve()
        for root in allowed_roots:
            if root.exists() and resolved.is_relative_to(root):
                root_str = str(root)
                if root_str not in seen:
                    binds.extend(["--ro-bind", root_str, root_str])
                    seen.add(root_str)

    return binds


def build_bwrap_args(
    original_args: list[str],
    workspace_path: str,
    home: str,
    owner: bool = False,
) -> list[str]:
    """Build the complete ``bwrap`` command line.

    Layout inside the sandbox:
      /workspace  — the user workspace (RW for owner, RO for others)
      /home/codex — tmpfs, serves as HOME so Codex can write .codex/ etc.
      /home/codex/.claude — bind from real ~/.claude (RW)
      /home/codex/.codex  — bind from real ~/.codex  (RW, if it exists)
      /tmp        — tmpfs
      /tmp/opentree — bind from host (RW, if it exists)

    Using a separate tmpfs for HOME avoids the "Can't mkdir inside a read-only
    bind mount" problem that occurs when HOME=/workspace and workspace is
    mounted read-only for non-owner users.
    """
    claude_dir = f"{home}/.claude"
    codex_dir = f"{home}/.codex"
    workspace_bind_mode = "--bind" if owner else "--ro-bind"

    # sandbox HOME is always a writable tmpfs dir, independent of workspace rw/ro
    sandbox_home = "/home/codex"

    bind_parts: list[str] = [
        "bwrap",
        "--unshare-all",
        "--share-net",
        "--die-with-parent",
        "--proc",
        "/proc",
        "--dev",
        "/dev",
        "--tmpfs",
        "/tmp",
        "--tmpfs",
        "/home",
        workspace_bind_mode,
        workspace_path,
        "/workspace",
    ]

    tmp_opentree = "/tmp/opentree"
    if Path(tmp_opentree).exists():
        bind_parts.extend(["--bind", tmp_opentree, tmp_opentree])

    # .claude and .codex are mounted under the tmpfs HOME, not under /workspace,
    # so bwrap never needs to mkdir inside a read-only bind.
    bind_parts.extend(
        [
            "--bind-try",
            claude_dir,
            f"{sandbox_home}/.claude",
        ]
    )
    if Path(codex_dir).exists():
        bind_parts.extend(["--bind", codex_dir, f"{sandbox_home}/.codex"])

    bind_parts.extend(
        [
            "--ro-bind",
            "/usr",
            "/usr",
            "--ro-bind",
            "/bin",
            "/bin",
            "--ro-bind",
            "/lib",
            "/lib",
            "--ro-bind-try",
            "/lib64",
            "/lib64",
            "--ro-bind-try",
            "/lib32",
            "/lib32",
            "--ro-bind-try",
            "/etc/resolv.conf",
            "/etc/resolv.conf",
            "--ro-bind-try",
            "/etc/hosts",
            "/etc/hosts",
            "--ro-bind-try",
            "/etc/nsswitch.conf",
            "/etc/nsswitch.conf",
            "--ro-bind-try",
            "/etc/ssl",
            "/etc/ssl",
            "--ro-bind-try",
            "/etc/ca-certificates",
            "/etc/ca-certificates",
            *_resolve_tool_binds(home, original_args[0] if original_args else ""),
            "--setenv",
            "HOME",
            sandbox_home,
            "--chdir",
            "/workspace",
            "--",
            *original_args,
        ]
    )
    return bind_parts
