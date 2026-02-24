"""Shared test fixtures — synthetic TIFF/NDPI/SVS/BIF/SCN/MRXS file generators."""

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


def build_tiff_multi_ifd(ifd_entries_list, endian='<'):
    """Build a TIFF with multiple linked IFDs.

    Args:
        ifd_entries_list: List of lists, each inner list contains
            (tag_id, type_id, count, value_or_bytes) tuples for one IFD.
        endian: '<' or '>'.

    Returns:
        bytes: Complete TIFF file with chained IFDs.
    """
    bo = b'II' if endian == '<' else b'MM'

    # Pre-compute out-of-line data sizes for layout calculation
    ool_sizes = []
    for entries in ifd_entries_list:
        ool_sizes.append(sum(len(v) for _, _, _, v in entries if isinstance(v, bytes)))

    # Compute start offset for each IFD
    ifd_starts = []
    offset = 8  # After header
    for i, entries in enumerate(ifd_entries_list):
        ifd_starts.append(offset)
        n = len(entries)
        offset += 2 + 12 * n + 4 + ool_sizes[i]

    # Build header
    result = bo + struct.pack(endian + 'H', 42)
    result += struct.pack(endian + 'I', ifd_starts[0])

    # Build each IFD
    for i, entries in enumerate(ifd_entries_list):
        n = len(entries)
        data_start = ifd_starts[i] + 2 + 12 * n + 4

        ifd_bytes = struct.pack(endian + 'H', n)
        data_bytes = b''

        for tag_id, type_id, count, value in entries:
            if isinstance(value, bytes):
                val_offset = data_start + len(data_bytes)
                ifd_bytes += struct.pack(endian + 'HHI', tag_id, type_id, count)
                ifd_bytes += struct.pack(endian + 'I', val_offset)
                data_bytes += value
            else:
                ifd_bytes += struct.pack(endian + 'HHI', tag_id, type_id, count)
                ifd_bytes += struct.pack(endian + 'I', value)

        # Next IFD offset
        if i + 1 < len(ifd_entries_list):
            next_ifd = ifd_starts[i + 1]
        else:
            next_ifd = 0
        ifd_bytes += struct.pack(endian + 'I', next_ifd)

        result += ifd_bytes + data_bytes

    return result


def build_tiff_with_strips(tag_entries, strip_data, endian='<'):
    """Build a TIFF with tag entries and image strip data.

    Automatically adds StripOffsets (273) and StripByteCounts (279) entries.

    Args:
        tag_entries: List of (tag_id, type_id, count, value_or_bytes) tuples.
        strip_data: bytes of image data for a single strip.
        endian: '<' or '>'.

    Returns:
        bytes: Complete TIFF file with strip data.
    """
    bo = b'II' if endian == '<' else b'MM'

    # Count out-of-line data from tag entries
    ool_data_size = sum(len(v) for _, _, _, v in tag_entries if isinstance(v, bytes))

    num_entries = len(tag_entries) + 2  # +2 for StripOffsets/StripByteCounts

    # Layout: header(8) + ifd_count(2) + entries(12*n) + next_ifd(4) + ool_data + strip_data
    data_start = 8 + 2 + 12 * num_entries + 4
    strip_data_offset = data_start + ool_data_size

    # Build entries
    ifd_header = struct.pack(endian + 'H', num_entries)
    entry_bytes = b''
    data_bytes = b''

    for tag_id, type_id, count, value in tag_entries:
        if isinstance(value, bytes):
            val_offset = data_start + len(data_bytes)
            entry_bytes += struct.pack(endian + 'HHI', tag_id, type_id, count)
            entry_bytes += struct.pack(endian + 'I', val_offset)
            data_bytes += value
        else:
            entry_bytes += struct.pack(endian + 'HHI', tag_id, type_id, count)
            entry_bytes += struct.pack(endian + 'I', value)

    # StripOffsets (273): LONG, count=1, inline value = strip_data_offset
    entry_bytes += struct.pack(endian + 'HHI', 273, 4, 1)
    entry_bytes += struct.pack(endian + 'I', strip_data_offset)

    # StripByteCounts (279): LONG, count=1, inline value = len(strip_data)
    entry_bytes += struct.pack(endian + 'HHI', 279, 4, 1)
    entry_bytes += struct.pack(endian + 'I', len(strip_data))

    next_ifd = struct.pack(endian + 'I', 0)
    header = bo + struct.pack(endian + 'H', 42) + struct.pack(endian + 'I', 8)

    return header + ifd_header + entry_bytes + next_ifd + data_bytes + strip_data


# ---------------------------------------------------------------------------
# NDPI fixtures
# ---------------------------------------------------------------------------

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
def tmp_tiff_clean(tmp_path):
    """Create a generic TIFF with no PHI."""
    entries = [
        (256, 3, 1, 512),
        (257, 3, 1, 512),
    ]
    content = build_tiff(entries)
    filepath = tmp_path / 'clean.tif'
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


# ---------------------------------------------------------------------------
# BIF fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_bif(tmp_path):
    """Create a synthetic BIF file with XMP PHI in tag 700."""
    xmp = (
        b'<?xpacket begin="" id="W5M0MpCehiHzreSzNTczkc9d"?>'
        b'<x:xmpmeta xmlns:x="adobe:ns:meta/">'
        b'<iScan BarCode1="AS-24-111111" ScanDate="2024-06-15" '
        b'OperatorID="jdoe" UniqueID="ABC123"/>'
        b'</x:xmpmeta>'
        b'<?xpacket end="w"?>\x00'
    )
    datetime_val = b'2024:06:15 10:30:00\x00'

    entries = [
        (256, 3, 1, 1024),
        (257, 3, 1, 768),
        (306, 2, len(datetime_val), datetime_val),  # DateTime
        (700, 7, len(xmp), xmp),  # XMP (UNDEFINED type)
    ]
    content = build_tiff(entries)
    filepath = tmp_path / 'test_slide.bif'
    filepath.write_bytes(content)
    return filepath


@pytest.fixture
def tmp_bif_clean(tmp_path):
    """Create a synthetic BIF file that has already been anonymized."""
    xmp = (
        b'<?xpacket begin="" id="W5M0MpCehiHzreSzNTczkc9d"?>'
        b'<x:xmpmeta xmlns:x="adobe:ns:meta/">'
        b'<iScan BarCode1="XXXXXXXXXXXX" ScanDate="XXXXXXXXXX" '
        b'OperatorID="XXXX" UniqueID="XXXXXX"/>'
        b'</x:xmpmeta>'
        b'<?xpacket end="w"?>\x00'
    )
    datetime_val = b'\x00' * 20

    entries = [
        (256, 3, 1, 1024),
        (257, 3, 1, 768),
        (306, 2, len(datetime_val), datetime_val),
        (700, 7, len(xmp), xmp),
    ]
    content = build_tiff(entries)
    filepath = tmp_path / 'clean_slide.bif'
    filepath.write_bytes(content)
    return filepath


# ---------------------------------------------------------------------------
# SCN fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_scn(tmp_path):
    """Create a synthetic SCN file with XML PHI in tag 270."""
    xml = (
        b'<?xml version="1.0" encoding="UTF-8"?>'
        b'<scn xmlns="http://www.leica-microsystems.com/scn/2010/10/01">'
        b'<collection>'
        b'<barcode>AS-24-222222</barcode>'
        b'<creationDate>2024-06-15T10:30:00</creationDate>'
        b'<device>Leica SCN400</device>'
        b'<user>operator1</user>'
        b'</collection>'
        b'</scn>\x00'
    )
    datetime_val = b'2024:06:15 10:30:00\x00'

    entries = [
        (256, 3, 1, 1024),
        (257, 3, 1, 768),
        (270, 2, len(xml), xml),  # ImageDescription with XML
        (306, 2, len(datetime_val), datetime_val),  # DateTime
    ]
    content = build_tiff(entries)
    filepath = tmp_path / 'test_slide.scn'
    filepath.write_bytes(content)
    return filepath


@pytest.fixture
def tmp_scn_clean(tmp_path):
    """Create a synthetic SCN file that has already been anonymized."""
    xml = (
        b'<?xml version="1.0" encoding="UTF-8"?>'
        b'<scn xmlns="http://www.leica-microsystems.com/scn/2010/10/01">'
        b'<collection>'
        b'<barcode>XXXXXXXXXXXX</barcode>'
        b'<creationDate>XXXXXXXXXXXXXXXXXXX</creationDate>'
        b'<device>XXXXXXXXXXXXX</device>'
        b'<user>XXXXXXXXX</user>'
        b'</collection>'
        b'</scn>\x00'
    )
    datetime_val = b'\x00' * 20

    entries = [
        (256, 3, 1, 1024),
        (257, 3, 1, 768),
        (270, 2, len(xml), xml),
        (306, 2, len(datetime_val), datetime_val),
    ]
    content = build_tiff(entries)
    filepath = tmp_path / 'clean_slide.scn'
    filepath.write_bytes(content)
    return filepath


# ---------------------------------------------------------------------------
# MRXS fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_mrxs(tmp_path):
    """Create a synthetic MRXS file with companion directory and Slidedat.ini."""
    # .mrxs file (can be minimal — MRXS handler just checks extension)
    filepath = tmp_path / 'test_slide.mrxs'
    filepath.write_bytes(b'MIRAX\x00')

    # Companion data directory
    data_dir = tmp_path / 'test_slide'
    data_dir.mkdir()

    # Slidedat.ini with PHI fields
    slidedat = data_dir / 'Slidedat.ini'
    slidedat.write_text(
        '[GENERAL]\n'
        'SLIDE_ID = 12345\n'
        'SLIDE_NAME = Patient Smith\n'
        'SLIDE_BARCODE = AS-24-333333\n'
        'SLIDE_CREATIONDATETIME = 20240615120000\n'
        'OBJECTIVE_MAGNIFICATION = 40\n'
        '[HIERARCHICAL]\n'
        'NONHIER_COUNT = 0\n',
        encoding='utf-8',
    )
    return filepath


@pytest.fixture
def tmp_mrxs_clean(tmp_path):
    """Create a synthetic MRXS file that has already been anonymized."""
    filepath = tmp_path / 'clean_slide.mrxs'
    filepath.write_bytes(b'MIRAX\x00')

    data_dir = tmp_path / 'clean_slide'
    data_dir.mkdir()

    slidedat = data_dir / 'Slidedat.ini'
    slidedat.write_text(
        '[GENERAL]\n'
        'SLIDE_ID = XXXXX\n'
        'SLIDE_NAME = XXXXXXXXXXXXX\n'
        'SLIDE_BARCODE = XXXXXXXXXXXX\n'
        'SLIDE_CREATIONDATETIME = 19000101000000\n'
        'OBJECTIVE_MAGNIFICATION = 40\n'
        '[HIERARCHICAL]\n'
        'NONHIER_COUNT = 0\n',
        encoding='utf-8',
    )
    return filepath


@pytest.fixture
def tmp_mrxs_no_companion(tmp_path):
    """Create an MRXS file without its companion directory."""
    filepath = tmp_path / 'orphan_slide.mrxs'
    filepath.write_bytes(b'MIRAX\x00')
    return filepath


# ---------------------------------------------------------------------------
# Multi-IFD and integrity fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_tiff_with_strips(tmp_path):
    """Create a TIFF file with actual strip data for integrity testing."""
    strip_data = b'\xAB\xCD\xEF' * 100  # 300 bytes of image data
    tag_entries = [
        (256, 3, 1, 64),   # ImageWidth
        (257, 3, 1, 64),   # ImageLength
    ]
    content = build_tiff_with_strips(tag_entries, strip_data)
    filepath = tmp_path / 'strips.tif'
    filepath.write_bytes(content)
    return filepath


@pytest.fixture
def tmp_tiff_multi_ifd(tmp_path):
    """Create a TIFF file with two linked IFDs, both containing DateTime."""
    datetime1 = b'2024:06:15 10:30:00\x00'
    datetime2 = b'2024:06:15 10:31:00\x00'

    ifd0 = [
        (256, 3, 1, 1024),
        (257, 3, 1, 768),
        (306, 2, len(datetime1), datetime1),
    ]
    ifd1 = [
        (256, 3, 1, 512),
        (257, 3, 1, 384),
        (306, 2, len(datetime2), datetime2),
    ]
    content = build_tiff_multi_ifd([ifd0, ifd1])
    filepath = tmp_path / 'multi_ifd.tif'
    filepath.write_bytes(content)
    return filepath


def build_tiff_multi_ifd_with_strips(ifd_specs, endian='<'):
    """Build a TIFF with multiple linked IFDs, each optionally having strip data.

    Args:
        ifd_specs: List of (tag_entries, strip_data_or_None) tuples.
            tag_entries: list of (tag_id, type_id, count, value_or_bytes).
            strip_data: bytes of image data, or None for no strip data.
        endian: '<' or '>'.

    Returns:
        bytes: Complete TIFF file with chained IFDs and strip data.
    """
    bo = b'II' if endian == '<' else b'MM'

    # Each IFD needs: 2 (count) + 12*n (entries) + 4 (next ptr) + ool_data + strip_data
    # If strip_data is provided, we auto-add StripOffsets(273) + StripByteCounts(279)

    # First pass: compute sizes
    ifd_infos = []
    for tag_entries, strip_data in ifd_specs:
        extra_tags = 2 if strip_data else 0
        n = len(tag_entries) + extra_tags
        ool_size = sum(len(v) for _, _, _, v in tag_entries if isinstance(v, bytes))
        strip_size = len(strip_data) if strip_data else 0
        ifd_infos.append((n, ool_size, strip_size, tag_entries, strip_data))

    # Second pass: compute start offsets
    ifd_starts = []
    offset = 8  # After header
    for n, ool_size, strip_size, _, _ in ifd_infos:
        ifd_starts.append(offset)
        offset += 2 + 12 * n + 4 + ool_size + strip_size

    # Build header
    result = bo + struct.pack(endian + 'H', 42)
    result += struct.pack(endian + 'I', ifd_starts[0])

    # Build each IFD
    for i, (n, ool_size, strip_size, tag_entries, strip_data) in enumerate(ifd_infos):
        data_start = ifd_starts[i] + 2 + 12 * n + 4
        strip_data_offset = data_start + ool_size

        ifd_bytes = struct.pack(endian + 'H', n)
        data_bytes = b''

        for tag_id, type_id, count, value in tag_entries:
            if isinstance(value, bytes):
                val_offset = data_start + len(data_bytes)
                ifd_bytes += struct.pack(endian + 'HHI', tag_id, type_id, count)
                ifd_bytes += struct.pack(endian + 'I', val_offset)
                data_bytes += value
            else:
                ifd_bytes += struct.pack(endian + 'HHI', tag_id, type_id, count)
                ifd_bytes += struct.pack(endian + 'I', value)

        if strip_data:
            # StripOffsets (273)
            ifd_bytes += struct.pack(endian + 'HHI', 273, 4, 1)
            ifd_bytes += struct.pack(endian + 'I', strip_data_offset)
            # StripByteCounts (279)
            ifd_bytes += struct.pack(endian + 'HHI', 279, 4, 1)
            ifd_bytes += struct.pack(endian + 'I', len(strip_data))

        # Next IFD offset
        if i + 1 < len(ifd_infos):
            next_ifd = ifd_starts[i + 1]
        else:
            next_ifd = 0
        ifd_bytes += struct.pack(endian + 'I', next_ifd)

        result += ifd_bytes + data_bytes
        if strip_data:
            result += strip_data

    return result


def build_bigtiff(entries, endian='<'):
    """Build a minimal BigTIFF file in memory.

    Args:
        entries: List of (tag_id, type_id, count, value_or_bytes) tuples.
        endian: '<' or '>'.

    Returns:
        bytes: Complete BigTIFF file content.
    """
    bo = b'II' if endian == '<' else b'MM'
    # BigTIFF header: byte order(2) + magic 43(2) + bytesize 8(2) + reserved(2) + first_ifd_offset(8)
    ifd_offset = 16  # After 16-byte header

    num_entries = len(entries)
    # IFD: entry_count(8) + entries(20*n) + next_ifd(8)
    data_start = ifd_offset + 8 + 20 * num_entries + 8

    header = bo + struct.pack(endian + 'H', 43)
    header += struct.pack(endian + 'H', 8)  # bytesize
    header += struct.pack(endian + 'H', 0)  # reserved
    header += struct.pack(endian + 'Q', ifd_offset)

    ifd_bytes = struct.pack(endian + 'Q', num_entries)
    data_bytes = b''

    for tag_id, type_id, count, value in entries:
        if isinstance(value, bytes):
            val_offset = data_start + len(data_bytes)
            ifd_bytes += struct.pack(endian + 'HH', tag_id, type_id)
            ifd_bytes += struct.pack(endian + 'Q', count)
            ifd_bytes += struct.pack(endian + 'Q', val_offset)
            data_bytes += value
        else:
            ifd_bytes += struct.pack(endian + 'HH', tag_id, type_id)
            ifd_bytes += struct.pack(endian + 'Q', count)
            # Inline: value stored in the 8-byte value/offset field
            ifd_bytes += struct.pack(endian + 'Q', value)

    ifd_bytes += struct.pack(endian + 'Q', 0)  # next IFD = 0
    return header + ifd_bytes + data_bytes


def build_bigtiff_multi_ifd(ifd_entries_list, endian='<'):
    """Build a BigTIFF with multiple linked IFDs.

    Args:
        ifd_entries_list: List of entry lists for each IFD.
        endian: '<' or '>'.

    Returns:
        bytes: Complete BigTIFF file with chained IFDs.
    """
    bo = b'II' if endian == '<' else b'MM'

    # Pre-compute out-of-line data sizes
    ool_sizes = []
    for entries in ifd_entries_list:
        ool_sizes.append(sum(len(v) for _, _, _, v in entries if isinstance(v, bytes)))

    # Compute start offset for each IFD
    ifd_starts = []
    offset = 16  # After 16-byte BigTIFF header
    for i, entries in enumerate(ifd_entries_list):
        ifd_starts.append(offset)
        n = len(entries)
        # entry_count(8) + entries(20*n) + next_ifd(8) + ool_data
        offset += 8 + 20 * n + 8 + ool_sizes[i]

    # Build header
    result = bo + struct.pack(endian + 'H', 43)
    result += struct.pack(endian + 'H', 8)
    result += struct.pack(endian + 'H', 0)
    result += struct.pack(endian + 'Q', ifd_starts[0])

    # Build each IFD
    for i, entries in enumerate(ifd_entries_list):
        n = len(entries)
        data_start = ifd_starts[i] + 8 + 20 * n + 8

        ifd_bytes = struct.pack(endian + 'Q', n)
        data_bytes = b''

        for tag_id, type_id, count, value in entries:
            if isinstance(value, bytes):
                val_offset = data_start + len(data_bytes)
                ifd_bytes += struct.pack(endian + 'HH', tag_id, type_id)
                ifd_bytes += struct.pack(endian + 'Q', count)
                ifd_bytes += struct.pack(endian + 'Q', val_offset)
                data_bytes += value
            else:
                ifd_bytes += struct.pack(endian + 'HH', tag_id, type_id)
                ifd_bytes += struct.pack(endian + 'Q', count)
                ifd_bytes += struct.pack(endian + 'Q', value)

        # Next IFD offset
        if i + 1 < len(ifd_entries_list):
            next_ifd = ifd_starts[i + 1]
        else:
            next_ifd = 0
        ifd_bytes += struct.pack(endian + 'Q', next_ifd)

        result += ifd_bytes + data_bytes

    return result


# ---------------------------------------------------------------------------
# Filename PHI fixtures
# ---------------------------------------------------------------------------

def build_tiff_multi_strip(tag_entries, strip_data_list, endian='<'):
    """Build a TIFF with multiple strips and given tag entries.

    Automatically adds StripOffsets (273) and StripByteCounts (279) entries
    for the given strips, stored out-of-line when there are multiple strips.

    Args:
        tag_entries: List of (tag_id, type_id, count, value_or_bytes) tuples.
        strip_data_list: List of bytes objects, one per strip.
        endian: '<' or '>'.

    Returns:
        bytes: Complete TIFF file with multiple strips.
    """
    bo = b'II' if endian == '<' else b'MM'
    num_strips = len(strip_data_list)

    # Count out-of-line data from tag entries
    ool_data_size = sum(len(v) for _, _, _, v in tag_entries if isinstance(v, bytes))

    num_entries = len(tag_entries) + 2  # +2 for StripOffsets/StripByteCounts

    # Layout: header(8) + ifd_count(2) + entries(12*n) + next_ifd(4) + ool_data
    data_start = 8 + 2 + 12 * num_entries + 4

    if num_strips == 1:
        # Single strip: inline values, strip data right after ool_data
        strip_data_start = data_start + ool_data_size
        strip_offsets = [strip_data_start]
        strip_counts = [len(strip_data_list[0])]
    else:
        # Multi-strip: out-of-line arrays + strip data
        offsets_array_start = data_start + ool_data_size
        counts_array_start = offsets_array_start + 4 * num_strips
        strip_data_start = counts_array_start + 4 * num_strips

        strip_offsets = []
        offset = strip_data_start
        for sd in strip_data_list:
            strip_offsets.append(offset)
            offset += len(sd)
        strip_counts = [len(sd) for sd in strip_data_list]

    # Build IFD entries
    ifd_header = struct.pack(endian + 'H', num_entries)
    entry_bytes = b''
    data_bytes = b''

    for tag_id, type_id, count, value in tag_entries:
        if isinstance(value, bytes):
            val_offset = data_start + len(data_bytes)
            entry_bytes += struct.pack(endian + 'HHI', tag_id, type_id, count)
            entry_bytes += struct.pack(endian + 'I', val_offset)
            data_bytes += value
        else:
            entry_bytes += struct.pack(endian + 'HHI', tag_id, type_id, count)
            entry_bytes += struct.pack(endian + 'I', value)

    # StripOffsets (273)
    if num_strips == 1:
        entry_bytes += struct.pack(endian + 'HHI', 273, 4, 1)
        entry_bytes += struct.pack(endian + 'I', strip_offsets[0])
    else:
        entry_bytes += struct.pack(endian + 'HHI', 273, 4, num_strips)
        entry_bytes += struct.pack(endian + 'I', offsets_array_start)

    # StripByteCounts (279)
    if num_strips == 1:
        entry_bytes += struct.pack(endian + 'HHI', 279, 4, 1)
        entry_bytes += struct.pack(endian + 'I', strip_counts[0])
    else:
        entry_bytes += struct.pack(endian + 'HHI', 279, 4, num_strips)
        entry_bytes += struct.pack(endian + 'I', counts_array_start)

    next_ifd = struct.pack(endian + 'I', 0)
    header = bo + struct.pack(endian + 'H', 42) + struct.pack(endian + 'I', 8)

    result = header + ifd_header + entry_bytes + next_ifd + data_bytes

    # Append out-of-line strip offset/count arrays (multi-strip only)
    if num_strips > 1:
        for so in strip_offsets:
            result += struct.pack(endian + 'I', so)
        for sc in strip_counts:
            result += struct.pack(endian + 'I', sc)

    # Append strip data
    for sd in strip_data_list:
        result += sd

    return result


@pytest.fixture
def tmp_ndpi_phi_filename(tmp_path):
    """NDPI file whose filename contains an accession number."""
    barcode = b'XXXXXXXXXXXX\x00'
    entries = [
        (256, 3, 1, 1024),
        (257, 3, 1, 768),
        (65468, 2, len(barcode), barcode),
    ]
    content = build_tiff(entries)
    filepath = tmp_path / 'AS-24-999999.ndpi'
    filepath.write_bytes(content)
    return filepath


# ---------------------------------------------------------------------------
# EXIF / GPS sub-IFD fixtures
# ---------------------------------------------------------------------------

def build_tiff_with_sub_ifd(main_entries, sub_ifd_entries, pointer_tag, endian='<'):
    """Build a TIFF where the main IFD has a LONG pointer tag to a sub-IFD.

    Two-pass layout: first computes sub-IFD offset, then writes everything.

    Args:
        main_entries: List of (tag_id, type_id, count, value_or_bytes) for the main IFD.
            Do NOT include the pointer tag — it will be added automatically.
        sub_ifd_entries: List of (tag_id, type_id, count, value_or_bytes) for the sub-IFD.
        pointer_tag: 34665 (EXIF) or 34853 (GPS).
        endian: '<' or '>'.

    Returns:
        bytes: Complete TIFF file.
    """
    bo = b'II' if endian == '<' else b'MM'

    # The main IFD gets one extra entry: the pointer tag
    all_main = list(main_entries) + [(pointer_tag, 4, 1, 0)]  # placeholder offset
    num_main = len(all_main)

    # Main IFD layout: header(8) + count(2) + entries(12*n) + next_ptr(4)
    main_ool_start = 8 + 2 + 12 * num_main + 4
    main_ool_size = sum(len(v) for _, _, _, v in main_entries if isinstance(v, bytes))

    # Sub-IFD starts right after main IFD + its out-of-line data
    sub_ifd_offset = main_ool_start + main_ool_size

    num_sub = len(sub_ifd_entries)
    sub_ool_start = sub_ifd_offset + 2 + 12 * num_sub + 4

    # Build header
    result = bo + struct.pack(endian + 'H', 42) + struct.pack(endian + 'I', 8)

    # Build main IFD entries
    ifd_bytes = struct.pack(endian + 'H', num_main)
    data_bytes = b''

    for tag_id, type_id, count, value in main_entries:
        if isinstance(value, bytes):
            val_offset = main_ool_start + len(data_bytes)
            ifd_bytes += struct.pack(endian + 'HHI', tag_id, type_id, count)
            ifd_bytes += struct.pack(endian + 'I', val_offset)
            data_bytes += value
        else:
            ifd_bytes += struct.pack(endian + 'HHI', tag_id, type_id, count)
            ifd_bytes += struct.pack(endian + 'I', value)

    # Pointer tag entry: LONG (type 4), count 1, value = sub_ifd_offset
    ifd_bytes += struct.pack(endian + 'HHI', pointer_tag, 4, 1)
    ifd_bytes += struct.pack(endian + 'I', sub_ifd_offset)

    # Next IFD = 0
    ifd_bytes += struct.pack(endian + 'I', 0)

    result += ifd_bytes + data_bytes

    # Build sub-IFD
    sub_ifd_bytes = struct.pack(endian + 'H', num_sub)
    sub_data = b''

    for tag_id, type_id, count, value in sub_ifd_entries:
        if isinstance(value, bytes):
            val_offset = sub_ool_start + len(sub_data)
            sub_ifd_bytes += struct.pack(endian + 'HHI', tag_id, type_id, count)
            sub_ifd_bytes += struct.pack(endian + 'I', val_offset)
            sub_data += value
        else:
            sub_ifd_bytes += struct.pack(endian + 'HHI', tag_id, type_id, count)
            sub_ifd_bytes += struct.pack(endian + 'I', value)

    # Next IFD pointer for sub-IFD = 0
    sub_ifd_bytes += struct.pack(endian + 'I', 0)

    result += sub_ifd_bytes + sub_data
    return result
