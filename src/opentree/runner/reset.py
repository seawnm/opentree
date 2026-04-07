"""Reset helpers for OpenTree bot.

Provides two reset levels:
- reset_bot(): Soft reset -- regenerate settings/symlinks/CLAUDE.md (session clearing is caller's responsibility)
- reset_bot_all(): Hard reset -- clear owner customizations + data, regenerate everything
"""

from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path

from opentree.core.config import load_user_config
from opentree.core.placeholders import PlaceholderEngine
from opentree.generator.claude_md import ClaudeMdGenerator
from opentree.generator.settings import SettingsGenerator
from opentree.generator.symlinks import SymlinkManager
from opentree.registry.registry import Registry

logger = logging.getLogger(__name__)


def reset_bot(home: Path) -> list[str]:
    """Soft reset: regenerate settings + symlinks + CLAUDE.md auto block.

    Session clearing is the caller's responsibility (call SessionManager.clear_all()).

    Preserves: .env.local, .env.secrets, CLAUDE.md owner content, data/
    Resets: settings.json, rules symlinks, CLAUDE.md auto block

    Returns list of action descriptions for logging/reporting.

    Raises:
        RuntimeError: If registry.json is not found (must run 'opentree init' first).
    """
    actions: list[str] = []
    config = load_user_config(home)

    # 1. Load registry
    reg_path = home / "config" / "registry.json"
    if not reg_path.exists():
        raise RuntimeError("Registry not found. Run 'opentree init' first.")
    registry_data = Registry.load(reg_path)

    # 2. Regenerate permissions + settings.json
    try:
        settings_gen = SettingsGenerator(home)
        settings_gen.reset_module_permissions()
        for name, _entry in registry_data.modules:
            manifest_path = home / "modules" / name / "opentree.json"
            if manifest_path.exists():
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                permissions = manifest.get("permissions", {})
                settings_gen.add_module_permissions(
                    name,
                    allow=permissions.get("allow", []),
                    deny=permissions.get("deny", []),
                )
        settings_gen.write_settings()
        actions.append("Regenerated settings.json")
    except Exception as exc:
        logger.warning("Failed to regenerate settings: %s", exc)
        actions.append(f"Failed to regenerate settings: {exc}")

    # 3. Regenerate symlinks
    try:
        engine = PlaceholderEngine(config)
        symlink_mgr = SymlinkManager(home)
        for name, _entry in registry_data.modules:
            symlink_mgr.remove_module_links(name)
            manifest_path = home / "modules" / name / "opentree.json"
            if manifest_path.exists():
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                rules = manifest.get("loading", {}).get("rules", [])
                results = symlink_mgr.create_module_links_with_resolution(
                    name, rules, engine
                )
                for r in results:
                    if not r.success:
                        logger.warning(
                            "Symlink failed for %s/%s: %s",
                            name,
                            r.source,
                            r.error,
                        )
        actions.append("Regenerated rule symlinks")
    except Exception as exc:
        logger.warning("Failed to regenerate symlinks: %s", exc)
        actions.append(f"Failed to regenerate symlinks: {exc}")

    # 4. Regenerate CLAUDE.md (preserve owner content)
    try:
        claude_md_path = home / "workspace" / "CLAUDE.md"
        existing = None
        if claude_md_path.exists():
            try:
                existing = claude_md_path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                pass
        gen = ClaudeMdGenerator()
        content = gen.generate_with_preservation(
            existing, home, registry_data, config
        )
        claude_md_path.parent.mkdir(parents=True, exist_ok=True)
        claude_md_path.write_text(content, encoding="utf-8")
        actions.append("Regenerated CLAUDE.md (owner content preserved)")
    except Exception as exc:
        logger.warning("Failed to regenerate CLAUDE.md: %s", exc)
        actions.append(f"Failed to regenerate CLAUDE.md: {exc}")

    return actions


def reset_bot_all(home: Path) -> list[str]:
    """Hard reset: clear owner customizations + data, regenerate everything.

    Preserves: modules/ source, .env.defaults (real tokens)
    Resets: .env.local, .env.secrets, CLAUDE.md (full), data contents

    Returns list of action descriptions.
    """
    actions: list[str] = []

    # 1. Delete .env.local and .env.secrets
    for env_file in (".env.local", ".env.secrets"):
        p = home / "config" / env_file
        if p.exists():
            try:
                p.unlink()
                actions.append(f"Deleted config/{env_file}")
            except OSError as exc:
                logger.warning("Failed to delete %s: %s", p, exc)

    # 2. Clear data contents (preserve directory)
    data_dir = home / "data"
    if data_dir.exists():
        for child in data_dir.iterdir():
            try:
                if child.is_dir():
                    shutil.rmtree(child)
                else:
                    child.unlink()
            except OSError as exc:
                logger.warning("Failed to remove %s: %s", child, exc)
        actions.append("Cleared data/ contents")

    # 3. Regenerate settings + symlinks + CLAUDE.md (no preservation)
    config = load_user_config(home)
    reg_path = home / "config" / "registry.json"
    if not reg_path.exists():
        actions.append("Registry not found, skipping regeneration")
        return actions

    registry_data = Registry.load(reg_path)

    # Settings
    try:
        settings_gen = SettingsGenerator(home)
        settings_gen.reset_module_permissions()
        for name, _entry in registry_data.modules:
            manifest_path = home / "modules" / name / "opentree.json"
            if manifest_path.exists():
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                permissions = manifest.get("permissions", {})
                settings_gen.add_module_permissions(
                    name,
                    allow=permissions.get("allow", []),
                    deny=permissions.get("deny", []),
                )
        settings_gen.write_settings()
        actions.append("Regenerated settings.json")
    except Exception as exc:
        logger.warning("Failed to regenerate settings: %s", exc)
        actions.append(f"Failed to regenerate settings: {exc}")

    # Symlinks
    try:
        engine = PlaceholderEngine(config)
        symlink_mgr = SymlinkManager(home)
        for name, _entry in registry_data.modules:
            symlink_mgr.remove_module_links(name)
            manifest_path = home / "modules" / name / "opentree.json"
            if manifest_path.exists():
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                rules = manifest.get("loading", {}).get("rules", [])
                symlink_mgr.create_module_links_with_resolution(
                    name, rules, engine
                )
        actions.append("Regenerated rule symlinks")
    except Exception as exc:
        logger.warning("Failed to regenerate symlinks: %s", exc)
        actions.append(f"Failed to regenerate symlinks: {exc}")

    # CLAUDE.md (no preservation -- full regeneration)
    try:
        gen = ClaudeMdGenerator()
        content = gen.wrap_with_markers(
            gen.generate(home, registry_data, config)
        )
        claude_md_path = home / "workspace" / "CLAUDE.md"
        claude_md_path.parent.mkdir(parents=True, exist_ok=True)
        claude_md_path.write_text(content, encoding="utf-8")
        actions.append("Regenerated CLAUDE.md (clean)")
    except Exception as exc:
        logger.warning("Failed to regenerate CLAUDE.md: %s", exc)
        actions.append(f"Failed to regenerate CLAUDE.md: {exc}")

    return actions
