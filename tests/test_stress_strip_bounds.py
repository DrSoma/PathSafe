"""Stress tests -- strip size boundaries for blank_ifd_image_data / is_ifd_image_blanked."""

import io
import struct

import pytest

from pathsafe.tiff import (
    read_header, iter_ifds,
    blank_ifd_image_data, is_ifd_image_blanked,
    _BLANK_JPEG, _LEGACY_BLANK_JPEG,
)
from tests.conftest import build_tiff_with_strips, build_tiff_multi_strip


# Size of _BLANK_JPEG for boundary tests
_JPEG_SIZE = len(_BLANK_JPEG)


class TestBoundaryStripSizes:
    """Test blank_ifd_image_data at exact boundary sizes."""

    def test_exact_jpeg_size(self):
        """Strip exactly _BLANK_JPEG size -- JPEG fits perfectly."""
        strip_data = b'\xAB' * _JPEG_SIZE
        tag_entries = [(256, 3, 1, 64), (257, 3, 1, 64)]
        content = build_tiff_with_strips(tag_entries, strip_data)

        f = io.BytesIO(bytearray(content))
        header = read_header(f)
        ifds = iter_ifds(f, header)
        _, entries = ifds[0]
        blanked = blank_ifd_image_data(f, header, entries)
        assert blanked == _JPEG_SIZE

        # Verify: entire strip is now _BLANK_JPEG with no padding
        assert is_ifd_image_blanked(f, header, entries) is True

    def test_one_byte_under_jpeg(self):
        """Strip one byte smaller than _BLANK_JPEG -- all zeros fallback."""
        strip_data = b'\xAB' * (_JPEG_SIZE - 1)
        tag_entries = [(256, 3, 1, 64), (257, 3, 1, 64)]
        content = build_tiff_with_strips(tag_entries, strip_data)

        f = io.BytesIO(bytearray(content))
        header = read_header(f)
        _, entries = iter_ifds(f, header)[0]
        blanked = blank_ifd_image_data(f, header, entries)
        assert blanked == _JPEG_SIZE - 1

        # Should be all zeros (too small for JPEG header)
        assert is_ifd_image_blanked(f, header, entries) is True

    def test_one_byte_over_jpeg(self):
        """Strip one byte larger -- JPEG + 1 zero byte padding."""
        strip_data = b'\xAB' * (_JPEG_SIZE + 1)
        tag_entries = [(256, 3, 1, 64), (257, 3, 1, 64)]
        content = build_tiff_with_strips(tag_entries, strip_data)

        f = io.BytesIO(bytearray(content))
        header = read_header(f)
        _, entries = iter_ifds(f, header)[0]
        blanked = blank_ifd_image_data(f, header, entries)
        assert blanked == _JPEG_SIZE + 1

        assert is_ifd_image_blanked(f, header, entries) is True

    def test_zero_byte_strip(self):
        """Zero-byte strip -- returns 0 blanked."""
        strip_data = b''
        tag_entries = [(256, 3, 1, 64), (257, 3, 1, 64)]
        content = build_tiff_with_strips(tag_entries, strip_data)

        f = io.BytesIO(bytearray(content))
        header = read_header(f)
        _, entries = iter_ifds(f, header)[0]
        blanked = blank_ifd_image_data(f, header, entries)
        assert blanked == 0

    def test_1_byte_strip(self):
        """1-byte strip -- becomes 1 zero byte."""
        strip_data = b'\xFF'
        tag_entries = [(256, 3, 1, 1), (257, 3, 1, 1)]
        content = build_tiff_with_strips(tag_entries, strip_data)

        f = io.BytesIO(bytearray(content))
        header = read_header(f)
        _, entries = iter_ifds(f, header)[0]
        blanked = blank_ifd_image_data(f, header, entries)
        assert blanked == 1

    def test_4_byte_strip(self):
        """4-byte strip -- too small for JPEG, all zeros."""
        strip_data = b'\xAB\xCD\xEF\x01'
        tag_entries = [(256, 3, 1, 2), (257, 3, 1, 2)]
        content = build_tiff_with_strips(tag_entries, strip_data)

        f = io.BytesIO(bytearray(content))
        header = read_header(f)
        _, entries = iter_ifds(f, header)[0]
        blanked = blank_ifd_image_data(f, header, entries)
        assert blanked == 4

    def test_8_byte_strip(self):
        """8-byte strip -- still too small for JPEG."""
        strip_data = b'\xAB' * 8
        tag_entries = [(256, 3, 1, 4), (257, 3, 1, 2)]
        content = build_tiff_with_strips(tag_entries, strip_data)

        f = io.BytesIO(bytearray(content))
        header = read_header(f)
        _, entries = iter_ifds(f, header)[0]
        blanked = blank_ifd_image_data(f, header, entries)
        assert blanked == 8

    def test_large_strip_1mb(self):
        """1MB strip -- JPEG header + zeros padding."""
        size = 1_000_000
        strip_data = b'\xAB' * size
        tag_entries = [(256, 3, 1, 1000), (257, 3, 1, 1000)]
        content = build_tiff_with_strips(tag_entries, strip_data)

        f = io.BytesIO(bytearray(content))
        header = read_header(f)
        _, entries = iter_ifds(f, header)[0]
        blanked = blank_ifd_image_data(f, header, entries)
        assert blanked == size


class TestMultipleStrips:
    """Test blanking behavior with multiple strips in one IFD."""

    def test_two_equal_strips(self):
        """Two strips of 1000 bytes each -- both blanked."""
        strip_data_list = [b'\xAB' * 1000, b'\xCD' * 1000]
        tag_entries = [(256, 3, 1, 64), (257, 3, 1, 128)]
        content = build_tiff_multi_strip(tag_entries, strip_data_list)

        f = io.BytesIO(bytearray(content))
        header = read_header(f)
        _, entries = iter_ifds(f, header)[0]
        blanked = blank_ifd_image_data(f, header, entries)
        assert blanked == 2000

    def test_mixed_size_strips(self):
        """Mixed sizes (1000 + 100 bytes) -- both blanked correctly."""
        strip_data_list = [b'\xAB' * 1000, b'\xCD' * 100]
        tag_entries = [(256, 3, 1, 64), (257, 3, 1, 64)]
        content = build_tiff_multi_strip(tag_entries, strip_data_list)

        f = io.BytesIO(bytearray(content))
        header = read_header(f)
        _, entries = iter_ifds(f, header)[0]
        blanked = blank_ifd_image_data(f, header, entries)
        assert blanked == 1100

    def test_large_plus_small_strips(self):
        """Large (2000B) + small (50B) in same IFD."""
        strip_data_list = [b'\xAB' * 2000, b'\xCD' * 50]
        tag_entries = [(256, 3, 1, 100), (257, 3, 1, 100)]
        content = build_tiff_multi_strip(tag_entries, strip_data_list)

        f = io.BytesIO(bytearray(content))
        header = read_header(f)
        _, entries = iter_ifds(f, header)[0]
        blanked = blank_ifd_image_data(f, header, entries)
        assert blanked == 2050


class TestIsIFDImageBlanked:
    """Test is_ifd_image_blanked detection logic."""

    def test_pathsafe_marker_detection(self):
        """PATHSAFE marker in JPEG COM segment → detected as blanked."""
        strip_data = _BLANK_JPEG + b'\x00' * 100
        tag_entries = [(256, 3, 1, 64), (257, 3, 1, 64)]
        content = build_tiff_with_strips(tag_entries, strip_data)

        f = io.BytesIO(content)
        header = read_header(f)
        _, entries = iter_ifds(f, header)[0]
        assert is_ifd_image_blanked(f, header, entries) is True

    def test_legacy_soi_eoi_detection(self):
        """Legacy SOI+EOI (FFD8FFD9) + zeros → detected as blanked."""
        strip_data = _LEGACY_BLANK_JPEG + b'\x00' * 96
        tag_entries = [(256, 3, 1, 64), (257, 3, 1, 64)]
        content = build_tiff_with_strips(tag_entries, strip_data)

        f = io.BytesIO(content)
        header = read_header(f)
        _, entries = iter_ifds(f, header)[0]
        assert is_ifd_image_blanked(f, header, entries) is True

    def test_all_zeros_detection(self):
        """All-zeros strip data → detected as blanked."""
        strip_data = b'\x00' * 500
        tag_entries = [(256, 3, 1, 64), (257, 3, 1, 64)]
        content = build_tiff_with_strips(tag_entries, strip_data)

        f = io.BytesIO(content)
        header = read_header(f)
        _, entries = iter_ifds(f, header)[0]
        assert is_ifd_image_blanked(f, header, entries) is True

    def test_non_blanked_returns_false(self):
        """Real (non-blanked) image data → returns False."""
        strip_data = b'\xFF\xD8\xFF\xE0' + b'\xAB\xCD' * 100
        tag_entries = [(256, 3, 1, 64), (257, 3, 1, 64)]
        content = build_tiff_with_strips(tag_entries, strip_data)

        f = io.BytesIO(content)
        header = read_header(f)
        _, entries = iter_ifds(f, header)[0]
        assert is_ifd_image_blanked(f, header, entries) is False

    def test_4_byte_strip_returns_false(self):
        """4-byte strip (too small to detect) → returns False."""
        strip_data = b'\xFF\xD8\xFF\xD9'  # SOI+EOI but only 4 bytes
        tag_entries = [(256, 3, 1, 2), (257, 3, 1, 2)]
        content = build_tiff_with_strips(tag_entries, strip_data)

        f = io.BytesIO(content)
        header = read_header(f)
        _, entries = iter_ifds(f, header)[0]
        # is_ifd_image_blanked requires first_cnt >= 8
        assert is_ifd_image_blanked(f, header, entries) is False

    def test_blanked_then_verified(self):
        """Blank via blank_ifd_image_data, then verify with is_ifd_image_blanked."""
        strip_data = b'\xAB\xCD\xEF' * 500  # 1500 bytes
        tag_entries = [(256, 3, 1, 64), (257, 3, 1, 64)]
        content = build_tiff_with_strips(tag_entries, strip_data)

        f = io.BytesIO(bytearray(content))
        header = read_header(f)
        _, entries = iter_ifds(f, header)[0]

        # Initially not blanked
        assert is_ifd_image_blanked(f, header, entries) is False

        # Blank it
        blanked = blank_ifd_image_data(f, header, entries)
        assert blanked == 1500

        # Now detected as blanked
        assert is_ifd_image_blanked(f, header, entries) is True
