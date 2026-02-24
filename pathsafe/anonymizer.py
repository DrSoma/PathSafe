"""Core anonymization logic — copy-then-anonymize, in-place, and batch processing.

Supports both sequential and parallel (thread pool) batch processing.
"""

import os
import shutil
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable, List, Optional

from pathsafe.formats import detect_format, get_handler
from pathsafe.models import AnonymizationResult, BatchResult

# File extensions considered for batch processing
WSI_EXTENSIONS = {'.ndpi', '.svs', '.tif', '.tiff', '.scn', '.bif',
                   '.mrxs', '.dcm', '.dicom'}

# Default number of parallel workers
DEFAULT_WORKERS = 4


def anonymize_file(
    filepath: Path,
    output_path: Optional[Path] = None,
    verify: bool = True,
    dry_run: bool = False,
) -> AnonymizationResult:
    """Anonymize a single WSI file.

    Args:
        filepath: Path to the source file.
        output_path: If provided, copy file here first (copy mode).
                     If None, anonymize in-place.
        verify: If True, re-scan after anonymization to confirm all PHI cleared.
        dry_run: If True, only scan — don't modify anything.

    Returns:
        AnonymizationResult with details of what was done.
    """
    filepath = Path(filepath)
    t0 = time.monotonic()

    if not filepath.exists():
        return AnonymizationResult(
            source_path=filepath,
            output_path=output_path or filepath,
            mode="copy" if output_path else "inplace",
            error=f"File not found: {filepath}",
        )

    handler = get_handler(filepath)

    # Determine mode and target
    if output_path is not None:
        mode = "copy"
        target = Path(output_path)
    else:
        mode = "inplace"
        target = filepath

    if dry_run:
        # Just scan, report what would be done
        scan_result = handler.scan(filepath)
        elapsed = (time.monotonic() - t0) * 1000
        return AnonymizationResult(
            source_path=filepath,
            output_path=target,
            mode=mode,
            findings_cleared=len(scan_result.findings),
            verified=False,
            anonymization_time_ms=elapsed,
        )

    # Copy mode: copy file to output path first
    if mode == "copy":
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(filepath), str(target))
        # MRXS: also copy companion data directory (slide/ next to slide.mrxs)
        companion_dir = filepath.parent / filepath.stem
        if companion_dir.is_dir():
            target_companion = target.parent / target.stem
            if not target_companion.exists():
                shutil.copytree(str(companion_dir), str(target_companion))

    # Anonymize
    try:
        findings = handler.anonymize(target)
    except Exception as e:
        elapsed = (time.monotonic() - t0) * 1000
        return AnonymizationResult(
            source_path=filepath, output_path=target, mode=mode,
            anonymization_time_ms=elapsed, error=str(e),
        )

    # Verify
    verified = False
    if verify and findings:
        from pathsafe.verify import verify_file
        verify_result = verify_file(target)
        verified = verify_result.is_clean

    elapsed = (time.monotonic() - t0) * 1000
    return AnonymizationResult(
        source_path=filepath, output_path=target, mode=mode,
        findings_cleared=len(findings), verified=verified,
        anonymization_time_ms=elapsed,
    )


def collect_wsi_files(path: Path, format_filter: Optional[str] = None) -> List[Path]:
    """Collect all WSI files from a path (file or directory).

    Args:
        path: File or directory to search.
        format_filter: If set, only collect files of this format ("ndpi", "svs", etc).
    """
    if path.is_file():
        return [path]

    extensions = WSI_EXTENSIONS
    if format_filter:
        ext_map = {
            'ndpi': {'.ndpi'}, 'svs': {'.svs'}, 'tiff': {'.tif', '.tiff'},
            'mrxs': {'.mrxs'}, 'dicom': {'.dcm', '.dicom'},
        }
        extensions = ext_map.get(format_filter, WSI_EXTENSIONS)

    files = []
    for root, _, filenames in os.walk(path):
        for fname in sorted(filenames):
            if Path(fname).suffix.lower() in extensions:
                files.append(Path(root) / fname)
    files.sort()
    return files


def anonymize_batch(
    input_path: Path,
    output_dir: Optional[Path] = None,
    verify: bool = True,
    dry_run: bool = False,
    format_filter: Optional[str] = None,
    progress_callback: Optional[Callable] = None,
    workers: int = 1,
) -> BatchResult:
    """Anonymize a batch of WSI files.

    Args:
        input_path: File or directory containing WSI files.
        output_dir: If provided, copy files here (copy mode).
        verify: Re-scan after anonymization.
        dry_run: Scan only, don't modify.
        format_filter: Only process files of this format.
        progress_callback: Called with (index, total, filepath, result) after each file.
        workers: Number of parallel workers. 1 = sequential (default).

    Returns:
        BatchResult with summary statistics.
    """
    input_path = Path(input_path)
    t0 = time.monotonic()

    files = collect_wsi_files(input_path, format_filter)
    total = len(files)

    batch = BatchResult(total_files=total)

    # Build list of (filepath, output_path) pairs
    file_pairs = []
    for filepath in files:
        if output_dir is not None:
            relative = filepath.relative_to(input_path) if input_path.is_dir() else filepath.name
            out = Path(output_dir) / relative
        else:
            out = None
        file_pairs.append((filepath, out))

    if workers > 1 and total > 1:
        results = _batch_parallel(file_pairs, verify, dry_run, workers,
                                  progress_callback, batch)
    else:
        results = _batch_sequential(file_pairs, verify, dry_run,
                                    progress_callback, batch)

    batch.results = results
    batch.total_time_seconds = time.monotonic() - t0
    return batch


def _batch_sequential(
    file_pairs: List,
    verify: bool,
    dry_run: bool,
    progress_callback: Optional[Callable],
    batch: BatchResult,
) -> List[AnonymizationResult]:
    """Process files sequentially."""
    results = []
    total = len(file_pairs)

    for i, (filepath, out) in enumerate(file_pairs):
        try:
            result = anonymize_file(filepath, output_path=out, verify=verify,
                                    dry_run=dry_run)
        except Exception as e:
            result = AnonymizationResult(
                source_path=filepath,
                output_path=out or filepath,
                mode="copy" if out else "inplace",
                error=str(e),
            )

        results.append(result)
        _update_batch_stats(batch, result)

        if progress_callback:
            progress_callback(i + 1, total, filepath, result)

    return results


def _batch_parallel(
    file_pairs: List,
    verify: bool,
    dry_run: bool,
    workers: int,
    progress_callback: Optional[Callable],
    batch: BatchResult,
) -> List[AnonymizationResult]:
    """Process files in parallel using a thread pool.

    Files are processed concurrently but results are collected in
    submission order for deterministic output.
    """
    total = len(file_pairs)
    # Pre-allocate results list to maintain order
    results = [None] * total
    lock = threading.Lock()
    completed_count = [0]  # mutable counter for closure

    def process_one(index, filepath, out):
        try:
            return index, anonymize_file(filepath, output_path=out,
                                         verify=verify, dry_run=dry_run)
        except Exception as e:
            return index, AnonymizationResult(
                source_path=filepath,
                output_path=out or filepath,
                mode="copy" if out else "inplace",
                error=str(e),
            )

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {}
        for i, (filepath, out) in enumerate(file_pairs):
            future = executor.submit(process_one, i, filepath, out)
            futures[future] = (i, filepath)

        for future in as_completed(futures):
            idx, filepath = futures[future]
            index, result = future.result()
            results[index] = result

            with lock:
                _update_batch_stats(batch, result)
                completed_count[0] += 1
                if progress_callback:
                    progress_callback(completed_count[0], total, filepath, result)

    return results


def _update_batch_stats(batch: BatchResult, result: AnonymizationResult):
    """Update batch statistics from a single result."""
    if result.error:
        batch.files_errored += 1
    elif result.findings_cleared > 0:
        batch.files_anonymized += 1
    else:
        batch.files_already_clean += 1
