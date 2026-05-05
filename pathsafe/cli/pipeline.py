"""Subcommand module."""

from __future__ import annotations

import sys
from pathlib import Path

import click

import pathsafe
from pathsafe.log import (
    cli_bold,
    cli_dim,
    cli_error,
    cli_header,
    cli_info,
    cli_separator,
    cli_success,
    cli_warning,
)


@click.command()
@click.argument("path", type=click.Path(exists=True))
@click.option("--output", "-o", type=click.Path(), help="Output JSON/CSV file for classifications.")
@click.option("--format", "out_fmt", type=click.Choice(["json", "csv"]), default="json")
@click.option(
    "--use-filenames", is_flag=True, help="Use filenames as keys (only for pre-deidentified files)."
)
@click.option("--limit", type=int, help="Process only first N files.")
def classify(path, output, out_fmt, use_filenames, limit):
    """Classify slide stain types from label images (OCR)."""
    try:
        from pathsafe.classifier import classify_batch, export_classifications
    except ImportError as e:
        click.echo(
            cli_error(
                "Error: Pipeline dependencies are required for classification. "
                "Install them with: pip install pathsafe[pipeline]"
            ),
            err=True,
        )
        raise SystemExit(1) from e

    input_path = Path(path)
    if not input_path.is_dir():
        click.echo(cli_error("Error: PATH must be a directory containing WSI files."), err=True)
        sys.exit(1)

    click.echo(cli_header(f"PathSafe v{pathsafe.__version__} -- Stain Classification"))
    click.echo(cli_info(f"Classifying slides in {input_path}..."))
    click.echo(cli_separator())

    def progress(i, total, filepath, result):
        counter = cli_dim(f"[{i}/{total}]")
        if result.error:
            click.echo(f"  {counter} {filepath.name} {cli_error('ERROR')} {cli_dim(result.error)}")
        elif result.stain_name:
            click.echo(
                f"  {counter} {filepath.name} "
                f"{cli_success(result.stain_name)} {cli_dim(f'({result.stain_type})')}"
            )
        else:
            click.echo(f"  {counter} {filepath.name} {cli_warning('unknown')}")

    try:
        results = classify_batch(
            input_path,
            use_filenames=use_filenames,
            progress_callback=progress,
        )
    except ImportError as e:
        click.echo(cli_error(f"Error: {e}"), err=True)
        raise SystemExit(1) from e

    # Summary
    classified = sum(1 for r in results.values() if r.stain_name)
    unknown = sum(1 for r in results.values() if not r.stain_name and not r.error)
    errors = sum(1 for r in results.values() if r.error)

    click.echo(cli_separator())
    click.echo(cli_bold("Summary"))
    click.echo(f"  Total:      {cli_bold(str(len(results)))}")
    if classified:
        click.echo(f"  Classified: {cli_success(str(classified))}")
    if unknown:
        click.echo(f"  Unknown:    {cli_warning(str(unknown))}")
    if errors:
        click.echo(f"  Errors:     {cli_error(str(errors))}")

    # Export if output path given
    if output:
        export_classifications(results, Path(output), format=out_fmt)
        click.echo(cli_info(f"Results written to {output}"))


@click.command()
@click.argument("path", type=click.Path(exists=True))
@click.option("--remote", "-r", required=True, help="Remote destination (user@host:/path/).")
@click.option("--ssh-key", type=click.Path(exists=True), help="SSH private key file.")
@click.option("--bwlimit", type=int, help="Bandwidth limit in KB/s.")
@click.option("--dry-run", is_flag=True, help="Show what would be transferred.")
@click.option("--verify", is_flag=True, default=True, help="Verify transfers via SHA256.")
def transfer(path, remote, ssh_key, bwlimit, dry_run, verify):
    """Transfer deidentified files to a remote server via rsync."""
    try:
        from pathsafe.transfer import TransferConfig, transfer_batch
    except ImportError as e:
        click.echo(
            cli_error(
                "Error: Transfer module could not be loaded. "
                "Install dependencies with: pip install pathsafe[pipeline]"
            ),
            err=True,
        )
        raise SystemExit(1) from e

    source_dir = Path(path)
    if not source_dir.is_dir():
        click.echo(
            cli_error("Error: PATH must be a directory containing files to transfer."), err=True
        )
        sys.exit(1)

    config = TransferConfig(
        remote=remote,
        ssh_key=Path(ssh_key) if ssh_key else None,
        bwlimit=bwlimit,
        dry_run=dry_run,
        verify=verify,
    )

    mode_str = "DRY RUN" if dry_run else "transfer"
    click.echo(cli_header(f"PathSafe v{pathsafe.__version__} -- {mode_str}"))
    click.echo(cli_info(f"Source: {source_dir}"))
    click.echo(cli_info(f"Remote: {remote}"))
    click.echo(cli_separator())

    def progress(files_done, total_files, pct):
        click.echo(cli_dim(f"  [{files_done}/{total_files}] {pct:.0f}%"))

    try:
        result = transfer_batch(source_dir, config, progress_callback=progress)
    except (RuntimeError, FileNotFoundError, ValueError) as e:
        click.echo(cli_error(f"Error: {e}"), err=True)
        sys.exit(1)

    # Summary
    click.echo(cli_separator())
    click.echo(cli_bold(f"Done in {result.elapsed_seconds:.1f}s"))
    click.echo(f"  Transferred: {cli_bold(str(result.files_transferred))}")
    if result.files_skipped:
        click.echo(f"  Skipped:     {cli_dim(str(result.files_skipped))}")
    if result.files_failed:
        click.echo(f"  Failed:      {cli_error(str(result.files_failed))}")
    if result.verified:
        click.echo(f"  Verified:    {cli_success('YES')}")

    for err_msg in result.errors:
        click.echo(cli_error(f"  {err_msg}"))

    if result.errors:
        sys.exit(1)


@click.command()
@click.argument("path", type=click.Path(exists=True))
@click.option("--output", "-o", required=True, type=click.Path(), help="Output directory.")
@click.option(
    "--classify", "do_classify", is_flag=True, help="Classify stain types from label images."
)
@click.option(
    "--stain", type=str, default=None, help='Keep only this stain type (e.g. "he", "ihc").'
)
@click.option("--include", multiple=True, help="Include files matching glob pattern.")
@click.option("--exclude", multiple=True, help="Exclude files matching glob pattern.")
@click.option("--filter-file", type=click.Path(exists=True), help="Filter file (txt/csv/json).")
@click.option("--rename", type=click.Choice(["keep", "auto"]), default="auto", help="Rename mode.")
@click.option("--prefix", default="ANON", help="Prefix for auto rename.")
@click.option(
    "--transfer", "do_transfer", is_flag=True, help="Transfer to remote after deidentification."
)
@click.option("--remote", "-r", type=str, help="Remote destination for transfer.")
@click.option("--workers", "-w", type=int, default=0, help="Parallel workers (0=auto).")
@click.option("--dry-run", is_flag=True, help="Preview without modifying files.")
@click.option("--certificate", type=click.Path(), help="Write compliance certificate.")
@click.option(
    "--lookup",
    type=click.Path(exists=True),
    help="Excel file (.xlsx) for identifier lookup and patient grouping.",
)
@click.option("--lookup-sheet", default="Sheet1", help="Sheet name in the Excel file.")
@click.option(
    "--lookup-key",
    default="deidentified_identifier",
    help="Column name for matching against filenames.",
)
@click.option(
    "--lookup-group",
    default="patient_id",
    help="Column name for patient/group folder organization.",
)
@click.option("--resume", is_flag=True, default=True, help="Resume from previous pipeline state.")
def pipeline(
    path,
    output,
    do_classify,
    stain,
    include,
    exclude,
    filter_file,
    rename,
    prefix,
    do_transfer,
    remote,
    workers,
    dry_run,
    certificate,
    lookup,
    lookup_sheet,
    lookup_key,
    lookup_group,
    resume,
):
    """Full pipeline: classify -> filter -> deidentify -> transfer.

    This is the recommended command for end-to-end slide processing.
    """
    try:
        from pathsafe.pipeline_runner import PipelineConfig, run_pipeline
    except ImportError as e:
        click.echo(
            cli_error(
                "Error: Pipeline dependencies are required. "
                "Install them with: pip install pathsafe[pipeline]"
            ),
            err=True,
        )
        raise SystemExit(1) from e

    if do_transfer and not remote:
        click.echo(cli_error("Error: --remote is required when --transfer is specified."), err=True)
        sys.exit(1)

    # Load Excel lookup table for patient grouping
    grouping_map: dict = {}
    if lookup:
        try:
            from pathsafe.lookup import load_lookup_table

            grouping_map, _ = load_lookup_table(
                Path(lookup),
                sheet_name=lookup_sheet,
                source_column=lookup_key,
                group_column=lookup_group,
            )
            click.echo(
                cli_info(
                    f"Loaded lookup: {len(grouping_map)} grouping entries from {Path(lookup).name}"
                )
            )
        except (ValueError, FileNotFoundError) as e:
            click.echo(cli_error(f"Lookup error: {e}"), err=True)
            sys.exit(1)

    config = PipelineConfig(
        input_path=Path(path),
        output_dir=Path(output),
        do_classify=do_classify,
        stain_filter=stain,
        include=list(include) if include else None,
        exclude=list(exclude) if exclude else None,
        filter_file=Path(filter_file) if filter_file else None,
        rename=rename,
        prefix=prefix,
        do_transfer=do_transfer,
        remote=remote,
        workers=workers,
        dry_run=dry_run,
        certificate_path=Path(certificate) if certificate else None,
        resume=resume,
    )

    mode_str = "DRY RUN" if dry_run else "pipeline"
    stages = ["deidentify"]
    if do_classify:
        stages.insert(0, "classify")
    if stain:
        stages.insert(stages.index("deidentify"), "filter")
    if do_transfer:
        stages.append("transfer")

    click.echo(cli_header(f"PathSafe v{pathsafe.__version__} -- {mode_str}"))
    click.echo(cli_info(f"Stages: {' -> '.join(stages)}"))
    click.echo(cli_info(f"Input:  {path}"))
    click.echo(cli_info(f"Output: {output}"))
    click.echo(cli_separator())

    def progress(stage, i, total, filepath, message):
        counter = cli_dim(f"[{i}/{total}]")
        click.echo(f"  {cli_info(stage)} {counter} {filepath.name} {cli_dim(message)}")

    try:
        manifest = run_pipeline(config, progress_callback=progress)
    except Exception as e:
        click.echo(cli_error(f"Pipeline error: {e}"), err=True)
        sys.exit(1)

    # Summary from manifest
    click.echo(cli_separator())
    click.echo(cli_bold("Pipeline Summary"))

    entries = getattr(manifest, "files", None) or getattr(manifest, "entries", {})
    total = len(entries)
    by_status = {}
    for entry in entries.values():
        status = (
            entry.get("status", "unknown")
            if isinstance(entry, dict)
            else getattr(entry, "status", "unknown")
        )
        by_status[status] = by_status.get(status, 0) + 1

    click.echo(f"  Total files: {cli_bold(str(total))}")
    for status, count in sorted(by_status.items()):
        if status == "error":
            click.echo(f"  {status:12s}: {cli_error(str(count))}")
        elif status in ("deidentified", "transferred"):
            click.echo(f"  {status:12s}: {cli_success(str(count))}")
        elif status == "filtered":
            click.echo(f"  {status:12s}: {cli_dim(str(count))}")
        else:
            click.echo(f"  {status:12s}: {cli_warning(str(count))}")

    error_count = by_status.get("error", 0)
    if error_count > 0:
        sys.exit(1)


@click.command("download-models")
def download_models():
    """Pre-download OCR models for offline use."""
    try:
        from paddleocr import PaddleOCR

        click.echo("Downloading PaddleOCR models (English, PP-OCRv4)...")
        PaddleOCR(use_angle_cls=True, lang="en", show_log=True)
        click.echo("Models downloaded successfully. PathSafe classify will now work offline.")
    except ImportError:
        click.echo("Error: paddleocr not installed. Run: pip install pathsafe[pipeline]", err=True)
        sys.exit(1)
