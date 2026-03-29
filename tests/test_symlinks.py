"""Tests for SymlinkManager — TDD RED phase first.

All tests use tmp_path to avoid filesystem side effects.
Mock module directories contain actual .md rule files.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from opentree.generator.symlinks import LinkResult, SymlinkManager


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _setup_opentree_home(tmp_path: Path) -> Path:
    """Create a minimal OPENTREE_HOME directory structure."""
    home = tmp_path / "opentree_home"
    (home / "modules").mkdir(parents=True)
    (home / "workspace" / ".claude" / "rules").mkdir(parents=True)
    return home


def _create_module_rules(
    home: Path, module_name: str, rule_files: list[str]
) -> Path:
    """Create a module directory with .md rule files on disk."""
    rules_dir = home / "modules" / module_name / "rules"
    rules_dir.mkdir(parents=True, exist_ok=True)
    for fname in rule_files:
        (rules_dir / fname).write_text(
            f"# {fname}\nRule content for {module_name}.", encoding="utf-8"
        )
    return rules_dir


# ---------------------------------------------------------------------------
# 1. test_create_module_links_symlink
# ---------------------------------------------------------------------------


def test_create_module_links_symlink(tmp_path: Path) -> None:
    """Symlinks are created in .claude/rules/<module>/ pointing to source."""
    home = _setup_opentree_home(tmp_path)
    _create_module_rules(home, "core", ["identity.md", "routing.md"])

    mgr = SymlinkManager(home)
    results = mgr.create_module_links("core", ["identity.md", "routing.md"])

    assert len(results) == 2
    for r in results:
        assert r.success is True
        target = Path(r.target)
        assert target.exists()
        assert target.read_text(encoding="utf-8").startswith("# ")
    # Verify target directory structure
    target_dir = home / "workspace" / ".claude" / "rules" / "core"
    assert target_dir.is_dir()
    assert (target_dir / "identity.md").exists()
    assert (target_dir / "routing.md").exists()


# ---------------------------------------------------------------------------
# 2. test_create_module_links_source_missing
# ---------------------------------------------------------------------------


def test_create_module_links_source_missing(tmp_path: Path) -> None:
    """Raises FileNotFoundError when a rule file does not exist on disk."""
    home = _setup_opentree_home(tmp_path)
    # Create module dir but no rule files
    (home / "modules" / "core" / "rules").mkdir(parents=True)

    mgr = SymlinkManager(home)
    with pytest.raises(FileNotFoundError, match="identity.md"):
        mgr.create_module_links("core", ["identity.md"])


# ---------------------------------------------------------------------------
# 3. test_create_module_links_creates_directory
# ---------------------------------------------------------------------------


def test_create_module_links_creates_directory(tmp_path: Path) -> None:
    """Target module directory is auto-created if it does not exist."""
    home = _setup_opentree_home(tmp_path)
    _create_module_rules(home, "guardrail", ["safety.md"])

    # Remove the target module directory if it exists
    target_dir = home / "workspace" / ".claude" / "rules" / "guardrail"
    assert not target_dir.exists()

    mgr = SymlinkManager(home)
    results = mgr.create_module_links("guardrail", ["safety.md"])

    assert results[0].success is True
    assert target_dir.is_dir()
    assert (target_dir / "safety.md").exists()


# ---------------------------------------------------------------------------
# 4. test_remove_module_links_symlink
# ---------------------------------------------------------------------------


def test_remove_module_links_symlink(tmp_path: Path) -> None:
    """Removes symlink dir cleanly when link_method='symlink'."""
    home = _setup_opentree_home(tmp_path)
    _create_module_rules(home, "core", ["identity.md"])

    mgr = SymlinkManager(home)
    mgr.create_module_links("core", ["identity.md"])

    target_dir = home / "workspace" / ".claude" / "rules" / "core"
    assert target_dir.exists()

    mgr.remove_module_links("core", link_method="symlink")
    assert not target_dir.exists()


# ---------------------------------------------------------------------------
# 5. test_remove_module_links_copy
# ---------------------------------------------------------------------------


def test_remove_module_links_copy(tmp_path: Path) -> None:
    """Removes copied files (rmtree) when link_method='copy'."""
    home = _setup_opentree_home(tmp_path)
    _create_module_rules(home, "core", ["identity.md"])

    mgr = SymlinkManager(home)
    # Manually create a copy (simulate copy link_method)
    target_dir = home / "workspace" / ".claude" / "rules" / "core"
    target_dir.mkdir(parents=True, exist_ok=True)
    source = home / "modules" / "core" / "rules" / "identity.md"
    import shutil

    shutil.copy2(source, target_dir / "identity.md")

    assert (target_dir / "identity.md").exists()
    assert not (target_dir / "identity.md").is_symlink()

    mgr.remove_module_links("core", link_method="copy")
    assert not target_dir.exists()


# ---------------------------------------------------------------------------
# 6. test_remove_preserves_user_files
# ---------------------------------------------------------------------------


def test_remove_preserves_user_files(tmp_path: Path) -> None:
    """Non-symlink files are moved to .trash/ before removal."""
    home = _setup_opentree_home(tmp_path)
    _create_module_rules(home, "core", ["identity.md"])

    mgr = SymlinkManager(home)
    mgr.create_module_links("core", ["identity.md"])

    # User adds a manual file inside the module's rules dir
    target_dir = home / "workspace" / ".claude" / "rules" / "core"
    user_file = target_dir / "my-custom-rule.md"
    user_file.write_text("# My custom rule", encoding="utf-8")

    mgr.remove_module_links("core", link_method="symlink")

    # Module dir should be gone
    assert not target_dir.exists()

    # User file should be preserved in .trash/
    trash_dir = home / "workspace" / ".claude" / "rules" / ".trash" / "core"
    assert trash_dir.exists()
    preserved = trash_dir / "my-custom-rule.md"
    assert preserved.exists()
    assert preserved.read_text(encoding="utf-8") == "# My custom rule"


# ---------------------------------------------------------------------------
# 7. test_reconcile_all_from_scratch
# ---------------------------------------------------------------------------


def test_reconcile_all_from_scratch(tmp_path: Path) -> None:
    """Builds all links for multiple modules from empty state."""
    home = _setup_opentree_home(tmp_path)
    _create_module_rules(home, "core", ["identity.md", "routing.md"])
    _create_module_rules(home, "guardrail", ["safety.md"])

    mgr = SymlinkManager(home)
    results = mgr.reconcile_all(
        {
            "core": ["identity.md", "routing.md"],
            "guardrail": ["safety.md"],
        }
    )

    assert "core" in results
    assert "guardrail" in results
    assert len(results["core"]) == 2
    assert len(results["guardrail"]) == 1
    assert all(r.success for r in results["core"])
    assert all(r.success for r in results["guardrail"])


# ---------------------------------------------------------------------------
# 8. test_reconcile_all_cleans_stale
# ---------------------------------------------------------------------------


def test_reconcile_all_cleans_stale(tmp_path: Path) -> None:
    """Removes dirs not in module_rules during reconcile."""
    home = _setup_opentree_home(tmp_path)
    _create_module_rules(home, "core", ["identity.md"])
    _create_module_rules(home, "old-module", ["legacy.md"])

    mgr = SymlinkManager(home)
    # First install both
    mgr.create_module_links("core", ["identity.md"])
    mgr.create_module_links("old-module", ["legacy.md"])

    rules_dir = home / "workspace" / ".claude" / "rules"
    assert (rules_dir / "old-module").exists()

    # Reconcile with only core
    mgr.reconcile_all({"core": ["identity.md"]})

    assert (rules_dir / "core").exists()
    assert not (rules_dir / "old-module").exists()


# ---------------------------------------------------------------------------
# 9. test_verify_all_valid
# ---------------------------------------------------------------------------


def test_verify_all_valid(tmp_path: Path) -> None:
    """Returns empty list when all symlinks resolve."""
    home = _setup_opentree_home(tmp_path)
    _create_module_rules(home, "core", ["identity.md"])

    mgr = SymlinkManager(home)
    mgr.create_module_links("core", ["identity.md"])

    broken = mgr.verify()
    assert broken == []


# ---------------------------------------------------------------------------
# 10. test_verify_broken_symlink
# ---------------------------------------------------------------------------


def test_verify_broken_symlink(tmp_path: Path) -> None:
    """Returns broken symlink path when source file is deleted."""
    home = _setup_opentree_home(tmp_path)
    _create_module_rules(home, "core", ["identity.md"])

    mgr = SymlinkManager(home)
    mgr.create_module_links("core", ["identity.md"])

    # Delete the source file to break the symlink
    source = home / "modules" / "core" / "rules" / "identity.md"
    source.unlink()

    broken = mgr.verify()
    assert len(broken) == 1
    assert "identity.md" in broken[0]


# ---------------------------------------------------------------------------
# 11. test_fallback_to_copy
# ---------------------------------------------------------------------------


def test_fallback_to_copy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """When os.symlink raises OSError, falls back to copy."""
    home = _setup_opentree_home(tmp_path)
    _create_module_rules(home, "core", ["identity.md"])

    # Mock os.symlink to always fail
    def _fail_symlink(*args: object, **kwargs: object) -> None:
        raise OSError("Symlink not supported")

    monkeypatch.setattr(os, "symlink", _fail_symlink)

    mgr = SymlinkManager(home)
    results = mgr.create_module_links("core", ["identity.md"])

    assert len(results) == 1
    r = results[0]
    assert r.success is True
    # Should have fallen back to copy (junction skipped for files)
    assert r.method == "copy"
    # Verify it's a real file copy, not a symlink
    target = Path(r.target)
    assert target.exists()
    assert not target.is_symlink()
    assert target.read_text(encoding="utf-8").startswith("# ")


# ---------------------------------------------------------------------------
# 12. test_link_result_frozen
# ---------------------------------------------------------------------------


def test_link_result_frozen() -> None:
    """LinkResult is immutable (frozen dataclass)."""
    result = LinkResult(
        source="/a/b", target="/c/d", method="symlink", success=True
    )
    with pytest.raises(AttributeError):
        result.success = False  # type: ignore[misc]


# ---------------------------------------------------------------------------
# 13. test_create_links_returns_consistent_method
# ---------------------------------------------------------------------------


def test_create_links_returns_consistent_method(tmp_path: Path) -> None:
    """All rules in a single create_module_links call use the same method."""
    home = _setup_opentree_home(tmp_path)
    _create_module_rules(home, "core", ["identity.md", "routing.md", "env.md"])

    mgr = SymlinkManager(home)
    results = mgr.create_module_links(
        "core", ["identity.md", "routing.md", "env.md"]
    )

    methods = {r.method for r in results}
    assert len(methods) == 1, f"Expected one method, got {methods}"


# ---------------------------------------------------------------------------
# 14. test_remove_empty_module
# ---------------------------------------------------------------------------


def test_remove_empty_module(tmp_path: Path) -> None:
    """Removing a module whose dir doesn't exist is idempotent (no error)."""
    home = _setup_opentree_home(tmp_path)
    mgr = SymlinkManager(home)

    # Should not raise
    mgr.remove_module_links("nonexistent", link_method="symlink")
