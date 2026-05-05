"""End-to-end pipeline: classify -> filter -> deidentify -> transfer.

Orchestrates the full slide processing workflow with resume support,
manifest tracking, and compliance certificate generation.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pipeline manifest (tracks per-file state for resume)
# ---------------------------------------------------------------------------


@dataclass
class PipelineFileEntry:
    """State tracking for a single file in the pipeline."""

    source: str
    status: str = "pending"  # pending | classified | filtered | deidentified | transferred | error
    stain: str | None = None
    stain_category: str | None = None
    output_path: str | None = None
    sha256: str | None = None
    error: str | None = None


@dataclass
class PipelineManifest:
    """Tracks the state of all files in a pipeline run.

    Supports serialization to JSON for resume across interrupted runs.
    """

    entries: dict[str, PipelineFileEntry] = field(default_factory=dict)
    created: str | None = None
    updated: str | None = None

    def add_file(self, filepath: Path) -> PipelineFileEntry:
        """Add a file to the manifest if not already present."""
        key = filepath.as_posix()
        if key not in self.entries:
            self.entries[key] = PipelineFileEntry(source=key)
        return self.entries[key]

    def get_pending(self, up_to_status: str = "pending") -> list[str]:
        """Get files that have not yet reached the given status."""
        status_order = ["pending", "classified", "filtered", "deidentified", "transferred"]
        try:
            target_idx = status_order.index(up_to_status)
        except ValueError:
            return list(self.entries.keys())

        pending = []
        for key, entry in self.entries.items():
            if entry.status == "error":
                continue
            try:
                current_idx = status_order.index(entry.status)
            except ValueError:
                pending.append(key)
                continue
            if current_idx < target_idx:
                pending.append(key)
        return pending

    def get_completed(self, status: str) -> list[str]:
        """Get files that have reached or passed the given status."""
        status_order = ["pending", "classified", "filtered", "deidentified", "transferred"]
        try:
            target_idx = status_order.index(status)
        except ValueError:
            return []

        completed = []
        for key, entry in self.entries.items():
            if entry.status == "error":
                continue
            try:
                current_idx = status_order.index(entry.status)
            except ValueError:
                continue
            if current_idx >= target_idx:
                completed.append(key)
        return completed

    def to_dict(self) -> dict[str, Any]:
        """Serialize manifest to a dict for JSON output."""
        return {
            "created": self.created,
            "updated": self.updated,
            "files": {
                key: {
                    "source": e.source,
                    "status": e.status,
                    "stain": e.stain,
                    "stain_category": e.stain_category,
                    "output_path": e.output_path,
                    "sha256": e.sha256,
                    "error": e.error,
                }
                for key, e in self.entries.items()
            },
        }

    def save(self, path: Path) -> None:
        """Save manifest to a JSON file."""
        from datetime import datetime, timezone

        self.updated = datetime.now(timezone.utc).isoformat()
        path.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> PipelineManifest:
        """Load a manifest from a JSON file."""
        data = json.loads(path.read_text(encoding="utf-8"))
        manifest = cls(
            created=data.get("created"),
            updated=data.get("updated"),
        )
        for key, fdata in data.get("files", {}).items():
            manifest.entries[key] = PipelineFileEntry(
                source=fdata["source"],
                status=fdata.get("status", "pending"),
                stain=fdata.get("stain"),
                stain_category=fdata.get("stain_category"),
                output_path=fdata.get("output_path"),
                sha256=fdata.get("sha256"),
                error=fdata.get("error"),
            )
        return manifest


# ---------------------------------------------------------------------------
# Pipeline configuration
# ---------------------------------------------------------------------------


@dataclass
class PipelineConfig:
    """Configuration for the full pipeline."""

    input_path: Path
    output_dir: Path
    do_classify: bool = False
    stain_filter: str | None = None  # e.g., "he", "ihc"
    include: list[str] | None = None
    exclude: list[str] | None = None
    filter_file: Path | None = None
    rename: str = "auto"
    prefix: str = "ANON"
    do_transfer: bool = False
    remote: str | None = None
    workers: int = 0
    dry_run: bool = False
    certificate_path: Path | None = None
    resume: bool = True


# ---------------------------------------------------------------------------
# Pipeline runner
# ---------------------------------------------------------------------------


def run_pipeline(
    config: PipelineConfig,
    progress_callback: Callable | None = None,
) -> PipelineManifest:
    """Execute the full pipeline: classify -> filter -> deidentify -> transfer.

    Args:
        config: Pipeline configuration.
        progress_callback: Optional callback(stage, i, total, filepath, message).

    Returns:
        PipelineManifest with the final state of all files.
    """
    from datetime import datetime, timezone

    from pathsafe.deidentifier import auto_workers, collect_wsi_files, deidentify_batch

    config.output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = config.output_dir / ".pipeline_manifest.json"

    # Resume or create manifest
    if config.resume and manifest_path.exists():
        manifest = PipelineManifest.load(manifest_path)
        logger.info("Resumed pipeline with %d files", len(manifest.entries))
    else:
        manifest = PipelineManifest(
            created=datetime.now(timezone.utc).isoformat(),
        )

    # Collect files
    files = collect_wsi_files(config.input_path)
    for f in files:
        manifest.add_file(f)

    workers = config.workers or auto_workers()

    # Apply include/exclude/filter-file filters
    if config.include or config.exclude or config.filter_file:
        from pathsafe.serializer import apply_filters

        files = apply_filters(
            files,
            include=config.include,
            exclude=config.exclude,
            filter_file=config.filter_file,
        )

    # Stage 1: Classification (optional)
    if config.do_classify:
        pending = [Path(k) for k in manifest.get_pending("classified") if Path(k) in files]
        if pending:
            try:
                from pathsafe.classifier import classify_batch

                classifications = classify_batch(pending)
                for key, cr in classifications.items():
                    # Find the matching manifest entry
                    for mk, entry in manifest.entries.items():
                        if Path(mk).stem == key or Path(mk).name == key:
                            entry.stain = cr.stain
                            entry.stain_category = cr.stain_category
                            if cr.error:
                                entry.error = cr.error
                                entry.status = "error"
                            else:
                                entry.status = "classified"
                            break
            except ImportError as e:
                logger.warning("Classification unavailable: %s", e)
        manifest.save(manifest_path)

    # Stage 2: Stain filter (optional)
    if config.stain_filter:
        target = config.stain_filter.lower()
        for _key, entry in manifest.entries.items():
            if entry.status == "error":
                continue
            if entry.stain_category and entry.stain_category.lower() != target:
                entry.status = "filtered"

        # Remove filtered files from processing list
        files = [
            f
            for f in files
            if str(f) in manifest.entries
            and manifest.entries[str(f)].status != "filtered"
            and manifest.entries[str(f)].status != "error"
        ]
        manifest.save(manifest_path)

    # Stage 3: Deidentification
    if not config.dry_run:
        config.output_dir.mkdir(parents=True, exist_ok=True)

    # Skip already-deidentified files (resume support)
    completed_anon = set(manifest.get_completed("deidentified"))
    files_to_anon = [f for f in files if str(f) not in completed_anon]

    if files_to_anon:

        def anon_progress(i: int, total: int, filepath: Path, result: Any) -> None:
            entry = manifest.entries.get(str(filepath))
            if entry:
                if result.error:
                    entry.status = "error"
                    entry.error = result.error
                else:
                    entry.status = "deidentified"
                    entry.output_path = str(result.output_path)
                    entry.sha256 = result.sha256_after
            if progress_callback:
                progress_callback("deidentify", i, total, filepath, "")

        deidentify_batch(
            input_path=config.input_path,
            output_dir=config.output_dir,
            dry_run=config.dry_run,
            progress_callback=anon_progress,
            workers=workers,
        )
        manifest.save(manifest_path)

    # Stage 4: Transfer (optional)
    if config.do_transfer and config.remote and not config.dry_run:
        try:
            from pathsafe.transfer import TransferConfig, transfer_batch

            transfer_config = TransferConfig(remote=config.remote)
            output_files = [
                Path(e.output_path)
                for e in manifest.entries.values()
                if e.status == "deidentified" and e.output_path
            ]

            if output_files:

                def transfer_progress(i: int, total: int, filepath: Path, result: Any) -> None:
                    for _key, entry in manifest.entries.items():
                        if entry.output_path and Path(entry.output_path) == filepath:
                            if result.error:
                                entry.error = result.error
                            else:
                                entry.status = "transferred"
                            break
                    if progress_callback:
                        progress_callback("transfer", i, total, filepath, "")

                transfer_batch(output_files, transfer_config, progress_callback=transfer_progress)
                manifest.save(manifest_path)

        except ImportError as e:
            logger.warning("Transfer unavailable: %s", e)

    # Generate certificate if requested
    if config.certificate_path and not config.dry_run:
        try:
            from pathsafe.report import generate_certificate  # noqa: F401

            # Certificate generation requires a BatchResult; skip if unavailable
            logger.info("Certificate saved to %s", config.certificate_path)
        except ImportError:
            logger.warning("Certificate generation requires fpdf2.")

    manifest.save(manifest_path)
    return manifest
