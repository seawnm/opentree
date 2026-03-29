"""CLI: opentree prompt -- debug/preview system prompt."""
from __future__ import annotations

import os
from pathlib import Path

import typer

from opentree.core.config import load_user_config
from opentree.core.prompt import PromptContext, assemble_system_prompt
from opentree.registry.registry import Registry

prompt_app = typer.Typer(no_args_is_help=True)


@prompt_app.command(name="show")
def show(
    user_id: str = typer.Option("", help="User ID"),
    user_name: str = typer.Option("", help="User name"),
    channel_id: str = typer.Option("", help="Channel ID"),
    thread_ts: str = typer.Option("", help="Thread TS"),
    workspace: str = typer.Option("", help="Workspace"),
) -> None:
    """Assemble and print the system prompt."""
    home = Path(
        os.environ.get("OPENTREE_HOME", str(Path.home() / ".opentree"))
    ).resolve()
    config = load_user_config(home)
    registry = Registry.load(home / "config" / "registry.json")
    ctx = PromptContext(
        user_id=user_id,
        user_name=user_name,
        channel_id=channel_id,
        thread_ts=thread_ts,
        workspace=workspace,
    )
    result = assemble_system_prompt(home, registry, config, ctx)
    typer.echo(result)
