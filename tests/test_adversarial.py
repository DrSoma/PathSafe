"""Adversarial edge-case tests — malformed inputs, hostile data, boundary conditions.

Tests that the parser and handlers gracefully handle corrupt, truncated,
or pathological files without crashing or reporting false negatives.
All tests use synthetic temporary files — no original WSI images are touched.
"""

import os
import struct
import pytest
from pathlib import Path

from pathsafe.tiff import (
    read_header, read_ifd, iter_ifds, read_tag_string,
    compute_image_hashes, compute_ifd_tile_hash,
    is_ifd_image_blanked, get_ifd_image_size,
)
from pathsafe.formats import get_handler, detect_format
from pathsafe.anonymizer import anonymize_file, collect_wsi_files
from pathsafe.scanner import scan_bytes_for_phi, scan_string_for_phi
from tests.conftest import build_tiff, build_tiff_with_strips


class TestTruncatedFiles:
    """Files that are cut short at various points."""

    def test_empty_file(self, tmp_path):
        f = tmp_path / 'empty.tif'
        f.write_bytes(b'')
        with open(f, 'rb') as fh:
            assert read_header(fh) is None

    def test_one_byte(self, tmp_path):
        f = tmp_path / 'one.tif'
        f.write_bytes(b'I')
        with open(f, 'rb') as fh:
            assert read_header(fh) is None

    def test_header_only_no_ifd(self, tmp_path):
        """Valid header but IFD offset points to EOF."""
        f = tmp_path / 'header_only.tif'
        f.write_bytes(b'II' + struct.pack('<HI', 42, 999))
        with open(f, 'rb') as fh:
            header = read_header(fh)
            assert header is not None
            entries, next_offset = read_ifd(fh, header, header.first_ifd_offset)
            assert entries == []
            assert next_offset == 0

    def test_partial_ifd_entry(self, tmp_path):
        """IFD says 5 entries but file ends mid-way."""
        data = b'II' + struct.pack('<HI', 42, 8)
        data += struct.pack('<H', 5)  # num_entries = 5
        data += struct.pack('<HHI I', 256, 3, 1, 100)  # only 1 complete entry
        # File ends here — remaining 4 entries missing
        f = tmp_path / 'partial.tif'
        f.write_bytes(data)
        with open(f, 'rb') as fh:
            header = read_header(fh)
            entries, _ = read_ifd(fh, header, 8)
            assert len(entries) == 1  # Should get the one valid entry

    def test_truncated_tag_value(self, tmp_path):
        """Tag points to data beyond EOF."""
        desc = b'Short\x00'
        entries = [
            (256, 3, 1, 512),
            (270, 2, 1000, desc),  # count says 1000 but only 6 bytes
        ]
        f = tmp_path / 'trunc_val.tif'
        f.write_bytes(build_tiff(entries))
        handler = get_handler(f)
        # Should not crash — may find partial data or nothing
        result = handler.scan(f)
        assert result is not None

    def test_zero_length_file_scan(self, tmp_path):
        """Zero-byte .tif file — handler should not crash."""
        f = tmp_path / 'zero.tif'
        f.write_bytes(b'')
        handler = get_handler(f)
        result = handler.scan(f)
        assert not result.is_clean  # fail-closed
        assert result.error is not None


class TestCorruptStructure:
    """Files with internally inconsistent TIFF structure."""

    def test_circular_ifd_chain(self, tmp_path):
        """IFD chain loops back to itself."""
        # Build: header -> IFD at offset 8, next_ifd = 8 (self-loop)
        data = b'II' + struct.pack('<HI', 42, 8)
        data += struct.pack('<H', 1)  # 1 entry
        data += struct.pack('<HHI I', 256, 3, 1, 100)
        data += struct.pack('<I', 8)  # next IFD = 8 (loop!)
        f = tmp_path / 'circular.tif'
        f.write_bytes(data)
        with open(f, 'rb') as fh:
            header = read_header(fh)
            ifds = iter_ifds(fh, header)
            assert len(ifds) == 1  # Loop detected, only 1 IFD returned

    def test_ifd_offset_past_eof(self, tmp_path):
        """IFD offset points past end of file."""
        data = b'II' + struct.pack('<HI', 42, 0x7FFFFFFF)
        f = tmp_path / 'past_eof.tif'
        f.write_bytes(data)
        with open(f, 'rb') as fh:
            header = read_header(fh)
            entries, _ = read_ifd(fh, header, header.first_ifd_offset)
            assert entries == []

    def test_huge_num_entries(self, tmp_path):
        """IFD claims to have 65535 entries (overflow value)."""
        data = b'II' + struct.pack('<HI', 42, 8)
        data += struct.pack('<H', 0xFFFF)  # 65535 entries
        data += b'\x00' * 20  # not enough data for any entries
        f = tmp_path / 'huge_entries.tif'
        f.write_bytes(data)
        with open(f, 'rb') as fh:
            header = read_header(fh)
            entries, _ = read_ifd(fh, header, 8)
            # Should stop reading when file runs out, not allocate 65535
            assert len(entries) < 100

    def test_wrong_magic_number(self, tmp_path):
        """Valid byte order but wrong magic number."""
        data = b'II' + struct.pack('<HI', 99, 8)
        f = tmp_path / 'bad_magic.tif'
        f.write_bytes(data)
        with open(f, 'rb') as fh:
            assert read_header(fh) is None

    def test_big_endian_file(self, tmp_path):
        """Valid big-endian TIFF."""
        desc = b'Test description\x00'
        entries = [(256, 3, 1, 512), (270, 2, len(desc), desc)]
        f = tmp_path / 'big_endian.tif'
        f.write_bytes(build_tiff(entries, endian='>'))
        with open(f, 'rb') as fh:
            header = read_header(fh)
            assert header is not None
            assert header.endian == '>'

    def test_next_ifd_offset_zero_after_entries(self, tmp_path):
        """Normal termination: next_ifd=0."""
        entries = [(256, 3, 1, 100)]
        f = tmp_path / 'terminated.tif'
        f.write_bytes(build_tiff(entries))
        with open(f, 'rb') as fh:
            header = read_header(fh)
            ifds = iter_ifds(fh, header)
            assert len(ifds) == 1


class TestGarbageData:
    """Tags with unexpected or malformed data."""

    def test_binary_garbage_in_ascii_tag(self, tmp_path):
        """Tag 270 (ImageDescription) with non-ASCII binary data."""
        garbage = bytes(range(256)) + b'\x00'
        entries = [
            (256, 3, 1, 512),
            (270, 2, len(garbage), garbage),
        ]
        f = tmp_path / 'garbage.tif'
        f.write_bytes(build_tiff(entries))
        handler = get_handler(f)
        result = handler.scan(f)
        # Should not crash
        assert result is not None

    def test_null_filled_tag(self, tmp_path):
        """Tag value is all null bytes."""
        null_data = b'\x00' * 100
        entries = [
            (256, 3, 1, 512),
            (270, 2, 100, null_data),
        ]
        f = tmp_path / 'nulltag.tif'
        f.write_bytes(build_tiff(entries))
        handler = get_handler(f)
        result = handler.scan(f)
        assert result is not None

    def test_tag_type_zero(self, tmp_path):
        """Tag with type=0 (invalid TIFF type)."""
        data = b'II' + struct.pack('<HI', 42, 8)
        data += struct.pack('<H', 1)
        data += struct.pack('<HHI I', 256, 0, 1, 100)  # type=0 invalid
        data += struct.pack('<I', 0)  # next IFD
        f = tmp_path / 'type_zero.tif'
        f.write_bytes(data)
        with open(f, 'rb') as fh:
            header = read_header(fh)
            entries, _ = read_ifd(fh, header, 8)
            # Should parse without crashing; entry exists but has fallback size
            assert len(entries) == 1

    def test_very_long_string_tag(self, tmp_path):
        """Tag with a very long string value (100KB)."""
        long_string = b'A' * 100_000 + b'\x00'
        entries = [
            (256, 3, 1, 512),
            (270, 2, len(long_string), long_string),
        ]
        f = tmp_path / 'longstring.tif'
        f.write_bytes(build_tiff(entries))
        handler = get_handler(f)
        result = handler.scan(f)
        assert result is not None


class TestHandlerEdgeCases:
    """Handler-level edge cases."""

    def test_wrong_extension_valid_tiff(self, tmp_path):
        """A valid TIFF file with .txt extension."""
        entries = [(256, 3, 1, 100)]
        f = tmp_path / 'slide.txt'
        f.write_bytes(build_tiff(entries))
        fmt = detect_format(f)
        assert fmt == 'unknown'

    def test_ndpi_extension_not_tiff(self, tmp_path):
        """A .ndpi file that's actually a JPEG."""
        f = tmp_path / 'fake.ndpi'
        f.write_bytes(b'\xFF\xD8\xFF\xE0' + b'\x00' * 100)
        handler = get_handler(f)
        # NDPI handler checks extension only
        assert handler.format_name == 'ndpi'
        result = handler.scan(f)
        # Should fail-closed (not crash)
        assert not result.is_clean

    def test_svs_empty_description(self, tmp_path):
        """SVS file with empty ImageDescription."""
        desc = b'\x00'
        entries = [
            (256, 3, 1, 512),
            (270, 2, 1, desc),
        ]
        f = tmp_path / 'empty_desc.svs'
        f.write_bytes(build_tiff(entries))
        handler = get_handler(f)
        result = handler.scan(f)
        assert result is not None

    def test_anonymize_missing_file(self, tmp_path):
        """Anonymize a non-existent file."""
        result = anonymize_file(tmp_path / 'nonexistent.ndpi')
        assert result.error is not None
        assert 'not found' in result.error.lower()

    def test_anonymize_read_only_file(self, tmp_path):
        """Anonymize a read-only file should fail gracefully."""
        entries = [
            (256, 3, 1, 512),
            (270, 2, 12, b'AS-24-12345\x00'),
        ]
        f = tmp_path / 'readonly.tif'
        f.write_bytes(build_tiff(entries))
        os.chmod(f, 0o444)
        try:
            result = anonymize_file(f)
            # Should either error or succeed (depends on OS)
            assert result is not None
        finally:
            os.chmod(f, 0o644)

    def test_collect_empty_directory(self, tmp_path):
        """collect_wsi_files on an empty directory."""
        empty = tmp_path / 'empty_dir'
        empty.mkdir()
        assert collect_wsi_files(empty) == []

    def test_collect_no_matching_format(self, tmp_path):
        """collect_wsi_files with format filter that matches nothing."""
        f = tmp_path / 'slide.svs'
        f.write_bytes(build_tiff([(256, 3, 1, 100)]))
        assert collect_wsi_files(tmp_path, format_filter='ndpi') == []


class TestScannerEdgeCases:
    """Scanner regex edge cases."""

    def test_scan_empty_bytes(self):
        assert scan_bytes_for_phi(b'') == []

    def test_scan_all_nulls(self):
        assert scan_bytes_for_phi(b'\x00' * 1000) == []

    def test_scan_huge_input(self):
        """Large input should not hang."""
        data = b'X' * 500_000
        result = scan_bytes_for_phi(data)
        assert isinstance(result, list)

    def test_scan_string_empty(self):
        assert scan_string_for_phi('') == []

    def test_scan_skip_offsets(self):
        """skip_offsets should exclude matches at those positions."""
        data = b'AS-24-123456\x00'
        # Without skip
        results = scan_bytes_for_phi(data)
        assert len(results) > 0
        # With skip at offset 0
        results = scan_bytes_for_phi(data, skip_offsets={0})
        assert len(results) == 0


class TestHashingEdgeCases:
    """Tile hashing edge cases."""

    def test_compute_hashes_nonexistent_file(self, tmp_path):
        result = compute_image_hashes(tmp_path / 'missing.tif')
        assert result == {}

    def test_compute_hashes_empty_file(self, tmp_path):
        f = tmp_path / 'empty.tif'
        f.write_bytes(b'')
        result = compute_image_hashes(f)
        assert result == {}

    def test_compute_hashes_non_tiff(self, tmp_path):
        f = tmp_path / 'not_tiff.tif'
        f.write_bytes(b'NOT A TIFF FILE AT ALL')
        result = compute_image_hashes(f)
        assert result == {}

    def test_ifd_with_zero_count_strips(self, tmp_path):
        """IFD with StripOffsets/ByteCounts but zero values."""
        data = b'II' + struct.pack('<HI', 42, 8)
        data += struct.pack('<H', 3)
        data += struct.pack('<HHI I', 256, 3, 1, 64)
        data += struct.pack('<HHI I', 273, 4, 1, 0)   # StripOffset = 0
        data += struct.pack('<HHI I', 279, 4, 1, 0)   # StripByteCount = 0
        data += struct.pack('<I', 0)
        f = tmp_path / 'zero_strips.tif'
        f.write_bytes(data)
        with open(f, 'rb') as fh:
            header = read_header(fh)
            ifds = iter_ifds(fh, header)
            assert len(ifds) == 1
            _, entries = ifds[0]
            result = compute_ifd_tile_hash(fh, header, entries)
            # Zero-size strip should not crash


class TestBigTIFF:
    """BigTIFF-specific edge cases."""

    def test_valid_bigtiff_header(self, tmp_path):
        """Minimal valid BigTIFF header."""
        data = b'II'
        data += struct.pack('<H', 43)     # BigTIFF magic
        data += struct.pack('<H', 8)      # offset size = 8
        data += struct.pack('<H', 0)      # reserved
        data += struct.pack('<Q', 0)      # first IFD offset = 0 (no IFDs)
        f = tmp_path / 'bigtiff.tif'
        f.write_bytes(data)
        with open(f, 'rb') as fh:
            header = read_header(fh)
            assert header is not None
            assert header.is_bigtiff

    def test_bigtiff_wrong_offset_size(self, tmp_path):
        """BigTIFF with wrong offset size (not 8)."""
        data = b'II'
        data += struct.pack('<H', 43)
        data += struct.pack('<H', 4)      # Should be 8
        data += struct.pack('<H', 0)
        data += struct.pack('<Q', 0)
        f = tmp_path / 'bad_bigtiff.tif'
        f.write_bytes(data)
        with open(f, 'rb') as fh:
            header = read_header(fh)
            assert header is None
