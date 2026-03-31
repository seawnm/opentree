"""Init and start commands for OpenTree.

``opentree init`` bootstraps an OpenTree home directory with bundled
modules and a pre-installed set.  ``opentree start`` launches Claude CLI
with the assembled system prompt.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import sys
from pathlib import Path
from typing import Annotated, Optional

import typer

from opentree.core.config import UserConfig, load_user_config
from opentree.core.placeholders import PlaceholderEngine
from opentree.generator.claude_md import ClaudeMdGenerator
from opentree.generator.settings import SettingsGenerator
from opentree.generator.symlinks import SymlinkManager
from opentree.manifest.validator import ManifestValidator
from opentree.registry.registry import Registry

logger = logging.getLogger(__name__)

# Topological order: dependencies must come before dependents.
_PRE_INSTALLED = (
    "core",
    "memory",
    "personality",
    "scheduler",
    "slack",
    "guardrail",
    "audit-logger",
)


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _resolve_home(home_flag: Optional[str]) -> Path:
    """Resolve OPENTREE_HOME from flag > env > default."""
    if home_flag:
        return Path(home_flag).resolve()
    env = os.environ.get("OPENTREE_HOME")
    if env:
        return Path(env).resolve()
    return Path.home() / ".opentree"


def _bundled_modules_dir() -> Path:
    """Locate the bundled modules/ directory.

    Search order:
    1. ``OPENTREE_BUNDLE_DIR`` environment variable
    2. ``<package_root>/../../../../modules`` (development layout)

    Raises:
        FileNotFoundError: If no modules directory can be found.
    """
    env = os.environ.get("OPENTREE_BUNDLE_DIR")
    if env:
        p = Path(env).resolve()
        if p.is_dir():
            return p
        msg = f"OPENTREE_BUNDLE_DIR points to a non-directory: {p}"
        raise FileNotFoundError(msg)
    # Development layout: src/opentree/cli/init.py -> ../../../../modules
    pkg_root = Path(__file__).resolve().parent.parent.parent.parent
    candidate = pkg_root / "modules"
    if candidate.is_dir():
        return candidate
    msg = (
        "Cannot find bundled modules directory. "
        "Set OPENTREE_BUNDLE_DIR or run from the project root."
    )
    raise FileNotFoundError(msg)


def _is_interactive() -> bool:
    """Return True if stdout is connected to a TTY (interactive mode)."""
    return hasattr(sys.stdout, "isatty") and sys.stdout.isatty()


def _preflight_check(
    home: Path,
    module_names: tuple[str, ...],
    config: UserConfig,
) -> list[str]:
    """Validate required placeholders for ALL modules before installing any.

    Returns a list of error strings (empty means all OK).
    """
    engine = PlaceholderEngine(config)
    errors: list[str] = []
    for name in module_names:
        manifest_path = home / "modules" / name / "opentree.json"
        if not manifest_path.is_file():
            errors.append(f"  {name}: manifest not found at {manifest_path}")
            continue
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        placeholders = manifest.get("placeholders", {})
        module_errors = engine.validate_module_placeholders(placeholders)
        for err in module_errors:
            errors.append(f"  {name}: {err}")
    return errors


def _install_single_module(
    home: Path,
    module_name: str,
    manifest: dict,
    engine: PlaceholderEngine,
    symlink_mgr: SymlinkManager,
    settings_gen: SettingsGenerator,
    reg_data,
):
    """Install one module: symlinks, permissions, register.

    Returns the updated RegistryData.
    """
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

    permissions = manifest.get("permissions", {})
    settings_gen.add_module_permissions(
        module_name,
        allow=permissions.get("allow", []),
        deny=permissions.get("deny", []),
    )

    depends_on = tuple(manifest.get("depends_on", []))
    return Registry.register(
        reg_data,
        name=module_name,
        version=manifest["version"],
        module_type=manifest.get("type", "optional"),
        source="bundled",
        link_method=link_method,
        depends_on=depends_on,
    )


def _backup_state(opentree_home: Path) -> Path | None:
    """Backup registry, settings, permissions, and rules for rollback.

    Returns the backup directory path, or None if nothing to back up.
    """
    backup_dir = opentree_home / "_install_backup"
    has_content = False

    reg_path = opentree_home / "config" / "registry.json"
    perm_path = opentree_home / "config" / "permissions.json"
    settings_path = opentree_home / "workspace" / ".claude" / "settings.json"
    rules_dir = opentree_home / "workspace" / ".claude" / "rules"

    for src in (reg_path, perm_path, settings_path):
        if src.exists():
            dest = backup_dir / src.relative_to(opentree_home)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
            has_content = True

    if rules_dir.exists() and any(rules_dir.iterdir()):
        dest_rules = backup_dir / rules_dir.relative_to(opentree_home)
        if dest_rules.exists():
            shutil.rmtree(dest_rules)
        shutil.copytree(rules_dir, dest_rules)
        has_content = True

    return backup_dir if has_content else None


def _restore_state(opentree_home: Path, backup_dir: Path) -> None:
    """Restore backed-up state files after a failed install."""
    for src in backup_dir.rglob("*"):
        if src.is_file():
            dest = opentree_home / src.relative_to(backup_dir)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)

    # Restore rules directory
    backup_rules = backup_dir / "workspace" / ".claude" / "rules"
    final_rules = opentree_home / "workspace" / ".claude" / "rules"
    if backup_rules.exists():
        if final_rules.exists():
            shutil.rmtree(final_rules)
        shutil.copytree(backup_rules, final_rules)


# ------------------------------------------------------------------
# init command
# ------------------------------------------------------------------


def init_command(
    home: Annotated[
        Optional[str],
        typer.Option("--home", help="Path to OPENTREE_HOME"),
    ] = None,
    force: Annotated[
        bool,
        typer.Option("--force", help="Re-initialize even if already set up"),
    ] = False,
    non_interactive: Annotated[
        bool,
        typer.Option("--non-interactive", help="Skip interactive prompts"),
    ] = False,
    bot_name: Annotated[
        Optional[str],
        typer.Option("--bot-name", help="Bot display name"),
    ] = None,
    team_name: Annotated[
        Optional[str],
        typer.Option("--team-name", help="Team name"),
    ] = None,
    admin_channel: Annotated[
        Optional[str],
        typer.Option("--admin-channel", help="Admin Slack channel ID"),
    ] = None,
) -> None:
    """Initialize an OpenTree home directory with bundled modules."""
    opentree_home = _resolve_home(home)
    reg_path = opentree_home / "config" / "registry.json"

    # Already initialized?
    if reg_path.exists() and not force:
        typer.echo(
            f"Error: Already initialized at {opentree_home}. "
            "Use --force to re-initialize.",
            err=True,
        )
        raise typer.Exit(code=1)

    # 1. Create directory structure
    for subdir in (
        "modules",
        "workspace/.claude/rules",
        "data/memory",
        "config",
    ):
        (opentree_home / subdir).mkdir(parents=True, exist_ok=True)

    # 2. Write user.json
    user_config_data = {
        "bot_name": bot_name or "OpenTree",
        "team_name": team_name or "",
        "admin_channel": admin_channel or "",
        "admin_description": "",
    }
    (opentree_home / "config" / "user.json").write_text(
        json.dumps(user_config_data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    # 3. Copy bundled modules
    try:
        bundle_dir = _bundled_modules_dir()
    except FileNotFoundError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1)

    dest_modules = opentree_home / "modules"

    # Issue 5: Warn about existing directories that --force will delete
    if force:
        existing_dirs = [
            dest_modules / child.name
            for child in sorted(bundle_dir.iterdir())
            if child.is_dir()
            and (child / "opentree.json").is_file()
            and (dest_modules / child.name).exists()
        ]
        if existing_dirs:
            dir_names = ", ".join(d.name for d in existing_dirs)
            logger.warning("--force will delete: %s", dir_names)

            # In interactive mode, prompt for confirmation
            if not non_interactive and _is_interactive():
                confirm = typer.confirm(
                    f"--force will delete {len(existing_dirs)} existing "
                    "module directories. Continue?"
                )
                if not confirm:
                    typer.echo("Aborted.", err=True)
                    raise typer.Exit(code=1)

    for child in sorted(bundle_dir.iterdir()):
        if child.is_dir() and (child / "opentree.json").is_file():
            target = dest_modules / child.name
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(child, target)

    # 4. Pre-flight: validate ALL pre-installed modules' placeholders
    config = load_user_config(opentree_home)
    errors = _preflight_check(opentree_home, _PRE_INSTALLED, config)
    if errors:
        typer.echo(
            "Error: Pre-flight placeholder validation failed:\n"
            + "\n".join(errors),
            err=True,
        )
        typer.echo(
            "\nHint: Provide missing values via --admin-channel, "
            "--bot-name, or --team-name flags.",
            err=True,
        )
        raise typer.Exit(code=1)

    # Issue 6: Transactional install — backup state before attempting
    backup_dir = _backup_state(opentree_home)

    # 5. Install pre-installed modules in topo order
    engine = PlaceholderEngine(config)
    symlink_mgr = SymlinkManager(opentree_home)
    settings_gen = SettingsGenerator(opentree_home)
    validator = ManifestValidator()
    reg_data = Registry.load(reg_path)

    try:
        with Registry.lock(reg_path):
            for name in _PRE_INSTALLED:
                manifest_path = opentree_home / "modules" / name / "opentree.json"
                manifest = json.loads(
                    manifest_path.read_text(encoding="utf-8")
                )
                # Validate manifest schema
                validation = validator.validate_file(
                    manifest_path, module_dir_name=name
                )
                if not validation.is_valid:
                    err_msgs = [i.message for i in validation.errors]
                    typer.echo(
                        f"Error: Invalid manifest for '{name}': "
                        + "; ".join(err_msgs),
                        err=True,
                    )
                    raise RuntimeError(
                        f"Invalid manifest for '{name}': "
                        + "; ".join(err_msgs)
                    )

                reg_data = _install_single_module(
                    opentree_home,
                    name,
                    manifest,
                    engine,
                    symlink_mgr,
                    settings_gen,
                    reg_data,
                )

            # Write settings.json and registry ONLY after ALL succeed
            settings_gen.write_settings()
            Registry.save(reg_path, reg_data)

            # Generate CLAUDE.md
            gen = ClaudeMdGenerator()
            content = gen.generate(opentree_home, reg_data, config)
            claude_md = opentree_home / "workspace" / "CLAUDE.md"
            claude_md.write_text(content, encoding="utf-8")

    except typer.Exit:
        raise
    except TimeoutError as exc:
        # Rollback on lock timeout
        if backup_dir and backup_dir.exists():
            logger.info("Rolling back to previous state...")
            _restore_state(opentree_home, backup_dir)
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1)
    except Exception as exc:
        # Rollback on any install failure
        logger.error("Module installation failed: %s", exc)
        if backup_dir and backup_dir.exists():
            logger.info("Rolling back to previous state...")
            _restore_state(opentree_home, backup_dir)
        typer.echo(f"Error: Module installation failed: {exc}", err=True)
        raise typer.Exit(code=1)
    finally:
        # Clean up backup directory on success or failure
        if backup_dir and backup_dir.exists():
            shutil.rmtree(backup_dir, ignore_errors=True)

    # 6. Generate bin/run.sh and config/.env.example
    bin_dir = opentree_home / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)

    template_dir = Path(__file__).resolve().parent.parent / "templates"
    run_sh_template = template_dir / "run.sh"
    if run_sh_template.is_file():
        content = run_sh_template.read_text(encoding="utf-8")
        content = content.replace("{{opentree_home}}", str(opentree_home))
        run_sh_path = bin_dir / "run.sh"
        run_sh_path.write_text(content, encoding="utf-8")
        run_sh_path.chmod(0o755)
        typer.echo(f"  Created {run_sh_path}")

    env_example = opentree_home / "config" / ".env.example"
    if not env_example.exists():
        env_example.write_text(
            "# OpenTree Bot Configuration\n"
            "# Copy this file to .env and fill in the values\n"
            "SLACK_BOT_TOKEN=xoxb-your-bot-token\n"
            "SLACK_APP_TOKEN=xapp-your-app-token\n",
            encoding="utf-8",
        )
        typer.echo(f"  Created {env_example}")

    # 7. Success summary
    installed = ", ".join(_PRE_INSTALLED)
    typer.echo(f"Initialized OpenTree at {opentree_home}")
    typer.echo(f"Pre-installed modules: {installed}")
    typer.echo(f"Workspace: {opentree_home / 'workspace'}")
    typer.echo("Run 'opentree start' to launch Claude CLI.")


# ------------------------------------------------------------------
# start command
# ------------------------------------------------------------------


def start_command(
    home: Annotated[
        Optional[str],
        typer.Option("--home", help="Path to OPENTREE_HOME"),
    ] = None,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Print command without executing"),
    ] = False,
    isolate: Annotated[
        bool,
        typer.Option("--isolate", help="Use isolated Claude config directory"),
    ] = False,
    mode: Annotated[
        str,
        typer.Option(
            "--mode",
            help="Run mode: 'interactive' (TUI) or 'slack' (bot daemon)",
        ),
    ] = "interactive",
) -> None:
    """Launch Claude CLI with the assembled system prompt."""
    opentree_home = _resolve_home(home)
    reg_path = opentree_home / "config" / "registry.json"

    if not reg_path.exists():
        typer.echo(
            f"Error: Not initialized at {opentree_home}. "
            "Run 'opentree init' first.",
            err=True,
        )
        raise typer.Exit(code=1)

    _VALID_MODES = {"slack", "interactive"}
    if mode not in _VALID_MODES:
        typer.echo(
            f"Error: unknown mode '{mode}'. Choose from: {', '.join(sorted(_VALID_MODES))}",
            err=True,
        )
        raise typer.Exit(code=1)

    if mode == "slack":
        from opentree.runner.bot import Bot

        bot = Bot(opentree_home)
        bot.start()
        return

    # --- interactive mode (default) ---
    from opentree.core.prompt import PromptContext, assemble_system_prompt

    config = load_user_config(opentree_home)
    registry = Registry.load(reg_path)
    context = PromptContext()
    prompt = assemble_system_prompt(opentree_home, registry, config, context)

    workspace_dir = str(opentree_home / "workspace")

    if isolate:
        config_dir = str(opentree_home / "config" / "claude")
        os.environ["CLAUDE_CONFIG_DIR"] = config_dir

    args = ["claude", "--system-prompt", prompt, "--cwd", workspace_dir]

    if dry_run:
        typer.echo(" ".join(args))
        if isolate:
            typer.echo(
                f"CLAUDE_CONFIG_DIR={os.environ.get('CLAUDE_CONFIG_DIR', '')}"
            )
        return

    os.execvp("claude", args)
