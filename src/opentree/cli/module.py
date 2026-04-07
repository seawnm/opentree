"""Module management CLI commands: install, remove, list, update, refresh.

Each command resolves ``OPENTREE_HOME``, acquires the registry lock
where needed, and orchestrates the Phase 2 components (Registry,
ManifestValidator, SymlinkManager, SettingsGenerator, ClaudeMdGenerator).
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
from pathlib import Path
from typing import Annotated, Optional

import typer

from opentree.core.config import load_user_config
from opentree.core.placeholders import PlaceholderEngine
from opentree.core.version import compare_versions
from opentree.generator.claude_md import ClaudeMdGenerator
from opentree.generator.settings import SettingsGenerator
from opentree.generator.symlinks import SymlinkManager
from opentree.manifest.validator import ManifestValidator
from opentree.registry.registry import Registry

module_app = typer.Typer(no_args_is_help=True)

_VALID_MODULE_NAME = re.compile(r'^[a-z]([a-z0-9-]*[a-z0-9])?$')

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _validate_module_name(name: str) -> None:
    """Validate module name to prevent path traversal."""
    if not _VALID_MODULE_NAME.match(name):
        typer.echo(
            f"Error: Invalid module name '{name}'. "
            "Only lowercase letters, digits, and hyphens allowed (no leading/trailing hyphen).",
            err=True,
        )
        raise typer.Exit(code=1)


def _resolve_home() -> Path:
    """Resolve OPENTREE_HOME from env var or default to ~/.opentree."""
    env = os.environ.get("OPENTREE_HOME")
    if env:
        return Path(env).resolve()
    return Path.home() / ".opentree"


def _registry_path(home: Path) -> Path:
    return home / "config" / "registry.json"


def _load_manifest(home: Path, module_name: str) -> dict:
    """Load and return the parsed opentree.json for a module."""
    manifest_path = home / "modules" / module_name / "opentree.json"
    if not manifest_path.is_file():
        msg = f"Module '{module_name}' not found at {manifest_path}"
        raise FileNotFoundError(msg)
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def _find_reverse_deps(
    registry_data,
    home: Path,
    module_name: str,
) -> list[str]:
    """Find modules that depend on *module_name*.

    Reads each registered module's manifest to check its depends_on.
    Also checks the depends_on stored in the registry entry itself.
    """
    dependents: list[str] = []
    for name, entry in registry_data.modules:
        if name == module_name:
            continue
        # Check stored depends_on first (cheap)
        if module_name in entry.depends_on:
            dependents.append(name)
            continue
        # Fallback: read manifest
        manifest_path = home / "modules" / name / "opentree.json"
        if manifest_path.is_file():
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
            if module_name in data.get("depends_on", []):
                dependents.append(name)
    return dependents


def _regenerate_claude_md(home: Path, registry_data) -> None:
    """Regenerate workspace/CLAUDE.md from current registry, preserving owner content."""
    config = load_user_config(home)
    gen = ClaudeMdGenerator()
    claude_md_path = home / "workspace" / "CLAUDE.md"
    claude_md_path.parent.mkdir(parents=True, exist_ok=True)

    # Read existing content (if any) for preservation
    existing = None
    if claude_md_path.exists():
        try:
            existing = claude_md_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            logger.warning(
                "Cannot read existing CLAUDE.md (%s), owner content will not be preserved",
                exc,
            )

    content = gen.generate_with_preservation(existing, home, registry_data, config)
    claude_md_path.write_text(content, encoding="utf-8")


# ------------------------------------------------------------------
# Commands
# ------------------------------------------------------------------


@module_app.command()
def install(
    module_name: Annotated[str, typer.Argument(help="Name of the module to install")],
    force: Annotated[bool, typer.Option("--force", help="Reinstall if already installed")] = False,
) -> None:
    """Install a module into the OpenTree workspace."""
    _validate_module_name(module_name)

    home = _resolve_home()
    reg_path = _registry_path(home)

    # Load and validate manifest
    try:
        manifest = _load_manifest(home, module_name)
    except FileNotFoundError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1)

    validator = ManifestValidator()
    manifest_path = home / "modules" / module_name / "opentree.json"
    validation = validator.validate_file(manifest_path, module_dir_name=module_name)
    if not validation.is_valid:
        typer.echo(f"Error: Invalid manifest for '{module_name}':", err=True)
        for issue in validation.errors:
            typer.echo(f"  - {issue.message}", err=True)
        raise typer.Exit(code=1)

    try:
        with Registry.lock(reg_path):
            data = Registry.load(reg_path)

            # Already installed?
            if Registry.is_registered(data, module_name) and not force:
                typer.echo(
                    f"Error: Module '{module_name}' is already installed. "
                    "Use --force to reinstall.",
                    err=True,
                )
                raise typer.Exit(code=1)

            # Check dependencies
            installed_names = data.names()
            dep_issues = validator.validate_dependencies(manifest, installed_names)
            dep_errors = [i for i in dep_issues if i.severity == "error"]
            if dep_errors:
                typer.echo(f"Error: Dependency check failed for '{module_name}':", err=True)
                for issue in dep_errors:
                    typer.echo(f"  - {issue.message}", err=True)
                raise typer.Exit(code=1)

            symlink_mgr = SymlinkManager(home)
            settings_gen = SettingsGenerator(home)

            # Validate placeholders before creating links
            config = load_user_config(home)
            engine = PlaceholderEngine(config)
            placeholder_errors = engine.validate_module_placeholders(
                manifest.get("placeholders", {})
            )
            if placeholder_errors:
                typer.echo(
                    f"Error: Placeholder validation failed for '{module_name}':",
                    err=True,
                )
                for err_msg in placeholder_errors:
                    typer.echo(f"  - {err_msg}", err=True)
                raise typer.Exit(code=1)

            try:
                # Create symlinks (with placeholder resolution)
                rules = manifest.get("loading", {}).get("rules", [])
                link_results = symlink_mgr.create_module_links_with_resolution(
                    module_name, rules, engine
                )
                # Determine link_method: "resolved_copy" if any file was resolved
                if any(r.method == "resolved_copy" for r in link_results):
                    link_method = "resolved_copy"
                elif link_results:
                    link_method = link_results[0].method
                else:
                    link_method = "symlink"

                # Add permissions
                permissions = manifest.get("permissions", {})
                settings_gen.add_module_permissions(
                    module_name,
                    allow=permissions.get("allow", []),
                    deny=permissions.get("deny", []),
                )
                settings_gen.write_settings()

                # Register
                depends_on = tuple(manifest.get("depends_on", []))
                data = Registry.register(
                    data,
                    name=module_name,
                    version=manifest["version"],
                    module_type=manifest.get("type", "optional"),
                    source="bundled",
                    link_method=link_method,
                    depends_on=depends_on,
                )
                Registry.save(reg_path, data)

                # Regenerate CLAUDE.md
                _regenerate_claude_md(home, data)
            except typer.Exit:
                raise
            except Exception as exc:
                # Rollback: remove symlinks if created
                try:
                    symlink_mgr.remove_module_links(module_name, link_method="symlink")
                except Exception:
                    pass
                # Rollback: remove permissions if added
                try:
                    settings_gen.remove_module_permissions(module_name)
                    settings_gen.write_settings()
                except Exception:
                    pass
                typer.echo(f"Error: Installation failed: {exc}", err=True)
                typer.echo("Rolled back partial changes.", err=True)
                raise typer.Exit(code=1)

    except TimeoutError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1)

    typer.echo(f"Installed module '{module_name}' (v{manifest['version']})")


@module_app.command()
def remove(
    module_name: Annotated[str, typer.Argument(help="Name of the module to remove")],
    force: Annotated[bool, typer.Option("--force", help="Force remove pre-installed modules")] = False,
) -> None:
    """Remove a module from the OpenTree workspace."""
    _validate_module_name(module_name)

    home = _resolve_home()
    reg_path = _registry_path(home)

    try:
        with Registry.lock(reg_path):
            data = Registry.load(reg_path)

            # Check registered
            entry = data.get(module_name)
            if entry is None:
                typer.echo(
                    f"Error: Module '{module_name}' is not installed.",
                    err=True,
                )
                raise typer.Exit(code=1)

            # Pre-installed protection
            if entry.module_type == "pre-installed" and not force:
                typer.echo(
                    f"Error: Module '{module_name}' is pre-installed and cannot be removed. "
                    "Use --force to override.",
                    err=True,
                )
                raise typer.Exit(code=1)

            # Reverse dependency check
            dependents = _find_reverse_deps(data, home, module_name)
            if dependents:
                dep_list = ", ".join(dependents)
                typer.echo(
                    f"Error: Cannot remove '{module_name}' because the following "
                    f"modules depend on it: {dep_list}",
                    err=True,
                )
                raise typer.Exit(code=1)

            try:
                # Remove symlinks
                symlink_mgr = SymlinkManager(home)
                symlink_mgr.remove_module_links(module_name, link_method=entry.link_method)

                # Remove permissions
                settings_gen = SettingsGenerator(home)
                settings_gen.remove_module_permissions(module_name)
                settings_gen.write_settings()

                # Unregister
                data = Registry.unregister(data, name=module_name)
                Registry.save(reg_path, data)

                # Regenerate CLAUDE.md (only if modules remain)
                if data.modules:
                    _regenerate_claude_md(home, data)
                else:
                    claude_md_path = home / "workspace" / "CLAUDE.md"
                    if claude_md_path.exists():
                        claude_md_path.unlink()
            except typer.Exit:
                raise
            except Exception as exc:
                typer.echo(f"Error: Operation failed: {exc}", err=True)
                raise typer.Exit(code=1)

    except TimeoutError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1)

    typer.echo(f"Removed module '{module_name}'")


@module_app.command(name="list")
def list_modules() -> None:
    """List all installed modules."""
    home = _resolve_home()
    reg_path = _registry_path(home)

    data = Registry.load(reg_path)
    if not data.modules:
        typer.echo("No modules installed.")
        return

    # Table header
    header = f"{'Name':<20} {'Version':<10} {'Type':<15} {'Link Method':<12}"
    typer.echo(header)
    typer.echo("-" * len(header))

    for name, entry in data.modules:
        typer.echo(
            f"{name:<20} {entry.version:<10} {entry.module_type:<15} {entry.link_method:<12}"
        )


def _bundled_modules_dir() -> Path:
    """Locate the bundled modules directory.

    Search order:
      1. ``OPENTREE_BUNDLE_DIR`` env var (explicit override)
      2. Package-relative ``bundled_modules/`` (after pip install)
      3. Dev layout: 4 levels up → ``modules/`` (source checkout)
    """
    env = os.environ.get("OPENTREE_BUNDLE_DIR")
    if env:
        p = Path(env).resolve()
        if p.is_dir():
            return p
        raise FileNotFoundError(
            f"OPENTREE_BUNDLE_DIR={env!r} is not a valid directory."
        )

    # Installed package: opentree/bundled_modules/
    pkg_root = Path(__file__).resolve().parent.parent  # opentree/
    candidate = pkg_root / "bundled_modules"
    if candidate.is_dir():
        return candidate

    # Dev layout: project_root / modules/
    dev_root = pkg_root.parent.parent  # project root
    candidate = dev_root / "modules"
    if candidate.is_dir():
        return candidate

    raise FileNotFoundError(
        "Cannot find bundled modules directory. "
        "Ensure opentree is installed correctly or set OPENTREE_BUNDLE_DIR."
    )


def _load_bundled_manifest(module_name: str) -> dict | None:
    """Load a module's bundled manifest. Returns None if not bundled."""
    try:
        bundle_dir = _bundled_modules_dir()
    except FileNotFoundError:
        return None
    manifest_path = bundle_dir / module_name / "opentree.json"
    if not manifest_path.is_file():
        return None
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def _copy_bundled_module(module_name: str, home: Path) -> None:
    """Copy a module from bundled source to the installed modules directory."""
    bundle_dir = _bundled_modules_dir()
    src = bundle_dir / module_name
    dst = home / "modules" / module_name
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)


def _update_single_module(
    module_name: str,
    home: Path,
    data,
    *,
    symlink_mgr: SymlinkManager,
    settings_gen: SettingsGenerator,
    engine: PlaceholderEngine,
) -> tuple:
    """Update a single module. Returns (new_data, old_version, new_version).

    Raises typer.Exit on validation failure.
    """
    entry = data.get(module_name)
    old_version = entry.version if entry else "0.0.0"

    # Copy bundled module files to installed location
    _copy_bundled_module(module_name, home)

    # Load the newly copied manifest
    manifest = _load_manifest(home, module_name)

    # Validate manifest
    validator = ManifestValidator()
    manifest_path = home / "modules" / module_name / "opentree.json"
    validation = validator.validate_file(manifest_path, module_dir_name=module_name)
    if not validation.is_valid:
        typer.echo(f"Error: Invalid manifest for '{module_name}':", err=True)
        for issue in validation.errors:
            typer.echo(f"  - {issue.message}", err=True)
        raise typer.Exit(code=1)

    # Remove old symlinks and permissions
    if entry:
        symlink_mgr.remove_module_links(module_name, link_method=entry.link_method)
        settings_gen.remove_module_permissions(module_name)

    # Create new symlinks
    rules = manifest.get("loading", {}).get("rules", [])
    link_results = symlink_mgr.create_module_links_with_resolution(
        module_name, rules, engine
    )
    if any(r.method == "resolved_copy" for r in link_results):
        link_method = "resolved_copy"
    elif link_results:
        link_method = link_results[0].method
    else:
        link_method = "symlink"

    # Add new permissions
    permissions = manifest.get("permissions", {})
    settings_gen.add_module_permissions(
        module_name,
        allow=permissions.get("allow", []),
        deny=permissions.get("deny", []),
    )

    # Register with new version
    depends_on = tuple(manifest.get("depends_on", []))
    new_data = Registry.register(
        data,
        name=module_name,
        version=manifest["version"],
        module_type=manifest.get("type", "optional"),
        source="bundled",
        link_method=link_method,
        depends_on=depends_on,
    )

    return new_data, old_version, manifest["version"]


@module_app.command()
def update(
    module_name: Annotated[
        Optional[str],
        typer.Argument(help="Name of the module to update (omit for --all)"),
    ] = None,
    all_modules: Annotated[
        bool, typer.Option("--all", help="Update all installed modules")
    ] = False,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Preview updates without applying")
    ] = False,
    force: Annotated[
        bool, typer.Option("--force", help="Allow downgrades")
    ] = False,
) -> None:
    """Update installed modules to their latest bundled versions."""
    if not module_name and not all_modules:
        typer.echo(
            "Error: Provide a module name or use --all.",
            err=True,
        )
        raise typer.Exit(code=1)

    home = _resolve_home()
    reg_path = _registry_path(home)

    try:
        with Registry.lock(reg_path):
            data = Registry.load(reg_path)

            if not data.modules:
                typer.echo("No modules installed. Nothing to update.")
                return

            # Build update plan
            targets: list[str] = []
            if all_modules:
                targets = [name for name, _entry in data.modules]
            else:
                _validate_module_name(module_name)
                entry = data.get(module_name)
                if entry is None:
                    typer.echo(
                        f"Error: Module '{module_name}' is not installed.",
                        err=True,
                    )
                    raise typer.Exit(code=1)
                targets = [module_name]

            # Check each target
            plan: list[tuple[str, str, str, str]] = []  # (name, installed, bundled, action)
            for name in targets:
                entry = data.get(name)
                bundled_manifest = _load_bundled_manifest(name)
                if bundled_manifest is None:
                    plan.append((name, entry.version, "—", "skip (not bundled)"))
                    continue
                bundled_version = bundled_manifest.get("version", "0.0.0")
                cmp = compare_versions(entry.version, bundled_version)
                if cmp == 0:
                    plan.append((name, entry.version, bundled_version, "up-to-date"))
                elif cmp == -1:
                    plan.append((name, entry.version, bundled_version, "upgrade"))
                else:
                    if force:
                        plan.append((name, entry.version, bundled_version, "downgrade (--force)"))
                    else:
                        plan.append((name, entry.version, bundled_version, "skip (downgrade, use --force)"))

            # Display plan
            upgradeable = [p for p in plan if p[3] in ("upgrade", "downgrade (--force)")]

            if dry_run or not upgradeable:
                header = f"{'Module':<20} {'Installed':<12} {'Bundled':<12} {'Action'}"
                typer.echo(header)
                typer.echo("-" * len(header))
                for name, installed, bundled, action in plan:
                    typer.echo(f"{name:<20} {installed:<12} {bundled:<12} {action}")
                if not upgradeable:
                    typer.echo("\nAll modules are up-to-date.")
                return

            # Execute updates
            config = load_user_config(home)
            engine = PlaceholderEngine(config)
            symlink_mgr = SymlinkManager(home)
            settings_gen = SettingsGenerator(home)

            updated: list[tuple[str, str, str]] = []
            try:
                for name, installed_v, bundled_v, action in upgradeable:
                    data, old_v, new_v = _update_single_module(
                        name, home, data,
                        symlink_mgr=symlink_mgr,
                        settings_gen=settings_gen,
                        engine=engine,
                    )
                    updated.append((name, old_v, new_v))

                # Batch write settings + registry + CLAUDE.md
                settings_gen.write_settings()
                Registry.save(reg_path, data)
                _regenerate_claude_md(home, data)
            except typer.Exit:
                raise
            except Exception as exc:
                typer.echo(f"Error: Update failed: {exc}", err=True)
                typer.echo("Some modules may be in an inconsistent state.", err=True)
                typer.echo("Run 'opentree module refresh' to repair.", err=True)
                raise typer.Exit(code=1)

            # Report
            for name, old_v, new_v in updated:
                typer.echo(f"Updated '{name}' (v{old_v} → v{new_v})")
            typer.echo(f"\n{len(updated)} module(s) updated.")

    except TimeoutError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1)


@module_app.command()
def refresh() -> None:
    """Refresh all symlinks, permissions, and CLAUDE.md."""
    home = _resolve_home()
    reg_path = _registry_path(home)

    try:
        with Registry.lock(reg_path):
            data = Registry.load(reg_path)
            if not data.modules:
                typer.echo("No modules installed. Nothing to refresh.")
                return

            try:
                # Load config + engine for placeholder resolution
                config = load_user_config(home)
                engine = PlaceholderEngine(config)

                # Collect rules for each module from manifests
                module_rules: dict[str, list[str]] = {}
                module_manifests: dict[str, dict] = {}
                for name, _entry in data.modules:
                    manifest_path = home / "modules" / name / "opentree.json"
                    if manifest_path.is_file():
                        manifest = json.loads(
                            manifest_path.read_text(encoding="utf-8")
                        )
                        module_rules[name] = manifest.get("loading", {}).get("rules", [])
                        module_manifests[name] = manifest
                    else:
                        module_rules[name] = []

                # Reconcile: teardown stale dirs, then rebuild with resolution
                symlink_mgr = SymlinkManager(home)

                # Remove stale module directories
                rules_dir = home / "workspace" / ".claude" / "rules"
                if rules_dir.exists():
                    for child in rules_dir.iterdir():
                        if child.is_dir() and child.name not in module_rules:
                            if child.name == ".trash":
                                continue
                            symlink_mgr.remove_module_links(child.name)

                # Remove + rebuild each module with resolution
                for name in module_rules:
                    target_dir = rules_dir / name
                    if target_dir.exists():
                        symlink_mgr.remove_module_links(name)
                    if module_rules[name]:
                        symlink_mgr.create_module_links_with_resolution(
                            name, module_rules[name], engine
                        )

                # Regenerate permissions from scratch (clear stale entries first)
                settings_gen = SettingsGenerator(home)
                settings_gen.reset_module_permissions()
                for name, _entry in data.modules:
                    manifest_path = home / "modules" / name / "opentree.json"
                    if manifest_path.is_file():
                        manifest = json.loads(
                            manifest_path.read_text(encoding="utf-8")
                        )
                        permissions = manifest.get("permissions", {})
                        settings_gen.add_module_permissions(
                            name,
                            allow=permissions.get("allow", []),
                            deny=permissions.get("deny", []),
                        )
                settings_gen.write_settings()

                # Regenerate CLAUDE.md
                _regenerate_claude_md(home, data)
            except typer.Exit:
                raise
            except Exception as exc:
                typer.echo(f"Error: Operation failed: {exc}", err=True)
                raise typer.Exit(code=1)

    except TimeoutError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1)

    typer.echo("Refresh complete.")
