"""Pipeline runner -- chains classify, filter, deidentify, transfer into one workflow.

The pipeline is the PRIMARY user-facing command.  It orchestrates the full
de-identification workflow in a single invocation:

    collect files -> filter -> classify (optional) -> rename -> deidentify -> transfer (optional)

State tracking uses a write-ahead JSON manifest so the pipeline can resume
after interruption.  Each file's intent is recorded BEFORE processing begins,
and its status is updated AFTER each stage completes.  Re-running the same
pipeline command skips files already at terminal states (deidentified/transferred).

Design decisions (from multi-AI debate):
- Producer-consumer model: classify results feed into filter, which feeds into deidentify
- Write-ahead manifest: write intent BEFORE processing each file, mark complete AFTER
- Pipeline is the PRIMARY user-facing command (others are advanced)
- No --classify flag on deidentify -- classify lives only here
- Resume support: re-running the pipeline skips already-completed files
- Classifier and transfer are imported lazily (optional dependencies)
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pathsafe.deidentifier import collect_wsi_files, deidentify_batch, preflight_check
from pathsafe.serializer import (
    RenameMode,
    SerializerConfig,
    apply_filters,
    compute_rename_plan,
    load_mapping,
)


logger = logging.getLogger(__name__)

# Manifest filename -- hidden dotfile stored in output_dir
MANIFEST_FILENAME = ".pathsafe_manifest.json"

# Terminal states: files at these statuses are skipped on resume
_TERMINAL_STATES = frozenset({"deidentified", "transferred"})

# Valid status transitions (defensive check against manifest corruption)
_VALID_STATUSES = frozenset(
    {
        "pending",
        "classifying",
        "classified",
        "filtering",
        "filtered",
        "deidentifying",
        "deidentified",
        "transferring",
        "transferred",
        "skipped",
        "error",
    }
)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass
class PipelineConfig:
    """Full pipeline configuration -- covers every stage.

    The pipeline runner reads these options once at startup and uses them to
    drive each stage.  CLI and GUI both construct this dataclass, so the
    pipeline itself has no direct dependency on Click or Qt.
    """

    input_dir: Path
    output_dir: Path

    # Classify stage (optional -- requires pathsafe-classify extra)
    classify: bool = False
    stain_filter: str | None = None  # e.g. "he" to keep only H&E after classification

    # Filter stage (include/exclude/filter_file from serializer)
    include: list[str] | None = None
    exclude: list[str] | None = None
    filter_file: Path | None = None

    # Deidentify stage
    workers: int = 1
    verify: bool = True
    certificate: Path | None = None
    rename: str = "keep"  # "keep" | "auto" | "mapping" | "template"
    prefix: str = "ANON"
    start: int = 1
    digits: int = 4
    separator: str = "_"
    mapping_file: Path | None = None
    rename_template: str = "{prefix}_{index}.{ext}"
    reset_timestamps: bool = True
    verify_integrity: bool = False
    compute_checksum: bool = False
    format_filter: str | None = None
    io_concurrency: int = 1

    # Transfer stage (optional -- requires pathsafe-transfer extra)
    transfer: bool = False
    remote: str | None = None

    # General
    dry_run: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-safe dict for embedding in the manifest."""
        d = asdict(self)
        # Convert Path objects to strings for JSON serialization
        for key, value in d.items():
            if isinstance(value, Path):
                d[key] = str(value)
        return d


# ---------------------------------------------------------------------------
# Manifest -- write-ahead state tracking
# ---------------------------------------------------------------------------


@dataclass
class PipelineManifest:
    """Tracks pipeline state for resumability.

    The manifest is written to ``output_dir/.pathsafe_manifest.json`` and
    updated after every status transition.  It serves two purposes:

    1. **Resume**: if the process is interrupted, re-running the pipeline
       loads the manifest and skips files already at a terminal state.
    2. **Audit**: the manifest records the full pipeline configuration,
       timestamps, stain classifications, output paths, and errors.
    """

    pipeline_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    config: dict[str, Any] = field(default_factory=dict)
    files: dict[str, dict[str, Any]] = field(default_factory=dict)

    # Runtime-only -- not serialized
    _path: Path | None = field(default=None, repr=False, compare=False)

    def set_file_status(
        self,
        filename: str,
        status: str,
        **extra: Any,
    ) -> None:
        """Update a file's status and any additional fields, then flush to disk.

        This is the write-ahead primitive: call it BEFORE starting a stage
        (e.g. status="classifying") and again AFTER completion
        (e.g. status="classified", stain_type="he").
        """
        if status not in _VALID_STATUSES:
            raise ValueError(f"Invalid file status: {status!r}")

        if filename not in self.files:
            self.files[filename] = {
                "status": "pending",
                "stain_type": None,
                "output_path": None,
                "error": None,
            }

        self.files[filename]["status"] = status
        for key, value in extra.items():
            self.files[filename][key] = value

        self._flush()

    def get_file_status(self, filename: str) -> str | None:
        """Return the current status of a file, or None if not tracked."""
        entry = self.files.get(filename)
        return entry["status"] if entry else None

    def _flush(self) -> None:
        """Write manifest to disk atomically (write-then-rename)."""
        if self._path is None:
            return

        data = {
            "pipeline_id": self.pipeline_id,
            "created_at": self.created_at,
            "config": self.config,
            "files": self.files,
        }

        # Write to a temp file, then atomic rename to prevent corruption
        # on crash during write.
        tmp_path = self._path.with_suffix(".tmp")
        try:
            tmp_path.write_text(
                json.dumps(data, indent=2, default=str),
                encoding="utf-8",
            )
            tmp_path.replace(self._path)
        except OSError as e:
            logger.error("Failed to write manifest to %s: %s", self._path, e)

    def pending_files(self) -> list[str]:
        """Return filenames that are NOT at a terminal state (need processing)."""
        return [
            fname
            for fname, entry in self.files.items()
            if entry.get("status") not in _TERMINAL_STATES and entry.get("status") != "skipped"
        ]

    def terminal_count(self) -> int:
        """Return how many files have reached a terminal state."""
        return sum(1 for entry in self.files.values() if entry.get("status") in _TERMINAL_STATES)

    def error_count(self) -> int:
        """Return how many files are in error state."""
        return sum(1 for entry in self.files.values() if entry.get("status") == "error")


def _load_manifest(manifest_path: Path) -> PipelineManifest | None:
    """Load an existing manifest from disk, or return None if not found."""
    if not manifest_path.exists():
        return None

    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Could not load existing manifest at %s: %s", manifest_path, e)
        return None

    manifest = PipelineManifest(
        pipeline_id=data.get("pipeline_id", str(uuid.uuid4())),
        created_at=data.get("created_at", ""),
        config=data.get("config", {}),
        files=data.get("files", {}),
    )
    manifest._path = manifest_path
    return manifest


def _create_manifest(
    manifest_path: Path,
    config: PipelineConfig,
) -> PipelineManifest:
    """Create a fresh manifest and write it to disk."""
    manifest = PipelineManifest(
        config=config.to_dict(),
    )
    manifest._path = manifest_path
    manifest._flush()
    return manifest


# ---------------------------------------------------------------------------
# Classification stage (lazy import)
# ---------------------------------------------------------------------------


def _classify_files(
    files: list[Path],
    manifest: PipelineManifest,
    stain_filter: str | None,
    progress_callback: Callable | None = None,
    stop_check: Callable[[], bool] | None = None,
) -> list[Path]:
    """Run stain classifier on files and optionally filter by stain type.

    Classifier is imported lazily because it depends on optional ML libraries.
    If the classifier is not installed, raises ImportError with a helpful message.

    Args:
        files: Files to classify.
        manifest: Pipeline manifest for status tracking.
        stain_filter: If set, only keep files classified as this stain type
                      (e.g. "he" for H&E).  None means classify but keep all.
        progress_callback: Called with (stage, current, total, filename, info).
        stop_check: Returns True to abort.

    Returns:
        Filtered list of files (subset of input if stain_filter is set).
    """
    try:
        from pathsafe.classifier import classify_slide
    except ImportError:
        raise ImportError(
            "Stain classification requires the 'pathsafe-classify' extra. "
            "Install with: pip install pathsafe[classify]"
        ) from None

    kept: list[Path] = []
    total = len(files)

    for i, filepath in enumerate(files):
        if stop_check and stop_check():
            logger.info("Pipeline aborted during classification at file %d/%d", i, total)
            break

        filename = filepath.name
        current_status = manifest.get_file_status(filename)

        # Resume: skip files already classified or beyond
        if current_status in (
            "classified",
            "deidentifying",
            "deidentified",
            "transferring",
            "transferred",
        ):
            stain = manifest.files[filename].get("stain_type")
            if stain_filter is None or stain == stain_filter:
                kept.append(filepath)
            continue

        # Write-ahead: mark as classifying BEFORE we process
        manifest.set_file_status(filename, "classifying")

        try:
            result = classify_slide(filepath)
            stain_type = result.get("stain_type", "unknown")

            manifest.set_file_status(
                filename,
                "classified",
                stain_type=stain_type,
                classify_confidence=result.get("confidence"),
            )

            if progress_callback:
                progress_callback("classify", i + 1, total, filename, {"stain_type": stain_type})

            # Apply stain filter
            if stain_filter is None or stain_type == stain_filter:
                kept.append(filepath)
            else:
                manifest.set_file_status(
                    filename, "skipped", skip_reason=f"stain={stain_type}, wanted={stain_filter}"
                )
                logger.info("Skipping %s: stain=%s (filter=%s)", filename, stain_type, stain_filter)

        except Exception as e:
            manifest.set_file_status(filename, "error", error=str(e))
            logger.error("Classification failed for %s: %s", filename, e)

    return kept


# ---------------------------------------------------------------------------
# Transfer stage (lazy import)
# ---------------------------------------------------------------------------


def _transfer_files(
    manifest: PipelineManifest,
    output_dir: Path,
    remote: str,
    progress_callback: Callable | None = None,
    stop_check: Callable[[], bool] | None = None,
    dry_run: bool = False,
) -> int:
    """Transfer deidentified files to a remote destination.

    Transfer module is imported lazily because it depends on optional
    libraries (e.g. paramiko for SFTP, boto3 for S3).

    Args:
        manifest: Pipeline manifest for status tracking.
        output_dir: Local output directory containing deidentified files.
        remote: Remote destination string (e.g. "sftp://host/path", "s3://bucket/prefix").
        progress_callback: Called with (stage, current, total, filename, info).
        stop_check: Returns True to abort.
        dry_run: If True, log what would be transferred but do nothing.

    Returns:
        Number of files successfully transferred.
    """
    try:
        from pathsafe.transfer import transfer_file
    except ImportError:
        raise ImportError(
            "File transfer requires the 'pathsafe-transfer' extra. "
            "Install with: pip install pathsafe[transfer]"
        ) from None

    # Collect files at "deidentified" status that need transfer
    to_transfer = [
        (fname, entry)
        for fname, entry in manifest.files.items()
        if entry.get("status") == "deidentified"
    ]

    if not to_transfer:
        logger.info("No deidentified files to transfer.")
        return 0

    transferred = 0
    total = len(to_transfer)

    for i, (filename, entry) in enumerate(to_transfer):
        if stop_check and stop_check():
            logger.info("Pipeline aborted during transfer at file %d/%d", i, total)
            break

        output_name = entry.get("output_path", filename)
        local_path = output_dir / output_name

        if not local_path.exists():
            manifest.set_file_status(
                filename,
                "error",
                error=f"Output file not found for transfer: {output_name}",
            )
            logger.error("Cannot transfer %s: output file %s not found", filename, local_path)
            continue

        # Write-ahead: mark as transferring BEFORE we start
        manifest.set_file_status(filename, "transferring")

        if dry_run:
            manifest.set_file_status(filename, "deidentified")  # revert for dry-run
            logger.info("[dry-run] Would transfer %s -> %s", output_name, remote)
            if progress_callback:
                progress_callback("transfer", i + 1, total, filename, {"dry_run": True})
            continue

        try:
            transfer_file(local_path, remote)
            manifest.set_file_status(filename, "transferred")
            transferred += 1

            if progress_callback:
                progress_callback("transfer", i + 1, total, filename, {"remote": remote})

        except Exception as e:
            manifest.set_file_status(filename, "error", error=str(e))
            logger.error("Transfer failed for %s: %s", filename, e)

    return transferred


# ---------------------------------------------------------------------------
# Main pipeline runner
# ---------------------------------------------------------------------------


def run_pipeline(
    config: PipelineConfig,
    progress_callback: Callable | None = None,
    stop_check: Callable[[], bool] | None = None,
) -> PipelineManifest:
    """Run the full pipeline: collect -> filter -> classify -> rename -> deidentify -> transfer.

    This is the PRIMARY user-facing entry point.  It chains all stages and
    uses a write-ahead manifest for resumability.

    Args:
        config: Full pipeline configuration.
        progress_callback: Optional callback for progress updates.
            Signature: (stage: str, current: int, total: int, filename: str, info: dict)
            Stages: "collect", "filter", "classify", "deidentify", "transfer", "complete"
        stop_check: Optional callable returning True to abort.  Checked between
            files and between stages.

    Returns:
        PipelineManifest with final state of all files.

    Raises:
        FileNotFoundError: If input_dir does not exist.
        ImportError: If classify/transfer are requested but extras not installed.
        ValueError: If configuration is invalid (e.g. rename collision).
    """
    t0 = time.monotonic()

    input_dir = Path(config.input_dir)
    output_dir = Path(config.output_dir)

    if not input_dir.exists():
        raise FileNotFoundError(f"Input directory not found: {input_dir}")

    # Ensure output directory exists (or can be created)
    output_dir.mkdir(parents=True, exist_ok=True)

    # ----- Load or create manifest -----

    manifest_path = output_dir / MANIFEST_FILENAME
    manifest = _load_manifest(manifest_path)
    is_resume = False

    if manifest is not None:
        skipped = manifest.terminal_count()
        if skipped > 0:
            is_resume = True
            logger.info(
                "Resuming pipeline %s: %d file(s) already complete, %d pending",
                manifest.pipeline_id,
                skipped,
                len(manifest.pending_files()),
            )
            if progress_callback:
                progress_callback(
                    "resume",
                    skipped,
                    skipped + len(manifest.pending_files()),
                    "",
                    {"pipeline_id": manifest.pipeline_id},
                )
    else:
        manifest = _create_manifest(manifest_path, config)
        logger.info("Created new pipeline %s", manifest.pipeline_id)

    def _should_stop() -> bool:
        return stop_check() if stop_check else False

    # ===================================================================
    # Stage 1: Collect files
    # ===================================================================

    if _should_stop():
        return manifest

    files = collect_wsi_files(input_dir, format_filter=config.format_filter)

    if not files:
        logger.warning("No WSI files found in %s", input_dir)
        if progress_callback:
            progress_callback("collect", 0, 0, "", {"warning": "no files found"})
        return manifest

    logger.info("Collected %d WSI file(s) from %s", len(files), input_dir)
    if progress_callback:
        progress_callback("collect", len(files), len(files), "", {"count": len(files)})

    # ===================================================================
    # Stage 2: Apply filename filters (include/exclude/filter_file)
    # ===================================================================

    if _should_stop():
        return manifest

    if config.include or config.exclude or config.filter_file:
        before_count = len(files)
        files = apply_filters(
            files,
            include=config.include,
            exclude=config.exclude,
            filter_file=config.filter_file,
        )
        dropped = before_count - len(files)
        logger.info(
            "Filters applied: %d of %d files kept (%d excluded)", len(files), before_count, dropped
        )
        if progress_callback:
            progress_callback(
                "filter", len(files), before_count, "", {"kept": len(files), "dropped": dropped}
            )

    if not files:
        logger.warning("No files remain after filtering.")
        return manifest

    # Register all collected files in the manifest (skip already-tracked ones)
    for filepath in files:
        fname = filepath.name
        if fname not in manifest.files:
            manifest.set_file_status(fname, "pending")

    # ===================================================================
    # Stage 3: Classification (optional)
    # ===================================================================

    if _should_stop():
        return manifest

    if config.classify:
        logger.info("Running stain classification on %d file(s)...", len(files))
        files = _classify_files(
            files,
            manifest=manifest,
            stain_filter=config.stain_filter,
            progress_callback=progress_callback,
            stop_check=stop_check,
        )
        logger.info("%d file(s) remain after classification/filtering", len(files))

        if not files:
            logger.warning("No files remain after stain classification filter.")
            manifest._flush()
            return manifest

    # ===================================================================
    # Stage 4: Pre-flight checks
    # ===================================================================

    if _should_stop():
        return manifest

    if not config.dry_run:
        preflight = preflight_check(files, output_dir)
        for w in preflight.warnings:
            logger.warning("Preflight: %s", w)
        if not preflight.ok:
            for e in preflight.errors:
                logger.error("Preflight: %s", e)
            raise RuntimeError("Pre-flight checks failed: " + "; ".join(preflight.errors))

    # ===================================================================
    # Stage 5: Compute rename plan
    # ===================================================================

    if _should_stop():
        return manifest

    # On resume, filter out files already at terminal states so the rename
    # counter does not include gaps from completed files.
    files_to_deidentify = []
    for f in files:
        status = manifest.get_file_status(f.name)
        if status in _TERMINAL_STATES:
            continue  # Already done -- skip
        if status == "skipped":
            continue  # Excluded by classifier -- skip
        files_to_deidentify.append(f)

    if not files_to_deidentify:
        logger.info("All files already processed -- nothing to do.")
        if progress_callback:
            progress_callback("complete", 0, 0, "", {"already_complete": True})
        return manifest

    rename_plan = None
    serializer_config = None

    if config.rename != "keep":
        mode_map = {
            "auto": RenameMode.AUTO,
            "mapping": RenameMode.MAPPING,
            "template": RenameMode.TEMPLATE,
        }
        serializer_config = SerializerConfig(
            mode=mode_map[config.rename],
            prefix=config.prefix,
            start=config.start,
            digits=config.digits,
            separator=config.separator,
            mapping_path=config.mapping_file,
            unmatched="skip",
            template=config.rename_template,
        )

        if serializer_config.mode == RenameMode.MAPPING:
            load_mapping(serializer_config)
            logger.info("Loaded rename mapping: %d entries", len(serializer_config._mapping))

        rename_plan = compute_rename_plan(
            serializer_config,
            files_to_deidentify,
            output_dir,
        )
        logger.info("Rename plan: %d file(s)", len(rename_plan))

        # Record planned output paths in manifest
        for source, final_output in rename_plan:
            manifest.set_file_status(
                source.name,
                "pending",
                output_path=final_output.name,
            )

    # ===================================================================
    # Stage 6: Deidentify
    # ===================================================================

    if _should_stop():
        return manifest

    logger.info(
        "Deidentifying %d file(s) with %d worker(s)...", len(files_to_deidentify), config.workers
    )

    # Mark all files as deidentifying (write-ahead) BEFORE batch starts
    for f in files_to_deidentify:
        manifest.set_file_status(f.name, "deidentifying")

    def _deidentify_progress(
        index: int,
        total: int,
        filepath: Path,
        result: Any,
    ) -> None:
        """Callback from deidentify_batch -- update manifest per file."""
        filename = filepath.name

        if result.error:
            manifest.set_file_status(
                filename,
                "error",
                error=result.error,
                output_path=(result.output_path.name if result.output_path else None),
            )
        else:
            manifest.set_file_status(
                filename,
                "deidentified",
                output_path=(result.output_path.name if result.output_path else filename),
                findings_cleared=result.findings_cleared,
                sha256=result.sha256_after,
            )

        if progress_callback:
            progress_callback(
                "deidentify",
                index,
                total,
                filename,
                {
                    "error": result.error,
                    "findings_cleared": result.findings_cleared,
                    "output_path": (str(result.output_path) if result.output_path else None),
                },
            )

    batch_kwargs: dict[str, Any] = {
        "input_path": input_dir,
        "output_dir": output_dir,
        "verify": config.verify,
        "dry_run": config.dry_run,
        "format_filter": config.format_filter,
        "progress_callback": _deidentify_progress,
        "workers": config.workers,
        "reset_timestamps": config.reset_timestamps,
        "verify_integrity": config.verify_integrity,
        "stop_check": stop_check,
        "compute_checksum": config.compute_checksum,
        "io_concurrency": config.io_concurrency,
    }

    if rename_plan is not None:
        batch_kwargs["precomputed_pairs"] = rename_plan
    else:
        batch_kwargs["file_list"] = files_to_deidentify

    batch_result = deidentify_batch(**batch_kwargs)

    logger.info(
        "Deidentification complete: %d deidentified, %d clean, %d errors (%.1fs)",
        batch_result.files_deidentified,
        batch_result.files_already_clean,
        batch_result.files_errored,
        batch_result.total_time_seconds,
    )

    # For dry-run, revert statuses back to pending (we didn't actually change anything)
    if config.dry_run:
        for f in files_to_deidentify:
            manifest.set_file_status(f.name, "pending")

    # ===================================================================
    # Stage 7: Generate certificate (if requested)
    # ===================================================================

    if config.certificate and not config.dry_run:
        try:
            from pathsafe.report import generate_certificate

            generate_certificate(
                batch_result,
                output_path=config.certificate,
                timestamps_reset=config.reset_timestamps,
            )
            logger.info("Compliance certificate written to %s", config.certificate)
        except Exception as e:
            logger.error("Failed to generate certificate: %s", e)

    # ===================================================================
    # Stage 8: Transfer (optional)
    # ===================================================================

    if _should_stop():
        return manifest

    if config.transfer and config.remote:
        logger.info("Transferring deidentified files to %s...", config.remote)
        transferred = _transfer_files(
            manifest=manifest,
            output_dir=output_dir,
            remote=config.remote,
            progress_callback=progress_callback,
            stop_check=stop_check,
            dry_run=config.dry_run,
        )
        logger.info("Transfer complete: %d file(s) transferred", transferred)

    # ===================================================================
    # Final: flush manifest and report summary
    # ===================================================================

    elapsed = time.monotonic() - t0

    # Record pipeline-level summary in manifest
    manifest.config["completed_at"] = datetime.now(timezone.utc).isoformat()
    manifest.config["elapsed_seconds"] = round(elapsed, 2)
    manifest._flush()

    if progress_callback:
        progress_callback(
            "complete",
            manifest.terminal_count(),
            len(manifest.files),
            "",
            {
                "elapsed_seconds": round(elapsed, 2),
                "deidentified": sum(
                    1 for e in manifest.files.values() if e["status"] == "deidentified"
                ),
                "transferred": sum(
                    1 for e in manifest.files.values() if e["status"] == "transferred"
                ),
                "errors": manifest.error_count(),
                "skipped": sum(1 for e in manifest.files.values() if e["status"] == "skipped"),
                "resumed": is_resume,
            },
        )

    logger.info(
        "Pipeline %s complete in %.1fs: %d terminal, %d errors",
        manifest.pipeline_id,
        elapsed,
        manifest.terminal_count(),
        manifest.error_count(),
    )

    return manifest
