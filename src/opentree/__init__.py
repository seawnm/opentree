"""OpenTree: Modular Claude Code CLI wrapper for personal AI agents."""

try:
    from importlib.metadata import PackageNotFoundError, version as _meta_version
    __version__ = _meta_version("opentree")
except PackageNotFoundError:
    __version__ = "0.6.1"  # SYNC: update on version bump (pyproject.toml is the source of truth)
