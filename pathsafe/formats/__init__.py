"""Format registry -- auto-detection by extension and magic bytes."""

from __future__ import annotations

from pathlib import Path

from pathsafe.formats.base import FormatHandler
from pathsafe.formats.bif import BIFHandler
from pathsafe.formats.generic_tiff import GenericTIFFHandler
from pathsafe.formats.mrxs import MRXSHandler
from pathsafe.formats.ndpi import NDPIHandler
from pathsafe.formats.scn import SCNHandler
from pathsafe.formats.svs import SVSHandler


# Registered handlers in priority order (most specific first)
_HANDLERS = [
    NDPIHandler(),
    SVSHandler(),
    MRXSHandler(),
    BIFHandler(),
    SCNHandler(),
    GenericTIFFHandler(),  # Fallback for unknown TIFF-based formats
]

# DICOM handler loaded lazily on first use to avoid importing pydicom/numpy
# at startup (~250ms savings). Inserted when a .dcm/.dicom file is encountered.
_DICOM_LOADED = False


def _ensure_dicom_handler():
    """Lazily load and register the DICOM handler on first use."""
    global _DICOM_LOADED
    if _DICOM_LOADED:
        return
    _DICOM_LOADED = True
    try:
        from pathsafe.formats.dicom import DICOMHandler

        _HANDLERS.insert(5, DICOMHandler())  # Before GenericTIFF
    except ImportError:
        pass


def detect_format(filepath: Path) -> str:
    """Detect the WSI format of a file.

    Returns format name string: "ndpi", "svs", "mrxs", "dicom", "tiff",
    or "unknown".
    """
    # Lazy-load DICOM handler when a DICOM file is encountered
    if filepath.suffix.lower() in (".dcm", ".dicom"):
        _ensure_dicom_handler()
    for handler in _HANDLERS:
        if handler.can_handle(filepath):
            return handler.format_name
    return "unknown"


def get_handler(filepath: Path) -> FormatHandler:
    """Get the appropriate format handler for a file.

    Falls back to GenericTIFFHandler if no specific handler matches.
    """
    if filepath.suffix.lower() in (".dcm", ".dicom"):
        _ensure_dicom_handler()
    for handler in _HANDLERS:
        if handler.can_handle(filepath):
            return handler
    return _HANDLERS[-1]  # GenericTIFF fallback


def list_supported_formats() -> list[str]:
    """List all supported format names."""
    return [h.format_name for h in _HANDLERS]
