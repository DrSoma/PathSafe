"""Verification -- re-scan anonymized files to confirm all PHI cleared."""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path

from pathsafe.anonymizer import collect_wsi_files
from pathsafe.formats import get_handler
from pathsafe.models import ScanResult
from pathsafe.utils import _sanitize_error


def verify_file(filepath: Path) -> ScanResult:
    """Verify that a file has been fully anonymized.

    Re-scans the file for PHI. Returns ScanResult where is_clean=True
    means no PHI was found.
    """
    filepath = Path(filepath)
    handler = get_handler(filepath)
    return handler.scan(filepath)


def verify_batch(
    path: Path,
    format_filter: str | None = None,
    progress_callback: Callable[[int, int, Path, ScanResult], None] | None = None,
) -> list[ScanResult]:
    """Verify a batch of files are clean.

    Args:
        path: File or directory to verify.
        format_filter: Only verify files of this format.
        progress_callback: Called with (index, total, filepath, result) after each file.

    Returns:
        List of ScanResult objects.
    """
    files = collect_wsi_files(Path(path), format_filter)
    total = len(files)
    results = []

    for i, filepath in enumerate(files):
        try:
            result = verify_file(filepath)
        except Exception as e:
            result = ScanResult(
                filepath=filepath,
                format="unknown",
                is_clean=False,
                file_size=os.path.getsize(filepath),
                error=_sanitize_error(e),
            )
        results.append(result)

        if progress_callback:
            progress_callback(i + 1, total, filepath, result)

    return results
