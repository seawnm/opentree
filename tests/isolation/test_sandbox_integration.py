from __future__ import annotations

import subprocess

import pytest

from opentree.runner.sandbox_launcher import is_bwrap_available

pytestmark = pytest.mark.skipif(
    not is_bwrap_available(),
    reason="bwrap not installed",
)


def test_bwrap_echo_works() -> None:
    result = subprocess.run(
        [
            "bwrap",
            "--unshare-all",
            "--share-net",
            "--proc",
            "/proc",
            "--dev",
            "/dev",
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
            "--",
            "/bin/echo",
            "hello",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "hello"


def test_bwrap_workspace_bind_writable(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    result = subprocess.run(
        [
            "bwrap",
            "--unshare-all",
            "--share-net",
            "--proc",
            "/proc",
            "--dev",
            "/dev",
            "--tmpfs",
            "/tmp",
            "--bind",
            str(workspace),
            "/workspace",
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
            "--chdir",
            "/workspace",
            "--",
            "/bin/sh",
            "-c",
            "touch /workspace/test.txt",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert (workspace / "test.txt").exists()


def test_bwrap_home_is_workspace(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    result = subprocess.run(
        [
            "bwrap",
            "--unshare-all",
            "--share-net",
            "--proc",
            "/proc",
            "--dev",
            "/dev",
            "--tmpfs",
            "/tmp",
            "--bind",
            str(workspace),
            "/workspace",
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
            "--setenv",
            "HOME",
            "/workspace",
            "--chdir",
            "/workspace",
            "--",
            "/bin/sh",
            "-c",
            "echo $HOME",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "/workspace"
