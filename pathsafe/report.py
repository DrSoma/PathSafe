"""JSON compliance certificate generation."""

import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

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


def _detect_format_from_ext(filepath: Path) -> str:
    """Simple format detection from extension for certificate records."""
    ext = filepath.suffix.lower()
    return {'.ndpi': 'ndpi', '.svs': 'svs', '.tif': 'tiff', '.tiff': 'tiff'}.get(ext, 'unknown')
