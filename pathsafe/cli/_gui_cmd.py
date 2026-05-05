"""Subcommand module."""

from __future__ import annotations

import click

from pathsafe.log import (
    cli_error,
)


@click.command()
def gui() -> None:
    """Launch the graphical user interface."""
    try:
        from pathsafe.gui_qt import main as gui_main
    except ImportError as e:
        click.echo(
            cli_error(
                "Error: PySide6 is required for the GUI. Install it with: pip install pathsafe[gui]"
            ),
            err=True,
        )
        raise SystemExit(1) from e
    gui_main()
