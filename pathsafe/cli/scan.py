"""Subcommand module."""

from __future__ import annotations

import json
from pathlib import Path

import click

import pathsafe
from pathsafe.cli._common import _apply_custom_patterns
from pathsafe.deidentifier import (
    auto_workers,
    collect_wsi_files,
    scan_batch,
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
from pathsafe.report import friendly_tag_name, generate_scan_report


@click.command()
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
