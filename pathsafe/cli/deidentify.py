"""Subcommand module."""

from __future__ import annotations

import sys
import time
from pathlib import Path

import click

import pathsafe
from pathsafe.cli._common import _apply_custom_patterns
from pathsafe.deidentifier import (
    auto_workers,
    collect_wsi_files,
    deidentify_batch,
    preflight_check,
)
from pathsafe.log import (
    cli_bold,
    cli_dim,
    cli_error,
    cli_header,
    cli_info,
    cli_separator,
    cli_success,
    cli_warning,
    log_error,
    log_info,
    log_warn,
)
from pathsafe.report import generate_certificate


@click.command()
@click.argument("path", type=click.Path(exists=True))
@click.option(
    "--output",
    "-o",
    type=click.Path(),
    help="Output directory (copy mode). If omitted, deidentifies in-place.",
)
@click.option(
    "--in-place",
    is_flag=True,
    help="Explicitly confirm in-place deidentification (required if no --output).",
)
@click.option("--dry-run", is_flag=True, help="Scan only, don't modify files.")
@click.option(
    "--format",
    "fmt",
    type=click.Choice(["ndpi", "svs", "mrxs", "bif", "scn", "dicom", "tiff"]),
    help="Only process files of this format.",
)
@click.option(
    "--certificate",
    "-c",
    type=click.Path(),
    help="Write compliance certificate (JSON + PDF) to this path.",
)
@click.option("--verbose", "-v", is_flag=True, help="Show detailed progress.")
@click.option(
    "--workers",
    "-w",
    type=int,
    default=0,
    help="Number of parallel workers (default: auto-detect from CPU cores).",
)
@click.option("--log", type=click.Path(), help="Write log to file.")
@click.option(
    "--reset-timestamps/--no-reset-timestamps",
    default=True,
    help="Reset file timestamps to epoch (default: on). Use --no-reset-timestamps to keep original timestamps.",
)
@click.option(
    "--verify-integrity",
    is_flag=True,
    default=False,
    help="Verify image tile data integrity via SHA-256 checksums (default: off).",
)
@click.option(
    "--checksum",
    is_flag=True,
    default=False,
    help="Compute SHA-256 checksum of each output file (default: off).",
)
@click.option(
    "--institution",
    "-i",
    type=str,
    default="",
    help="Institution name to display on the PDF certificate header.",
)
@click.option(
    "--patterns",
    type=click.Path(exists=True),
    help="JSON file with custom PHI patterns (merged with built-in defaults).",
)
@click.option(
    "--rename",
    type=click.Choice(["keep", "auto", "mapping", "template"]),
    default="keep",
    help="Rename output files: keep (default), auto (sequential), mapping (CSV lookup), template (pattern).",
)
@click.option(
    "--prefix", default="ANON", help="Prefix for auto/template rename modes (default: ANON)."
)
@click.option(
    "--start", type=int, default=1, help="Start number for auto-sequential rename (default: 1)."
)
@click.option(
    "--digits",
    type=int,
    default=4,
    help="Zero-padding width for auto-sequential rename (default: 4).",
)
@click.option("--separator", default="_", help="Separator between prefix and number (default: _).")
@click.option(
    "--mapping-file",
    type=click.Path(exists=True),
    help='CSV mapping file for rename mode "mapping" (columns: source_filename, output_name).',
)
@click.option(
    "--template",
    "rename_template",
    default="{prefix}_{index}.{ext}",
    help="Naming pattern for template mode. Tokens: {prefix}, {index}, {ext}, {sha8}, {format}, {date}.",
)
@click.option(
    "--manifest",
    type=click.Path(),
    help="Write source-to-output filename manifest CSV to this path.",
)
@click.option(
    "--include",
    multiple=True,
    help='Only process files matching this glob pattern (repeatable, e.g. --include "*HE*").',
)
@click.option(
    "--exclude",
    multiple=True,
    help='Skip files matching this glob pattern (repeatable, e.g. --exclude "*IHC*").',
)
@click.option(
    "--filter-file",
    type=click.Path(exists=True),
    help="Text/CSV/JSON file listing filenames to include. "
    'Accepts one-per-line text, CSV with a "file" column, '
    "or JSON list/dict of filenames.",
)
@click.option(
    "--yes",
    "-y",
    is_flag=True,
    default=False,
    help="Skip interactive confirmation prompts (e.g., for --in-place).",
)
def deidentify(
    path: str,
    output: str | None,
    in_place: bool,
    dry_run: bool,
    fmt: str | None,
    certificate: str | None,
    verbose: bool,
    workers: int,
    log: str | None,
    reset_timestamps: bool,
    verify_integrity: bool,
    checksum: bool,
    institution: str,
    patterns: str | None,
    rename: str,
    prefix: str,
    start: int,
    digits: int,
    separator: str,
    mapping_file: str | None,
    rename_template: str,
    manifest: str | None,
    include: tuple,
    exclude: tuple,
    filter_file: str | None,
    yes: bool,
) -> None:
    """Deidentify PHI in WSI files.

    PATH can be a single file or a directory to process recursively.

    By default, uses copy mode (--output required). Use --in-place to
    modify original files directly.
    """
    workers = workers or auto_workers()
    if patterns:
        _apply_custom_patterns(patterns)

    input_path = Path(path)
    output_dir = Path(output) if output else None

    # Safety check: require explicit flag for in-place
    if output_dir is None and not in_place and not dry_run:
        click.echo(
            cli_error(
                "Error: Must specify --output for copy mode, or --in-place "
                "to modify originals directly."
            ),
            err=True,
        )
        sys.exit(1)

    # Interactive confirmation for destructive in-place mode unless --yes
    if (
        in_place
        and not dry_run
        and not yes
        and not click.confirm(
            cli_warning(
                "WARNING: --in-place will modify original files. This cannot be undone. Continue?"
            ),
            default=False,
        )
    ):
        click.echo("Aborted.")
        sys.exit(0)

    log_file = None
    try:
        log_file = open(log, "w") if log else None  # noqa: SIM115
    except OSError as e:
        click.echo(cli_error(f"Warning: Could not open log file: {e}"), err=True)

    def emit(console_msg: str, log_line: str | None = None) -> None:
        """Print to terminal and write to log file."""
        click.echo(console_msg)
        if log_file:
            log_file.write((log_line or console_msg) + "\n")
            log_file.flush()

    try:
        files = collect_wsi_files(input_path, format_filter=fmt)
        if not files:
            emit(
                cli_warning(f"No WSI files found in {input_path}"),
                log_info(f"No WSI files found in {input_path}"),
            )
            return

        # Apply file filters (include/exclude globs, filter-file whitelist)
        if include or exclude or filter_file:
            from pathsafe.serializer import apply_filters

            before_count = len(files)
            files = apply_filters(
                files,
                include=list(include) if include else None,
                exclude=list(exclude) if exclude else None,
                filter_file=Path(filter_file) if filter_file else None,
            )
            dropped = before_count - len(files)
            if dropped:
                emit(
                    cli_info(
                        f"Filters applied: {len(files)} of {before_count} files selected ({dropped} excluded)"
                    ),
                    log_info(f"Filters: {len(files)}/{before_count} selected, {dropped} excluded"),
                )
            if not files:
                emit(
                    cli_warning("No files remain after filtering."),
                    log_info("No files remain after filtering."),
                )
                return

        # Pre-flight validation
        if not dry_run:
            preflight = preflight_check(files, output_dir)
            for w in preflight.warnings:
                emit(cli_warning(f"Warning: {w}"), log_warn(f"Preflight: {w}"))
            if not preflight.ok:
                for e in preflight.errors:
                    emit(cli_error(f"Error: {e}"), log_error(f"Preflight: {e}"))
                sys.exit(1)

        mode_str = "DRY RUN" if dry_run else ("copy" if output_dir else "in-place")
        workers_str = f", {workers} workers" if workers > 1 else ""

        # --- Serializer: compute rename plan upfront ---
        rename_plan = None
        serializer_config = None
        if rename != "keep" and output_dir:
            from pathsafe.serializer import (
                RenameMode,
                SerializerConfig,
                compute_rename_plan,
                load_mapping,
                write_manifest,
            )

            mode_map = {
                "auto": RenameMode.AUTO,
                "mapping": RenameMode.MAPPING,
                "template": RenameMode.TEMPLATE,
            }
            serializer_config = SerializerConfig(
                mode=mode_map[rename],
                prefix=prefix,
                start=start,
                digits=digits,
                separator=separator,
                mapping_path=Path(mapping_file) if mapping_file else None,
                unmatched="skip",
                template=rename_template,
                manifest_path=Path(manifest) if manifest else None,
            )

            if serializer_config.mode == RenameMode.MAPPING:
                try:
                    load_mapping(serializer_config)
                    emit(
                        cli_info(f"Loaded mapping: {len(serializer_config._mapping)} entries"),
                        log_info(f"Loaded mapping: {len(serializer_config._mapping)} entries"),
                    )
                except (ValueError, FileNotFoundError) as e:
                    emit(cli_error(f"Mapping error: {e}"), log_error(str(e)))
                    sys.exit(1)

            try:
                rename_plan = compute_rename_plan(serializer_config, files, output_dir)
                emit(
                    cli_info(f"Rename plan: {len(rename_plan)} file(s) will be serialized"),
                    log_info(f"Rename plan: {len(rename_plan)} file(s)"),
                )
            except ValueError as e:
                emit(cli_error(f"Rename error: {e}"), log_error(str(e)))
                sys.exit(1)

        emit(
            cli_header(
                f"PathSafe v{pathsafe.__version__} -- {mode_str} deidentification{workers_str}"
            ),
            log_info(
                f"PathSafe v{pathsafe.__version__} -- {mode_str} deidentification{workers_str}"
            ),
        )
        emit(
            cli_info(f"Processing {len(files)} file(s)..."),
            log_info(f"Processing {len(files)} file(s)..."),
        )
        emit(cli_separator(), "-" * 60)

        t0 = time.time()

        def progress(i: int, total: int, filepath: Path, result: object) -> None:
            elapsed = time.time() - t0
            rate = i / elapsed if elapsed > 0 else 0
            eta = (total - i) / rate / 60 if rate > 0 else 0

            counter = cli_dim(f"[{i}/{total}]")
            stats = cli_dim(f"{rate:.1f}/s ETA {eta:.0f}m")

            if result.error:
                status_cli = cli_error(f"ERROR: {result.error}")
                status_log = f"ERROR: {result.error}"
                log_fn = log_error
            elif result.findings_cleared > 0:
                status_cli = cli_warning(f"cleared {result.findings_cleared} finding(s)")
                status_log = f"cleared {result.findings_cleared} finding(s)"
                log_fn = log_warn
            else:
                status_cli = cli_success("already clean")
                status_log = "already clean"
                log_fn = log_info

            emit(
                f"  {counter} {stats} | {filepath.name} | {status_cli}",
                log_fn(f"[{i}/{total}] {filepath.name} | {status_log}"),
            )

            # Image integrity result
            if result.image_integrity_verified is True:
                emit(
                    f"         {cli_success('Image integrity: VERIFIED')}",
                    log_info("  Image integrity: VERIFIED"),
                )
            elif result.image_integrity_verified is False:
                emit(
                    f"         {cli_error('Image integrity: FAILED')}",
                    log_error("  Image integrity: FAILED"),
                )

            # SHA-256 of output file
            if result.sha256_after:
                emit(
                    f"         {cli_dim('SHA-256: ' + result.sha256_after)}",
                    log_info(f"  SHA-256: {result.sha256_after}"),
                )

            # Filename PHI warning
            if result.filename_has_phi:
                emit(
                    f"         {cli_error('WARNING: Filename contains PHI -- rename file manually')}",
                    log_warn("  WARNING: Filename contains PHI -- rename file manually"),
                )

        batch_kwargs = dict(
            input_path=input_path,
            output_dir=output_dir,
            dry_run=dry_run,
            format_filter=fmt,
            progress_callback=progress,
            workers=workers,
            reset_timestamps=reset_timestamps,
            verify_integrity=verify_integrity,
            compute_checksum=checksum,
        )
        if rename_plan is not None:
            batch_kwargs["precomputed_pairs"] = rename_plan
        batch_result = deidentify_batch(**batch_kwargs)

        # Summary
        emit(cli_separator(), "-" * 60)
        emit(
            cli_bold(f"Done in {batch_result.total_time_seconds:.1f}s"),
            log_info(f"Done in {batch_result.total_time_seconds:.1f}s"),
        )
        emit(
            f"  Total:         {cli_bold(str(batch_result.total_files))}",
            log_info(f"  Total:         {batch_result.total_files}"),
        )
        if batch_result.files_deidentified:
            emit(
                f"  Deidentified:    {cli_warning(str(batch_result.files_deidentified))}",
                log_info(f"  Deidentified:    {batch_result.files_deidentified}"),
            )
        if batch_result.files_already_clean:
            emit(
                f"  Already clean: {cli_success(str(batch_result.files_already_clean))}",
                log_info(f"  Already clean: {batch_result.files_already_clean}"),
            )
        if batch_result.files_errored:
            emit(
                f"  Errors:        {cli_error(str(batch_result.files_errored))}",
                log_error(f"  Errors:        {batch_result.files_errored}"),
            )

        # Filename PHI warnings (skip if rename was applied since filenames are clean)
        if rename_plan is None:
            phi_filenames = sum(1 for r in batch_result.results if r.filename_has_phi)
            if phi_filenames:
                emit(
                    f"\n  {cli_error(f'WARNING: {phi_filenames} file(s) have PHI in their filename -- rename manually')}",
                    log_warn(
                        f"  WARNING: {phi_filenames} file(s) have PHI in their filename -- rename manually"
                    ),
                )

        # Write manifest CSV (exclude errored files whose outputs don't exist)
        if rename_plan is not None and not dry_run:
            from pathsafe.serializer import write_manifest

            checksums = {}
            successful_outputs = set()
            for r in batch_result.results:
                if not r.error:
                    successful_outputs.add(str(r.output_path))
                if r.sha256_after:
                    checksums[r.output_path.name] = r.sha256_after
            # Filter plan to only include successful files
            successful_plan = [
                (src, out) for src, out in rename_plan if str(out) in successful_outputs
            ]
            manifest_out = serializer_config.manifest_path or (output_dir / "manifest.csv")
            try:
                write_manifest(successful_plan, manifest_out, checksums)
                emit(cli_info(f"\nManifest: {manifest_out}"), log_info(f"Manifest: {manifest_out}"))
            except OSError as e:
                emit(
                    cli_error(f"Manifest write error: {e}"), log_error(f"Manifest write error: {e}")
                )

        # Generate certificate
        if certificate and not dry_run:
            generate_certificate(
                batch_result,
                output_path=Path(certificate),
                timestamps_reset=reset_timestamps,
                institution=institution,
            )
            batch_result.certificate_path = Path(certificate)
            pdf_path = Path(certificate).with_suffix(".pdf")
            emit(
                cli_info(f"\nCompliance certificate: {certificate}"),
                log_info(f"Compliance certificate: {certificate}"),
            )
            emit(cli_info(f"PDF certificate: {pdf_path}"), log_info(f"PDF certificate: {pdf_path}"))

        if batch_result.files_errored > 0:
            sys.exit(1)
    finally:
        if log_file:
            log_file.close()
