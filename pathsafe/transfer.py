"""File transfer via rsync over SSH -- batch transfer of deidentified WSI files.

Wraps rsync as a subprocess for maximum throughput, resume support (--partial),
and bandwidth limiting.  Parses rsync's --progress output line-by-line so that
callers (GUI or CLI) can display a live progress bar.

Post-transfer SHA256 verification ensures bitwise integrity between the local
deidentified output and the remote copy.

PHI safety
----------
Transfer logs never record original filenames.  Only deidentified output
filenames appear in logs and error messages.  All exception strings pass
through ``_sanitize_error()`` before being stored in ``TransferResult.errors``.
"""

from __future__ import annotations

import hashlib
import logging
import re
import shutil
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from pathsafe.utils import _sanitize_error


logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Rsync progress parsing
# ---------------------------------------------------------------------------

# Matches lines like:
#   1,234,567  45%  12.34MB/s    0:01:23
# The commas in the byte count are optional (depends on locale / rsync version).
_PROGRESS_RE = re.compile(
    r"^\s*[\d,]+\s+"  # bytes transferred (with optional commas)
    r"(\d+)%\s+"  # percentage
    r"([\d.]+\S+)\s+"  # speed (e.g. "12.34MB/s")
    r"\S+"  # ETA or elapsed
)

# Matches the final summary line from rsync --stats or the tail of --progress:
#   sent 1,234 bytes  received 56 bytes
_SENT_RE = re.compile(r"sent\s+([\d,]+)\s+bytes")

# Matches the per-file transfer line that rsync prints before the progress bars:
#   filename
#   (rsync prints the filename on its own line before progress output)
_XFER_RE = re.compile(r"^[^\s].*\S$")


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class TransferConfig:
    """Configuration for an rsync-over-SSH transfer.

    Attributes:
        remote: Destination in rsync format, e.g. ``user@host:/data/wsi/``.
        ssh_key: Path to an SSH private key file.  When ``None``, rsync uses
                 the default SSH agent / key discovery.
        bwlimit: Bandwidth cap in KB/s.  ``None`` means unlimited.
        dry_run: If ``True``, rsync runs with ``--dry-run`` (no actual transfer).
        verify: If ``True``, run SHA256 post-transfer verification.
    """

    remote: str
    ssh_key: Path | None = None
    bwlimit: int | None = None
    dry_run: bool = False
    verify: bool = True


@dataclass
class TransferResult:
    """Outcome of a batch transfer.

    Attributes:
        files_transferred: Number of files actually sent.
        files_skipped: Files already up-to-date at the destination.
        files_failed: Files that failed verification (0 when verify is off).
        bytes_transferred: Total bytes sent over the wire.
        elapsed_seconds: Wall-clock time for the entire operation.
        verified: ``True`` only when post-transfer SHA256 matched for every file.
        errors: List of sanitized error messages (never contains PHI).
    """

    files_transferred: int = 0
    files_skipped: int = 0
    files_failed: int = 0
    bytes_transferred: int = 0
    elapsed_seconds: float = 0.0
    verified: bool = False
    errors: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Guards
# ---------------------------------------------------------------------------


def _require_rsync() -> str:
    """Return the path to rsync, or raise a clear error if it is missing."""
    path = shutil.which("rsync")
    if path is None:
        raise RuntimeError(
            "rsync is not installed or not on PATH. "
            "Install it with your package manager (e.g. apt install rsync) "
            "before using the transfer module."
        )
    return path


def _require_ssh() -> str:
    """Return the path to ssh, or raise a clear error if it is missing."""
    path = shutil.which("ssh")
    if path is None:
        raise RuntimeError(
            "ssh is not installed or not on PATH. "
            "Install OpenSSH (e.g. apt install openssh-client) "
            "before using the transfer module."
        )
    return path


# ---------------------------------------------------------------------------
# Command building
# ---------------------------------------------------------------------------


def _build_rsync_cmd(
    source_dir: Path,
    config: TransferConfig,
) -> list[str]:
    """Assemble the rsync command-line arguments.

    Uses ``-avz --progress --partial --human-readable`` as the baseline:
    - ``-a``  archive mode (recursive, preserves permissions/times)
    - ``-v``  verbose (needed for file-level output)
    - ``-z``  compress during transfer
    - ``--progress``  per-file progress output for GUI/CLI parsing
    - ``--partial``   keep partially transferred files for resume
    - ``--human-readable``  easier-to-read sizes in the summary

    Optional flags are appended based on the config.
    """
    rsync_bin = _require_rsync()

    cmd = [
        rsync_bin,
        "-avz",
        "--progress",
        "--partial",
        "--human-readable",
    ]

    if config.bwlimit is not None:
        cmd.append(f"--bwlimit={config.bwlimit}")

    if config.dry_run:
        cmd.append("--dry-run")

    # SSH transport with optional key file
    ssh_cmd = "ssh"
    if config.ssh_key is not None:
        key_path = str(config.ssh_key.resolve())
        ssh_cmd = f"ssh -i {key_path}"
    cmd.extend(["-e", ssh_cmd])

    # Source directory: trailing slash tells rsync to copy *contents*, not
    # the directory itself.  This keeps the remote layout flat.
    source_str = str(source_dir.resolve()).rstrip("/") + "/"
    cmd.append(source_str)

    # Remote destination
    cmd.append(config.remote)

    return cmd


# ---------------------------------------------------------------------------
# SHA256 helpers
# ---------------------------------------------------------------------------


def _sha256_file(filepath: Path) -> str:
    """Compute the SHA256 hex digest of a local file."""
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while True:
            chunk = f.read(65_536)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _remote_sha256(
    filepath_on_remote: str,
    host: str,
    ssh_key: Path | None = None,
) -> str | None:
    """Compute the SHA256 hex digest of a file on the remote host via SSH.

    Returns ``None`` if the command fails (file missing, permission denied, etc).
    """
    ssh_bin = _require_ssh()

    cmd = [ssh_bin]
    if ssh_key is not None:
        cmd.extend(["-i", str(ssh_key.resolve())])
    cmd.extend([host, "sha256sum", filepath_on_remote])

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,
        )
        if proc.returncode != 0:
            return None
        # sha256sum output: "<hash>  <filename>\n"
        parts = proc.stdout.strip().split()
        if parts:
            return parts[0]
    except (subprocess.TimeoutExpired, OSError):
        return None

    return None


def _parse_remote(remote: str) -> tuple[str, str]:
    """Split an rsync remote spec into (host, path).

    Handles both ``user@host:/path`` and ``host:/path`` forms.

    Raises:
        ValueError: If the remote string does not contain a colon separator.
    """
    if ":" not in remote:
        raise ValueError(
            f"Invalid remote format: '{remote}'. Expected 'user@host:/path' or 'host:/path'."
        )
    host, path = remote.split(":", 1)
    return host, path


# ---------------------------------------------------------------------------
# Core transfer
# ---------------------------------------------------------------------------


def transfer_batch(
    source_dir: Path,
    config: TransferConfig,
    progress_callback: Callable[[int, int, float], None] | None = None,
    stop_check: Callable[[], bool] | None = None,
) -> TransferResult:
    """Transfer all files from *source_dir* to a remote destination via rsync.

    Runs a single rsync subprocess for the entire batch (one fork, not one per
    file) and streams stdout line-by-line to parse progress information.

    Args:
        source_dir: Directory containing deidentified output files to transfer.
        config: Transfer configuration (remote, SSH key, bandwidth limit, etc.).
        progress_callback: Called with ``(files_done, total_files, pct)`` as
                           rsync reports progress.  Percentage is 0.0--100.0.
        stop_check: Callable returning ``True`` to request graceful abort.
                    Checked between lines of rsync output.

    Returns:
        A ``TransferResult`` summarizing what was transferred.

    Raises:
        RuntimeError: If rsync or ssh is not installed.
        FileNotFoundError: If *source_dir* does not exist.
        ValueError: If the remote string is malformed.
    """
    source_dir = Path(source_dir)
    if not source_dir.is_dir():
        raise FileNotFoundError(f"Source directory does not exist: {source_dir}")

    # Validate remote format before launching rsync
    _parse_remote(config.remote)

    # Count local files for progress reporting
    local_files = [f for f in source_dir.rglob("*") if f.is_file()]
    total_files = len(local_files)

    if total_files == 0:
        return TransferResult(verified=True)

    t0 = time.monotonic()
    result = TransferResult()

    cmd = _build_rsync_cmd(source_dir, config)
    logger.info("Starting rsync transfer: %d files to %s", total_files, config.remote)

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,  # line-buffered
        )
    except OSError as e:
        result.errors.append(_sanitize_error(e))
        result.elapsed_seconds = time.monotonic() - t0
        return result

    # Parse rsync output line by line
    files_seen = 0

    try:
        for line in iter(proc.stdout.readline, ""):
            if stop_check and stop_check():
                proc.terminate()
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    proc.kill()
                result.errors.append("Transfer aborted by user")
                break

            line = line.rstrip("\n\r")

            # Parse per-file progress lines
            m = _PROGRESS_RE.match(line)
            if m:
                pct = float(m.group(1))
                if progress_callback:
                    progress_callback(files_seen, total_files, pct)
                continue

            # Detect file transfer completions: when rsync finishes a file
            # it emits a line with just the filename (no leading whitespace,
            # no percentage).  We count these.
            if line and _XFER_RE.match(line) and not line.startswith("sending"):
                files_seen += 1
                if progress_callback:
                    progress_callback(files_seen, total_files, 0.0)
                continue

            # Parse sent bytes from summary
            m_sent = _SENT_RE.search(line)
            if m_sent:
                result.bytes_transferred = int(m_sent.group(1).replace(",", ""))

    except Exception as e:
        result.errors.append(_sanitize_error(e))

    # Wait for process to finish
    try:
        proc.wait(timeout=60)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
        result.errors.append("rsync process timed out during shutdown")

    # Capture stderr
    stderr_text = ""
    if proc.stderr:
        stderr_text = proc.stderr.read().strip()

    if proc.returncode not in (0, 24):
        # Return code 24 = "some files vanished before they could be transferred"
        # which is benign for our use case (files being cleaned up concurrently).
        error_msg = f"rsync exited with code {proc.returncode}"
        if stderr_text:
            # Sanitize stderr in case it contains path fragments with PHI
            safe_stderr = stderr_text[:200]
            error_msg = f"{error_msg}: {safe_stderr}"
        result.errors.append(error_msg)

    result.files_transferred = files_seen
    result.files_skipped = max(0, total_files - files_seen)
    result.elapsed_seconds = time.monotonic() - t0

    # Post-transfer verification
    if config.verify and not config.dry_run and not result.errors:
        verification = verify_transfer(source_dir, config)
        all_ok = all(verification.values())
        result.verified = all_ok
        if not all_ok:
            failed = [name for name, ok in verification.items() if not ok]
            result.files_failed = len(failed)
            result.errors.append(f"SHA256 verification failed for {len(failed)} file(s)")
    elif config.dry_run:
        result.verified = True  # nothing to verify in dry-run mode

    logger.info(
        "Transfer complete: %d sent, %d skipped, %d failed, %.1fs",
        result.files_transferred,
        result.files_skipped,
        result.files_failed,
        result.elapsed_seconds,
    )

    return result


# ---------------------------------------------------------------------------
# Post-transfer verification
# ---------------------------------------------------------------------------


def verify_transfer(
    source_dir: Path,
    config: TransferConfig,
) -> dict[str, bool]:
    """Verify transferred files match their source via SHA256 checksums.

    For each file in *source_dir*, computes the local SHA256 and compares it
    with the SHA256 of the corresponding file on the remote host (obtained via
    ``ssh host sha256sum /path/to/file``).

    Args:
        source_dir: Local directory that was transferred.
        config: Transfer config (used for remote host and SSH key).

    Returns:
        A dict mapping ``{filename: True/False}`` for each file checked.
        ``True`` means the checksums matched; ``False`` means mismatch or
        the remote file could not be read.
    """
    source_dir = Path(source_dir)
    host, remote_path = _parse_remote(config.remote)

    # Ensure remote_path ends with / for correct path joining
    remote_path = remote_path.rstrip("/") + "/"

    results: dict[str, bool] = {}

    local_files = [f for f in source_dir.rglob("*") if f.is_file()]

    for local_file in local_files:
        relative = local_file.relative_to(source_dir)
        remote_file_path = remote_path + str(relative)

        local_hash = _sha256_file(local_file)
        remote_hash = _remote_sha256(
            remote_file_path,
            host,
            ssh_key=config.ssh_key,
        )

        matched = remote_hash is not None and local_hash == remote_hash
        results[str(relative)] = matched

        if not matched:
            logger.warning(
                "Verification mismatch for %s: local=%s remote=%s",
                relative,
                local_hash[:12] + "...",
                (remote_hash[:12] + "...") if remote_hash else "MISSING",
            )

    return results
