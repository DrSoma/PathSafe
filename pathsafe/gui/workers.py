"""Background worker threads for PathSafe GUI operations."""

import time
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QThread, Signal, QObject

import pathsafe
from pathsafe.anonymizer import anonymize_batch, collect_wsi_files, scan_batch
from pathsafe.formats import detect_format, get_handler
from pathsafe.log import (
    html_dim, html_error, html_finding, html_header, html_info,
    html_separator, html_success, html_summary_line, html_warning,
)
from pathsafe.report import generate_certificate, generate_scan_report, friendly_tag_name
from pathsafe.verify import verify_batch


class WorkerSignals(QObject):
    """Signals for background worker threads."""
    log = Signal(str)
    progress = Signal(float)
    status = Signal(str)
    finished = Signal()
    summary = Signal(dict)  # Summary data for popup at completion


class ScanWorker(QThread):
    """Background thread for scanning files."""

    def __init__(self, input_path, workers, signals, format_filter=None,
                 institution="", output_dir=None, file_list=None):
        super().__init__()
        self.input_path = input_path
        self.workers = workers
        self.signals = signals
        self.format_filter = format_filter
        self.institution = institution
        self.output_dir = output_dir
        self.file_list = file_list
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        try:
            if self.file_list:
                files = list(self.file_list)
            else:
                files = collect_wsi_files(self.input_path,
                                          format_filter=self.format_filter)
            total = len(files)
            if total == 0:
                self.signals.log.emit(html_warning('No WSI files found.'))
                return

            fmt_str = f' [{self.format_filter.upper()}]' if self.format_filter else ''
            self.signals.log.emit(
                html_header(f'PathSafe v{pathsafe.__version__} - PHI Scan'
                            f'{fmt_str}'))
            self.signals.log.emit(
                html_info(f'Scanning {total} file(s)...'))
            self.signals.log.emit(html_separator())

            clean = 0
            phi_count = 0
            error_count = 0
            results_json = []

            def on_result(i, total_files, filepath, result):
                nonlocal clean, phi_count, error_count

                pct = i / total_files * 100
                self.signals.progress.emit(pct)
                self.signals.status.emit(
                    f'Scanning {i}/{total_files}: {filepath.name}')

                # Compute SHA-256 of the scanned file (pre-anonymization)
                sha256 = ''
                try:
                    import hashlib
                    h = hashlib.sha256()
                    with open(filepath, 'rb') as fh:
                        while True:
                            chunk = fh.read(65536)
                            if not chunk:
                                break
                            h.update(chunk)
                    sha256 = h.hexdigest()
                except OSError:
                    pass

                # Collect JSON-serializable result
                entry = {
                    'filepath': str(filepath),
                    'is_clean': result.is_clean,
                    'error': result.error,
                    'sha256': sha256,
                    'findings': [
                        {'tag_name': f.tag_name, 'value_preview': f.value_preview}
                        for f in result.findings
                    ] if result.findings else [],
                }
                results_json.append(entry)

                if result.error:
                    error_count += 1
                    self.signals.log.emit(html_error(
                        f'  [{i}/{total_files}] {filepath.name} - ERROR: {result.error}'))
                elif result.is_clean:
                    clean += 1
                    self.signals.log.emit(html_success(
                        f'  [{i}/{total_files}] {filepath.name} - CLEAN'))
                else:
                    phi_count += len(result.findings)
                    self.signals.log.emit(html_warning(
                        f'  [{i}/{total_files}] {filepath.name} - '
                        f'{len(result.findings)} finding(s):'))
                    for f in result.findings:
                        self.signals.log.emit(html_finding(
                            f'    {friendly_tag_name(f.tag_name)}: {f.value_preview}'))

            scan_batch(self.input_path, progress_callback=on_result,
                       workers=self.workers,
                       format_filter=self.format_filter,
                       stop_check=lambda: self._stop,
                       file_list=self.file_list)

            # Summary
            self.signals.log.emit(html_separator())
            self.signals.log.emit(html_header('Summary'))
            self.signals.log.emit(
                html_summary_line('Total scanned:', total, 'white'))
            if clean:
                self.signals.log.emit(
                    html_summary_line('Clean:', clean, 'green'))
            phi_files = total - clean - error_count
            if phi_files:
                self.signals.log.emit(
                    html_summary_line(
                        'PHI detected:', f'{phi_files} files ({phi_count} findings)',
                        'orange'))
            if error_count:
                self.signals.log.emit(
                    html_summary_line('Errors:', error_count, 'red'))

            if phi_files == 0 and error_count == 0:
                self.signals.log.emit(html_success(
                    'All files are clean - no PHI detected.'))

            # Generate scan report PDF
            scan_report_path = ''
            try:
                scan_data = {
                    'total': total,
                    'clean': clean,
                    'phi_files': phi_files,
                    'phi_findings': phi_count,
                    'errors': error_count,
                    'results': results_json,
                }
                if self.output_dir:
                    report_dir = Path(self.output_dir)
                    report_dir.mkdir(parents=True, exist_ok=True)
                else:
                    report_dir = Path(self.input_path) if Path(self.input_path).is_dir() \
                        else Path(self.input_path).parent
                stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                report_path = report_dir / f'pathsafe_scan_report_{stamp}.pdf'
                generate_scan_report(scan_data, report_path,
                                     institution=self.institution)
                scan_report_path = str(report_path)
                self.signals.log.emit(html_info(
                    f'Scan report saved: {report_path.name}'))
            except Exception as e:
                self.signals.log.emit(html_warning(
                    f'Could not generate scan report PDF: {e}'))

            self.signals.summary.emit({
                'type': 'scan',
                'total': total,
                'clean': clean,
                'phi_files': phi_files,
                'phi_findings': phi_count,
                'errors': error_count,
                'results_json': results_json,
                'scan_report': scan_report_path,
            })
            self.signals.status.emit('Scan complete')
        except Exception as e:
            self.signals.log.emit(html_error(f'ERROR: {e}'))
            self.signals.status.emit(f'Error: {e}')
        finally:
            self.signals.finished.emit()


class AnonymizeWorker(QThread):
    """Background thread for anonymizing files."""

    def __init__(self, input_path, output_dir, verify, workers, signals,
                 reset_timestamps=True,
                 format_filter=None,
                 dry_run=False, verify_integrity=True,
                 institution="", file_list=None):
        super().__init__()
        self.input_path = input_path
        self.output_dir = output_dir
        self.verify = verify
        self.workers = workers
        self.signals = signals
        self.reset_timestamps = reset_timestamps
        self.format_filter = format_filter
        self.institution = institution
        self.dry_run = dry_run
        self.verify_integrity = verify_integrity
        self.file_list = file_list
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        try:
            if self.file_list:
                files = list(self.file_list)
            else:
                files = collect_wsi_files(self.input_path,
                                          format_filter=self.format_filter)
            total = len(files)
            if total == 0:
                self.signals.log.emit(html_warning('No WSI files found.'))
                return

            mode_str = 'DRY RUN' if self.dry_run else (
                'copy' if self.output_dir else 'in-place')
            workers_str = f', {self.workers} workers' if self.workers > 1 else ''
            fmt_str = f' [{self.format_filter.upper()}]' if self.format_filter else ''
            self.signals.log.emit(html_header(
                f'PathSafe v{pathsafe.__version__} - {mode_str} '
                f'anonymization{fmt_str}{workers_str}'))
            self.signals.log.emit(
                html_info(f'Processing {total} file(s)...'))
            if self.dry_run:
                self.signals.log.emit(
                    html_warning('DRY RUN - no files will be modified.'))
            self.signals.log.emit(html_separator())

            t0 = time.time()

            def progress(i, total_files, filepath, result):
                if self._stop:
                    return
                elapsed = time.time() - t0
                rate = i / elapsed if elapsed > 0 else 0
                pct = i / total_files * 100
                self.signals.progress.emit(pct)
                self.signals.status.emit(
                    f'{i}/{total_files} ({rate:.1f}/s) - {filepath.name}')

                if result.error:
                    self.signals.log.emit(html_error(
                        f'  [{i}/{total_files}] {filepath.name} | '
                        f'ERROR: {result.error}'))
                elif result.findings_cleared > 0:
                    verified = ' [verified]' if result.verified else ''
                    self.signals.log.emit(html_warning(
                        f'  [{i}/{total_files}] {filepath.name} | '
                        f'cleared {result.findings_cleared} finding(s)'
                        f'{verified}'))
                else:
                    self.signals.log.emit(html_success(
                        f'  [{i}/{total_files}] {filepath.name} | '
                        f'already clean'))

                # Image integrity result
                if result.image_integrity_verified is True:
                    self.signals.log.emit(html_success(
                        '    Image data integrity: VERIFIED (SHA-256 match)'))
                elif result.image_integrity_verified is False:
                    self.signals.log.emit(html_error(
                        '    Image data integrity: FAILED'))

                # SHA-256 of output file
                if result.sha256_after:
                    self.signals.log.emit(html_dim(
                        f'    SHA-256: {result.sha256_after}'))

                # Filename PHI warning
                if result.filename_has_phi:
                    self.signals.log.emit(html_error(
                        '    WARNING: Filename contains PHI -- rename file manually'))

            batch_result = anonymize_batch(
                self.input_path, output_dir=self.output_dir,
                verify=self.verify, progress_callback=progress,
                workers=self.workers,
                reset_timestamps=self.reset_timestamps,
                dry_run=self.dry_run,
                format_filter=self.format_filter,
                verify_integrity=self.verify_integrity,
                stop_check=lambda: self._stop,
                file_list=self.file_list,
            )

            cert_path = None

            # Generate certificate (skip in dry-run mode)
            if not self.dry_run:
                if self.output_dir:
                    cert_path = self.output_dir / 'pathsafe_certificate.json'
                elif self.input_path.is_dir():
                    cert_path = self.input_path / 'pathsafe_certificate.json'
                else:
                    cert_path = self.input_path.parent / 'pathsafe_certificate.json'

                generate_certificate(
                    batch_result, output_path=cert_path,
                    timestamps_reset=self.reset_timestamps,
                    institution=self.institution,
                )

            # Summary
            self.signals.log.emit(html_separator())
            self.signals.log.emit(html_header(
                f'Done in {batch_result.total_time_seconds:.1f}s'))
            self.signals.log.emit(
                html_summary_line('Total:', batch_result.total_files, 'white'))
            if batch_result.files_anonymized:
                self.signals.log.emit(
                    html_summary_line('Anonymized:',
                                      batch_result.files_anonymized, 'orange'))
            if batch_result.files_already_clean:
                self.signals.log.emit(
                    html_summary_line('Already clean:',
                                      batch_result.files_already_clean, 'green'))
            if batch_result.files_errored:
                self.signals.log.emit(
                    html_summary_line('Errors:',
                                      batch_result.files_errored, 'red'))
            pdf_cert_path = None
            if cert_path:
                pdf_cert_path = cert_path.with_suffix('.pdf')
                self.signals.log.emit(
                    html_info(f'Certificate: {cert_path}'))
                self.signals.log.emit(
                    html_info(f'PDF certificate: {pdf_cert_path}'))
            if self.dry_run:
                self.signals.log.emit(
                    html_warning('DRY RUN - no files were modified.'))

            # Count integrity results
            integrity_verified = sum(
                1 for r in batch_result.results
                if r.image_integrity_verified is True)
            integrity_failed = sum(
                1 for r in batch_result.results
                if r.image_integrity_verified is False)
            phi_filenames = sum(
                1 for r in batch_result.results
                if r.filename_has_phi)

            # Log filename PHI warning in summary
            if phi_filenames:
                self.signals.log.emit(html_error(
                    f'WARNING: {phi_filenames} file(s) have PHI in their '
                    f'filename -- rename manually'))

            self.signals.summary.emit({
                'type': 'anonymize',
                'total': batch_result.total_files,
                'anonymized': batch_result.files_anonymized,
                'already_clean': batch_result.files_already_clean,
                'errors': batch_result.files_errored,
                'time': f'{batch_result.total_time_seconds:.1f}s',
                'certificate': str(cert_path) if cert_path else '',
                'pdf_certificate': str(pdf_cert_path) if pdf_cert_path else '',
                'output_dir': str(self.output_dir) if self.output_dir else '',
                'timestamps_reset': self.reset_timestamps,
                'dry_run': self.dry_run,
                'integrity_verified': integrity_verified,
                'integrity_failed': integrity_failed,
                'phi_filenames': phi_filenames,
                'output_paths': [
                    str(r.output_path) for r in batch_result.results
                    if not r.error
                ],
            })
            if batch_result.files_errored == 0:
                self.signals.status.emit('Anonymization complete')
            else:
                self.signals.status.emit(
                    f'Done with {batch_result.files_errored} error(s)')
        except Exception as e:
            self.signals.log.emit(html_error(f'ERROR: {e}'))
            self.signals.status.emit(f'Error: {e}')
        finally:
            self.signals.finished.emit()


class VerifyWorker(QThread):
    """Background thread for verifying files."""

    def __init__(self, input_path, signals, format_filter=None,
                 file_list=None):
        super().__init__()
        self.input_path = input_path
        self.signals = signals
        self.format_filter = format_filter
        self.file_list = file_list  # specific files to verify (from last anonymize)

    def run(self):
        try:
            if self.file_list:
                # Verify only the specific files from the last anonymize run
                files = [Path(p) for p in self.file_list if Path(p).exists()]
            else:
                files = collect_wsi_files(self.input_path,
                                          format_filter=self.format_filter)
            total = len(files)
            if total == 0:
                self.signals.log.emit(html_warning('No WSI files found.'))
                return

            fmt_str = f' [{self.format_filter.upper()}]' if self.format_filter else ''
            self.signals.log.emit(
                html_header(f'PathSafe v{pathsafe.__version__} - Verification'
                            f'{fmt_str}'))
            self.signals.log.emit(
                html_info(f'Verifying {total} file(s)...'))
            self.signals.log.emit(html_separator())

            clean = 0
            dirty = 0

            if self.file_list:
                # Verify individual files directly
                for i, filepath in enumerate(files):
                    handler = get_handler(filepath)
                    result = handler.scan(filepath)
                    pct = (i + 1) / total * 100
                    self.signals.progress.emit(pct)
                    self.signals.status.emit(
                        f'Verifying {i + 1}/{total}: {filepath.name}')
                    if result.is_clean:
                        clean += 1
                    else:
                        dirty += 1
                        findings_str = ', '.join(
                            f.tag_name for f in result.findings)
                        self.signals.log.emit(html_error(
                            f'  PHI FOUND: {filepath.name} - '
                            f'{findings_str}'))
            else:
                def progress(i, total_files, filepath, result):
                    pct = i / total_files * 100
                    self.signals.progress.emit(pct)
                    self.signals.status.emit(
                        f'Verifying {i}/{total_files}: {filepath.name}')

                results = verify_batch(
                    self.input_path, progress_callback=progress,
                    format_filter=self.format_filter)

                for result in results:
                    if result.is_clean:
                        clean += 1
                    else:
                        dirty += 1
                        findings_str = ', '.join(
                            f.tag_name for f in result.findings)
                        self.signals.log.emit(html_error(
                            f'  PHI FOUND: {result.filepath.name} - '
                            f'{findings_str}'))

            # Summary
            self.signals.log.emit(html_separator())
            self.signals.log.emit(html_header('Verification Results'))
            if clean:
                self.signals.log.emit(
                    html_summary_line('Clean:', clean, 'green'))
            if dirty:
                self.signals.log.emit(
                    html_summary_line('PHI remaining:', dirty, 'red'))

            self.signals.summary.emit({
                'type': 'verify',
                'total': total,
                'clean': clean,
                'dirty': dirty,
            })
            if dirty == 0:
                self.signals.log.emit(
                    html_success('All files verified clean.'))
                self.signals.status.emit(
                    'Verification passed - all files clean')
            else:
                self.signals.log.emit(
                    html_error('WARNING: Some files still contain PHI!'))
                self.signals.status.emit(
                    f'WARNING: {dirty} file(s) with remaining PHI')
        except Exception as e:
            self.signals.log.emit(html_error(f'ERROR: {e}'))
            self.signals.status.emit(f'Error: {e}')
        finally:
            self.signals.finished.emit()


class InfoWorker(QThread):
    """Background thread for retrieving file information."""

    def __init__(self, filepath, signals):
        super().__init__()
        self.filepath = filepath
        self.signals = signals

    def run(self):
        try:
            self.signals.log.emit(
                html_header(f'PathSafe v{pathsafe.__version__} - File Info'))
            self.signals.log.emit(
                html_info(f'File: {self.filepath.name}'))
            self.signals.log.emit(html_separator())

            fmt = detect_format(self.filepath)
            handler = get_handler(self.filepath)
            file_info = handler.get_format_info(self.filepath)
            scan_result = handler.scan(self.filepath)

            file_size = self.filepath.stat().st_size
            if file_size >= 1_073_741_824:
                size_str = f'{file_size / 1_073_741_824:.2f} GB'
            elif file_size >= 1_048_576:
                size_str = f'{file_size / 1_048_576:.1f} MB'
            elif file_size >= 1024:
                size_str = f'{file_size / 1024:.1f} KB'
            else:
                size_str = f'{file_size} bytes'

            metadata_count = len(file_info) if isinstance(file_info, dict) else 0

            self.signals.log.emit(
                html_summary_line('Format:', fmt.upper(), 'white'))
            self.signals.log.emit(
                html_summary_line('File size:', size_str, 'white'))
            self.signals.log.emit(
                html_summary_line('Metadata entries:', metadata_count, 'white'))

            if isinstance(file_info, dict):
                for key, value in file_info.items():
                    val_str = str(value)
                    if len(val_str) > 120:
                        val_str = val_str[:120] + '...'
                    self.signals.log.emit(html_dim(f'  {key}: {val_str}'))

            self.signals.log.emit(html_separator())

            if scan_result.is_clean:
                phi_status = 'Clean - no PHI detected'
                self.signals.log.emit(
                    html_success(f'PHI Status: {phi_status}'))
            else:
                phi_status = f'{len(scan_result.findings)} finding(s)'
                self.signals.log.emit(
                    html_warning(f'PHI Status: {phi_status}'))
                for f in scan_result.findings:
                    self.signals.log.emit(html_finding(
                        f'  {f.tag_name}: {f.value_preview}'))

            self.signals.summary.emit({
                'type': 'info',
                'format': fmt.upper(),
                'size': size_str,
                'metadata_count': metadata_count,
                'phi_status': phi_status,
            })
            self.signals.status.emit('File info complete')
        except Exception as e:
            self.signals.log.emit(html_error(f'ERROR: {e}'))
            self.signals.status.emit(f'Error: {e}')
        finally:
            self.signals.finished.emit()


class ConvertWorker(QThread):
    """Background thread for converting files."""

    def __init__(self, input_path, output_path, target_format, extract,
                 tile_size, quality, anonymize_after, reset_timestamps,
                 workers, format_filter, signals):
        super().__init__()
        self.input_path = input_path
        self.output_path = output_path
        self.target_format = target_format
        self.extract = extract
        self.tile_size = tile_size
        self.quality = quality
        self.anonymize_after = anonymize_after
        self.reset_timestamps = reset_timestamps
        self.workers = workers
        self.format_filter = format_filter
        self.signals = signals
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        try:
            try:
                from pathsafe.converter import convert_file, convert_batch
            except ImportError:
                self.signals.log.emit(html_error(
                    'Conversion requires openslide, tifffile, and numpy. '
                    'Install with: pip install pathsafe[convert]'))
                return

            if self.extract and self.input_path.is_dir():
                self.signals.log.emit(html_error(
                    'Extract mode (label/macro/thumbnail) is only supported '
                    'for single files, not directories.'))
                return

            t0 = time.time()

            if self.input_path.is_file():
                self.signals.log.emit(html_header(
                    f'PathSafe v{pathsafe.__version__} - File Conversion'))
                self.signals.log.emit(html_info(
                    f'Converting: {self.input_path.name}'))
                self.signals.log.emit(html_separator())

                result = convert_file(
                    self.input_path, self.output_path,
                    target_format=self.target_format,
                    tile_size=self.tile_size,
                    quality=self.quality,
                    extract=self.extract,
                    anonymize=self.anonymize_after,
                    reset_timestamps=self.reset_timestamps,
                )

                elapsed = time.time() - t0

                if result.error:
                    self.signals.log.emit(html_error(
                        f'  {self.input_path.name} - ERROR: {result.error}'))
                    self.signals.summary.emit({
                        'type': 'convert',
                        'total': 1,
                        'converted': 0,
                        'errors': 1,
                        'time': f'{elapsed:.1f}s',
                    })
                else:
                    self.signals.log.emit(html_success(
                        f'  {self.input_path.name} - converted successfully'))
                    self.signals.progress.emit(100)
                    self.signals.summary.emit({
                        'type': 'convert',
                        'total': 1,
                        'converted': 1,
                        'errors': 0,
                        'time': f'{elapsed:.1f}s',
                    })

                self.signals.status.emit('Conversion complete')

            else:
                # Directory batch conversion
                workers_str = (f', {self.workers} workers'
                               if self.workers > 1 else '')
                fmt_str = (f' [{self.format_filter.upper()}]'
                           if self.format_filter else '')
                self.signals.log.emit(html_header(
                    f'PathSafe v{pathsafe.__version__} - Batch Conversion'
                    f'{fmt_str}{workers_str}'))

                files = collect_wsi_files(self.input_path,
                                          format_filter=self.format_filter)
                total = len(files)
                if total == 0:
                    self.signals.log.emit(
                        html_warning('No WSI files found.'))
                    return

                self.signals.log.emit(html_info(
                    f'Converting {total} file(s)...'))
                self.signals.log.emit(html_separator())

                converted_count = 0
                error_count = 0

                def on_progress(i, total_files, filepath, result):
                    nonlocal converted_count, error_count
                    pct = i / total_files * 100
                    self.signals.progress.emit(pct)
                    self.signals.status.emit(
                        f'Converting {i}/{total_files}: {filepath.name}')

                    if result.error:
                        error_count += 1
                        self.signals.log.emit(html_error(
                            f'  [{i}/{total_files}] {filepath.name} - '
                            f'ERROR: {result.error}'))
                    else:
                        converted_count += 1
                        self.signals.log.emit(html_success(
                            f'  [{i}/{total_files}] {filepath.name} - '
                            f'converted'))

                convert_batch(
                    self.input_path, self.output_path,
                    target_format=self.target_format,
                    tile_size=self.tile_size,
                    quality=self.quality,
                    anonymize=self.anonymize_after,
                    format_filter=self.format_filter,
                    progress_callback=on_progress,
                    workers=self.workers,
                    reset_timestamps=self.reset_timestamps,
                )

                elapsed = time.time() - t0

                self.signals.log.emit(html_separator())
                self.signals.log.emit(html_header(
                    f'Done in {elapsed:.1f}s'))

                self.signals.summary.emit({
                    'type': 'convert',
                    'total': total,
                    'converted': converted_count,
                    'errors': error_count,
                    'time': f'{elapsed:.1f}s',
                })
                self.signals.status.emit('Conversion complete')

        except Exception as e:
            self.signals.log.emit(html_error(f'ERROR: {e}'))
            self.signals.status.emit(f'Error: {e}')
        finally:
            self.signals.finished.emit()
