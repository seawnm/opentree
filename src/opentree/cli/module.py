"""Module management CLI commands: install, remove, list, refresh.

Each command resolves ``OPENTREE_HOME``, acquires the registry lock
where needed, and orchestrates the Phase 2 components (Registry,
ManifestValidator, SymlinkManager, SettingsGenerator, ClaudeMdGenerator).
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Annotated, Optional

import typer

from opentree.core.config import load_user_config
from opentree.generator.claude_md import ClaudeMdGenerator
from opentree.generator.settings import SettingsGenerator
from opentree.generator.symlinks import SymlinkManager
from opentree.manifest.validator import ManifestValidator
from opentree.registry.registry import Registry

module_app = typer.Typer(no_args_is_help=True)

_VALID_MODULE_NAME = re.compile(r'^[a-z]([a-z0-9-]*[a-z0-9])?$')


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
    """Regenerate workspace/CLAUDE.md from current registry."""
    config = load_user_config(home)
    gen = ClaudeMdGenerator()
    content = gen.generate(home, registry_data, config)
    claude_md_path = home / "workspace" / "CLAUDE.md"
    claude_md_path.parent.mkdir(parents=True, exist_ok=True)
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

            try:
                # Create symlinks
                rules = manifest.get("loading", {}).get("rules", [])
                link_results = symlink_mgr.create_module_links(module_name, rules)
                link_method = link_results[0].method if link_results else "symlink"

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
                # Collect rules for each module from manifests
                module_rules: dict[str, list[str]] = {}
                for name, _entry in data.modules:
                    manifest_path = home / "modules" / name / "opentree.json"
                    if manifest_path.is_file():
                        manifest = json.loads(
                            manifest_path.read_text(encoding="utf-8")
                        )
                        module_rules[name] = manifest.get("loading", {}).get("rules", [])
                    else:
                        module_rules[name] = []

                # Reconcile symlinks
                symlink_mgr = SymlinkManager(home)
                symlink_mgr.reconcile_all(module_rules)

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
