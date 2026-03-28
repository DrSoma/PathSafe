"""EXIF and GPS sub-IFD traversal and blanking."""

from __future__ import annotations

import logging
import struct
from typing import BinaryIO


logger = logging.getLogger(__name__)

from pathsafe.tiff.parser import (  # noqa: E402
    EXIF_IFD_POINTER_TAG,
    GPS_IFD_POINTER_TAG,
    IFDEntry,
    TIFFHeader,
    read_ifd,
    read_tag_long_array,
    read_tag_numeric,
    read_tag_value_bytes,
)


# TIFF SubIFD pointer tag
SUB_IFD_TAG = 330

# Maximum recursion depth for nested SubIFDs to prevent infinite loops
MAX_SUB_IFD_DEPTH = 3

# GPS tag names (tags 0-31)
GPS_TAG_NAMES: dict[int, str] = {
    0: "GPSVersionID",
    1: "GPSLatitudeRef",
    2: "GPSLatitude",
    3: "GPSLongitudeRef",
    4: "GPSLongitude",
    5: "GPSAltitudeRef",
    6: "GPSAltitude",
    7: "GPSTimeStamp",
    8: "GPSSatellites",
    9: "GPSStatus",
    10: "GPSMeasureMode",
    11: "GPSDOP",
    12: "GPSSpeedRef",
    13: "GPSSpeed",
    14: "GPSTrackRef",
    15: "GPSTrack",
    16: "GPSImgDirectionRef",
    17: "GPSImgDirection",
    18: "GPSMapDatum",
    19: "GPSDestLatitudeRef",
    20: "GPSDestLatitude",
    21: "GPSDestLongitudeRef",
    22: "GPSDestLongitude",
    23: "GPSDestBearingRef",
    24: "GPSDestBearing",
    25: "GPSDestDistanceRef",
    26: "GPSDestDistance",
    27: "GPSProcessingMethod",
    28: "GPSAreaInformation",
    29: "GPSDateStamp",
    30: "GPSDifferential",
    31: "GPSHPositioningError",
}

# EXIF sub-IFD tags that contain PHI (dates, free text, unique IDs)
EXIF_SUB_IFD_PHI_TAGS: dict[int, str] = {
    36867: "DateTimeOriginal",
    36868: "DateTimeDigitized",
    37500: "MakerNote",
    37510: "UserComment",
    37520: "SubSecTime",
    37521: "SubSecTimeOriginal",
    37522: "SubSecTimeDigitized",
    42016: "ImageUniqueID",
}


def read_exif_sub_ifd(
    f: BinaryIO, header: TIFFHeader, entries: list[IFDEntry]
) -> tuple[int, list[IFDEntry]] | None:
    """Find tag 34665 (ExifIFDPointer) and read the sub-IFD it points to.

    Returns (sub_ifd_offset, sub_entries) or None if tag not present / invalid.
    """
    for entry in entries:
        if entry.tag_id == EXIF_IFD_POINTER_TAG:
            sub_offset = read_tag_numeric(f, header, entry)
            if sub_offset is None or sub_offset == 0:
                return None
            try:
                sub_entries, _ = read_ifd(f, header, int(sub_offset))
                if sub_entries:
                    return (int(sub_offset), sub_entries)
            except (struct.error, OSError) as e:
                logger.warning("Failed to read EXIF sub-IFD at offset %d: %s", sub_offset, e)
            return None
    return None


def read_gps_sub_ifd(
    f: BinaryIO, header: TIFFHeader, entries: list[IFDEntry]
) -> tuple[int, list[IFDEntry]] | None:
    """Find tag 34853 (GPSInfoIFDPointer) and read the sub-IFD it points to.

    Returns (sub_ifd_offset, sub_entries) or None if tag not present / invalid.
    """
    for entry in entries:
        if entry.tag_id == GPS_IFD_POINTER_TAG:
            sub_offset = read_tag_numeric(f, header, entry)
            if sub_offset is None or sub_offset == 0:
                return None
            try:
                sub_entries, _ = read_ifd(f, header, int(sub_offset))
                if sub_entries:
                    return (int(sub_offset), sub_entries)
            except (struct.error, OSError) as e:
                logger.warning("Failed to read GPS sub-IFD at offset %d: %s", sub_offset, e)
            return None
    return None


def scan_exif_sub_ifd_tags(
    f: BinaryIO, header: TIFFHeader, entries: list[IFDEntry]
) -> list[tuple[IFDEntry, str]]:
    """Scan EXIF sub-IFD entries for PHI (dates, UserComment, ImageUniqueID).

    Args:
        entries: The entries of the EXIF sub-IFD (not the main IFD).

    Returns list of (entry, value_preview) for tags with non-empty, non-anonymized content.
    """
    findings = []
    for entry in entries:
        if entry.tag_id not in EXIF_SUB_IFD_PHI_TAGS:
            continue
        raw = read_tag_value_bytes(f, entry)
        if not raw or raw == b"\x00" * len(raw):
            continue
        stripped = raw.rstrip(b"\x00")
        if stripped and all(b == ord("X") for b in stripped):
            continue
        value = stripped.decode("utf-8", errors="replace")[:200]
        if value.strip():
            findings.append((entry, value))
    return findings


def scan_gps_sub_ifd(
    f: BinaryIO, header: TIFFHeader, entries: list[IFDEntry]
) -> list[tuple[IFDEntry, str]]:
    """Scan ALL GPS sub-IFD entries -- every GPS tag is PHI (location data).

    Returns list of (entry, preview_string) for tags with non-zero content.
    """
    findings = []
    for entry in entries:
        raw = read_tag_value_bytes(f, entry)
        if not raw or raw == b"\x00" * len(raw):
            continue
        # For RATIONAL types (lat/lon), show numeric preview
        if entry.dtype in (5, 10):  # RATIONAL / SRATIONAL
            val = read_tag_numeric(f, header, entry)
            if val is not None:
                preview = f"{GPS_TAG_NAMES.get(entry.tag_id, f'GPSTag_{entry.tag_id}')}={val}"
            else:
                preview = GPS_TAG_NAMES.get(entry.tag_id, f"GPSTag_{entry.tag_id}")
        elif entry.dtype == 2:  # ASCII
            preview = raw.rstrip(b"\x00").decode("ascii", errors="replace")[:50]
        else:
            preview = GPS_TAG_NAMES.get(entry.tag_id, f"GPSTag_{entry.tag_id}")
        findings.append((entry, preview))
    return findings


def blank_exif_sub_ifd_tags(f: BinaryIO, header: TIFFHeader, entries: list[IFDEntry]) -> int:
    """Blank PHI tags in an EXIF sub-IFD. Returns total bytes blanked."""
    total = 0
    for entry in entries:
        if entry.tag_id not in EXIF_SUB_IFD_PHI_TAGS:
            continue
        raw = read_tag_value_bytes(f, entry)
        if not raw or raw == b"\x00" * len(raw):
            continue
        stripped = raw.rstrip(b"\x00")
        if stripped and all(b == ord("X") for b in stripped):
            continue
        f.seek(entry.value_offset)
        f.write(b"\x00" * entry.total_size)
        total += entry.total_size
    return total


def blank_gps_sub_ifd(f: BinaryIO, header: TIFFHeader, entries: list[IFDEntry]) -> int:
    """Zero out ALL GPS tag values. Returns total bytes blanked."""
    total = 0
    for entry in entries:
        raw = read_tag_value_bytes(f, entry)
        if not raw or raw == b"\x00" * len(raw):
            continue
        f.seek(entry.value_offset)
        f.write(b"\x00" * entry.total_size)
        total += entry.total_size
    return total


# ----------------------------------------------------------------
# TIFF SubIFD (tag 330) traversal
# ----------------------------------------------------------------

# PHI-bearing tags to check inside SubIFDs (same set as main IFD scans)
_SUB_IFD_PHI_TAGS: dict[int, str] = {
    270: "ImageDescription",
    305: "Software",
    306: "DateTime",
    315: "Artist",
    316: "HostComputer",
    700: "XMP",
    33432: "Copyright",
    33723: "IPTC",
    34675: "ICCProfile",
    36867: "DateTimeOriginal",
    36868: "DateTimeDigitized",
    37500: "MakerNote",
    37510: "UserComment",
    42016: "ImageUniqueID",
}


def read_sub_ifds(
    f: BinaryIO, header: TIFFHeader, entries: list[IFDEntry]
) -> list[tuple[int, list[IFDEntry]]]:
    """Find tag 330 (SubIFDs) and read each sub-IFD it points to.

    Tag 330 contains one or more LONG offsets pointing to child IFDs.
    Returns list of (sub_ifd_offset, sub_entries) pairs, or empty list
    if tag not present or invalid.
    """
    for entry in entries:
        if entry.tag_id == SUB_IFD_TAG:
            offsets = read_tag_long_array(f, header, entry)
            if not offsets:
                return []
            results = []
            for sub_offset in offsets:
                if sub_offset == 0:
                    continue
                try:
                    sub_entries, _ = read_ifd(f, header, sub_offset)
                    if sub_entries:
                        results.append((sub_offset, sub_entries))
                except (struct.error, OSError) as e:
                    logger.warning("Failed to read SubIFD at offset %d: %s", sub_offset, e)
            return results
    return []


def scan_sub_ifds(
    f: BinaryIO, header: TIFFHeader, entries: list[IFDEntry], depth: int = 0
) -> list[tuple[IFDEntry, str]]:
    """Recursively scan SubIFDs (tag 330) for PHI-bearing tags.

    Traverses nested SubIFDs up to MAX_SUB_IFD_DEPTH to prevent
    infinite recursion from circular pointers.

    Returns list of (entry, value_preview) for tags with non-empty content.
    """
    if depth >= MAX_SUB_IFD_DEPTH:
        return []

    findings: list[tuple[IFDEntry, str]] = []
    sub_ifds = read_sub_ifds(f, header, entries)

    for _, sub_entries in sub_ifds:
        # Scan PHI-bearing tags in this SubIFD
        for sub_entry in sub_entries:
            if sub_entry.tag_id not in _SUB_IFD_PHI_TAGS:
                continue
            if sub_entry.dtype not in (2, 7):  # ASCII or UNDEFINED
                continue
            raw = read_tag_value_bytes(f, sub_entry)
            if not raw or raw == b"\x00" * len(raw):
                continue
            stripped = raw.rstrip(b"\x00")
            if stripped and all(b == ord("X") for b in stripped):
                continue
            value = stripped.decode("utf-8", errors="replace")[:200]
            if value.strip():
                findings.append((sub_entry, value))

        # Also check for EXIF/GPS sub-IFDs within the SubIFD
        exif_result = read_exif_sub_ifd(f, header, sub_entries)
        if exif_result is not None:
            _, exif_entries = exif_result
            findings.extend(scan_exif_sub_ifd_tags(f, header, exif_entries))

        gps_result = read_gps_sub_ifd(f, header, sub_entries)
        if gps_result is not None:
            _, gps_entries = gps_result
            findings.extend(scan_gps_sub_ifd(f, header, gps_entries))

        # Recurse into nested SubIFDs
        findings.extend(scan_sub_ifds(f, header, sub_entries, depth + 1))

    return findings


def blank_sub_ifds(f: BinaryIO, header: TIFFHeader, entries: list[IFDEntry], depth: int = 0) -> int:
    """Recursively blank PHI-bearing tags in SubIFDs (tag 330).

    Returns total bytes blanked across all nested SubIFDs.
    """
    if depth >= MAX_SUB_IFD_DEPTH:
        return 0

    total = 0
    sub_ifds = read_sub_ifds(f, header, entries)

    for _, sub_entries in sub_ifds:
        # Blank PHI-bearing tags in this SubIFD
        for sub_entry in sub_entries:
            if sub_entry.tag_id not in _SUB_IFD_PHI_TAGS:
                continue
            if sub_entry.dtype not in (2, 7):
                continue
            raw = read_tag_value_bytes(f, sub_entry)
            if not raw or raw == b"\x00" * len(raw):
                continue
            stripped = raw.rstrip(b"\x00")
            if stripped and all(b == ord("X") for b in stripped):
                continue
            f.seek(sub_entry.value_offset)
            f.write(b"\x00" * sub_entry.total_size)
            total += sub_entry.total_size

        # Blank EXIF/GPS sub-IFDs within the SubIFD
        exif_result = read_exif_sub_ifd(f, header, sub_entries)
        if exif_result is not None:
            _, exif_entries = exif_result
            total += blank_exif_sub_ifd_tags(f, header, exif_entries)

        gps_result = read_gps_sub_ifd(f, header, sub_entries)
        if gps_result is not None:
            _, gps_entries = gps_result
            total += blank_gps_sub_ifd(f, header, gps_entries)

        # Recurse into nested SubIFDs
        total += blank_sub_ifds(f, header, sub_entries, depth + 1)

    return total
