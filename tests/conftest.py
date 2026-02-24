"""Shared test fixtures — synthetic TIFF/NDPI/SVS file generators."""

import struct
import pytest
from pathlib import Path


def build_tiff(entries, endian='<', extra_data=None):
    """Build a minimal TIFF file in memory with given IFD entries.

    Args:
        entries: List of (tag_id, type_id, count, value_or_bytes) tuples.
            For inline values (<=4 bytes), pass an int.
            For out-of-line values, pass bytes.
        endian: '<' for little-endian, '>' for big-endian.
        extra_data: Optional bytes to append after the IFD (for raw binary scanning tests).

    Returns:
        bytes: Complete TIFF file content.
    """
    bo = b'II' if endian == '<' else b'MM'
    header = bo + struct.pack(endian + 'H', 42)

    # IFD starts at offset 8
    ifd_offset = 8
    header += struct.pack(endian + 'I', ifd_offset)

    # Build IFD entries and collect out-of-line data
    num_entries = len(entries)
    ifd_header = struct.pack(endian + 'H', num_entries)

    # Out-of-line data starts after: header(8) + ifd_count(2) + entries(12*n) + next_ifd(4)
    data_offset = 8 + 2 + 12 * num_entries + 4
    entry_bytes = b''
    data_bytes = b''

    for tag_id, type_id, count, value in entries:
        if isinstance(value, bytes):
            # Out-of-line: store offset to data area
            val_offset = data_offset + len(data_bytes)
            entry_bytes += struct.pack(endian + 'HHI', tag_id, type_id, count)
            entry_bytes += struct.pack(endian + 'I', val_offset)
            # Pad value to at least 'count' bytes for ASCII
            data_bytes += value
        else:
            # Inline value
            entry_bytes += struct.pack(endian + 'HHI', tag_id, type_id, count)
            entry_bytes += struct.pack(endian + 'I', value)

    next_ifd = struct.pack(endian + 'I', 0)  # No next IFD

    result = header + ifd_header + entry_bytes + next_ifd + data_bytes
    if extra_data:
        result += extra_data
    return result


@pytest.fixture
def tmp_ndpi(tmp_path):
    """Create a synthetic NDPI file with tag 65468 containing an accession number."""
    barcode = b'AS-24-123456\x00'
    reference = b'REF-001\x00'
    datetime_val = b'2024:06:15 10:30:00\x00'

    entries = [
        (256, 3, 1, 1024),           # ImageWidth
        (257, 3, 1, 768),            # ImageLength
        (306, 2, len(datetime_val), datetime_val),   # DateTime
        (65427, 2, len(reference), reference),        # NDPI_REFERENCE
        (65468, 2, len(barcode), barcode),            # NDPI_BARCODE
    ]
    content = build_tiff(entries)
    filepath = tmp_path / 'test_slide.ndpi'
    filepath.write_bytes(content)
    return filepath


@pytest.fixture
def tmp_ndpi_clean(tmp_path):
    """Create a synthetic NDPI file that has already been anonymized."""
    barcode = b'XXXXXXXXXXXX\x00'
    reference = b'XXXXXXX\x00'
    datetime_val = b'\x00' * 20

    entries = [
        (256, 3, 1, 1024),
        (257, 3, 1, 768),
        (306, 2, len(datetime_val), datetime_val),
        (65427, 2, len(reference), reference),
        (65468, 2, len(barcode), barcode),
    ]
    content = build_tiff(entries)
    filepath = tmp_path / 'clean_slide.ndpi'
    filepath.write_bytes(content)
    return filepath


@pytest.fixture
def tmp_svs(tmp_path):
    """Create a synthetic SVS file with tag 270 containing PHI fields."""
    desc = (
        b'Aperio Image Library v12.0.16\n'
        b'1024x768 [0,0 1024x768] (256x256) JPEG Q=70'
        b'|AppMag = 40'
        b'|ScanScope ID = SS1234'
        b'|Filename = AS-24-999999.svs'
        b'|Date = 06/15/24'
        b'|Time = 10:30:00'
        b'|User = jdoe@hospital.org'
        b'|MPP = 0.2520'
        b'\x00'
    )
    entries = [
        (256, 3, 1, 1024),
        (257, 3, 1, 768),
        (270, 2, len(desc), desc),  # ImageDescription
    ]
    content = build_tiff(entries)
    filepath = tmp_path / 'test_slide.svs'
    filepath.write_bytes(content)
    return filepath


@pytest.fixture
def tmp_tiff_with_phi(tmp_path):
    """Create a generic TIFF with PHI in a string tag."""
    desc = b'Patient: AS-22-555555 scanned 2024:03:01\x00'
    entries = [
        (256, 3, 1, 512),
        (257, 3, 1, 512),
        (270, 2, len(desc), desc),
    ]
    content = build_tiff(entries)
    filepath = tmp_path / 'generic.tif'
    filepath.write_bytes(content)
    return filepath


@pytest.fixture
def tmp_ndpi_with_regex_phi(tmp_path):
    """NDPI file with PHI only detectable via regex (not in known tags)."""
    # Tag 65468 is clean, but accession number is embedded in raw data
    barcode = b'XXXXXXXXXXXX\x00'
    entries = [
        (256, 3, 1, 1024),
        (65468, 2, len(barcode), barcode),
    ]
    # Embed accession pattern in extra data area
    extra = b'\x00' * 50 + b'AC-23-987654\x00' + b'\x00' * 50
    content = build_tiff(entries, extra_data=extra)
    filepath = tmp_path / 'regex_test.ndpi'
    filepath.write_bytes(content)
    return filepath
