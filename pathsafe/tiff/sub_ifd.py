"""EXIF and GPS sub-IFD traversal and blanking."""

import struct
from typing import BinaryIO, Dict, List, Optional, Tuple

from pathsafe.tiff.parser import (
    IFDEntry,
    TIFFHeader,
    EXIF_IFD_POINTER_TAG,
    GPS_IFD_POINTER_TAG,
    read_ifd,
    read_tag_numeric,
    read_tag_value_bytes,
)

# GPS tag names (tags 0-31)
GPS_TAG_NAMES: Dict[int, str] = {
    0: 'GPSVersionID', 1: 'GPSLatitudeRef', 2: 'GPSLatitude',
    3: 'GPSLongitudeRef', 4: 'GPSLongitude', 5: 'GPSAltitudeRef',
    6: 'GPSAltitude', 7: 'GPSTimeStamp', 8: 'GPSSatellites',
    9: 'GPSStatus', 10: 'GPSMeasureMode', 11: 'GPSDOP',
    12: 'GPSSpeedRef', 13: 'GPSSpeed', 14: 'GPSTrackRef',
    15: 'GPSTrack', 16: 'GPSImgDirectionRef', 17: 'GPSImgDirection',
    18: 'GPSMapDatum', 19: 'GPSDestLatitudeRef', 20: 'GPSDestLatitude',
    21: 'GPSDestLongitudeRef', 22: 'GPSDestLongitude', 23: 'GPSDestBearingRef',
    24: 'GPSDestBearing', 25: 'GPSDestDistanceRef', 26: 'GPSDestDistance',
    27: 'GPSProcessingMethod', 28: 'GPSAreaInformation', 29: 'GPSDateStamp',
    30: 'GPSDifferential', 31: 'GPSHPositioningError',
}

# EXIF sub-IFD tags that contain PHI (dates, free text, unique IDs)
EXIF_SUB_IFD_PHI_TAGS: Dict[int, str] = {
    36867: 'DateTimeOriginal',
    36868: 'DateTimeDigitized',
    37510: 'UserComment',
    37520: 'SubSecTime',
    37521: 'SubSecTimeOriginal',
    37522: 'SubSecTimeDigitized',
    42016: 'ImageUniqueID',
}


def read_exif_sub_ifd(f: BinaryIO, header: TIFFHeader,
                      entries: List[IFDEntry]) -> Optional[Tuple[int, List[IFDEntry]]]:
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
            except (struct.error, OSError):
                pass
            return None
    return None


def read_gps_sub_ifd(f: BinaryIO, header: TIFFHeader,
                     entries: List[IFDEntry]) -> Optional[Tuple[int, List[IFDEntry]]]:
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
            except (struct.error, OSError):
                pass
            return None
    return None


def scan_exif_sub_ifd_tags(f: BinaryIO, header: TIFFHeader,
                           entries: List[IFDEntry]) -> List[Tuple[IFDEntry, str]]:
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
        if not raw or raw == b'\x00' * len(raw):
            continue
        stripped = raw.rstrip(b'\x00')
        if stripped and all(b == ord('X') for b in stripped):
            continue
        value = stripped.decode('utf-8', errors='replace')[:200]
        if value.strip():
            findings.append((entry, value))
    return findings


def scan_gps_sub_ifd(f: BinaryIO, header: TIFFHeader,
                     entries: List[IFDEntry]) -> List[Tuple[IFDEntry, str]]:
    """Scan ALL GPS sub-IFD entries -- every GPS tag is PHI (location data).

    Returns list of (entry, preview_string) for tags with non-zero content.
    """
    findings = []
    for entry in entries:
        raw = read_tag_value_bytes(f, entry)
        if not raw or raw == b'\x00' * len(raw):
            continue
        # For RATIONAL types (lat/lon), show numeric preview
        if entry.dtype in (5, 10):  # RATIONAL / SRATIONAL
            val = read_tag_numeric(f, header, entry)
            if val is not None:
                preview = f'{GPS_TAG_NAMES.get(entry.tag_id, f"GPSTag_{entry.tag_id}")}={val}'
            else:
                preview = GPS_TAG_NAMES.get(entry.tag_id, f'GPSTag_{entry.tag_id}')
        elif entry.dtype == 2:  # ASCII
            preview = raw.rstrip(b'\x00').decode('ascii', errors='replace')[:50]
        else:
            preview = GPS_TAG_NAMES.get(entry.tag_id, f'GPSTag_{entry.tag_id}')
        findings.append((entry, preview))
    return findings


def blank_exif_sub_ifd_tags(f: BinaryIO, header: TIFFHeader,
                            entries: List[IFDEntry]) -> int:
    """Blank PHI tags in an EXIF sub-IFD. Returns total bytes blanked."""
    total = 0
    for entry in entries:
        if entry.tag_id not in EXIF_SUB_IFD_PHI_TAGS:
            continue
        raw = read_tag_value_bytes(f, entry)
        if not raw or raw == b'\x00' * len(raw):
            continue
        stripped = raw.rstrip(b'\x00')
        if stripped and all(b == ord('X') for b in stripped):
            continue
        f.seek(entry.value_offset)
        f.write(b'\x00' * entry.total_size)
        total += entry.total_size
    return total


def blank_gps_sub_ifd(f: BinaryIO, header: TIFFHeader,
                      entries: List[IFDEntry]) -> int:
    """Zero out ALL GPS tag values. Returns total bytes blanked."""
    total = 0
    for entry in entries:
        raw = read_tag_value_bytes(f, entry)
        if not raw or raw == b'\x00' * len(raw):
            continue
        f.seek(entry.value_offset)
        f.write(b'\x00' * entry.total_size)
        total += entry.total_size
    return total
