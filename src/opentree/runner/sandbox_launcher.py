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
      /workspace                   — user workspace (RW for owner, RO for others)
      /home/codex                  — tmpfs, serves as HOME
      /home/codex/.codex           — RW bind from workspace/.codex (persistent state)
      /home/codex/.codex/auth.json — RO bind from ~/.codex/auth.json (overlaid on top)
      /home/codex/.claude          — bind from real ~/.claude (RW)
      /tmp                         — tmpfs
      /tmp/opentree                — bind from host (RW, if it exists)

    Codex uses HOME/.codex for BOTH authentication (auth.json) and persistent state
    (state_5.sqlite, sessions/, rollout files for resume).  workspace/.codex is bound
    directly to HOME/.codex so that state survives across bwrap invocations and
    ``codex exec resume`` can find the rollout from a previous turn.

    auth.json is overlaid RO on top of the RW workspace/.codex bind so the host
    credential is shared across instances without being writable inside the sandbox.
    Since --ro-bind-try mounts a new filesystem layer over the existing bind, the RW
    workspace/.codex directory need not contain auth.json itself.

    The workspace/.codex directory must be pre-created on the host by the caller
    (CodexProcess.run) before bwrap is launched; bwrap cannot mkdir inside a
    read-only bind mount.
    """
    claude_dir = f"{home}/.claude"
    workspace_bind_mode = "--bind" if owner else "--ro-bind"

    # sandbox HOME is always a writable tmpfs dir, independent of workspace rw/ro
    sandbox_home = "/home/codex"

    bind_parts: list[str] = [
        "bwrap",
        "--unshare-all",
        "--share-net",
        "--die-with-parent",
        "--new-session",  # setsid: detach from controlling TTY so Codex never reads stdin
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

    # Bind workspace/.codex → HOME/.codex (always RW).
    # Codex uses HOME/.codex for both session state (state_5.sqlite, sessions/,
    # rollout files) and auth.  Binding workspace/.codex here ensures state
    # persists across bwrap invocations so `codex exec resume` can find rollouts.
    # Pre-creation of workspace/.codex on the host is the caller's responsibility
    # (CodexProcess.run), since bwrap cannot mkdir inside a read-only bind mount.
    workspace_codex_dir = Path(workspace_path) / ".codex"
    if workspace_codex_dir.exists():
        bind_parts.extend(["--bind", str(workspace_codex_dir), f"{sandbox_home}/.codex"])

    # Overlay auth.json RO on top of the workspace/.codex bind.
    # auth_mode=chatgpt: Codex reads tokens from HOME/.codex/auth.json.
    # --ro-bind-try mounts a fresh filesystem layer over the existing directory
    # bind, so auth.json from the host is visible inside without being writable.
    host_auth_json = Path(home) / ".codex" / "auth.json"
    if host_auth_json.exists():
        bind_parts.extend(
            ["--ro-bind-try", str(host_auth_json), f"{sandbox_home}/.codex/auth.json"]
        )

    tmp_opentree = "/tmp/opentree"
    if Path(tmp_opentree).exists():
        bind_parts.extend(["--bind", tmp_opentree, tmp_opentree])

    # .claude is mounted under the tmpfs HOME, not under /workspace,
    # so bwrap never needs to mkdir inside a read-only bind.
    bind_parts.extend(
        [
            "--bind-try",
            claude_dir,
            f"{sandbox_home}/.claude",
        ]
    )

    # System CA bundle path — needed for Codex (Node.js) TLS verification.
    _CA_BUNDLE = "/etc/ssl/certs/ca-certificates.crt"

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
            # Use --ro-bind (not --ro-bind-try) so the mount fails loudly if
            # /etc/ssl is missing rather than silently leaving Codex without TLS.
            "--ro-bind",
            "/etc/ssl",
            "/etc/ssl",
            "--ro-bind-try",
            "/etc/ca-certificates",
            "/etc/ca-certificates",
            *_resolve_tool_binds(home, original_args[0] if original_args else ""),
            "--setenv",
            "HOME",
            sandbox_home,
            # Codex (Node.js / Rust native-tls) needs to find the system CA
            # bundle inside the sandbox; point both common env vars at it.
            "--setenv",
            "SSL_CERT_FILE",
            _CA_BUNDLE,
            "--setenv",
            "NODE_EXTRA_CA_CERTS",
            _CA_BUNDLE,
            "--chdir",
            "/workspace",
            "--",
            *original_args,
        ]
    )
    return bind_parts
