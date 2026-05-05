"""Subcommand module."""

from __future__ import annotations

import sys
import time
from pathlib import Path

import click

import pathsafe
from pathsafe.deidentifier import (
    auto_workers,
)
from pathsafe.log import (
    cli_bold,
    cli_dim,
    cli_error,
    cli_header,
    cli_info,
    cli_separator,
    cli_success,
)


@click.command()
@click.argument("path", type=click.Path(exists=True))
@click.option("--output", "-o", type=click.Path(), required=True, help="Output file or directory.")
@click.option(
    "--target-format",
    "-t",
    type=click.Choice(["tiff", "png", "jpeg"]),
    default="tiff",
    help="Target format (default: tiff).",
)
@click.option(
    "--deidentify", "-a", is_flag=True, help="Run PathSafe deidentification on converted output."
)
@click.option(
    "--tile-size",
    type=int,
    default=256,
    help="Tile size in pixels for pyramidal TIFF (default: 256).",
)
@click.option(
    "--quality",
    type=click.IntRange(1, 100),
    default=90,
    help="JPEG compression quality 1-100 (default: 90).",
)
@click.option(
    "--extract",
    type=click.Choice(["label", "macro", "thumbnail"]),
    help="Extract an associated image instead of converting.",
)
@click.option(
    "--format",
    "fmt",
    type=click.Choice(["ndpi", "svs", "mrxs", "bif", "scn", "dicom", "tiff"]),
    help="Only convert files of this format (batch mode).",
)
@click.option(
    "--workers",
    "-w",
    type=int,
    default=0,
    help="Number of parallel workers for batch conversion (default: auto-detect).",
)
@click.option("--verbose", "-v", is_flag=True, help="Show detailed output.")
@click.option(
    "--reset-timestamps",
    is_flag=True,
    help="Reset file timestamps to epoch on output files (removes temporal PHI).",
)
def convert(
    path: str,
    output: str,
    target_format: str,
    deidentify: bool,
    tile_size: int,
    quality: int,
    extract: str | None,
    fmt: str | None,
    workers: int,
    verbose: bool,
    reset_timestamps: bool,
) -> None:
    """Convert WSI files between formats.

    PATH can be a single file or a directory to convert recursively.

    \b
    Examples:
        pathsafe convert slide.ndpi -o slide.tiff
        pathsafe convert slide.ndpi -o slide.tiff --deidentify
        pathsafe convert slide.ndpi -o label.png --extract label
        pathsafe convert /slides/ -o /converted/ -t tiff -w 4
    """
    workers = workers or auto_workers()
    try:
        from pathsafe.converter import convert_batch, convert_file
    except ImportError as e:
        click.echo(cli_error(f"Error: {e}"), err=True)
        sys.exit(1)

    input_path = Path(path)
    output_path = Path(output)

    click.echo(cli_header(f"PathSafe v{pathsafe.__version__} -- Format Conversion"))

    if extract:
        # Single file extraction
        if input_path.is_dir():
            click.echo(
                cli_error("Error: --extract requires a single file, not a directory."), err=True
            )
            sys.exit(1)

        click.echo(cli_info(f"Extracting {extract} image from {input_path.name}..."))
        result = convert_file(
            input_path, output_path, extract=extract, reset_timestamps=reset_timestamps
        )

        if result.error:
            click.echo(cli_error(f"Error: {result.error}"))
            sys.exit(1)
        else:
            click.echo(cli_success(f"Saved {extract} image to {output_path}"))
            click.echo(cli_dim(f"  Time: {result.conversion_time_ms:.0f}ms"))
        return

    if input_path.is_file():
        # Single file conversion
        anon_str = " + deidentify" if deidentify else ""
        click.echo(cli_info(f"Converting {input_path.name} → {target_format}{anon_str}"))

        result = convert_file(
            input_path,
            output_path,
            target_format=target_format,
            tile_size=tile_size,
            quality=quality,
            deidentify=deidentify,
            reset_timestamps=reset_timestamps,
        )

        if result.error:
            click.echo(cli_error(f"Error: {result.error}"))
            sys.exit(1)
        else:
            click.echo(cli_success(f"Converted to {output_path}"))
            details = [f"{result.levels_written} level(s)"]
            details.append(f"{result.conversion_time_ms / 1000:.1f}s")
            if result.deidentified:
                details.append("deidentified")
            click.echo(cli_dim(f"  {', '.join(details)}"))
    else:
        # Batch conversion
        workers_str = f", {workers} workers" if workers > 1 else ""
        click.echo(cli_info(f"Batch conversion to {target_format}{workers_str}"))
        click.echo(cli_separator())

        t0 = time.time()

        def progress(i: int, total: int, filepath: Path, result: object) -> None:
            elapsed = time.time() - t0
            rate = i / elapsed if elapsed > 0 else 0
            eta = (total - i) / rate / 60 if rate > 0 else 0

            counter = cli_dim(f"[{i}/{total}]")
            stats = cli_dim(f"{rate:.1f}/s ETA {eta:.0f}m")

            if result.error:
                status = cli_error(f"ERROR: {result.error}")
            else:
                parts = [f"{result.levels_written} level(s)"]
                parts.append(f"{result.conversion_time_ms / 1000:.1f}s")
                if result.deidentified:
                    parts.append("deidentified")
                status = cli_success(", ".join(parts))

            click.echo(f"  {counter} {stats} | {filepath.name} | {status}")

        batch_result = convert_batch(
            input_path,
            output_path,
            target_format=target_format,
            tile_size=tile_size,
            quality=quality,
            deidentify=deidentify,
            format_filter=fmt,
            progress_callback=progress,
            workers=workers,
            reset_timestamps=reset_timestamps,
        )

        # Summary
        click.echo(cli_separator())
        click.echo(cli_bold(f"Done in {batch_result.total_time_seconds:.1f}s"))
        click.echo(f"  Total:     {cli_bold(str(batch_result.total_files))}")
        if batch_result.files_converted:
            click.echo(f"  Converted: {cli_success(str(batch_result.files_converted))}")
        if batch_result.files_errored:
            click.echo(f"  Errors:    {cli_error(str(batch_result.files_errored))}")

        if batch_result.files_errored > 0:
            sys.exit(1)
