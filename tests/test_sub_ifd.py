"""Tests for SubIFD (tag 330) traversal: scan_sub_ifds() and blank_sub_ifds().

Validates that PathSafe detects and blanks PHI-bearing tags inside
SubIFDs pointed to by TIFF tag 330, including depth-limited recursion
to prevent infinite loops from circular SubIFD pointers.
"""

import io
import struct

from pathsafe.tiff import (
    MAX_SUB_IFD_DEPTH,
    SUB_IFD_TAG,
    blank_sub_ifds,
    read_header,
    read_ifd,
    read_sub_ifds,
    read_tag_value_bytes,
    scan_sub_ifds,
)
from tests.conftest import build_tiff, build_tiff_with_sub_ifd


def _build_tiff_with_sub_ifd_tag330(main_entries, sub_ifd_entries, endian="<"):
    """Build a TIFF where the main IFD has tag 330 (SubIFD) pointing to a child IFD.

    This uses the conftest build_tiff_with_sub_ifd helper with pointer_tag=330.
    """
    return build_tiff_with_sub_ifd(main_entries, sub_ifd_entries, SUB_IFD_TAG, endian)


def _build_tiff_with_nested_sub_ifds(main_entries, level1_entries, level2_entries, endian="<"):
    """Build a TIFF with two levels of nested SubIFDs via tag 330.

    main IFD -> tag 330 -> level1 sub-IFD -> tag 330 -> level2 sub-IFD.
    """
    bo = b"II" if endian == "<" else b"MM"

    # Compute sizes for layout
    # Main IFD: len(main_entries) + 1 (tag 330 pointer)
    all_main = list(main_entries) + [(SUB_IFD_TAG, 4, 1, 0)]  # placeholder
    num_main = len(all_main)
    main_ool_size = sum(len(v) for _, _, _, v in main_entries if isinstance(v, bytes))
    main_ool_start = 8 + 2 + 12 * num_main + 4

    # Level 1 sub-IFD: level1_entries + tag 330 pointer to level 2
    all_level1 = list(level1_entries) + [(SUB_IFD_TAG, 4, 1, 0)]  # placeholder
    num_level1 = len(all_level1)
    level1_offset = main_ool_start + main_ool_size
    level1_ool_start = level1_offset + 2 + 12 * num_level1 + 4
    level1_ool_size = sum(len(v) for _, _, _, v in level1_entries if isinstance(v, bytes))

    # Level 2 sub-IFD
    num_level2 = len(level2_entries)
    level2_offset = level1_ool_start + level1_ool_size
    level2_ool_start = level2_offset + 2 + 12 * num_level2 + 4

    # Build header
    result = bo + struct.pack(endian + "H", 42) + struct.pack(endian + "I", 8)

    # Build main IFD
    ifd_bytes = struct.pack(endian + "H", num_main)
    data_bytes = b""
    for tag_id, type_id, count, value in main_entries:
        if isinstance(value, bytes):
            val_offset = main_ool_start + len(data_bytes)
            ifd_bytes += struct.pack(endian + "HHI", tag_id, type_id, count)
            ifd_bytes += struct.pack(endian + "I", val_offset)
            data_bytes += value
        else:
            ifd_bytes += struct.pack(endian + "HHI", tag_id, type_id, count)
            ifd_bytes += struct.pack(endian + "I", value)
    # Tag 330 pointing to level1_offset
    ifd_bytes += struct.pack(endian + "HHI", SUB_IFD_TAG, 4, 1)
    ifd_bytes += struct.pack(endian + "I", level1_offset)
    ifd_bytes += struct.pack(endian + "I", 0)  # next IFD = 0
    result += ifd_bytes + data_bytes

    # Build level 1 sub-IFD
    l1_ifd = struct.pack(endian + "H", num_level1)
    l1_data = b""
    for tag_id, type_id, count, value in level1_entries:
        if isinstance(value, bytes):
            val_offset = level1_ool_start + len(l1_data)
            l1_ifd += struct.pack(endian + "HHI", tag_id, type_id, count)
            l1_ifd += struct.pack(endian + "I", val_offset)
            l1_data += value
        else:
            l1_ifd += struct.pack(endian + "HHI", tag_id, type_id, count)
            l1_ifd += struct.pack(endian + "I", value)
    # Tag 330 pointing to level2_offset
    l1_ifd += struct.pack(endian + "HHI", SUB_IFD_TAG, 4, 1)
    l1_ifd += struct.pack(endian + "I", level2_offset)
    l1_ifd += struct.pack(endian + "I", 0)  # next IFD = 0
    result += l1_ifd + l1_data

    # Build level 2 sub-IFD
    l2_ifd = struct.pack(endian + "H", num_level2)
    l2_data = b""
    for tag_id, type_id, count, value in level2_entries:
        if isinstance(value, bytes):
            val_offset = level2_ool_start + len(l2_data)
            l2_ifd += struct.pack(endian + "HHI", tag_id, type_id, count)
            l2_ifd += struct.pack(endian + "I", val_offset)
            l2_data += value
        else:
            l2_ifd += struct.pack(endian + "HHI", tag_id, type_id, count)
            l2_ifd += struct.pack(endian + "I", value)
    l2_ifd += struct.pack(endian + "I", 0)  # next IFD = 0
    result += l2_ifd + l2_data

    return result


class TestReadSubIFDs:
    """Test read_sub_ifds() -- locating and parsing SubIFDs from tag 330."""

    def test_reads_sub_ifd_with_phi_tag(self):
        """Tag 330 pointing to a sub-IFD with ImageDescription is read correctly."""
        desc = b"Patient: John Doe\x00"
        main = [(256, 3, 1, 1024), (257, 3, 1, 768)]
        sub = [(270, 2, len(desc), desc)]  # ImageDescription in SubIFD
        data = _build_tiff_with_sub_ifd_tag330(main, sub)

        f = io.BytesIO(data)
        header = read_header(f)
        entries, _ = read_ifd(f, header, header.first_ifd_offset)
        sub_ifds = read_sub_ifds(f, header, entries)
        assert len(sub_ifds) == 1
        _, sub_entries = sub_ifds[0]
        assert any(e.tag_id == 270 for e in sub_entries)

    def test_returns_empty_when_no_tag_330(self):
        """No tag 330 in main IFD returns empty list."""
        data = build_tiff([(256, 3, 1, 1024)])
        f = io.BytesIO(data)
        header = read_header(f)
        entries, _ = read_ifd(f, header, header.first_ifd_offset)
        assert read_sub_ifds(f, header, entries) == []


class TestScanSubIFDs:
    """Test scan_sub_ifds() -- finding PHI in SubIFDs."""

    def test_finds_phi_in_sub_ifd_image_description(self):
        """PHI in a SubIFD ImageDescription (tag 270) is detected."""
        desc = b"Patient: Jane Smith AS-24-999999\x00"
        main = [(256, 3, 1, 1024)]
        sub = [(270, 2, len(desc), desc)]
        data = _build_tiff_with_sub_ifd_tag330(main, sub)

        f = io.BytesIO(data)
        header = read_header(f)
        entries, _ = read_ifd(f, header, header.first_ifd_offset)
        findings = scan_sub_ifds(f, header, entries)
        assert len(findings) >= 1
        assert any(e.tag_id == 270 for e, _ in findings)

    def test_finds_phi_in_sub_ifd_datetime(self):
        """DateTime (tag 306) in a SubIFD is detected as PHI."""
        dt = b"2024:06:15 10:30:00\x00"
        main = [(256, 3, 1, 1024)]
        sub = [(306, 2, len(dt), dt)]
        data = _build_tiff_with_sub_ifd_tag330(main, sub)

        f = io.BytesIO(data)
        header = read_header(f)
        entries, _ = read_ifd(f, header, header.first_ifd_offset)
        findings = scan_sub_ifds(f, header, entries)
        assert len(findings) >= 1
        assert any(e.tag_id == 306 for e, _ in findings)

    def test_finds_phi_in_sub_ifd_maker_note(self):
        """MakerNote (tag 37500) in a SubIFD is detected."""
        maker = b"Hamamatsu NanoZoomer S360\x00"
        main = [(256, 3, 1, 1024)]
        # MakerNote is UNDEFINED type (7)
        sub = [(37500, 7, len(maker), maker)]
        data = _build_tiff_with_sub_ifd_tag330(main, sub)

        f = io.BytesIO(data)
        header = read_header(f)
        entries, _ = read_ifd(f, header, header.first_ifd_offset)
        findings = scan_sub_ifds(f, header, entries)
        assert len(findings) >= 1
        assert any(e.tag_id == 37500 for e, _ in findings)

    def test_skips_zeroed_sub_ifd_tags(self):
        """Already-blanked SubIFD tags (all zeros) are not reported."""
        zeroed = b"\x00" * 20
        main = [(256, 3, 1, 1024)]
        sub = [(306, 2, len(zeroed), zeroed)]
        data = _build_tiff_with_sub_ifd_tag330(main, sub)

        f = io.BytesIO(data)
        header = read_header(f)
        entries, _ = read_ifd(f, header, header.first_ifd_offset)
        findings = scan_sub_ifds(f, header, entries)
        assert len(findings) == 0


class TestBlankSubIFDs:
    """Test blank_sub_ifds() -- clearing PHI in SubIFDs."""

    def test_blanks_phi_in_sub_ifd(self):
        """PHI in a SubIFD is blanked (zeroed out)."""
        desc = b"Patient: John Doe\x00"
        main = [(256, 3, 1, 1024)]
        sub = [(270, 2, len(desc), desc)]
        data = _build_tiff_with_sub_ifd_tag330(main, sub)

        f = io.BytesIO(data)
        header = read_header(f)
        entries, _ = read_ifd(f, header, header.first_ifd_offset)

        blanked = blank_sub_ifds(f, header, entries)
        assert blanked > 0

        # Re-scan should find nothing
        findings = scan_sub_ifds(f, header, entries)
        assert len(findings) == 0

    def test_blank_returns_byte_count(self):
        """blank_sub_ifds() returns the total number of bytes blanked."""
        desc = b"AS-24-123456 scanned on 2024-06-15\x00"
        main = [(256, 3, 1, 1024)]
        sub = [(270, 2, len(desc), desc)]
        data = _build_tiff_with_sub_ifd_tag330(main, sub)

        f = io.BytesIO(data)
        header = read_header(f)
        entries, _ = read_ifd(f, header, header.first_ifd_offset)

        blanked = blank_sub_ifds(f, header, entries)
        assert blanked == len(desc)  # Total size of the tag value

    def test_blank_does_nothing_when_already_clean(self):
        """Blanking a clean SubIFD returns 0 bytes blanked."""
        zeroed = b"\x00" * 20
        main = [(256, 3, 1, 1024)]
        sub = [(306, 2, len(zeroed), zeroed)]
        data = _build_tiff_with_sub_ifd_tag330(main, sub)

        f = io.BytesIO(data)
        header = read_header(f)
        entries, _ = read_ifd(f, header, header.first_ifd_offset)

        blanked = blank_sub_ifds(f, header, entries)
        assert blanked == 0


class TestSubIFDDepthLimit:
    """Test that MAX_SUB_IFD_DEPTH prevents excessive recursion."""

    def test_max_depth_constant_is_3(self):
        """The depth limit is set to 3."""
        assert MAX_SUB_IFD_DEPTH == 3

    def test_nested_sub_ifds_within_depth_scanned(self):
        """PHI in a level-2 nested SubIFD (depth=1) is still found."""
        desc_l2 = b"Secret data in nested SubIFD\x00"
        main = [(256, 3, 1, 1024)]
        level1 = [(257, 3, 1, 768)]  # No PHI at level 1
        level2 = [(270, 2, len(desc_l2), desc_l2)]  # PHI at level 2

        data = _build_tiff_with_nested_sub_ifds(main, level1, level2)

        f = io.BytesIO(data)
        header = read_header(f)
        entries, _ = read_ifd(f, header, header.first_ifd_offset)

        findings = scan_sub_ifds(f, header, entries, depth=0)
        # The level-2 SubIFD PHI should be found (depth 0 -> level1 at depth 1 -> level2 at depth 2)
        assert len(findings) >= 1
        assert any(e.tag_id == 270 for e, _ in findings)

    def test_scan_at_max_depth_returns_empty(self):
        """Calling scan_sub_ifds with depth=MAX_SUB_IFD_DEPTH returns nothing."""
        desc = b"Should not be found\x00"
        main = [(256, 3, 1, 1024)]
        sub = [(270, 2, len(desc), desc)]
        data = _build_tiff_with_sub_ifd_tag330(main, sub)

        f = io.BytesIO(data)
        header = read_header(f)
        entries, _ = read_ifd(f, header, header.first_ifd_offset)

        # Starting at max depth should immediately return empty
        findings = scan_sub_ifds(f, header, entries, depth=MAX_SUB_IFD_DEPTH)
        assert findings == []

    def test_blank_at_max_depth_returns_zero(self):
        """Calling blank_sub_ifds with depth=MAX_SUB_IFD_DEPTH blanks nothing."""
        desc = b"Should not be blanked\x00"
        main = [(256, 3, 1, 1024)]
        sub = [(270, 2, len(desc), desc)]
        data = _build_tiff_with_sub_ifd_tag330(main, sub)

        f = io.BytesIO(data)
        header = read_header(f)
        entries, _ = read_ifd(f, header, header.first_ifd_offset)

        blanked = blank_sub_ifds(f, header, entries, depth=MAX_SUB_IFD_DEPTH)
        assert blanked == 0

        # The data should still be there (not blanked)
        sub_ifds = read_sub_ifds(f, header, entries)
        assert len(sub_ifds) == 1
        _, sub_entries = sub_ifds[0]
        for e in sub_entries:
            if e.tag_id == 270:
                raw = read_tag_value_bytes(f, e)
                assert b"Should not be blanked" in raw
