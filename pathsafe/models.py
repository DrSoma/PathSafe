"""Data models for PathSafe scan and deidentification results."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class PHIFinding:
    """A single piece of PHI found in a file."""

    offset: int
    length: int
    tag_id: int | None
    tag_name: str
    value_preview: str
    source: str  # "tiff_tag" | "regex_scan" | "image_metadata"

    def mask_preview(self) -> str:
        """Return a masked version of the value for safe logging."""
        val = self.value_preview
        if len(val) <= 4:
            return "*" * len(val)
        return val[:2] + "*" * (len(val) - 4) + val[-2:]


@dataclass
class ScanResult:
    """Result of scanning a single file for PHI."""

    filepath: Path
    format: str  # "ndpi" | "svs" | "tiff" | "unknown"
    findings: list[PHIFinding] = field(default_factory=list)
    is_clean: bool = True
    scan_time_ms: float = 0.0
    file_size: int = 0
    error: str | None = None


@dataclass
class DeidentificationResult:
    """Result of deidentifying a single file."""

    source_path: Path
    output_path: Path
    mode: str  # "copy" | "inplace"
    findings_cleared: int = 0
    findings: list[PHIFinding] = field(default_factory=list)  # detailed findings
    verified: bool | None = None  # None=verify not run, True=clean, False=verification failed
    deidentification_time_ms: float = 0.0
    image_integrity_verified: bool | None = None  # None=not checked, True=matched, False=mismatch
    filename_has_phi: bool = False  # True if output filename still contains PHI patterns
    sha256_after: str | None = None  # SHA-256 hex digest of output file after deidentification
    error: str | None = None


@dataclass
class BatchResult:
    """Result of a batch deidentification run."""

    results: list[DeidentificationResult] = field(default_factory=list)
    total_files: int = 0
    files_deidentified: int = 0
    files_already_clean: int = 0
    files_skipped: int = 0  # Reserved for future use (e.g. format-filter skips)
    files_errored: int = 0
    total_time_seconds: float = 0.0
    certificate_path: Path | None = None


@dataclass
class PreflightResult:
    """Result of pre-flight validation before batch deidentification."""

    ok: bool = True
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    estimated_size_bytes: int = 0
    available_space_bytes: int = 0


@dataclass
class ConversionResult:
    """Result of converting a single WSI file."""

    source_path: Path
    output_path: Path
    source_format: str
    target_format: str
    levels_written: int = 0
    conversion_time_ms: float = 0.0
    deidentified: bool = False
    error: str | None = None


@dataclass
class ConversionBatchResult:
    """Result of a batch conversion run."""

    results: list[ConversionResult] = field(default_factory=list)
    total_files: int = 0
    files_converted: int = 0
    files_errored: int = 0
    total_time_seconds: float = 0.0
