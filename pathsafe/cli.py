"""CLI interface for PathSafe — scan, anonymize, verify, info subcommands.

Color-coded terminal output with structured log file support.
"""

import hashlib
import json
import sys
import time
from pathlib import Path

import click

import pathsafe
from pathsafe.anonymizer import anonymize_batch, anonymize_file, collect_wsi_files, scan_batch
from pathsafe.formats import detect_format, get_handler
from pathsafe.log import (
    cli_bold, cli_dim, cli_error, cli_finding, cli_header, cli_info,
    cli_separator, cli_success, cli_warning,
    log_error, log_info, log_warn,
)
from pathsafe.report import generate_certificate, generate_scan_report, friendly_tag_name
from pathsafe.verify import verify_batch, verify_file


@click.group()
@click.version_option(version=pathsafe.__version__, prog_name='pathsafe')
def main():
    """PathSafe — Production-tested WSI anonymizer.

    Detect and remove Protected Health Information (PHI) from
    whole-slide image files (NDPI, SVS, TIFF).
    """
    pass


@main.command()
@click.argument('path', type=click.Path(exists=True))
@click.option('--verbose', '-v', is_flag=True, help='Show detailed findings.')
@click.option('--format', 'fmt', type=click.Choice(['ndpi', 'svs', 'mrxs', 'bif', 'scn', 'dicom', 'tiff']),
              help='Only scan files of this format.')
@click.option('--json-out', type=click.Path(), help='Write results as JSON to file.')
@click.option('--workers', '-w', type=int, default=1,
              help='Number of parallel workers (default: 1, sequential).')
@click.option('--report', '-r', type=click.Path(), help='Write scan report PDF to this path.')
@click.option('--institution', '-i', type=str, default='',
              help='Institution name to display on the PDF report header.')
def scan(path, verbose, fmt, json_out, workers, report, institution):
    """Scan files for PHI (read-only).

    PATH can be a single file or a directory to scan recursively.
    """
    input_path = Path(path)
    files = collect_wsi_files(input_path, format_filter=fmt)

    if not files:
        click.echo(cli_warning(f'No WSI files found in {input_path}'))
        return

    workers_str = f', {workers} workers' if workers > 1 else ''
    click.echo(cli_header(f'PathSafe v{pathsafe.__version__} — PHI Scan{workers_str}'))
    click.echo(cli_info(f'Scanning {len(files)} file(s)...'))
    click.echo(cli_separator())

    total_findings = 0
    clean_count = 0
    error_count = 0
    results_json = []
    report_results = []

    def on_result(i, total, filepath, result):
        nonlocal total_findings, clean_count, error_count

        counter = cli_dim(f'[{i}/{total}]')

        if result.error:
            error_count += 1
            click.echo(f'  {counter} {filepath.name} {cli_error("ERROR")} {cli_dim(result.error)}')
        elif result.is_clean:
            clean_count += 1
            if verbose:
                click.echo(f'  {counter} {filepath.name} {cli_success("CLEAN")}')
        else:
            total_findings += len(result.findings)
            n = len(result.findings)
            click.echo(f'  {counter} {filepath.name} '
                       f'{cli_warning(f"{n} finding(s)")}')
            if verbose:
                for f in result.findings:
                    click.echo(f'         {cli_finding(friendly_tag_name(f.tag_name))} '
                               f'{cli_dim("at offset")} {f.offset}: '
                               f'{cli_warning(f.value_preview)}')

        # Compute SHA-256 for scan report
        file_sha256 = ''
        if report:
            try:
                h = hashlib.sha256()
                with open(str(filepath), 'rb') as fh:
                    while True:
                        chunk = fh.read(65536)
                        if not chunk:
                            break
                        h.update(chunk)
                file_sha256 = h.hexdigest()
            except (OSError, FileNotFoundError):
                pass

        if json_out:
            results_json.append({
                'file': str(filepath),
                'format': result.format,
                'is_clean': result.is_clean,
                'findings': len(result.findings),
                'scan_time_ms': round(result.scan_time_ms, 1),
                'error': result.error,
            })

        if report:
            report_results.append({
                'filepath': str(filepath),
                'is_clean': result.is_clean,
                'error': result.error,
                'sha256': file_sha256,
                'findings': [
                    {'tag_name': f.tag_name, 'value_preview': f.value_preview}
                    for f in result.findings
                ] if result.findings else [],
            })

    scan_batch(input_path, format_filter=fmt, progress_callback=on_result,
               workers=workers)

    # Summary
    click.echo(cli_separator())
    phi_count = len(files) - clean_count - error_count
    click.echo(cli_bold('Summary'))
    click.echo(f'  Total scanned:  {cli_bold(str(len(files)))}')
    if clean_count:
        click.echo(f'  Clean:          {cli_success(str(clean_count))}')
    if phi_count:
        click.echo(f'  PHI detected:   {cli_warning(str(phi_count))} '
                   f'{cli_dim(f"({total_findings} total findings)")}')
    if error_count:
        click.echo(f'  Errors:         {cli_error(str(error_count))}')

    if phi_count == 0 and error_count == 0:
        click.echo(cli_success('\nAll files are clean — no PHI detected.'))
    elif phi_count > 0:
        click.echo(cli_warning(f'\n{phi_count} file(s) contain PHI — run "pathsafe anonymize" to clean.'))

    if report:
        scan_data = {
            'total': len(files),
            'clean': clean_count,
            'phi_files': phi_count,
            'phi_findings': total_findings,
            'errors': error_count,
            'results': report_results,
        }
        report_path = generate_scan_report(scan_data, Path(report),
                                                 institution=institution)
        click.echo(cli_info(f'Scan report saved to {report_path}'))

    if json_out:
        with open(json_out, 'w') as f:
            json.dump(results_json, f, indent=2)
        click.echo(cli_info(f'Results written to {json_out}'))


@main.command()
@click.argument('path', type=click.Path(exists=True))
@click.option('--output', '-o', type=click.Path(),
              help='Output directory (copy mode). If omitted, anonymizes in-place.')
@click.option('--in-place', is_flag=True,
              help='Explicitly confirm in-place anonymization (required if no --output).')
@click.option('--dry-run', is_flag=True, help='Scan only, don\'t modify files.')
@click.option('--no-verify', is_flag=True, help='Skip post-anonymization verification.')
@click.option('--format', 'fmt', type=click.Choice(['ndpi', 'svs', 'mrxs', 'bif', 'scn', 'dicom', 'tiff']),
              help='Only process files of this format.')
@click.option('--certificate', '-c', type=click.Path(),
              help='Write compliance certificate (JSON + PDF) to this path.')
@click.option('--verbose', '-v', is_flag=True, help='Show detailed progress.')
@click.option('--workers', '-w', type=int, default=1,
              help='Number of parallel workers (default: 1, sequential).')
@click.option('--log', type=click.Path(), help='Write log to file.')
@click.option('--reset-timestamps/--no-reset-timestamps', default=True,
              help='Reset file timestamps to epoch (default: on). Use --no-reset-timestamps to keep original timestamps.')
@click.option('--verify-integrity/--no-verify-integrity', default=True,
              help='Verify image tile data integrity via SHA-256 checksums (default: on).')
@click.option('--institution', '-i', type=str, default='',
              help='Institution name to display on the PDF certificate header.')
def anonymize(path, output, in_place, dry_run, no_verify, fmt, certificate, verbose, workers, log,
              reset_timestamps, verify_integrity, institution):
    """Anonymize PHI in WSI files.

    PATH can be a single file or a directory to process recursively.

    By default, uses copy mode (--output required). Use --in-place to
    modify original files directly.
    """
    input_path = Path(path)
    output_dir = Path(output) if output else None

    # Safety check: require explicit flag for in-place
    if output_dir is None and not in_place and not dry_run:
        click.echo(cli_error('Error: Must specify --output for copy mode, or --in-place '
                             'to modify originals directly.'), err=True)
        sys.exit(1)

    log_file = None
    try:
        log_file = open(log, 'w') if log else None
    except OSError as e:
        click.echo(cli_error(f'Warning: Could not open log file: {e}'), err=True)

    def emit(console_msg: str, log_line: str = None):
        """Print to terminal and write to log file."""
        click.echo(console_msg)
        if log_file:
            log_file.write((log_line or console_msg) + '\n')
            log_file.flush()

    try:
        files = collect_wsi_files(input_path, format_filter=fmt)
        if not files:
            emit(cli_warning(f'No WSI files found in {input_path}'),
                 log_info(f'No WSI files found in {input_path}'))
            return

        mode_str = 'DRY RUN' if dry_run else ('copy' if output_dir else 'in-place')
        workers_str = f', {workers} workers' if workers > 1 else ''

        emit(cli_header(f'PathSafe v{pathsafe.__version__} — {mode_str} anonymization{workers_str}'),
             log_info(f'PathSafe v{pathsafe.__version__} — {mode_str} anonymization{workers_str}'))
        emit(cli_info(f'Processing {len(files)} file(s)...'),
             log_info(f'Processing {len(files)} file(s)...'))
        emit(cli_separator(), '-' * 60)

        t0 = time.time()

        def progress(i, total, filepath, result):
            elapsed = time.time() - t0
            rate = i / elapsed if elapsed > 0 else 0
            eta = (total - i) / rate / 60 if rate > 0 else 0

            counter = cli_dim(f'[{i}/{total}]')
            stats = cli_dim(f'{rate:.1f}/s ETA {eta:.0f}m')

            if result.error:
                status_cli = cli_error(f'ERROR: {result.error}')
                status_log = f'ERROR: {result.error}'
                log_fn = log_error
            elif result.findings_cleared > 0:
                verified = ' [verified]' if result.verified else ''
                status_cli = cli_warning(f'cleared {result.findings_cleared} finding(s)') + \
                             (cli_success(verified) if result.verified else cli_dim(verified))
                status_log = f'cleared {result.findings_cleared} finding(s){verified}'
                log_fn = log_warn
            else:
                status_cli = cli_success('already clean')
                status_log = 'already clean'
                log_fn = log_info

            emit(f'  {counter} {stats} | {filepath.name} | {status_cli}',
                 log_fn(f'[{i}/{total}] {filepath.name} | {status_log}'))

            # Image integrity result
            if result.image_integrity_verified is True:
                emit(f'         {cli_success("Image integrity: VERIFIED")}',
                     log_info(f'  Image integrity: VERIFIED'))
            elif result.image_integrity_verified is False:
                emit(f'         {cli_error("Image integrity: FAILED")}',
                     log_error(f'  Image integrity: FAILED'))

            # SHA-256 of output file
            if result.sha256_after:
                emit(f'         {cli_dim("SHA-256: " + result.sha256_after)}',
                     log_info(f'  SHA-256: {result.sha256_after}'))

            # Filename PHI warning
            if result.filename_has_phi:
                emit(f'         {cli_error("WARNING: Filename contains PHI — rename file manually")}',
                     log_warn(f'  WARNING: Filename contains PHI — rename file manually'))

        batch_result = anonymize_batch(
            input_path, output_dir=output_dir,
            verify=not no_verify, dry_run=dry_run,
            format_filter=fmt, progress_callback=progress,
            workers=workers, reset_timestamps=reset_timestamps,
            verify_integrity=verify_integrity,
        )

        # Summary
        emit(cli_separator(), '-' * 60)
        emit(cli_bold(f'Done in {batch_result.total_time_seconds:.1f}s'),
             log_info(f'Done in {batch_result.total_time_seconds:.1f}s'))
        emit(f'  Total:         {cli_bold(str(batch_result.total_files))}',
             log_info(f'  Total:         {batch_result.total_files}'))
        if batch_result.files_anonymized:
            emit(f'  Anonymized:    {cli_warning(str(batch_result.files_anonymized))}',
                 log_info(f'  Anonymized:    {batch_result.files_anonymized}'))
        if batch_result.files_already_clean:
            emit(f'  Already clean: {cli_success(str(batch_result.files_already_clean))}',
                 log_info(f'  Already clean: {batch_result.files_already_clean}'))
        if batch_result.files_errored:
            emit(f'  Errors:        {cli_error(str(batch_result.files_errored))}',
                 log_error(f'  Errors:        {batch_result.files_errored}'))

        # Filename PHI warnings
        phi_filenames = sum(1 for r in batch_result.results if r.filename_has_phi)
        if phi_filenames:
            emit(f'\n  {cli_error(f"WARNING: {phi_filenames} file(s) have PHI in their filename — rename manually")}',
                 log_warn(f'  WARNING: {phi_filenames} file(s) have PHI in their filename — rename manually'))

        # Generate certificate
        if certificate and not dry_run:
            cert = generate_certificate(batch_result, output_path=Path(certificate),
                                        timestamps_reset=reset_timestamps,
                                        institution=institution)
            batch_result.certificate_path = Path(certificate)
            pdf_path = Path(certificate).with_suffix('.pdf')
            emit(cli_info(f'\nCompliance certificate: {certificate}'),
                 log_info(f'Compliance certificate: {certificate}'))
            emit(cli_info(f'PDF certificate: {pdf_path}'),
                 log_info(f'PDF certificate: {pdf_path}'))

        if batch_result.files_errored > 0:
            sys.exit(1)
    finally:
        if log_file:
            log_file.close()


@main.command()
@click.argument('path', type=click.Path(exists=True))
@click.option('--verbose', '-v', is_flag=True, help='Show detailed findings.')
@click.option('--format', 'fmt', type=click.Choice(['ndpi', 'svs', 'mrxs', 'bif', 'scn', 'dicom', 'tiff']),
              help='Only verify files of this format.')
def verify(path, verbose, fmt):
    """Verify that files have been fully anonymized.

    Re-scans all files to confirm no PHI remains.
    """
    input_path = Path(path)
    files = collect_wsi_files(input_path, format_filter=fmt)

    if not files:
        click.echo(cli_warning(f'No WSI files found in {input_path}'))
        return

    click.echo(cli_header(f'PathSafe v{pathsafe.__version__} — Verification'))
    click.echo(cli_info(f'Verifying {len(files)} file(s)...'))
    click.echo(cli_separator())

    clean_count = 0
    dirty_count = 0

    def progress(i, total, filepath, result):
        nonlocal clean_count, dirty_count
        counter = cli_dim(f'[{i}/{total}]')

        if result.is_clean:
            clean_count += 1
            if verbose:
                click.echo(f'  {counter} {filepath.name} {cli_success("CLEAN")}')
        else:
            dirty_count += 1
            n = len(result.findings)
            click.echo(f'  {counter} {filepath.name} '
                       f'{cli_error(f"PHI FOUND ({n} finding(s))")}')
            if verbose:
                for f in result.findings:
                    click.echo(f'         {cli_finding(f.tag_name)}: '
                               f'{cli_warning(f.value_preview)}')

    verify_batch(input_path, format_filter=fmt, progress_callback=progress)

    click.echo(cli_separator())
    click.echo(cli_bold('Verification Results'))
    if clean_count:
        click.echo(f'  Clean:          {cli_success(str(clean_count))}')
    if dirty_count:
        click.echo(f'  PHI remaining:  {cli_error(str(dirty_count))}')

    if dirty_count > 0:
        click.echo(cli_error('\nWARNING: Some files still contain PHI!'))
        sys.exit(1)
    else:
        click.echo(cli_success('\nAll files verified clean.'))


@main.command()
def gui():
    """Launch the graphical user interface."""
    try:
        from pathsafe.gui_qt import main as gui_main
    except ImportError:
        click.echo(
            cli_error('Error: PySide6 is required for the GUI. '
                      'Install it with: pip install pathsafe[gui]'),
            err=True,
        )
        raise SystemExit(1)
    gui_main()


@main.command()
@click.argument('path', type=click.Path(exists=True))
@click.option('--output', '-o', type=click.Path(), required=True,
              help='Output file or directory.')
@click.option('--target-format', '-t', type=click.Choice(['tiff', 'png', 'jpeg']),
              default='tiff', help='Target format (default: tiff).')
@click.option('--anonymize', '-a', is_flag=True,
              help='Run PathSafe anonymization on converted output.')
@click.option('--tile-size', type=int, default=256,
              help='Tile size in pixels for pyramidal TIFF (default: 256).')
@click.option('--quality', type=click.IntRange(1, 100), default=90,
              help='JPEG compression quality 1-100 (default: 90).')
@click.option('--extract', type=click.Choice(['label', 'macro', 'thumbnail']),
              help='Extract an associated image instead of converting.')
@click.option('--format', 'fmt', type=click.Choice(['ndpi', 'svs', 'mrxs', 'bif', 'scn', 'dicom', 'tiff']),
              help='Only convert files of this format (batch mode).')
@click.option('--workers', '-w', type=int, default=1,
              help='Number of parallel workers for batch conversion (default: 1).')
@click.option('--verbose', '-v', is_flag=True, help='Show detailed output.')
@click.option('--reset-timestamps', is_flag=True,
              help='Reset file timestamps to epoch on output files (removes temporal PHI).')
def convert(path, output, target_format, anonymize, tile_size, quality, extract, fmt, workers, verbose,
            reset_timestamps):
    """Convert WSI files between formats.

    PATH can be a single file or a directory to convert recursively.

    \b
    Examples:
        pathsafe convert slide.ndpi -o slide.tiff
        pathsafe convert slide.ndpi -o slide.tiff --anonymize
        pathsafe convert slide.ndpi -o label.png --extract label
        pathsafe convert /slides/ -o /converted/ -t tiff -w 4
    """
    try:
        from pathsafe.converter import convert_batch, convert_file
    except ImportError as e:
        click.echo(cli_error(f'Error: {e}'), err=True)
        sys.exit(1)

    input_path = Path(path)
    output_path = Path(output)

    click.echo(cli_header(f'PathSafe v{pathsafe.__version__} — Format Conversion'))

    if extract:
        # Single file extraction
        if input_path.is_dir():
            click.echo(cli_error('Error: --extract requires a single file, not a directory.'), err=True)
            sys.exit(1)

        click.echo(cli_info(f'Extracting {extract} image from {input_path.name}...'))
        result = convert_file(input_path, output_path, extract=extract,
                              reset_timestamps=reset_timestamps)

        if result.error:
            click.echo(cli_error(f'Error: {result.error}'))
            sys.exit(1)
        else:
            click.echo(cli_success(f'Saved {extract} image to {output_path}'))
            click.echo(cli_dim(f'  Time: {result.conversion_time_ms:.0f}ms'))
        return

    if input_path.is_file():
        # Single file conversion
        anon_str = ' + anonymize' if anonymize else ''
        click.echo(cli_info(f'Converting {input_path.name} → {target_format}{anon_str}'))

        result = convert_file(
            input_path, output_path,
            target_format=target_format,
            tile_size=tile_size,
            quality=quality,
            anonymize=anonymize,
            reset_timestamps=reset_timestamps,
        )

        if result.error:
            click.echo(cli_error(f'Error: {result.error}'))
            sys.exit(1)
        else:
            click.echo(cli_success(f'Converted to {output_path}'))
            details = [f'{result.levels_written} level(s)']
            details.append(f'{result.conversion_time_ms / 1000:.1f}s')
            if result.anonymized:
                details.append('anonymized')
            click.echo(cli_dim(f'  {", ".join(details)}'))
    else:
        # Batch conversion
        workers_str = f', {workers} workers' if workers > 1 else ''
        click.echo(cli_info(f'Batch conversion to {target_format}{workers_str}'))
        click.echo(cli_separator())

        t0 = time.time()

        def progress(i, total, filepath, result):
            elapsed = time.time() - t0
            rate = i / elapsed if elapsed > 0 else 0
            eta = (total - i) / rate / 60 if rate > 0 else 0

            counter = cli_dim(f'[{i}/{total}]')
            stats = cli_dim(f'{rate:.1f}/s ETA {eta:.0f}m')

            if result.error:
                status = cli_error(f'ERROR: {result.error}')
            else:
                parts = [f'{result.levels_written} level(s)']
                parts.append(f'{result.conversion_time_ms / 1000:.1f}s')
                if result.anonymized:
                    parts.append('anonymized')
                status = cli_success(', '.join(parts))

            click.echo(f'  {counter} {stats} | {filepath.name} | {status}')

        batch_result = convert_batch(
            input_path, output_path,
            target_format=target_format,
            tile_size=tile_size,
            quality=quality,
            anonymize=anonymize,
            format_filter=fmt,
            progress_callback=progress,
            workers=workers,
            reset_timestamps=reset_timestamps,
        )

        # Summary
        click.echo(cli_separator())
        click.echo(cli_bold(f'Done in {batch_result.total_time_seconds:.1f}s'))
        click.echo(f'  Total:     {cli_bold(str(batch_result.total_files))}')
        if batch_result.files_converted:
            click.echo(f'  Converted: {cli_success(str(batch_result.files_converted))}')
        if batch_result.files_errored:
            click.echo(f'  Errors:    {cli_error(str(batch_result.files_errored))}')

        if batch_result.files_errored > 0:
            sys.exit(1)


@main.command()
@click.argument('path', type=click.Path(exists=True))
def info(path):
    """Show metadata and format information for a WSI file."""
    filepath = Path(path)

    if filepath.is_dir():
        click.echo(cli_error('Error: info command requires a single file, not a directory.'),
                   err=True)
        sys.exit(1)

    fmt = detect_format(filepath)
    handler = get_handler(filepath)
    file_info = handler.get_format_info(filepath)

    click.echo(cli_header(f'File: {filepath.name}'))
    click.echo(f'  Format: {cli_bold(fmt)}')
    click.echo(f'  Size:   {cli_bold(f"{file_info.get("file_size", 0) / 1e6:.1f} MB")}')

    for key, value in file_info.items():
        if key not in ('format', 'filename', 'file_size'):
            click.echo(f'  {key}: {cli_dim(str(value))}')

    # PHI scan result
    click.echo(cli_separator())
    result = handler.scan(filepath)
    if result.is_clean:
        click.echo(f'  PHI Status: {cli_success("CLEAN")}')
    else:
        click.echo(f'  PHI Status: {cli_warning(f"{len(result.findings)} finding(s)")}')
        for f in result.findings:
            click.echo(f'    {cli_finding(friendly_tag_name(f.tag_name))} '
                       f'{cli_dim("at offset")} {f.offset}: '
                       f'{cli_warning(f.value_preview)}')


if __name__ == '__main__':
    main()
