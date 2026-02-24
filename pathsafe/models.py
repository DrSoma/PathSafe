"""Data models for PathSafe scan and anonymization results."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional


@dataclass
class PHIFinding:
    """A single piece of PHI found in a file."""
    offset: int
    length: int
    tag_id: Optional[int]
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
    findings: List[PHIFinding] = field(default_factory=list)
    is_clean: bool = True
    scan_time_ms: float = 0.0
    file_size: int = 0
    error: Optional[str] = None


@dataclass
class AnonymizationResult:
    """Result of anonymizing a single file."""
    source_path: Path
    output_path: Path
    mode: str  # "copy" | "inplace"
    findings_cleared: int = 0
    verified: bool = False
    anonymization_time_ms: float = 0.0
    error: Optional[str] = None


@dataclass
class BatchResult:
    """Result of a batch anonymization run."""
    results: List[AnonymizationResult] = field(default_factory=list)
    total_files: int = 0
    files_anonymized: int = 0
    files_already_clean: int = 0
    files_skipped: int = 0
    files_errored: int = 0
    total_time_seconds: float = 0.0
    certificate_path: Optional[Path] = None
