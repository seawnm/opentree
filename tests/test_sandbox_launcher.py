from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from opentree.runner.sandbox_launcher import (
    BLOCKED_DOMAINS,
    _resolve_tool_binds,
    build_bwrap_args,
    check_bwrap_or_raise,
    is_bwrap_available,
)


def test_build_bwrap_args_starts_with_bwrap() -> None:
    args = build_bwrap_args(["claude", "--print"], "/work", "/home/test")
    assert args[0] == "bwrap"


def test_build_bwrap_args_has_unshare_all() -> None:
    args = build_bwrap_args(["claude"], "/work", "/home/test")
    assert "--unshare-all" in args


def test_build_bwrap_args_has_share_net() -> None:
    args = build_bwrap_args(["claude"], "/work", "/home/test")
    assert "--share-net" in args


def test_build_bwrap_args_has_die_with_parent() -> None:
    args = build_bwrap_args(["claude"], "/work", "/home/test")
    assert "--die-with-parent" in args


def test_build_bwrap_args_owner_workspace_is_rw() -> None:
    args = build_bwrap_args(["claude"], "/host/workspace", "/home/test", owner=True)
    idx = args.index("--bind")
    assert args[idx + 1] == "/host/workspace"
    assert args[idx + 2] == "/workspace"


def test_build_bwrap_args_non_owner_workspace_is_ro() -> None:
    args = build_bwrap_args(["claude"], "/host/workspace", "/home/test", owner=False)
    idx = args.index("--ro-bind")
    assert args[idx + 1] == "/host/workspace"
    assert args[idx + 2] == "/workspace"


def test_build_bwrap_args_home_claude_bind_is_rw() -> None:
    args = build_bwrap_args(["claude"], "/work", "/home/test")
    for idx in range(len(args) - 2):
        if args[idx:idx + 3] == ["--bind-try", "/home/test/.claude", "/workspace/.claude"]:
            break
    else:
        pytest.fail("missing ~/.claude -> /workspace/.claude bind")
    assert args[idx] == "--bind-try"


def test_build_bwrap_args_usr_bin_lib_are_ro() -> None:
    args = build_bwrap_args(["claude"], "/work", "/home/test")
    assert ["--ro-bind", "/usr", "/usr"] in [args[i:i + 3] for i in range(len(args) - 2)]
    assert ["--ro-bind", "/bin", "/bin"] in [args[i:i + 3] for i in range(len(args) - 2)]
    assert ["--ro-bind", "/lib", "/lib"] in [args[i:i + 3] for i in range(len(args) - 2)]


def test_build_bwrap_args_lib64_uses_ro_bind_try() -> None:
    args = build_bwrap_args(["claude"], "/work", "/home/test")
    assert ["--ro-bind-try", "/lib64", "/lib64"] in [
        args[i:i + 3] for i in range(len(args) - 2)
    ]


def test_build_bwrap_args_etc_resolv_conf_present() -> None:
    args = build_bwrap_args(["claude"], "/work", "/home/test")
    assert ["--ro-bind-try", "/etc/resolv.conf", "/etc/resolv.conf"] in [
        args[i:i + 3] for i in range(len(args) - 2)
    ]


def test_build_bwrap_args_claude_bound_to_workspace_home() -> None:
    args = build_bwrap_args(["claude"], "/work", "/home/test")
    assert ["--bind-try", "/home/test/.claude", "/workspace/.claude"] in [
        args[i:i + 3] for i in range(len(args) - 2)
    ]


def test_build_bwrap_args_setenv_home_workspace() -> None:
    args = build_bwrap_args(["claude"], "/work", "/home/test")
    idx = args.index("--setenv")
    assert args[idx + 1:idx + 4] == ["HOME", "/workspace", "--chdir"]


def test_build_bwrap_args_chdir_workspace() -> None:
    args = build_bwrap_args(["claude"], "/work", "/home/test")
    idx = args.index("--chdir")
    assert args[idx + 1] == "/workspace"


def test_build_bwrap_args_separator_before_original_args() -> None:
    args = build_bwrap_args(["claude", "--print"], "/work", "/home/test")
    sep_idx = args.index("--")
    assert args[sep_idx + 1] == "claude"


def test_build_bwrap_args_original_args_at_end() -> None:
    original = ["claude", "--print", "hello"]
    args = build_bwrap_args(original, "/work", "/home/test")
    assert args[-len(original):] == original


def test_is_bwrap_available_true() -> None:
    with patch("opentree.runner.sandbox_launcher.shutil.which", return_value="/usr/bin/bwrap"):
        assert is_bwrap_available() is True


def test_is_bwrap_available_false() -> None:
    with patch("opentree.runner.sandbox_launcher.shutil.which", return_value=None):
        assert is_bwrap_available() is False


def test_check_bwrap_or_raise_raises_when_missing() -> None:
    with patch("opentree.runner.sandbox_launcher.shutil.which", return_value=None):
        with pytest.raises(RuntimeError, match="bubblewrap \\(bwrap\\) is required but not installed"):
            check_bwrap_or_raise()


def test_check_bwrap_or_raise_no_raise_when_present() -> None:
    with patch("opentree.runner.sandbox_launcher.shutil.which", return_value="/usr/bin/bwrap"):
        check_bwrap_or_raise()


def test_blocked_domains_is_empty_list() -> None:
    assert BLOCKED_DOMAINS == []


def test_resolve_tool_binds_returns_empty_when_under_usr(tmp_path: Path) -> None:
    home = tmp_path / "home"
    (home / ".local").mkdir(parents=True)
    (home / ".nvm").mkdir(parents=True)

    def fake_which(name: str) -> str | None:
        if name == "node":
            return "/usr/bin/node"
        if name == "claude":
            return "/usr/bin/claude"
        return None

    with patch("opentree.runner.sandbox_launcher.shutil.which", side_effect=fake_which):
        assert _resolve_tool_binds(str(home), "claude") == []


def test_resolve_tool_binds_returns_bind_when_nvm(tmp_path: Path) -> None:
    home = tmp_path / "home"
    nvm_root = home / ".nvm"
    node_path = nvm_root / "versions" / "node" / "v20.0.0" / "bin" / "node"
    nvm_root.mkdir(parents=True)
    node_path.parent.mkdir(parents=True)
    node_path.write_text("", encoding="utf-8")

    def fake_which(name: str) -> str | None:
        if name == "node":
            return str(node_path)
        return None

    with patch("opentree.runner.sandbox_launcher.shutil.which", side_effect=fake_which):
        assert _resolve_tool_binds(str(home), "claude") == [
            "--ro-bind",
            str(nvm_root),
            str(nvm_root),
        ]


def test_resolve_tool_binds_never_binds_whole_home(tmp_path: Path) -> None:
    home = tmp_path / "home"
    local_root = home / ".local"
    node_path = local_root / "bin" / "node"
    local_root.mkdir(parents=True)
    node_path.parent.mkdir(parents=True)
    node_path.write_text("", encoding="utf-8")

    def fake_which(name: str) -> str | None:
        if name == "node":
            return str(node_path)
        return None

    with patch("opentree.runner.sandbox_launcher.shutil.which", side_effect=fake_which):
        binds = _resolve_tool_binds(str(home), "claude")

    assert binds == [
        "--ro-bind",
        str(local_root),
        str(local_root),
    ]
    assert str(home) not in binds
