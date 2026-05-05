"""Subcommand module."""

from __future__ import annotations

import sys
from pathlib import Path

import click

from pathsafe.formats import detect_format, get_handler
from pathsafe.log import (
    cli_bold,
    cli_dim,
    cli_error,
    cli_finding,
    cli_header,
    cli_separator,
    cli_success,
    cli_warning,
)
from pathsafe.report import friendly_tag_name


@click.command()
@click.argument("path", type=click.Path(exists=True))
def info(path: str) -> None:
    """Show metadata and format information for a WSI file."""
    filepath = Path(path)

    if filepath.is_dir():
        click.echo(
            cli_error("Error: info command requires a single file, not a directory."), err=True
        )
        sys.exit(1)

    fmt = detect_format(filepath)
    handler = get_handler(filepath)
    file_info = handler.get_format_info(filepath)

    click.echo(cli_header(f"File: {filepath.name}"))
    click.echo(f"  Format: {cli_bold(fmt)}")
    size_mb = file_info.get("file_size", 0) / 1e6
    click.echo(f"  Size:   {cli_bold(f'{size_mb:.1f} MB')}")

    for key, value in file_info.items():
        if key not in ("format", "filename", "file_size"):
            click.echo(f"  {key}: {cli_dim(str(value))}")

    # PHI scan result
    click.echo(cli_separator())
    result = handler.scan(filepath)
    if result.is_clean:
        click.echo(f"  PHI Status: {cli_success('CLEAN')}")
    else:
        click.echo(f"  PHI Status: {cli_warning(f'{len(result.findings)} finding(s)')}")
        for f in result.findings:
            click.echo(
                f"    {cli_finding(friendly_tag_name(f.tag_name))} "
                f"{cli_dim('at offset')} {f.offset}: "
                f"{cli_warning(f.mask_preview())}"
            )
