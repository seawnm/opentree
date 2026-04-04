"""OpenTree: Modular Claude Code CLI wrapper for personal AI agents."""

try:
    from importlib.metadata import version as _meta_version
    __version__ = _meta_version("opentree")
except Exception:
    __version__ = "0.4.0"  # SYNC: update on version bump (pyproject.toml is the source of truth)
