"""Extended tests for TIFF parser -- multi-IFD, integrity hashing, ICC profile."""

import io
import struct
import pytest
from pathsafe.tiff import (
    read_header, read_ifd, iter_ifds,
    compute_ifd_tile_hash, compute_image_hashes,
    is_ifd_image_blanked, blank_ifd_image_data,
    get_ifd_image_data_size, get_ifd_image_size,
    read_tag_long_array,
    scan_extra_metadata_tags, blank_extra_metadata_tag,
    EXTRA_METADATA_TAGS,
)
from tests.conftest import build_tiff, build_tiff_multi_ifd, build_tiff_with_strips


class TestIterIFDs:
    """Test multi-IFD chain iteration."""

    def test_two_ifds(self, tmp_tiff_multi_ifd):
        with open(tmp_tiff_multi_ifd, 'rb') as f:
            header = read_header(f)
            assert header is not None
            ifds = iter_ifds(f, header)
        assert len(ifds) == 2

    def test_both_ifds_have_datetime(self, tmp_tiff_multi_ifd):
        with open(tmp_tiff_multi_ifd, 'rb') as f:
            header = read_header(f)
            ifds = iter_ifds(f, header)
        for _, entries in ifds:
            tag_ids = {e.tag_id for e in entries}
            assert 306 in tag_ids

    def test_single_ifd(self, tmp_ndpi):
        with open(tmp_ndpi, 'rb') as f:
            header = read_header(f)
            ifds = iter_ifds(f, header)
        assert len(ifds) == 1

    def test_max_pages_limit(self, tmp_tiff_multi_ifd):
        with open(tmp_tiff_multi_ifd, 'rb') as f:
            header = read_header(f)
            ifds = iter_ifds(f, header, max_pages=1)
        assert len(ifds) == 1


class TestComputeIFDTileHash:
    """Test per-IFD tile/strip hashing."""

    def test_hash_strip_data(self, tmp_tiff_with_strips):
        with open(tmp_tiff_with_strips, 'rb') as f:
            header = read_header(f)
            ifds = iter_ifds(f, header)
            assert len(ifds) == 1
            _, entries = ifds[0]
            digest = compute_ifd_tile_hash(f, header, entries)
        assert digest is not None
        assert len(digest) == 64  # SHA-256 hex

    def test_hash_deterministic(self, tmp_tiff_with_strips):
        with open(tmp_tiff_with_strips, 'rb') as f:
            header = read_header(f)
            _, entries = iter_ifds(f, header)[0]
            d1 = compute_ifd_tile_hash(f, header, entries)
            d2 = compute_ifd_tile_hash(f, header, entries)
        assert d1 == d2

    def test_no_strips_returns_none(self, tmp_ndpi):
        """IFD without strip/tile data returns None."""
        with open(tmp_ndpi, 'rb') as f:
            header = read_header(f)
            _, entries = iter_ifds(f, header)[0]
            digest = compute_ifd_tile_hash(f, header, entries)
        assert digest is None


class TestComputeImageHashes:
    """Test whole-file tile hash computation."""

    def test_returns_dict(self, tmp_tiff_with_strips):
        hashes = compute_image_hashes(tmp_tiff_with_strips)
        assert isinstance(hashes, dict)
        assert len(hashes) == 1

    def test_empty_for_no_strips(self, tmp_ndpi):
        hashes = compute_image_hashes(tmp_ndpi)
        assert hashes == {}

    def test_empty_for_invalid_file(self, tmp_path):
        bad = tmp_path / 'bad.tif'
        bad.write_bytes(b'NOT A TIFF')
        hashes = compute_image_hashes(bad)
        assert hashes == {}


class TestIsIFDImageBlanked:
    """Test detection of blanked/non-blanked image data."""

    def test_not_blanked(self, tmp_tiff_with_strips):
        with open(tmp_tiff_with_strips, 'rb') as f:
            header = read_header(f)
            _, entries = iter_ifds(f, header)[0]
            assert not is_ifd_image_blanked(f, header, entries)

    def test_blanked_after_blank(self, tmp_tiff_with_strips):
        # Blank the image data
        with open(tmp_tiff_with_strips, 'r+b') as f:
            header = read_header(f)
            _, entries = iter_ifds(f, header)[0]
            blanked = blank_ifd_image_data(f, header, entries)
            assert blanked > 0

        # Now check it's blanked
        with open(tmp_tiff_with_strips, 'rb') as f:
            header = read_header(f)
            _, entries = iter_ifds(f, header)[0]
            assert is_ifd_image_blanked(f, header, entries)

    def test_no_strips_not_blanked(self, tmp_ndpi):
        with open(tmp_ndpi, 'rb') as f:
            header = read_header(f)
            _, entries = iter_ifds(f, header)[0]
            assert not is_ifd_image_blanked(f, header, entries)


class TestGetIFDImageSize:
    """Test image dimension extraction."""

    def test_get_size(self, tmp_tiff_with_strips):
        with open(tmp_tiff_with_strips, 'rb') as f:
            header = read_header(f)
            _, entries = iter_ifds(f, header)[0]
            w, h = get_ifd_image_size(header, entries, f)
        assert w == 64
        assert h == 64


class TestGetIFDImageDataSize:
    """Test image data size extraction."""

    def test_get_data_size(self, tmp_tiff_with_strips):
        with open(tmp_tiff_with_strips, 'rb') as f:
            header = read_header(f)
            _, entries = iter_ifds(f, header)[0]
            size = get_ifd_image_data_size(header, entries, f)
        assert size == 300  # 3 bytes * 100

    def test_no_strips_returns_zero(self, tmp_ndpi):
        with open(tmp_ndpi, 'rb') as f:
            header = read_header(f)
            _, entries = iter_ifds(f, header)[0]
            size = get_ifd_image_data_size(header, entries, f)
        assert size == 0


class TestICCProfile:
    """Test ICC profile (tag 34675) scanning."""

    def test_icc_tag_in_extra_metadata(self):
        """Tag 34675 is registered in EXTRA_METADATA_TAGS."""
        assert 34675 in EXTRA_METADATA_TAGS
        assert EXTRA_METADATA_TAGS[34675] == 'ICCProfile'

    def test_scan_detects_icc_profile(self):
        """ICC profile with content is detected by scan_extra_metadata_tags."""
        # ICC profile data (UNDEFINED type 7) -- contains a device serial
        icc_data = b'Device: SN-12345-XYZ\x00' + b'\x00' * 20
        entries = [
            (256, 3, 1, 1024),
            (34675, 7, len(icc_data), icc_data),
        ]
        data = build_tiff(entries)
        f = io.BytesIO(data)
        header = read_header(f)
        ifd_entries, _ = read_ifd(f, header, header.first_ifd_offset)
        findings = scan_extra_metadata_tags(f, header, ifd_entries)
        assert len(findings) >= 1
        assert any(e.tag_id == 34675 for e, _ in findings)

    def test_blank_zeros_icc_profile(self):
        """Blanking ICC profile tag writes zeros."""
        icc_data = b'Device: SN-12345-XYZ\x00' + b'\x00' * 20
        entries = [
            (256, 3, 1, 1024),
            (34675, 7, len(icc_data), icc_data),
        ]
        data = build_tiff(entries)
        f = io.BytesIO(data)
        header = read_header(f)
        ifd_entries, _ = read_ifd(f, header, header.first_ifd_offset)

        findings = scan_extra_metadata_tags(f, header, ifd_entries)
        assert len(findings) >= 1
        for entry, _ in findings:
            if entry.tag_id == 34675:
                blank_extra_metadata_tag(f, entry)

        # Re-scan should find nothing
        findings2 = scan_extra_metadata_tags(f, header, ifd_entries)
        assert not any(e.tag_id == 34675 for e, _ in findings2)

    def test_already_zeroed_skipped(self):
        """ICC profile that is all zeros is not reported."""
        icc_data = b'\x00' * 40
        entries = [
            (256, 3, 1, 1024),
            (34675, 7, len(icc_data), icc_data),
        ]
        data = build_tiff(entries)
        f = io.BytesIO(data)
        header = read_header(f)
        ifd_entries, _ = read_ifd(f, header, header.first_ifd_offset)
        findings = scan_extra_metadata_tags(f, header, ifd_entries)
        assert not any(e.tag_id == 34675 for e, _ in findings)

    def test_icc_ascii_type_detected(self):
        """ICC profile stored as ASCII (type 2) is also detected."""
        icc_text = b'sRGB IEC61966-2.1 SN:ABC123\x00'
        entries = [
            (256, 3, 1, 1024),
            (34675, 2, len(icc_text), icc_text),
        ]
        data = build_tiff(entries)
        f = io.BytesIO(data)
        header = read_header(f)
        ifd_entries, _ = read_ifd(f, header, header.first_ifd_offset)
        findings = scan_extra_metadata_tags(f, header, ifd_entries)
        assert any(e.tag_id == 34675 for e, _ in findings)
