"""CLI interface for PathSafe — scan, anonymize, verify, info subcommands."""

import json
import sys
import time
from pathlib import Path

import click

import pathsafe
from pathsafe.anonymizer import anonymize_batch, anonymize_file, collect_wsi_files
from pathsafe.formats import detect_format, get_handler
from pathsafe.report import generate_certificate
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
@click.option('--format', 'fmt', type=click.Choice(['ndpi', 'svs', 'mrxs', 'dicom', 'tiff']),
              help='Only scan files of this format.')
@click.option('--json-out', type=click.Path(), help='Write results as JSON to file.')
def scan(path, verbose, fmt, json_out):
    """Scan files for PHI (read-only).

    PATH can be a single file or a directory to scan recursively.
    """
    input_path = Path(path)
    files = collect_wsi_files(input_path, format_filter=fmt)

    if not files:
        click.echo(f'No WSI files found in {input_path}')
        return

    click.echo(f'Scanning {len(files)} file(s)...')

    total_findings = 0
    clean_count = 0
    results_json = []

    for i, filepath in enumerate(files, 1):
        handler = get_handler(filepath)
        result = handler.scan(filepath)

        if result.is_clean:
            clean_count += 1
            if verbose:
                click.echo(f'  [{i}/{len(files)}] {filepath.name} — CLEAN')
        else:
            total_findings += len(result.findings)
            click.echo(f'  [{i}/{len(files)}] {filepath.name} — '
                       f'{len(result.findings)} finding(s)')
            if verbose:
                for f in result.findings:
                    click.echo(f'    {f.tag_name} at offset {f.offset}: '
                               f'{f.value_preview}')

        if result.error:
            click.echo(f'    WARNING: {result.error}')

        if json_out:
            results_json.append({
                'file': str(filepath),
                'format': result.format,
                'is_clean': result.is_clean,
                'findings': len(result.findings),
                'scan_time_ms': round(result.scan_time_ms, 1),
                'error': result.error,
            })

    click.echo(f'\nSummary: {len(files)} files scanned, '
               f'{clean_count} clean, '
               f'{len(files) - clean_count} with PHI '
               f'({total_findings} total findings)')

    if json_out:
        with open(json_out, 'w') as f:
            json.dump(results_json, f, indent=2)
        click.echo(f'Results written to {json_out}')


@main.command()
@click.argument('path', type=click.Path(exists=True))
@click.option('--output', '-o', type=click.Path(),
              help='Output directory (copy mode). If omitted, anonymizes in-place.')
@click.option('--in-place', is_flag=True,
              help='Explicitly confirm in-place anonymization (required if no --output).')
@click.option('--dry-run', is_flag=True, help='Scan only, don\'t modify files.')
@click.option('--no-verify', is_flag=True, help='Skip post-anonymization verification.')
@click.option('--format', 'fmt', type=click.Choice(['ndpi', 'svs', 'mrxs', 'dicom', 'tiff']),
              help='Only process files of this format.')
@click.option('--certificate', '-c', type=click.Path(),
              help='Write compliance certificate JSON to this path.')
@click.option('--verbose', '-v', is_flag=True, help='Show detailed progress.')
@click.option('--workers', '-w', type=int, default=1,
              help='Number of parallel workers (default: 1, sequential).')
@click.option('--log', type=click.Path(), help='Write log to file.')
def anonymize(path, output, in_place, dry_run, no_verify, fmt, certificate, verbose, workers, log):
    """Anonymize PHI in WSI files.

    PATH can be a single file or a directory to process recursively.

    By default, uses copy mode (--output required). Use --in-place to
    modify original files directly.
    """
    input_path = Path(path)
    output_dir = Path(output) if output else None

    # Safety check: require explicit flag for in-place
    if output_dir is None and not in_place and not dry_run:
        click.echo('Error: Must specify --output for copy mode, or --in-place '
                    'to modify originals directly.', err=True)
        sys.exit(1)

    log_file = open(log, 'w') if log else None

    def log_msg(msg):
        click.echo(msg)
        if log_file:
            log_file.write(msg + '\n')
            log_file.flush()

    files = collect_wsi_files(input_path, format_filter=fmt)
    if not files:
        log_msg(f'No WSI files found in {input_path}')
        return

    mode_str = 'DRY RUN' if dry_run else ('copy' if output_dir else 'in-place')
    workers_str = f', {workers} workers' if workers > 1 else ''
    log_msg(f'PathSafe v{pathsafe.__version__} — {mode_str} anonymization{workers_str}')
    log_msg(f'Processing {len(files)} file(s)...\n')

    t0 = time.time()

    def progress(i, total, filepath, result):
        elapsed = time.time() - t0
        rate = i / elapsed if elapsed > 0 else 0
        eta = (total - i) / rate / 60 if rate > 0 else 0

        if result.error:
            status = f'ERROR: {result.error}'
        elif result.findings_cleared > 0:
            status = f'cleared {result.findings_cleared} finding(s)'
            if result.verified:
                status += ' [verified]'
        else:
            status = 'already clean'

        msg = (f'  [{i}/{total}] {rate:.1f}/s ETA {eta:.0f}m | '
               f'{filepath.name} | {status}')
        log_msg(msg)

    batch_result = anonymize_batch(
        input_path, output_dir=output_dir,
        verify=not no_verify, dry_run=dry_run,
        format_filter=fmt, progress_callback=progress,
        workers=workers,
    )

    # Summary
    log_msg(f'\nDone in {batch_result.total_time_seconds:.1f}s')
    log_msg(f'  Total:         {batch_result.total_files}')
    log_msg(f'  Anonymized:    {batch_result.files_anonymized}')
    log_msg(f'  Already clean: {batch_result.files_already_clean}')
    log_msg(f'  Errors:        {batch_result.files_errored}')

    # Generate certificate
    if certificate and not dry_run:
        cert = generate_certificate(batch_result, output_path=Path(certificate))
        batch_result.certificate_path = Path(certificate)
        log_msg(f'\nCompliance certificate: {certificate}')

    if log_file:
        log_file.close()

    if batch_result.files_errored > 0:
        sys.exit(1)


@main.command()
@click.argument('path', type=click.Path(exists=True))
@click.option('--verbose', '-v', is_flag=True, help='Show detailed findings.')
@click.option('--format', 'fmt', type=click.Choice(['ndpi', 'svs', 'mrxs', 'dicom', 'tiff']),
              help='Only verify files of this format.')
def verify(path, verbose, fmt):
    """Verify that files have been fully anonymized.

    Re-scans all files to confirm no PHI remains.
    """
    input_path = Path(path)
    files = collect_wsi_files(input_path, format_filter=fmt)

    if not files:
        click.echo(f'No WSI files found in {input_path}')
        return

    click.echo(f'Verifying {len(files)} file(s)...')

    clean_count = 0
    dirty_count = 0

    def progress(i, total, filepath, result):
        nonlocal clean_count, dirty_count
        if result.is_clean:
            clean_count += 1
            if verbose:
                click.echo(f'  [{i}/{total}] {filepath.name} — CLEAN')
        else:
            dirty_count += 1
            click.echo(f'  [{i}/{total}] {filepath.name} — '
                       f'PHI FOUND ({len(result.findings)} finding(s))')
            if verbose:
                for f in result.findings:
                    click.echo(f'    {f.tag_name}: {f.value_preview}')

    verify_batch(input_path, format_filter=fmt, progress_callback=progress)

    click.echo(f'\nVerification: {clean_count} clean, {dirty_count} with remaining PHI')
    if dirty_count > 0:
        click.echo('WARNING: Some files still contain PHI!')
        sys.exit(1)
    else:
        click.echo('All files verified clean.')


@main.command()
def gui():
    """Launch the graphical user interface."""
    try:
        from pathsafe.gui_qt import main as gui_main
    except ImportError:
        from pathsafe.gui import main as gui_main
    gui_main()


@main.command()
@click.argument('path', type=click.Path(exists=True))
def info(path):
    """Show metadata and format information for a WSI file."""
    filepath = Path(path)

    if filepath.is_dir():
        click.echo('Error: info command requires a single file, not a directory.', err=True)
        sys.exit(1)

    fmt = detect_format(filepath)
    handler = get_handler(filepath)
    file_info = handler.get_format_info(filepath)

    click.echo(f'File: {filepath.name}')
    click.echo(f'Format: {fmt}')
    click.echo(f'Size: {file_info.get("file_size", 0) / 1e6:.1f} MB')

    for key, value in file_info.items():
        if key not in ('format', 'filename', 'file_size'):
            click.echo(f'{key}: {value}')

    # Also show PHI scan result
    result = handler.scan(filepath)
    if result.is_clean:
        click.echo('\nPHI Status: CLEAN')
    else:
        click.echo(f'\nPHI Status: {len(result.findings)} finding(s)')
        for f in result.findings:
            click.echo(f'  {f.tag_name} at offset {f.offset}: {f.value_preview}')


if __name__ == '__main__':
    main()
