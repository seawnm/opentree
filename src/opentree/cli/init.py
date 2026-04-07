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
import subprocess
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


_VALID_CMD_MODES = {"auto", "bare", "uv-run"}


def _resolve_opentree_cmd(cmd_mode: str = "auto") -> tuple[str, Path | None]:
    """Determine how to invoke opentree in run.sh.

    Detection priority (``auto`` mode):
      1. ``pyproject.toml`` at project root → ``uv run --directory``
      2. ``shutil.which("opentree")`` — installed on PATH → bare command
      3. fallback → bare ``opentree``

    Explicit modes:
      - ``bare``: always use bare ``opentree`` (assumes installed)
      - ``uv-run``: always use ``uv run --directory`` (source checkout)

    Returns:
        ``(command_string, project_root_or_None)``
    """
    if cmd_mode not in _VALID_CMD_MODES:
        raise typer.BadParameter(
            f"Invalid --cmd-mode '{cmd_mode}'. "
            f"Choose from: {', '.join(sorted(_VALID_CMD_MODES))}"
        )

    if cmd_mode == "bare":
        return "opentree", None

    project_root = Path(__file__).resolve().parent.parent.parent.parent

    if cmd_mode == "uv-run":
        if (project_root / "pyproject.toml").is_file():
            return f"uv run --directory {project_root} opentree", project_root
        typer.echo("  WARNING: --cmd-mode uv-run but no pyproject.toml found; falling back to bare", err=True)
        return "opentree", None

    # cmd_mode == "auto": source checkout takes priority over PATH detection
    if (project_root / "pyproject.toml").is_file():
        return f"uv run --directory {project_root} opentree", project_root
    resolved = shutil.which("opentree")
    if resolved:
        typer.echo(f"  Detected installed opentree: {resolved}")
        return "opentree", None
    return "opentree", None


def _ensure_slack_deps(project_root: Path) -> None:
    """Run 'uv sync --extra slack' to ensure Slack dependencies are installed.

    Logs a warning on failure but does not raise — the init process
    should not fail because of a transient network issue.
    """
    typer.echo("  Installing Slack dependencies...")
    try:
        subprocess.run(
            ["uv", "sync", "--extra", "slack", "--directory", str(project_root)],
            check=True,
            capture_output=True,
            text=True,
            timeout=120,
        )
        typer.echo("  Slack dependencies installed")
    except Exception as exc:
        logger.warning(
            "Failed to install Slack dependencies (uv sync --extra slack): %s. "
            "You may need to run this manually before starting the bot.",
            exc,
        )


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
    claude_md_path = opentree_home / "workspace" / "CLAUDE.md"
    rules_dir = opentree_home / "workspace" / ".claude" / "rules"

    for src in (reg_path, perm_path, settings_path, claude_md_path):
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


def _parse_admin_users(raw: str) -> list[str]:
    """Parse comma-separated admin Slack User IDs.

    Validates that each ID starts with 'U' (Slack convention).
    """
    users = [u.strip() for u in raw.split(",") if u.strip()]
    if not users:
        raise typer.BadParameter("At least one admin user ID is required.")
    for uid in users:
        if not uid.startswith("U"):
            raise typer.BadParameter(
                f"Invalid Slack User ID '{uid}'. "
                "Slack User IDs start with 'U' (e.g. U0AJRPQ55PH)."
            )
    return users


def init_command(
    bot_name: Annotated[
        str,
        typer.Option("--bot-name", help="Bot display name (required)"),
    ] = ...,
    owner: Annotated[
        Optional[str],
        typer.Option(
            "--owner",
            help="Comma-separated owner Slack User IDs (required, e.g. U123,U456)",
        ),
    ] = None,
    admin_users: Annotated[
        Optional[str],
        typer.Option(
            "--admin-users",
            help="(deprecated, use --owner) Comma-separated owner Slack User IDs",
            hidden=True,
        ),
    ] = None,
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
    team_name: Annotated[
        Optional[str],
        typer.Option("--team-name", help="Team name"),
    ] = None,
    cmd_mode: Annotated[
        str,
        typer.Option(
            "--cmd-mode",
            help="How to invoke opentree in run.sh: auto, bare, uv-run",
        ),
    ] = "auto",
) -> None:
    """Initialize an OpenTree home directory with bundled modules."""
    # Resolve --owner vs --admin-users (backward compat alias).
    owner_value = owner or admin_users
    if not owner_value:
        typer.echo(
            "Error: Missing option '--owner' (or deprecated '--admin-users').",
            err=True,
        )
        raise typer.Exit(code=2)

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
        "bot_name": bot_name,
        "team_name": team_name or "",
        "admin_channel": "",  # deprecated: kept for backward compat
        "owner_description": "",
    }
    (opentree_home / "config" / "user.json").write_text(
        json.dumps(user_config_data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    # 2b. Write config/runner.json (admin_users)
    parsed_admin = _parse_admin_users(owner_value)
    runner_json_path = opentree_home / "config" / "runner.json"
    runner_data: dict = {}
    if runner_json_path.exists():
        try:
            runner_data = json.loads(
                runner_json_path.read_text(encoding="utf-8")
            )
        except (json.JSONDecodeError, ValueError):
            runner_data = {}
    runner_data["admin_users"] = parsed_admin
    runner_json_path.write_text(
        json.dumps(runner_data, indent=2, ensure_ascii=False) + "\n",
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
            "\nHint: Provide missing values via "
            "--bot-name or --team-name flags.",
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

            # Generate CLAUDE.md (with marker preservation on --force re-init)
            gen = ClaudeMdGenerator()
            claude_md = opentree_home / "workspace" / "CLAUDE.md"
            existing = None
            if force and claude_md.exists():
                try:
                    existing = claude_md.read_text(encoding="utf-8")
                except (OSError, UnicodeDecodeError):
                    pass
            if existing is not None:
                content = gen.generate_with_preservation(
                    existing, opentree_home, reg_data, config
                )
            else:
                content = gen.wrap_with_markers(
                    gen.generate(opentree_home, reg_data, config)
                )
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

    # 6. Generate bin/run.sh and config/.env.defaults + .env.local.example
    bin_dir = opentree_home / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)

    template_dir = Path(__file__).resolve().parent.parent / "templates"
    run_sh_template = template_dir / "run.sh"
    if run_sh_template.is_file():
        content = run_sh_template.read_text(encoding="utf-8")
        content = content.replace("{{opentree_home}}", str(opentree_home))
        opentree_cmd, project_root = _resolve_opentree_cmd(cmd_mode)
        content = content.replace("{{opentree_cmd}}", opentree_cmd)
        run_sh_path = bin_dir / "run.sh"

        # Warn when --force would change the command vs existing run.sh
        if force and run_sh_path.exists():
            existing = run_sh_path.read_text(encoding="utf-8")
            if opentree_cmd not in existing:
                typer.echo(
                    f"  \u26a0 run.sh command will change. New: {opentree_cmd}",
                    err=True,
                )

        run_sh_path.write_text(content, encoding="utf-8")
        run_sh_path.chmod(0o755)
        typer.echo(f"  Created {run_sh_path}")

        # Auto-install slack dependencies when using uv run mode
        if project_root is not None:
            _ensure_slack_deps(project_root)

    # Generate config/.env.defaults (bot tokens)
    env_defaults = opentree_home / "config" / ".env.defaults"
    if not env_defaults.exists() or force:
        env_defaults.write_text(
            "# OpenTree Bot Configuration — Default Tokens\n"
            "# This file contains bot-level secrets.\n"
            "# Owner should NOT edit this file directly.\n"
            "#\n"
            "SLACK_BOT_TOKEN=xoxb-your-bot-token\n"
            "SLACK_APP_TOKEN=xapp-your-app-token\n",
            encoding="utf-8",
        )
        # Set restrictive permissions (owner-only read/write)
        try:
            env_defaults.chmod(0o600)
        except OSError:
            pass  # Windows or restricted environments
        typer.echo("  Created config/.env.defaults")

    # Generate config/.env.local.example (owner customization template)
    env_local_example = opentree_home / "config" / ".env.local.example"
    if not env_local_example.exists() or force:
        env_local_example.write_text(
            "# Owner Customization\n"
            "# Copy this file to .env.local and add your own keys.\n"
            "# Keys here override values in .env.defaults.\n"
            "#\n"
            "# Example:\n"
            "# OPENAI_API_KEY=sk-your-key-here\n"
            "#\n"
            "# To override Slack tokens:\n"
            "# SLACK_BOT_TOKEN=xoxb-your-custom-token\n",
            encoding="utf-8",
        )
        typer.echo("  Created config/.env.local.example")

    # Clean up legacy .env.example on --force
    if force:
        legacy_example = opentree_home / "config" / ".env.example"
        if legacy_example.exists():
            legacy_example.unlink()
            typer.echo("  Removed legacy config/.env.example")

    # 7. Success summary
    installed = ", ".join(_PRE_INSTALLED)
    typer.echo(f"Initialized OpenTree at {opentree_home}")
    typer.echo(f"  Bot name: {bot_name}")
    typer.echo(f"  Owner: {', '.join(parsed_admin)}")
    typer.echo(f"  Pre-installed modules: {installed}")
    typer.echo(f"  Workspace: {opentree_home / 'workspace'}")
    typer.echo("Run 'opentree start' to launch.")


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
