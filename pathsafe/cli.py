"""CLI interface for PathSafe -- scan, deidentify, verify, info subcommands.

Color-coded terminal output with structured log file support.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import click

import pathsafe
from pathsafe.deidentifier import (
    auto_workers,
    collect_wsi_files,
    deidentify_batch,
    preflight_check,
    scan_batch,
)
from pathsafe.formats import detect_format, get_handler
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
    log_error,
    log_info,
    log_warn,
)
from pathsafe.report import friendly_tag_name, generate_certificate, generate_scan_report
from pathsafe.verify import verify_batch


def _apply_custom_patterns(patterns_path: str) -> None:
    """Load a custom patterns JSON and replace module-level pattern lists."""
    from pathsafe import scanner
    from pathsafe.scanner import PatternConfig

    config = PatternConfig.from_json(patterns_path)
    scanner.PHI_BYTE_PATTERNS = config.byte_patterns
    scanner.PHI_STRING_PATTERNS = config.string_patterns
    scanner.DATE_BYTE_PATTERNS = config.date_byte_patterns


@click.group(
    epilog="Note: PathSafe is not a medical device. De-identification should be verified per institutional requirements."
)
@click.version_option(version=pathsafe.__version__, prog_name="pathsafe")
def main() -> None:
    """PathSafe -- WSI de-identifier.

    Detect and remove Protected Health Information (PHI) from
    whole-slide image files (NDPI, SVS, TIFF).
    """
    pass


@main.command()
@click.argument("path", type=click.Path(exists=True))
@click.option("--verbose", "-v", is_flag=True, help="Show detailed findings.")
@click.option(
    "--format",
    "fmt",
    type=click.Choice(["ndpi", "svs", "mrxs", "bif", "scn", "dicom", "tiff"]),
    help="Only scan files of this format.",
)
@click.option("--json-out", type=click.Path(), help="Write results as JSON to file.")
@click.option(
    "--workers",
    "-w",
    type=int,
    default=0,
    help="Number of parallel workers (default: auto-detect from CPU cores).",
)
@click.option("--report", "-r", type=click.Path(), help="Write scan report PDF to this path.")
@click.option(
    "--institution",
    "-i",
    type=str,
    default="",
    help="Institution name to display on the PDF report header.",
)
@click.option(
    "--patterns",
    type=click.Path(exists=True),
    help="JSON file with custom PHI patterns (merged with built-in defaults).",
)
def scan(
    path: str,
    verbose: bool,
    fmt: str | None,
    json_out: str | None,
    workers: int,
    report: str | None,
    institution: str,
    patterns: str | None,
) -> None:
    """Scan files for PHI (read-only).

    PATH can be a single file or a directory to scan recursively.
    """
    workers = workers or auto_workers()
    if patterns:
        _apply_custom_patterns(patterns)

    input_path = Path(path)
    files = collect_wsi_files(input_path, format_filter=fmt)

    if not files:
        click.echo(cli_warning(f"No WSI files found in {input_path}"))
        return

    workers_str = f", {workers} workers" if workers > 1 else ""
    click.echo(cli_header(f"PathSafe v{pathsafe.__version__} -- PHI Scan{workers_str}"))
    click.echo(cli_info(f"Scanning {len(files)} file(s)..."))
    click.echo(cli_separator())

    total_findings = 0
    clean_count = 0
    error_count = 0
    results_json = []
    report_results = []

    def on_result(i: int, total: int, filepath: Path, result: object) -> None:
        nonlocal total_findings, clean_count, error_count

        counter = cli_dim(f"[{i}/{total}]")

        if result.error:
            error_count += 1
            click.echo(f"  {counter} {filepath.name} {cli_error('ERROR')} {cli_dim(result.error)}")
        elif result.is_clean:
            clean_count += 1
            if verbose:
                click.echo(f"  {counter} {filepath.name} {cli_success('CLEAN')}")
        else:
            total_findings += len(result.findings)
            n = len(result.findings)
            click.echo(f"  {counter} {filepath.name} {cli_warning(f'{n} finding(s)')}")
            if verbose:
                for f in result.findings:
                    click.echo(
                        f"         {cli_finding(friendly_tag_name(f.tag_name))} "
                        f"{cli_dim('at offset')} {f.offset}: "
                        f"{cli_warning(f.mask_preview())}"
                    )

        # NOTE: Do NOT hash the original (pre-deidentification) file here.
        # A hash of the original could link deidentified output back to a
        # specific patient.  Hashing is only safe on post-deidentification files.
        file_sha256 = ""

        if json_out:
            results_json.append(
                {
                    "file": str(filepath),
                    "format": result.format,
                    "is_clean": result.is_clean,
                    "findings": len(result.findings),
                    "scan_time_ms": round(result.scan_time_ms, 1),
                    "error": result.error,
                }
            )

        if report:
            report_results.append(
                {
                    "filepath": str(filepath),
                    "is_clean": result.is_clean,
                    "error": result.error,
                    "sha256": file_sha256,
                    "findings": [
                        {"tag_name": f.tag_name, "value_preview": f.mask_preview()}
                        for f in result.findings
                    ]
                    if result.findings
                    else [],
                }
            )

    scan_batch(input_path, format_filter=fmt, progress_callback=on_result, workers=workers)

    # Summary
    click.echo(cli_separator())
    phi_count = len(files) - clean_count - error_count
    click.echo(cli_bold("Summary"))
    click.echo(f"  Total scanned:  {cli_bold(str(len(files)))}")
    if clean_count:
        click.echo(f"  Clean:          {cli_success(str(clean_count))}")
    if phi_count:
        click.echo(
            f"  PHI detected:   {cli_warning(str(phi_count))} "
            f"{cli_dim(f'({total_findings} total findings)')}"
        )
    if error_count:
        click.echo(f"  Errors:         {cli_error(str(error_count))}")

    if phi_count == 0 and error_count == 0:
        click.echo(cli_success("\nAll files are clean -- no PHI detected."))
    elif phi_count > 0:
        click.echo(
            cli_warning(f'\n{phi_count} file(s) contain PHI -- run "pathsafe deidentify" to clean.')
        )

    if report:
        scan_data = {
            "total": len(files),
            "clean": clean_count,
            "phi_files": phi_count,
            "phi_findings": total_findings,
            "errors": error_count,
            "results": report_results,
        }
        report_path = generate_scan_report(scan_data, Path(report), institution=institution)
        click.echo(cli_info(f"Scan report saved to {report_path}"))

    if json_out:
        with open(json_out, "w") as f:
            json.dump(results_json, f, indent=2)
        click.echo(cli_info(f"Results written to {json_out}"))


@main.command()
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


@main.command()
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


@main.command()
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


@main.command()
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


@main.command()
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


@main.command()
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


@main.command()
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


@main.command()
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


@main.command("download-models")
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


if __name__ == "__main__":
    main()
