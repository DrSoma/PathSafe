"""JSON compliance certificate and anonymization assessment generation."""

import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

import pathsafe
from pathsafe.models import BatchResult


def _sha256_file(filepath: Path) -> str:
    """Compute SHA-256 hash of a file."""
    h = hashlib.sha256()
    with open(filepath, 'rb') as f:
        while True:
            chunk = f.read(65536)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def generate_certificate(
    batch_result: BatchResult,
    output_path: Optional[Path] = None,
) -> dict:
    """Generate a JSON compliance certificate for a batch anonymization run.

    Args:
        batch_result: The BatchResult from anonymize_batch().
        output_path: If provided, write the certificate JSON to this file.

    Returns:
        The certificate as a dict.
    """
    # Determine mode from results
    mode = "unknown"
    if batch_result.results:
        mode = batch_result.results[0].mode

    # Build per-file records
    file_records = []
    verified_count = 0
    for result in batch_result.results:
        record = {
            'filename': result.output_path.name,
            'source_path': str(result.source_path),
            'output_path': str(result.output_path),
            'format': _detect_format_from_ext(result.output_path),
            'findings_cleared': result.findings_cleared,
            'verified_clean': result.verified,
            'anonymization_time_ms': round(result.anonymization_time_ms, 1),
        }

        if result.image_integrity_verified is not None:
            record['image_integrity_verified'] = result.image_integrity_verified

        if result.error:
            record['error'] = result.error
        else:
            # Compute hash of output file if it exists
            try:
                record['sha256_after'] = _sha256_file(result.output_path)
            except (OSError, FileNotFoundError):
                pass

        if result.verified:
            verified_count += 1

        file_records.append(record)

    certificate = {
        'pathsafe_version': pathsafe.__version__,
        'certificate_id': str(uuid.uuid4()),
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'mode': mode,
        'summary': {
            'total_files': batch_result.total_files,
            'anonymized': batch_result.files_anonymized,
            'already_clean': batch_result.files_already_clean,
            'errors': batch_result.files_errored,
            'verified': verified_count == len(batch_result.results) and verified_count > 0,
            'total_time_seconds': round(batch_result.total_time_seconds, 2),
        },
        'files': file_records,
    }

    if output_path is not None:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, 'w') as f:
            json.dump(certificate, f, indent=2)

    return certificate


def generate_checklist(
    batch_result: BatchResult,
    output_path: Optional[Path] = None,
    timestamps_reset: bool = False,
) -> dict:
    """Generate an anonymization assessment checklist.

    Combines auto-filled technical measures (based on what PathSafe did)
    with procedural measures for the institution to complete.

    Args:
        batch_result: The BatchResult from anonymize_batch().
        output_path: If provided, write the checklist JSON to this file.
        timestamps_reset: Whether --reset-timestamps was used.

    Returns:
        The checklist as a dict.
    """
    # Compute technical measures from batch results
    total_findings = sum(r.findings_cleared for r in batch_result.results)
    verified_count = sum(1 for r in batch_result.results if r.verified)
    error_count = batch_result.files_errored

    # Image integrity stats
    integrity_verified = sum(1 for r in batch_result.results
                             if r.image_integrity_verified is True)
    integrity_failed = sum(1 for r in batch_result.results
                           if r.image_integrity_verified is False)
    integrity_checked = integrity_verified + integrity_failed

    # Collect SHA-256 hashes for output files
    hashes = []
    for result in batch_result.results:
        if not result.error:
            try:
                hashes.append({
                    'file': result.output_path.name,
                    'sha256': _sha256_file(result.output_path),
                })
            except (OSError, FileNotFoundError):
                pass

    technical_measures = [
        {
            'measure': 'Metadata tags cleared',
            'status': 'applied' if total_findings > 0 else 'not_needed',
            'details': f'{total_findings} finding(s) cleared across {batch_result.files_anonymized} file(s)',
        },
        {
            'measure': 'Label/macro images blanked',
            'status': 'applied' if total_findings > 0 else 'not_needed',
            'details': 'Included in metadata tag clearing',
        },
        {
            'measure': 'Filename PHI detection',
            'status': 'applied',
            'details': f'{batch_result.total_files} file(s) scanned for PHI in filenames',
        },
        {
            'measure': 'Post-anonymization verification',
            'status': 'passed' if verified_count == len(batch_result.results) and verified_count > 0 else 'skipped',
            'details': f'{verified_count}/{len(batch_result.results)} file(s) verified clean',
        },
        {
            'measure': 'Image data integrity verification',
            'status': 'passed' if integrity_checked > 0 and integrity_failed == 0
                      else ('failed' if integrity_failed > 0 else 'not_applied'),
            'details': (f'SHA-256 checksums of image tile data verified matching '
                        f'before and after anonymization for {integrity_verified} file(s)')
                       if integrity_checked > 0
                       else 'Use --verify-integrity to enable tile data integrity checking',
        },
        {
            'measure': 'Filesystem timestamps reset',
            'status': 'applied' if timestamps_reset else 'not_applied',
            'details': 'Access and modification times set to epoch (1970-01-01)' if timestamps_reset
                       else 'Use --reset-timestamps to remove temporal metadata',
        },
        {
            'measure': 'SHA-256 hashes recorded',
            'status': 'recorded' if hashes else 'skipped',
            'details': f'{len(hashes)} hash(es) computed',
            'hashes': hashes,
        },
    ]

    checklist = {
        'pathsafe_version': pathsafe.__version__,
        'checklist_id': str(uuid.uuid4()),
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'summary': {
            'total_files': batch_result.total_files,
            'files_anonymized': batch_result.files_anonymized,
            'files_with_errors': error_count,
        },
        'technical_measures': technical_measures,
    }

    if output_path is not None:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, 'w') as f:
            json.dump(checklist, f, indent=2)

    return checklist


def _detect_format_from_ext(filepath: Path) -> str:
    """Simple format detection from extension for certificate records."""
    ext = filepath.suffix.lower()
    return {'.ndpi': 'ndpi', '.svs': 'svs', '.tif': 'tiff', '.tiff': 'tiff'}.get(ext, 'unknown')
