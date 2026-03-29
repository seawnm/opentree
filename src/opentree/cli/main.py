"""OpenTree CLI — top-level application.

Registers sub-command groups (``module``, etc.) and serves as the
single entry point for the ``opentree`` console script.
"""

from __future__ import annotations

import typer

from opentree.cli.module import module_app

app = typer.Typer(
    name="opentree",
    help="OpenTree — Modular Claude Code CLI wrapper",
    no_args_is_help=True,
)
app.add_typer(module_app, name="module", help="Module management commands")

if __name__ == "__main__":
    app()
