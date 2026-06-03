"""Core deidentification logic -- copy-then-deidentify, in-place, and batch processing.

Supports both sequential and parallel (thread pool) batch processing.
"""

from __future__ import annotations

import hashlib
import logging
import os
import shutil
import struct
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path


logger = logging.getLogger(__name__)

from pathsafe.formats import get_handler  # noqa: E402
from pathsafe.models import (  # noqa: E402
    BatchResult,
    DeidentificationResult,
    PreflightResult,
    ScanResult,
)
from pathsafe.utils import _sanitize_error  # noqa: E402


# File extensions considered for batch processing
WSI_EXTENSIONS = {".ndpi", ".svs", ".tif", ".tiff", ".scn", ".bif", ".mrxs", ".dcm", ".dicom"}

# Suffix marker for the temporary staging file used during deidentification.
# Files whose name contains this marker are skipped by collect_wsi_files so a
# crashed run's PHI-bearing staging copy is never re-ingested as a slide.
PENDING_MARKER = ".pathsafe_pending"

# Mapping from format filter name to file extensions
FORMAT_EXT_MAP = {
    "ndpi": {".ndpi"},
    "svs": {".svs"},
    "tiff": {".tif", ".tiff"},
    "mrxs": {".mrxs"},
    "bif": {".bif"},
    "scn": {".scn"},
    "dicom": {".dcm", ".dicom"},
}

# Default number of parallel workers
DEFAULT_WORKERS = 4


def auto_workers() -> int:
    """Determine optimal worker count based on available hardware.

    WSI deidentification is I/O-bound (large file reads/writes), so more workers
    than ~8 just creates disk contention. Uses half the CPU cores, clamped
    between 1 and 8.
    """
    cores = os.cpu_count() or 2
    return max(1, min(cores // 2, 8))


def preflight_check(files: list[Path], output_dir: Path | None = None) -> PreflightResult:
    """Run pre-flight validation before a batch deidentification.

    Checks:
    - Output directory is writable (or can be created)
    - Sufficient disk space for copy-mode output
    - Files exist and are readable

    Args:
        files: List of source file paths.
        output_dir: Target directory for copy mode. None means in-place.

    Returns:
        PreflightResult with ok=True if all checks pass.
    """
    result = PreflightResult()

    if not files:
        result.errors.append("No files to process.")
        result.ok = False
        return result

    # Estimate total size
    total_size = 0
    for f in files:
        try:
            total_size += os.path.getsize(f)
        except OSError as e:
            result.errors.append(f"Cannot read {f.name}: {e}")
    result.estimated_size_bytes = total_size

    if output_dir is not None:
        # Check if output directory exists or can be created
        if output_dir.exists():
            if not output_dir.is_dir():
                result.errors.append(f"Output path exists but is not a directory: {output_dir}")
            elif not os.access(output_dir, os.W_OK):
                result.errors.append(f"Output directory is not writable: {output_dir}")
        else:
            # Check if parent exists and is writable
            parent = output_dir.parent
            if parent.exists() and os.access(parent, os.W_OK):
                result.warnings.append(f"Output directory will be created: {output_dir}")
            else:
                result.errors.append(
                    f"Cannot create output directory (parent not writable): {output_dir}"
                )

        # Check available disk space
        try:
            check_path = output_dir if output_dir.exists() else output_dir.parent
            if check_path.exists():
                stat = shutil.disk_usage(check_path)
                result.available_space_bytes = stat.free
                if stat.free < total_size:
                    result.errors.append(
                        f"Insufficient disk space: need {total_size / 1e9:.1f} GB, "
                        f"have {stat.free / 1e9:.1f} GB"
                    )
                elif stat.free < total_size * 1.1:
                    result.warnings.append(
                        f"Low disk space: need {total_size / 1e9:.1f} GB, "
                        f"have {stat.free / 1e9:.1f} GB (< 10% margin)"
                    )
        except OSError:
            result.warnings.append("Could not check disk space.")

    result.ok = len(result.errors) == 0
    return result


def _verify_image_integrity(filepath: Path, pre_hashes: dict[int, str]) -> bool | None:
    """Compare pre-deidentification tile hashes with post-deidentification hashes.

    Returns True if all non-blanked IFDs match, False if any mismatch,
    None if not a TIFF or no hashes to compare.
    """
    if not pre_hashes:
        return None

    from pathsafe.tiff import (
        compute_ifd_tile_hash,
        is_ifd_image_blanked,
        iter_ifds,
        read_header,
    )

    try:
        with open(str(filepath), "rb") as f:
            header = read_header(f)
            if header is None:
                return None

            for ifd_offset, entries in iter_ifds(f, header):
                if ifd_offset not in pre_hashes:
                    continue
                # Skip IFDs that were intentionally blanked (label/macro)
                if is_ifd_image_blanked(f, header, entries):
                    continue
                post_hash = compute_ifd_tile_hash(f, header, entries)
                if post_hash is None:
                    continue
                if post_hash != pre_hashes[ifd_offset]:
                    return False
    except (OSError, struct.error, ValueError) as e:
        logger.error(
            "Image integrity verification failed for %s: %s", filepath.name, _sanitize_error(e)
        )
        return False

    return True


def deidentify_file(
    filepath: Path,
    output_path: Path | None = None,
    verify: bool = False,
    dry_run: bool = False,
    reset_timestamps: bool = False,
    verify_integrity: bool = False,
    phase_callback: Callable[[str, Path, float | None], None] | None = None,
    io_semaphore: threading.Semaphore | None = None,
    compute_checksum: bool = False,
) -> DeidentificationResult:
    """Deidentify a single WSI file.

    Args:
        filepath: Path to the source file.
        output_path: If provided, copy file here first (copy mode).
                     If None, deidentify in-place.
        verify: If True, re-scan after deidentification to confirm all PHI cleared.
        dry_run: If True, only scan -- don't modify anything.
        reset_timestamps: If True, reset file access/modification times to epoch.
        verify_integrity: If True, verify image tile data integrity via SHA-256.

    Returns:
        DeidentificationResult with details of what was done.
    """
    filepath = Path(filepath)
    t0 = time.monotonic()

    if not filepath.exists():
        return DeidentificationResult(
            source_path=filepath,
            output_path=output_path or filepath,
            mode="copy" if output_path else "inplace",
            error=f"File not found: {filepath.name}",
        )

    handler = get_handler(filepath)

    # Determine mode and target
    if output_path is not None:
        mode = "copy"
        target = Path(output_path)
    else:
        mode = "inplace"
        target = filepath

    # Symlink safety: reject symlinked output paths to prevent writing
    # deidentified data through a symlink to an unintended location, and
    # reject symlinked source files to prevent reading outside the
    # intended directory tree.
    if target.is_symlink():
        return DeidentificationResult(
            source_path=filepath,
            output_path=target,
            mode=mode,
            error="Refusing to write to symlinked output path",
        )
    if filepath.is_symlink():
        return DeidentificationResult(
            source_path=filepath,
            output_path=target,
            mode=mode,
            error="Refusing to process symlinked source file",
        )

    if dry_run:
        # Just scan, report what would be done
        if phase_callback:
            phase_callback("Scanning", filepath)
        scan_result = handler.scan(filepath)
        elapsed = (time.monotonic() - t0) * 1000
        return DeidentificationResult(
            source_path=filepath,
            output_path=target,
            mode=mode,
            findings_cleared=len(scan_result.findings),
            findings=scan_result.findings,
            verified=None,
            deidentification_time_ms=elapsed,
        )

    # Staging: copy to a temporary file, deidentify it, then atomically
    # os.replace() it onto the target.  This prevents Ctrl+C or a crash from
    # leaving a partially-deidentified (PHI-leaking) file at the target path.
    #
    # We stage in BOTH copy mode and in-place mode.  In-place staging means we
    # never write into the original slide directly -- the original may be open
    # in a viewer, cloud-synced (OneDrive), or on a network share, where
    # in-place writes can silently fail to persist; the original is only ever
    # touched by the final atomic os.replace().  Exception: multi-file MRXS
    # slides (which have a companion data directory) are deidentified directly
    # in place, because a single atomic file swap cannot cover the companion
    # files.
    copy_hash_hex = None
    staging = None  # Path of the staging file (set when staging is used)
    companion_dir = filepath.parent / filepath.stem
    # Stage in copy mode always; in in-place mode stage single-file slides only.
    # MRXS is identified by EXTENSION (not a sibling directory, which a
    # single-file slide could coincidentally have).  Multi-file slides (MRXS, or
    # NDPI with annotation sidecars) are de-identified directly in place because
    # a single atomic file swap cannot cover their companion files.
    is_mrxs = filepath.suffix.lower() == ".mrxs"
    use_staging = mode == "copy" or not _has_companion_artifacts(filepath)
    if use_staging:
        staging = target.parent / (target.stem + PENDING_MARKER + target.suffix)
        if io_semaphore:
            io_semaphore.acquire()
        try:
            if phase_callback:
                phase_callback("Copying", filepath)
            target.parent.mkdir(parents=True, exist_ok=True)
            # Chunked copy with sub-progress reporting (+ inline hashing)
            src_size = os.path.getsize(str(filepath))
            copied = 0
            last_pct = -1
            copy_hasher = hashlib.sha256() if compute_checksum else None
            with open(str(filepath), "rb") as fsrc, open(str(staging), "wb") as fdst:
                while True:
                    buf = fsrc.read(1_048_576)  # 1 MB chunks
                    if not buf:
                        break
                    fdst.write(buf)
                    if copy_hasher is not None:
                        copy_hasher.update(buf)
                    copied += len(buf)
                    if phase_callback and src_size > 0:
                        new_pct = int(copied * 100 / src_size)
                        if new_pct > last_pct:
                            last_pct = new_pct
                            phase_callback("Copying", filepath, copied / src_size)
            if copy_hasher is not None:
                copy_hash_hex = copy_hasher.hexdigest()
            shutil.copystat(str(filepath), str(staging))
            # MRXS (copy mode only): also copy the companion data directory
            # (slide/ next to slide.mrxs) using the staging stem so
            # _get_data_dir() can find it during deidentification; it is
            # renamed alongside the .mrxs file later.  (In-place MRXS does not
            # stage, so companion_dir.is_dir() here implies copy mode.)
            if is_mrxs and companion_dir.is_dir():
                staging_companion = staging.parent / staging.stem
                if not staging_companion.exists():
                    shutil.copytree(str(companion_dir), str(staging_companion))
        except BaseException:
            # Clean up the staging copy on any failure or interrupt (incl.
            # Ctrl-C / SystemExit) so a PHI-bearing partial copy is never left
            # behind, then propagate.
            _cleanup_staging(staging)
            raise
        finally:
            if io_semaphore:
                io_semaphore.release()

        # Defense-in-depth: verify the staging file was not replaced by a
        # symlink between the mkdir and the write (TOCTOU mitigation).
        if staging.is_symlink():
            staging.unlink(missing_ok=True)
            return DeidentificationResult(
                source_path=filepath,
                output_path=target,
                mode=mode,
                error="Staging file became a symlink (possible race condition)",
            )

    # work_path is the file we actually read/write during processing.
    # In copy mode this is the staging file; in in-place mode it is target.
    work_path = staging if staging is not None else target

    # Pre-hash tile data for integrity verification
    pre_hashes = {}
    if verify_integrity and not dry_run:
        acquired = False
        try:
            if io_semaphore:
                io_semaphore.acquire()
                acquired = True
            if phase_callback:
                phase_callback("Hashing tiles", filepath)
            from pathsafe.tiff import compute_image_hashes

            pre_hashes = compute_image_hashes(work_path)
        except BaseException:
            # Interrupt/error (incl. while blocked acquiring the semaphore or
            # hashing the PHI-bearing staging copy) -- clean up, then propagate.
            _cleanup_staging(staging)
            raise
        finally:
            if acquired:
                io_semaphore.release()

    # Deidentify
    if phase_callback:
        phase_callback("Deidentifying", filepath)
    try:
        findings = handler.deidentify(work_path)
    except Exception as e:
        # Per-file failure: clean up the staging copy and report an error.
        _cleanup_staging(staging)
        elapsed = (time.monotonic() - t0) * 1000
        return DeidentificationResult(
            source_path=filepath,
            output_path=target,
            mode=mode,
            deidentification_time_ms=elapsed,
            error=_sanitize_error(e),
        )
    except BaseException:
        # Interrupt (Ctrl-C / SystemExit): clean up the PHI-bearing staging
        # copy before propagating so it is not left at rest.
        _cleanup_staging(staging)
        raise

    # Post-deidentification phases: wrap in try/except to clean up staging on failure
    try:
        # Verify image tile data integrity
        integrity_result = None
        if verify_integrity and not dry_run:
            if io_semaphore:
                io_semaphore.acquire()
            try:
                if phase_callback:
                    phase_callback("Verifying integrity", filepath)
                integrity_result = _verify_image_integrity(work_path, pre_hashes)
            finally:
                if io_semaphore:
                    io_semaphore.release()

        # Verify -- re-scan after deidentification.  When enabled this is
        # AUTHORITATIVE: if any residual PHI remains (or the scan errors), the
        # file is reported as an ERROR and the staging copy is NOT promoted, so a
        # run never silently reports success while PHI survives on disk.
        verified = None
        if verify:
            if phase_callback:
                phase_callback("Verifying clean", filepath)
            from pathsafe.verify import verify_file

            verify_result = verify_file(work_path)
            # Filename PHI is surfaced separately as a (non-fatal) warning
            # (filename_has_phi) -- the file CONTENT is what must be clean here.
            content_findings = [f for f in verify_result.findings if f.source != "filename"]
            if verify_result.error or content_findings:
                _cleanup_staging(staging)  # discard the unverified copy; do not promote
                elapsed = (time.monotonic() - t0) * 1000
                if verify_result.error:
                    detail = f"post-deidentification verification could not run: {verify_result.error}"
                else:
                    detail = (
                        f"post-deidentification verification found "
                        f"{len(content_findings)} residual PHI finding(s)"
                    )
                return DeidentificationResult(
                    source_path=filepath,
                    output_path=target,
                    mode=mode,
                    findings_cleared=len(findings),
                    findings=findings,
                    verified=False,
                    deidentification_time_ms=elapsed,
                    error=detail,
                )
            verified = True

        # Check if output filename still contains PHI patterns
        from pathsafe.scanner import scan_filename_for_phi

        filename_has_phi = len(scan_filename_for_phi(target)) > 0
    except BaseException:
        # Clean up the staging copy on failure or interrupt, then propagate.
        _cleanup_staging(staging)
        raise

    # Finalize: compute SHA-256 (only when requested) and reset timestamps.
    # Optimisation: if the file was copied with inline hashing and
    # deidentification did not modify any bytes, reuse the copy-time hash
    # instead of re-reading the entire output file.
    file_sha256 = None
    if compute_checksum:
        if copy_hash_hex is not None and len(findings) == 0:
            # Nothing was modified after the copy -- the copy hash is valid.
            file_sha256 = copy_hash_hex
        else:
            acquired = False
            try:
                if io_semaphore:
                    io_semaphore.acquire()
                    acquired = True
                if phase_callback:
                    phase_callback("Finalizing", filepath)
                try:
                    target_size = os.path.getsize(str(work_path))
                    h = hashlib.sha256()
                    hashed = 0
                    last_pct = -1
                    with open(str(work_path), "rb") as fh:
                        while True:
                            chunk = fh.read(65536)
                            if not chunk:
                                break
                            h.update(chunk)
                            hashed += len(chunk)
                            if phase_callback and target_size > 0:
                                new_pct = int(hashed * 100 / target_size)
                                if new_pct > last_pct:
                                    last_pct = new_pct
                                    phase_callback("Finalizing", filepath, hashed / target_size)
                    file_sha256 = h.hexdigest()
                except (OSError, FileNotFoundError) as e:
                    logger.warning(
                        "Failed to compute SHA-256 checksum for %s: %s", work_path.name, e
                    )
            except BaseException:
                # Interrupt (incl. while blocked acquiring the semaphore or
                # hashing the staging copy) -- clean up, then propagate.
                _cleanup_staging(staging)
                raise
            finally:
                if acquired:
                    io_semaphore.release()

    # Atomic promote: os.replace() the staging file onto the target path.
    # It is atomic on the same filesystem and overwrites any existing file at
    # the destination (the original slide, in in-place mode).  If the process
    # is interrupted before this point, the target still holds the original
    # file and only the .pathsafe_pending staging copy exists -- the target
    # never contains partially-deidentified data.
    if staging is not None and staging.exists():
        try:
            # Durably persist the deidentified staging data before the swap so
            # a crash cannot leave the promoted file referencing unwritten
            # blocks; a failing fsync surfaces a contended handle loudly.
            try:
                _fd = os.open(str(staging), os.O_RDWR)
                try:
                    os.fsync(_fd)
                finally:
                    os.close(_fd)
            except OSError as fsync_err:
                logger.warning("fsync of staging file failed: %s", _sanitize_error(fsync_err))
            os.replace(str(staging), str(target))
            # Also rename MRXS companion directory from staging stem to target stem
            staging_companion = staging.parent / staging.stem
            target_companion = target.parent / target.stem
            if is_mrxs and staging_companion.is_dir() and not target_companion.exists():
                os.rename(str(staging_companion), str(target_companion))
        except OSError as rename_err:
            staging.unlink(missing_ok=True)
            staging_companion = staging.parent / staging.stem
            if staging_companion.is_dir():
                shutil.rmtree(str(staging_companion), ignore_errors=True)
            elapsed = (time.monotonic() - t0) * 1000
            return DeidentificationResult(
                source_path=filepath,
                output_path=target,
                mode=mode,
                deidentification_time_ms=elapsed,
                error=f"Failed to rename staging file: {_sanitize_error(rename_err)}",
            )
        except BaseException:
            # Interrupt during fsync/replace (the fsync can block for seconds on
            # a contended/cloud handle) -- clean up the staging copy, then propagate.
            _cleanup_staging(staging)
            raise

    # Reset filesystem timestamps to epoch (removes temporal PHI)
    if reset_timestamps:
        os.utime(target, (0, 0))
        # Also reset the MRXS companion directory and files (MRXS only -- keyed
        # on extension so a single-file slide's coincidental sibling dir is not
        # touched).
        companion_dir = target.parent / target.stem
        if is_mrxs and companion_dir.is_dir():
            for root, dirs, filenames in os.walk(companion_dir):
                for fname in filenames:
                    try:
                        os.utime(os.path.join(root, fname), (0, 0))
                    except OSError as e:
                        logger.warning(
                            "Failed to reset timestamp for %s: %s", os.path.join(root, fname), e
                        )
                for dname in dirs:
                    try:
                        os.utime(os.path.join(root, dname), (0, 0))
                    except OSError as e:
                        logger.warning(
                            "Failed to reset timestamp for %s: %s", os.path.join(root, dname), e
                        )
            try:
                os.utime(str(companion_dir), (0, 0))
            except OSError as e:
                logger.warning(
                    "Failed to reset timestamp for companion dir %s: %s", companion_dir, e
                )

    elapsed = (time.monotonic() - t0) * 1000
    return DeidentificationResult(
        source_path=filepath,
        output_path=target,
        mode=mode,
        findings_cleared=len(findings),
        findings=findings,
        verified=verified,
        deidentification_time_ms=elapsed,
        image_integrity_verified=integrity_result,
        filename_has_phi=filename_has_phi,
        sha256_after=file_sha256,
    )


def _has_companion_artifacts(filepath: Path) -> bool:
    """True if a slide has companion files/dirs that in-place staging cannot
    atomically swap, so it must be de-identified directly in place.

    MRXS always has a companion data directory.  NDPI may have ``.ndpa``/``.ndpis``
    annotation sidecars, which the NDPI handler locates by the slide's own name
    (and deletes) -- so they must sit alongside the file the handler operates on;
    staging (which renames the base) would orphan the real PHI sidecars.
    """
    suffix = filepath.suffix.lower()
    if suffix == ".mrxs":
        return True
    if suffix == ".ndpi":
        parent = filepath.parent
        name = filepath.name
        if (parent / (name + ".ndpa")).exists() or (parent / (name + ".ndpis")).exists():
            return True
        try:
            next(iter(parent.glob(f"{name}_*.ndpa")))
            return True
        except StopIteration:
            pass
    return False


def _cleanup_staging(staging: Path | None) -> None:
    """Best-effort removal of a staging file and its MRXS companion directory.

    Used on every failure/interrupt path so a PHI-bearing staging copy is never
    left at rest.
    """
    if staging is None:
        return
    try:
        staging.unlink(missing_ok=True)
    except OSError as e:
        logger.error("Failed to remove staging file %s: %s", staging.name, _sanitize_error(e))
    staging_companion = staging.parent / staging.stem
    if staging_companion.is_dir():
        shutil.rmtree(str(staging_companion), ignore_errors=True)


def _is_staging_name(name: str) -> bool:
    """True if a name is a PathSafe staging artifact (staging file or MRXS
    companion dir), e.g. ``slide.pathsafe_pending.svs`` or ``slide.pathsafe_pending``.

    Matches the marker only as a whole dotted component, so an unrelated slide
    whose name merely contains the substring is not skipped/removed.
    """
    return name.endswith(PENDING_MARKER) or (PENDING_MARKER + ".") in name


def _sweep_stale_staging(directory: Path) -> None:
    """Remove leftover staging artifacts (a previously interrupted run's
    PHI-bearing ``*.pathsafe_pending*`` copies) from a directory before
    processing.  Best-effort and precise-matched, so it only removes PathSafe's
    own reserved-marker files/dirs.
    """
    try:
        entries = list(directory.iterdir())
    except OSError:
        return
    for entry in entries:
        if not _is_staging_name(entry.name):
            continue
        try:
            if entry.is_dir() and not entry.is_symlink():
                shutil.rmtree(str(entry), ignore_errors=True)
            else:
                entry.unlink(missing_ok=True)
            logger.warning("Removed stale staging artifact: %s", entry.name)
        except OSError as e:
            logger.warning("Failed to remove stale staging artifact %s: %s", entry.name, e)


def collect_wsi_files(path: Path, format_filter: str | None = None) -> list[Path]:
    """Collect all WSI files from a path (file or directory).

    Args:
        path: File or directory to search.
        format_filter: If set, only collect files of this format ("ndpi", "svs", etc).
    """
    if path.is_file():
        # Reject symlinked files -- an attacker could point a symlink at
        # a sensitive file outside the intended directory tree.
        if path.is_symlink():
            logger.warning("Skipping symlinked file: %s", path.name)
            return []
        # Skip leftover staging files (a crashed run's PHI-bearing copy).
        if _is_staging_name(path.name):
            return []
        if format_filter:
            allowed = FORMAT_EXT_MAP.get(format_filter, WSI_EXTENSIONS)
            if path.suffix.lower() not in allowed:
                return []
        elif path.suffix.lower() not in WSI_EXTENSIONS:
            return []
        return [path]

    extensions = WSI_EXTENSIONS
    if format_filter:
        extensions = FORMAT_EXT_MAP.get(format_filter, WSI_EXTENSIONS)

    files = []
    for root, _, filenames in os.walk(path):
        for fname in sorted(filenames):
            fpath = Path(root) / fname
            if fpath.is_symlink():
                logger.warning("Skipping symlinked file: %s", fpath.name)
                continue
            # Skip leftover staging files (a crashed run's PHI-bearing copy).
            if _is_staging_name(fname):
                continue
            if Path(fname).suffix.lower() in extensions:
                files.append(fpath)
    files.sort()
    return files


def deidentify_batch(
    input_path: Path,
    output_dir: Path | None = None,
    verify: bool = False,
    dry_run: bool = False,
    format_filter: str | None = None,
    progress_callback: Callable[[int, int, Path, DeidentificationResult], None] | None = None,
    workers: int = 1,
    reset_timestamps: bool = False,
    verify_integrity: bool = False,
    stop_check: Callable[[], bool] | None = None,
    file_list: list[Path] | None = None,
    phase_callback: Callable[[str, Path, float | None], None] | None = None,
    compute_checksum: bool = False,
    precomputed_pairs: list[tuple] | None = None,
    io_concurrency: int = 1,
) -> BatchResult:
    """Deidentify a batch of WSI files.

    Args:
        input_path: File or directory containing WSI files.
        output_dir: If provided, copy files here (copy mode).
        verify: Re-scan after deidentification.
        dry_run: Scan only, don't modify.
        format_filter: Only process files of this format.
        progress_callback: Called with (index, total, filepath, result) after each file.
        workers: Number of parallel workers. 1 = sequential (default).
        reset_timestamps: If True, reset file timestamps to epoch after deidentification.
        verify_integrity: If True, verify image tile data integrity via SHA-256.
        stop_check: Optional callable returning True to abort immediately.
        file_list: If provided, use these files instead of collecting from input_path.
        phase_callback: Called with (phase_name, filepath) at each processing phase.
        io_concurrency: Max concurrent I/O-heavy operations (copy, hash).
                        Default 1 (HDD-safe). Use 2-4 for SSD/NVMe.

    Returns:
        BatchResult with summary statistics.
    """
    input_path = Path(input_path)
    t0 = time.monotonic()

    # If precomputed (source, output) pairs are provided (e.g., from serializer),
    # use them directly because the output paths already have the final serialized names.
    if precomputed_pairs is not None:
        file_pairs = list(precomputed_pairs)
        total = len(file_pairs)
    else:
        if file_list:
            files = list(file_list)
        else:
            files = collect_wsi_files(input_path, format_filter)
        total = len(files)

        # Build list of (filepath, output_path) pairs
        file_pairs = []
        for filepath in files:
            if output_dir is not None:
                if file_list:
                    out = Path(output_dir) / filepath.name
                else:
                    relative = (
                        filepath.relative_to(input_path) if input_path.is_dir() else filepath.name
                    )
                    out = Path(output_dir) / relative
                # Path containment check: prevent symlink-based path escapes
                resolved_out = out.resolve()
                resolved_dir = Path(output_dir).resolve()
                if not resolved_out.is_relative_to(resolved_dir):
                    logger.warning(
                        "Skipping file with output path outside output directory: %s", filepath
                    )
                    continue
            else:
                out = None
            file_pairs.append((filepath, out))

    # Remove any stale staging artifacts (a previously interrupted run's
    # PHI-bearing copies) from the directories we are about to write to.
    if not dry_run:
        sweep_dirs = {(out.parent if out is not None else src.parent) for src, out in file_pairs}
        for _dir in sweep_dirs:
            _sweep_stale_staging(_dir)

    batch = BatchResult(total_files=total)

    if workers > 1 and total > 1:
        results = _batch_parallel(
            file_pairs,
            verify,
            dry_run,
            workers,
            progress_callback,
            batch,
            reset_timestamps,
            verify_integrity,
            stop_check,
            phase_callback,
            compute_checksum,
            io_concurrency=io_concurrency,
        )
    else:
        results = _batch_sequential(
            file_pairs,
            verify,
            dry_run,
            progress_callback,
            batch,
            reset_timestamps,
            verify_integrity,
            stop_check,
            phase_callback,
            compute_checksum,
        )

    batch.results = results
    batch.total_time_seconds = time.monotonic() - t0
    return batch


def _batch_sequential(
    file_pairs: list[tuple[Path, Path | None]],
    verify: bool,
    dry_run: bool,
    progress_callback: Callable[[int, int, Path, DeidentificationResult], None] | None,
    batch: BatchResult,
    reset_timestamps: bool = False,
    verify_integrity: bool = False,
    stop_check: Callable[[], bool] | None = None,
    phase_callback: Callable[[str, Path, float | None], None] | None = None,
    compute_checksum: bool = False,
) -> list[DeidentificationResult]:
    """Process files sequentially."""
    results = []
    total = len(file_pairs)

    for i, (filepath, out) in enumerate(file_pairs):
        if stop_check and stop_check():
            break
        try:
            result = deidentify_file(
                filepath,
                output_path=out,
                verify=verify,
                dry_run=dry_run,
                reset_timestamps=reset_timestamps,
                verify_integrity=verify_integrity,
                phase_callback=phase_callback,
                compute_checksum=compute_checksum,
            )
        except Exception as e:
            result = DeidentificationResult(
                source_path=filepath,
                output_path=out or filepath,
                mode="copy" if out else "inplace",
                error=_sanitize_error(e),
            )

        results.append(result)
        _update_batch_stats(batch, result)

        if progress_callback:
            progress_callback(i + 1, total, filepath, result)

    return results


def _batch_parallel(
    file_pairs: list[tuple[Path, Path | None]],
    verify: bool,
    dry_run: bool,
    workers: int,
    progress_callback: Callable[[int, int, Path, DeidentificationResult], None] | None,
    batch: BatchResult,
    reset_timestamps: bool = False,
    verify_integrity: bool = False,
    stop_check: Callable[[], bool] | None = None,
    phase_callback: Callable[[str, Path, float | None], None] | None = None,
    compute_checksum: bool = False,
    io_concurrency: int = 1,
) -> list[DeidentificationResult]:
    """Process files in parallel using a thread pool.

    Files are processed concurrently but results are collected in
    submission order for deterministic output.
    """
    total = len(file_pairs)
    workers = min(workers, total)  # no point creating more threads than files
    # Cap concurrent I/O to prevent disk thrashing.
    # Default 1 is safe for HDD; use 2-4 for SSD/NVMe.
    io_semaphore = threading.Semaphore(max(1, io_concurrency))
    # Pre-allocate results list to maintain order
    results = [None] * total
    lock = threading.Lock()
    completed_count = [0]  # mutable counter for closure

    def process_one(
        index: int, filepath: Path, out: Path | None
    ) -> tuple[int, DeidentificationResult]:
        try:
            return index, deidentify_file(
                filepath,
                output_path=out,
                verify=verify,
                dry_run=dry_run,
                reset_timestamps=reset_timestamps,
                verify_integrity=verify_integrity,
                phase_callback=phase_callback,
                io_semaphore=io_semaphore,
                compute_checksum=compute_checksum,
            )
        except Exception as e:
            return index, DeidentificationResult(
                source_path=filepath,
                output_path=out or filepath,
                mode="copy" if out else "inplace",
                error=_sanitize_error(e),
            )

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {}
        for i, (filepath, out) in enumerate(file_pairs):
            if stop_check and stop_check():
                break
            future = executor.submit(process_one, i, filepath, out)
            futures[future] = (i, filepath)

        for future in as_completed(futures):
            if stop_check and stop_check():
                for f in futures:
                    f.cancel()
                break
            idx, filepath = futures[future]
            index, result = future.result()
            results[index] = result

            with lock:
                _update_batch_stats(batch, result)
                completed_count[0] += 1
                if progress_callback:
                    progress_callback(completed_count[0], total, filepath, result)

    return [r for r in results if r is not None]


def scan_batch(
    input_path: Path,
    format_filter: str | None = None,
    progress_callback: Callable[[int, int, Path, ScanResult], None] | None = None,
    workers: int = 1,
    stop_check: Callable[[], bool] | None = None,
    file_list: list[Path] | None = None,
) -> list[tuple[Path, ScanResult]]:
    """Scan a batch of WSI files for PHI (read-only).

    Args:
        input_path: File or directory containing WSI files.
        format_filter: Only scan files of this format.
        progress_callback: Called with (index, total, filepath, result) after each file.
        workers: Number of parallel workers. 1 = sequential (default).
        stop_check: Optional callable returning True to abort immediately.
        file_list: If provided, use these files instead of collecting from input_path.

    Returns:
        List of (filepath, ScanResult) tuples.
    """
    from pathsafe.formats import get_handler
    from pathsafe.models import ScanResult

    if file_list:
        files = list(file_list)
    else:
        input_path = Path(input_path)
        files = collect_wsi_files(input_path, format_filter)
    total = len(files)

    if total == 0:
        return []

    def scan_one(filepath: Path) -> ScanResult:
        handler = get_handler(filepath)
        return handler.scan(filepath)

    results = []

    if workers > 1 and total > 1:
        lock = threading.Lock()
        completed = [0]

        def _do_scan(index: int, filepath: Path) -> tuple[int, Path, ScanResult]:
            try:
                return index, filepath, scan_one(filepath)
            except Exception as e:
                return (
                    index,
                    filepath,
                    ScanResult(
                        filepath=filepath,
                        format="unknown",
                        is_clean=False,
                        file_size=0,
                        error=_sanitize_error(e),
                    ),
                )

        ordered = [None] * total
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {}
            for i, fp in enumerate(files):
                if stop_check and stop_check():
                    break
                future = executor.submit(_do_scan, i, fp)
                futures[future] = i

            for future in as_completed(futures):
                if stop_check and stop_check():
                    for f in futures:
                        f.cancel()
                    break
                idx, filepath, result = future.result()
                ordered[idx] = (filepath, result)

                with lock:
                    completed[0] += 1
                    if progress_callback:
                        progress_callback(completed[0], total, filepath, result)

        results = [r for r in ordered if r is not None]
    else:
        for i, filepath in enumerate(files):
            if stop_check and stop_check():
                break
            try:
                result = scan_one(filepath)
            except Exception as e:
                result = ScanResult(
                    filepath=filepath,
                    format="unknown",
                    is_clean=False,
                    file_size=0,
                    error=_sanitize_error(e),
                )
            results.append((filepath, result))
            if progress_callback:
                progress_callback(i + 1, total, filepath, result)

    return results


def _update_batch_stats(batch: BatchResult, result: DeidentificationResult) -> None:
    """Update batch statistics from a single result."""
    if result.error:
        batch.files_errored += 1
    elif result.findings_cleared > 0:
        batch.files_deidentified += 1
    else:
        batch.files_already_clean += 1
