"""Subcommand module."""

from __future__ import annotations

import sys
from pathlib import Path

import click

import pathsafe
from pathsafe.deidentifier import (
    collect_wsi_files,
)
from pathsafe.log import (
    cli_bold,
    cli_dim,
    cli_error,
    cli_finding,
    cli_header,
    cli_info,
    cli_separator,
    cli_success,
    cli_warning,
)
from pathsafe.verify import verify_batch


@click.command()
@click.argument("path", type=click.Path(exists=True))
@click.option("--verbose", "-v", is_flag=True, help="Show detailed findings.")
@click.option(
    "--format",
    "fmt",
    type=click.Choice(["ndpi", "svs", "mrxs", "bif", "scn", "dicom", "tiff"]),
    help="Only verify files of this format.",
)
def verify(path: str, verbose: bool, fmt: str | None) -> None:
    """Verify that files have been fully deidentified.

    Re-scans all files to confirm no PHI remains.
    """
    input_path = Path(path)
    files = collect_wsi_files(input_path, format_filter=fmt)

    if not files:
        click.echo(cli_warning(f"No WSI files found in {input_path}"))
        return

    click.echo(cli_header(f"PathSafe v{pathsafe.__version__} -- Verification"))
    click.echo(cli_info(f"Verifying {len(files)} file(s)..."))
    click.echo(cli_separator())

    clean_count = 0
    dirty_count = 0

    def progress(i: int, total: int, filepath: Path, result: object) -> None:
        nonlocal clean_count, dirty_count
        counter = cli_dim(f"[{i}/{total}]")

        if result.is_clean:
            clean_count += 1
            if verbose:
                click.echo(f"  {counter} {filepath.name} {cli_success('CLEAN')}")
        else:
            dirty_count += 1
            n = len(result.findings)
            click.echo(f"  {counter} {filepath.name} {cli_error(f'PHI FOUND ({n} finding(s))')}")
            if verbose:
                for f in result.findings:
                    click.echo(
                        f"         {cli_finding(f.tag_name)}: {cli_warning(f.mask_preview())}"
                    )

    verify_batch(input_path, format_filter=fmt, progress_callback=progress)

    click.echo(cli_separator())
    click.echo(cli_bold("Verification Results"))
    if clean_count:
        click.echo(f"  Clean:          {cli_success(str(clean_count))}")
    if dirty_count:
        click.echo(f"  PHI remaining:  {cli_error(str(dirty_count))}")

    if dirty_count > 0:
        click.echo(cli_error("\nWARNING: Some files still contain PHI!"))
        sys.exit(1)
    else:
        click.echo(cli_success("\nAll files verified clean."))
