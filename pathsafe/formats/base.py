"""Abstract base class for WSI format handlers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from pathsafe.models import PHIFinding, ScanResult
from pathsafe.scanner import scan_filename_for_phi


class FormatHandler(ABC):
    """Base class for all WSI format handlers.

    Each handler knows how to detect, scan, and anonymize one WSI format.
    """

    @abstractmethod
    def can_handle(self, filepath: Path) -> bool:
        """Check if this handler can process the given file.

        Should check file extension and optionally magic bytes.
        """
        ...

    @abstractmethod
    def scan(self, filepath: Path) -> ScanResult:
        """Scan a file for PHI. Read-only operation.

        Returns a ScanResult with all detected PHI findings.
        """
        ...

    @abstractmethod
    def anonymize(self, filepath: Path) -> list[PHIFinding]:
        """Anonymize PHI in a file. Modifies the file in-place.

        Returns list of PHIFinding objects describing what was cleared.
        The file at filepath must already exist (copy done by caller).
        """
        ...

    @abstractmethod
    def get_format_info(self, filepath: Path) -> dict[str, Any]:
        """Get metadata/format information about a file.

        Returns a dict with format-specific information.
        """
        ...

    def scan_filename(self, filepath: Path) -> list[PHIFinding]:
        """Scan the filename for PHI patterns (common to all formats).

        Returns PHIFinding objects for any accession numbers, SSNs, etc.
        found in the filename stem. These cannot be automatically fixed
        (would require renaming the file), so they are reported as warnings.
        """
        hits = scan_filename_for_phi(filepath)
        findings = []
        for _, length, _matched, label in hits:
            findings.append(
                PHIFinding(
                    offset=0,
                    length=length,
                    tag_id=None,
                    tag_name=f"Filename:{label}",
                    value_preview=f"{filepath.name}",
                    source="filename",
                )
            )
        return findings
