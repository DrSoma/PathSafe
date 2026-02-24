"""Format registry — auto-detection by extension and magic bytes."""

from pathlib import Path
from typing import Optional

from pathsafe.formats.base import FormatHandler
from pathsafe.formats.ndpi import NDPIHandler
from pathsafe.formats.svs import SVSHandler
from pathsafe.formats.mrxs import MRXSHandler
from pathsafe.formats.generic_tiff import GenericTIFFHandler

# Registered handlers in priority order (most specific first)
_HANDLERS = [
    NDPIHandler(),
    SVSHandler(),
    MRXSHandler(),
    GenericTIFFHandler(),  # Fallback for unknown TIFF-based formats
]

# Conditionally add DICOM handler if pydicom is available
try:
    from pathsafe.formats.dicom import DICOMHandler
    _HANDLERS.insert(3, DICOMHandler())  # Before GenericTIFF
except ImportError:
    pass


def detect_format(filepath: Path) -> str:
    """Detect the WSI format of a file.

    Returns format name string: "ndpi", "svs", "mrxs", "dicom", "tiff",
    or "unknown".
    """
    for handler in _HANDLERS:
        if handler.can_handle(filepath):
            return handler.format_name
    return "unknown"


def get_handler(filepath: Path) -> FormatHandler:
    """Get the appropriate format handler for a file.

    Falls back to GenericTIFFHandler if no specific handler matches.
    """
    for handler in _HANDLERS:
        if handler.can_handle(filepath):
            return handler
    return _HANDLERS[-1]  # GenericTIFF fallback


def list_supported_formats() -> list:
    """List all supported format names."""
    return [h.format_name for h in _HANDLERS]
