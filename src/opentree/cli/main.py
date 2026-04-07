"""OpenTree CLI — top-level application.

Registers sub-command groups (``module``, etc.) and serves as the
single entry point for the ``opentree`` console script.
"""

from __future__ import annotations

import typer

from opentree.cli.init import init_command, start_command
from opentree.cli.lifecycle import stop_command
from opentree.cli.module import module_app
from opentree.cli.prompt import prompt_app

app = typer.Typer(
    name="opentree",
    help="OpenTree — Modular Claude Code CLI wrapper",
    no_args_is_help=True,
)
app.command(name="init")(init_command)
app.command(name="start")(start_command)
app.command(name="stop")(stop_command)
app.add_typer(module_app, name="module", help="Module management commands")
app.add_typer(prompt_app, name="prompt", help="System prompt preview/debug")

if __name__ == "__main__":
    app()
