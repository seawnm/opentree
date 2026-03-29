"""Shared test fixtures for OpenTree tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest


@pytest.fixture()
def valid_minimal_manifest() -> dict[str, Any]:
    """A minimal valid manifest with only required fields."""
    return {
        "name": "test-module",
        "version": "1.0.0",
        "description": "A test module for validation",
        "type": "optional",
        "loading": {
            "rules": ["test-rule.md"],
        },
    }


@pytest.fixture()
def valid_full_manifest() -> dict[str, Any]:
    """A fully populated valid manifest with all optional fields."""
    return {
        "name": "full-module",
        "version": "2.1.0",
        "description": "A fully featured test module",
        "author": "OpenTree Test",
        "license": "MIT",
        "type": "pre-installed",
        "depends_on": ["core"],
        "conflicts_with": ["legacy-module"],
        "loading": {
            "rules": ["main-rule.md", "helper-rule.md"],
        },
        "triggers": {
            "keywords": ["test", "demo"],
            "description": "Test module for validation",
        },
        "permissions": {
            "allow": ["Bash(echo:*)"],
            "deny": ["mcp__dangerous_tool"],
        },
        "prompt_hook": "prompt_hook.py",
        "placeholders": {
            "bot_name": "required",
            "opentree_home": "auto",
            "team_name": "optional",
        },
        "hooks": {
            "on_install": "scripts/install.sh",
            "on_remove": None,
        },
    }


@pytest.fixture()
def tmp_registry_dir(tmp_path: Path) -> Path:
    """Create a temporary directory structure mimicking a module registry.

    Returns the tmp_path that can be used as a base for test modules.
    """
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    modules_dir = tmp_path / "modules"
    modules_dir.mkdir()
    return tmp_path


def write_manifest(module_dir: Path, manifest: dict[str, Any]) -> Path:
    """Helper to write a manifest dict to a module directory.

    Args:
        module_dir: The module directory (will be created if needed).
        manifest: The manifest data to write.

    Returns:
        The path to the written opentree.json file.
    """
    module_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = module_dir / "opentree.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest_path
