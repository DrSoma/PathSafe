"""Stress tests — unsorted IFD tag ordering from real scanners."""

import io
import struct

import pytest

from pathsafe.tiff import (
    read_header, iter_ifds, read_ifd, read_tag_string,
    blank_ifd_image_data, scan_extra_metadata_tags,
)
from pathsafe.formats.ndpi import NDPIHandler
from tests.conftest import build_tiff, build_tiff_with_strips


def _build_tiff_ordered(entries_with_strips, strip_data, endian='<'):
    """Build a TIFF where entries appear in the given order.

    StripOffsets (273) and StripByteCounts (279) entries in the list
    must use placeholder value 0 — they will be patched to point at
    strip_data appended via extra_data.
    """
    ool_size = sum(len(v) for _, _, _, v in entries_with_strips if isinstance(v, bytes))
    n = len(entries_with_strips)
    strip_offset = 8 + 2 + 12 * n + 4 + ool_size

    patched = []
    for tag_id, type_id, count, value in entries_with_strips:
        if tag_id == 273:  # StripOffsets
            patched.append((273, 4, 1, strip_offset))
        elif tag_id == 279:  # StripByteCounts
            patched.append((279, 4, 1, len(strip_data)))
        else:
            patched.append((tag_id, type_id, count, value))

    return build_tiff(patched, endian=endian, extra_data=strip_data)


class TestStripTagsBeforeImageTags:
    """Verify parsing works when strip tags precede dimension tags."""

    def test_strip_offsets_before_width(self):
        """StripOffsets before ImageWidth — both parsed correctly."""
        strip_data = b'\xAB' * 100
        entries = [
            (273, 4, 1, 0),       # StripOffsets (placeholder)
            (279, 4, 1, 0),       # StripByteCounts (placeholder)
            (256, 3, 1, 64),      # ImageWidth
            (257, 3, 1, 64),      # ImageLength
        ]
        data = _build_tiff_ordered(entries, strip_data)
        f = io.BytesIO(data)
        header = read_header(f)
        ifds = iter_ifds(f, header)
        assert len(ifds) == 1
        ifd_entries = ifds[0][1]
        tags = [e.tag_id for e in ifd_entries]
        assert 273 in tags
        assert 256 in tags

    def test_strip_bytecounts_before_offsets(self):
        """StripByteCounts before StripOffsets — blanking still works."""
        strip_data = b'\xCD' * 200
        entries = [
            (256, 3, 1, 64),
            (257, 3, 1, 64),
            (279, 4, 1, 0),       # StripByteCounts before StripOffsets
            (273, 4, 1, 0),       # StripOffsets
        ]
        data = _build_tiff_ordered(entries, strip_data)
        filepath_bytes = data
        f = io.BytesIO(bytearray(filepath_bytes))
        header = read_header(f)
        ifds = iter_ifds(f, header)
        _, ifd_entries = ifds[0]
        blanked = blank_ifd_image_data(f, header, ifd_entries)
        assert blanked == 200


class TestMetadataTagsInterspersed:
    """Metadata tags mixed among strip/dimension tags."""

    def test_tag270_after_strip_tags(self):
        """Tag 270 (ImageDescription) after strip tags — still readable."""
        desc = b'Test description\x00'
        strip_data = b'\xEF' * 100
        entries = [
            (273, 4, 1, 0),
            (279, 4, 1, 0),
            (256, 3, 1, 64),
            (257, 3, 1, 64),
            (270, 2, len(desc), desc),
        ]
        data = _build_tiff_ordered(entries, strip_data)
        f = io.BytesIO(data)
        header = read_header(f)
        ifds = iter_ifds(f, header)
        _, ifd_entries = ifds[0]
        desc_entry = [e for e in ifd_entries if e.tag_id == 270][0]
        value = read_tag_string(f, desc_entry)
        assert value == 'Test description'

    def test_extra_metadata_among_strips(self):
        """Tags 305 (Software), 315 (Artist), 700 (XMP) among strip tags."""
        software = b'TestScanner v1.0\x00'
        artist = b'Operator John\x00'
        strip_data = b'\x00' * 50
        entries = [
            (256, 3, 1, 64),
            (273, 4, 1, 0),
            (305, 2, len(software), software),  # Between strip tags
            (257, 3, 1, 64),
            (279, 4, 1, 0),
            (315, 2, len(artist), artist),       # After strip tags
        ]
        data = _build_tiff_ordered(entries, strip_data)
        f = io.BytesIO(data)
        header = read_header(f)
        ifds = iter_ifds(f, header)
        _, ifd_entries = ifds[0]

        # scan_extra_metadata_tags should find Software and Artist
        found = scan_extra_metadata_tags(f, header, ifd_entries)
        found_tags = {e.tag_id for e, _ in found}
        assert 305 in found_tags
        assert 315 in found_tags


class TestNDPISourceLensTagPosition:
    """Test NDPI SOURCELENS tag at various positions."""

    def test_sourcelens_before_other_ndpi_tags(self):
        """SOURCELENS (65421) before BARCODE (65468) — still detected."""
        barcode = b'AS-24-123456\x00'
        entries = [
            (65421, 11, 1, 0),   # SOURCELENS (FLOAT, inline = 0.0 = slide image)
            (256, 3, 1, 1024),
            (257, 3, 1, 768),
            (65468, 2, len(barcode), barcode),
        ]
        content = build_tiff(entries)
        f = io.BytesIO(content)
        header = read_header(f)
        ifds = iter_ifds(f, header)
        _, ifd_entries = ifds[0]
        tags = [e.tag_id for e in ifd_entries]
        assert 65421 in tags
        assert 65468 in tags


class TestBlankingWithUnsortedTags:
    """Verify blank_ifd_image_data works with all tag orderings."""

    @pytest.mark.parametrize("order", [
        [256, 257, 273, 279],  # Standard sorted
        [279, 273, 257, 256],  # Fully reversed
        [273, 256, 279, 257],  # Strips first, then dimensions
        [257, 279, 256, 273],  # Interleaved
    ])
    def test_blanking_all_tag_orderings(self, order):
        """Blanking works regardless of tag ordering."""
        strip_data = b'\xAB\xCD\xEF' * 100  # 300 bytes
        entries = []
        for tag_id in order:
            if tag_id == 256:
                entries.append((256, 3, 1, 64))
            elif tag_id == 257:
                entries.append((257, 3, 1, 64))
            elif tag_id == 273:
                entries.append((273, 4, 1, 0))  # Placeholder
            elif tag_id == 279:
                entries.append((279, 4, 1, 0))  # Placeholder

        data = _build_tiff_ordered(entries, strip_data)
        f = io.BytesIO(bytearray(data))
        header = read_header(f)
        ifds = iter_ifds(f, header)
        _, ifd_entries = ifds[0]
        blanked = blank_ifd_image_data(f, header, ifd_entries)
        assert blanked == 300
