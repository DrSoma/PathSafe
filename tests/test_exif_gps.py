"""Tests for EXIF sub-IFD and GPS sub-IFD scanning and blanking."""

import struct
import io
import pytest

from pathsafe.tiff import (
    read_header, read_ifd, iter_ifds,
    read_exif_sub_ifd, read_gps_sub_ifd,
    scan_exif_sub_ifd_tags, scan_gps_sub_ifd,
    blank_exif_sub_ifd_tags, blank_gps_sub_ifd,
    EXIF_IFD_POINTER_TAG, GPS_IFD_POINTER_TAG,
    EXIF_SUB_IFD_PHI_TAGS, GPS_TAG_NAMES,
)
from pathsafe.formats.ndpi import NDPIHandler
from pathsafe.formats.svs import SVSHandler
from pathsafe.formats.generic_tiff import GenericTIFFHandler
from tests.conftest import build_tiff, build_tiff_with_sub_ifd, build_tiff_with_strips


# ---------------------------------------------------------------------------
# EXIF sub-IFD parser
# ---------------------------------------------------------------------------

class TestExifSubIFDParser:
    """Test read_exif_sub_ifd() — finding and parsing EXIF sub-IFDs."""

    def test_returns_entries_when_present(self):
        """Tag 34665 pointing to a valid sub-IFD returns entries."""
        date_val = b'2024:06:15 10:30:00\x00'
        main = [(256, 3, 1, 1024), (257, 3, 1, 768)]
        sub = [(36867, 2, len(date_val), date_val)]  # DateTimeOriginal
        data = build_tiff_with_sub_ifd(main, sub, EXIF_IFD_POINTER_TAG)

        f = io.BytesIO(data)
        header = read_header(f)
        entries, _ = read_ifd(f, header, header.first_ifd_offset)
        result = read_exif_sub_ifd(f, header, entries)
        assert result is not None
        sub_offset, sub_entries = result
        assert sub_offset > 0
        assert any(e.tag_id == 36867 for e in sub_entries)

    def test_returns_none_when_absent(self):
        """No tag 34665 → returns None."""
        data = build_tiff([(256, 3, 1, 1024)])
        f = io.BytesIO(data)
        header = read_header(f)
        entries, _ = read_ifd(f, header, header.first_ifd_offset)
        assert read_exif_sub_ifd(f, header, entries) is None

    def test_handles_zero_offset(self):
        """Tag 34665 with offset 0 returns None."""
        # Manually create a TIFF with tag 34665 pointing to offset 0
        entries = [(256, 3, 1, 1024), (EXIF_IFD_POINTER_TAG, 4, 1, 0)]
        data = build_tiff(entries)
        f = io.BytesIO(data)
        header = read_header(f)
        ifd_entries, _ = read_ifd(f, header, header.first_ifd_offset)
        assert read_exif_sub_ifd(f, header, ifd_entries) is None


class TestExifSubIFDScanning:
    """Test scan_exif_sub_ifd_tags() — PHI detection in EXIF sub-IFDs."""

    def test_date_tags_detected(self):
        """DateTimeOriginal in EXIF sub-IFD is detected as PHI."""
        date_val = b'2024:06:15 10:30:00\x00'
        main = [(256, 3, 1, 1024)]
        sub = [(36867, 2, len(date_val), date_val)]
        data = build_tiff_with_sub_ifd(main, sub, EXIF_IFD_POINTER_TAG)

        f = io.BytesIO(data)
        header = read_header(f)
        entries, _ = read_ifd(f, header, header.first_ifd_offset)
        _, sub_entries = read_exif_sub_ifd(f, header, entries)
        findings = scan_exif_sub_ifd_tags(f, header, sub_entries)
        assert len(findings) >= 1
        assert any(e.tag_id == 36867 for e, _ in findings)

    def test_user_comment_detected(self):
        """UserComment (37510) in EXIF sub-IFD is detected."""
        comment = b'Scanned by Dr. Smith\x00'
        main = [(256, 3, 1, 1024)]
        sub = [(37510, 7, len(comment), comment)]  # UNDEFINED type
        data = build_tiff_with_sub_ifd(main, sub, EXIF_IFD_POINTER_TAG)

        f = io.BytesIO(data)
        header = read_header(f)
        entries, _ = read_ifd(f, header, header.first_ifd_offset)
        _, sub_entries = read_exif_sub_ifd(f, header, entries)
        findings = scan_exif_sub_ifd_tags(f, header, sub_entries)
        assert len(findings) >= 1
        assert any(e.tag_id == 37510 for e, _ in findings)

    def test_already_anonymized_skipped(self):
        """Zeroed-out EXIF tags are skipped."""
        date_val = b'\x00' * 20
        main = [(256, 3, 1, 1024)]
        sub = [(36867, 2, len(date_val), date_val)]
        data = build_tiff_with_sub_ifd(main, sub, EXIF_IFD_POINTER_TAG)

        f = io.BytesIO(data)
        header = read_header(f)
        entries, _ = read_ifd(f, header, header.first_ifd_offset)
        _, sub_entries = read_exif_sub_ifd(f, header, entries)
        findings = scan_exif_sub_ifd_tags(f, header, sub_entries)
        assert len(findings) == 0

    def test_image_unique_id_detected(self):
        """ImageUniqueID (42016) in EXIF sub-IFD is detected."""
        uid = b'abc123def456ghi7\x00'
        main = [(256, 3, 1, 1024)]
        sub = [(42016, 2, len(uid), uid)]
        data = build_tiff_with_sub_ifd(main, sub, EXIF_IFD_POINTER_TAG)

        f = io.BytesIO(data)
        header = read_header(f)
        entries, _ = read_ifd(f, header, header.first_ifd_offset)
        _, sub_entries = read_exif_sub_ifd(f, header, entries)
        findings = scan_exif_sub_ifd_tags(f, header, sub_entries)
        assert len(findings) >= 1
        assert any(e.tag_id == 42016 for e, _ in findings)

    def test_blank_exif_sub_ifd(self):
        """blank_exif_sub_ifd_tags zeros out PHI tags."""
        date_val = b'2024:06:15 10:30:00\x00'
        main = [(256, 3, 1, 1024)]
        sub = [(36867, 2, len(date_val), date_val)]
        data = build_tiff_with_sub_ifd(main, sub, EXIF_IFD_POINTER_TAG)

        f = io.BytesIO(data)
        header = read_header(f)
        entries, _ = read_ifd(f, header, header.first_ifd_offset)
        _, sub_entries = read_exif_sub_ifd(f, header, entries)

        blanked = blank_exif_sub_ifd_tags(f, header, sub_entries)
        assert blanked > 0

        # Re-scan should find nothing
        findings = scan_exif_sub_ifd_tags(f, header, sub_entries)
        assert len(findings) == 0


# ---------------------------------------------------------------------------
# GPS sub-IFD parser
# ---------------------------------------------------------------------------

class TestGPSSubIFDParser:
    """Test read_gps_sub_ifd() — finding and parsing GPS sub-IFDs."""

    def test_returns_entries_when_present(self):
        """Tag 34853 pointing to a valid sub-IFD returns entries."""
        lat_ref = b'N\x00'
        main = [(256, 3, 1, 1024)]
        sub = [(1, 2, len(lat_ref), lat_ref)]  # GPSLatitudeRef
        data = build_tiff_with_sub_ifd(main, sub, GPS_IFD_POINTER_TAG)

        f = io.BytesIO(data)
        header = read_header(f)
        entries, _ = read_ifd(f, header, header.first_ifd_offset)
        result = read_gps_sub_ifd(f, header, entries)
        assert result is not None
        _, sub_entries = result
        assert any(e.tag_id == 1 for e in sub_entries)

    def test_returns_none_when_absent(self):
        """No tag 34853 → returns None."""
        data = build_tiff([(256, 3, 1, 1024)])
        f = io.BytesIO(data)
        header = read_header(f)
        entries, _ = read_ifd(f, header, header.first_ifd_offset)
        assert read_gps_sub_ifd(f, header, entries) is None


class TestGPSScanning:
    """Test scan_gps_sub_ifd() — GPS PHI detection."""

    def test_ascii_ref_detected(self):
        """GPS latitude reference (ASCII) detected as PHI."""
        lat_ref = b'N\x00'
        main = [(256, 3, 1, 1024)]
        sub = [(1, 2, len(lat_ref), lat_ref)]
        data = build_tiff_with_sub_ifd(main, sub, GPS_IFD_POINTER_TAG)

        f = io.BytesIO(data)
        header = read_header(f)
        entries, _ = read_ifd(f, header, header.first_ifd_offset)
        _, sub_entries = read_gps_sub_ifd(f, header, entries)
        findings = scan_gps_sub_ifd(f, header, sub_entries)
        assert len(findings) >= 1

    def test_all_zeroed_skipped(self):
        """Zeroed GPS data is not reported."""
        # Use >4 bytes to force out-of-line storage (inline reads wrong offset)
        zeroed = b'\x00' * 8
        main = [(256, 3, 1, 1024)]
        sub = [(29, 2, len(zeroed), zeroed)]  # GPSDateStamp, 8 zero bytes
        data = build_tiff_with_sub_ifd(main, sub, GPS_IFD_POINTER_TAG)

        f = io.BytesIO(data)
        header = read_header(f)
        entries, _ = read_ifd(f, header, header.first_ifd_offset)
        _, sub_entries = read_gps_sub_ifd(f, header, entries)
        findings = scan_gps_sub_ifd(f, header, sub_entries)
        assert len(findings) == 0

    def test_blank_gps_sub_ifd(self):
        """blank_gps_sub_ifd zeros out all GPS tags."""
        lat_ref = b'N\x00'
        main = [(256, 3, 1, 1024)]
        sub = [(1, 2, len(lat_ref), lat_ref)]
        data = build_tiff_with_sub_ifd(main, sub, GPS_IFD_POINTER_TAG)

        f = io.BytesIO(data)
        header = read_header(f)
        entries, _ = read_ifd(f, header, header.first_ifd_offset)
        _, sub_entries = read_gps_sub_ifd(f, header, entries)

        blanked = blank_gps_sub_ifd(f, header, sub_entries)
        assert blanked > 0

        # Re-scan should find nothing
        findings = scan_gps_sub_ifd(f, header, sub_entries)
        assert len(findings) == 0

    def test_multiple_gps_tags(self):
        """Multiple GPS tags all detected."""
        lat_ref = b'N\x00'
        lon_ref = b'W\x00'
        date_stamp = b'2024:06:15\x00'
        main = [(256, 3, 1, 1024)]
        sub = [
            (1, 2, len(lat_ref), lat_ref),        # GPSLatitudeRef
            (3, 2, len(lon_ref), lon_ref),         # GPSLongitudeRef
            (29, 2, len(date_stamp), date_stamp),  # GPSDateStamp
        ]
        data = build_tiff_with_sub_ifd(main, sub, GPS_IFD_POINTER_TAG)

        f = io.BytesIO(data)
        header = read_header(f)
        entries, _ = read_ifd(f, header, header.first_ifd_offset)
        _, sub_entries = read_gps_sub_ifd(f, header, entries)
        findings = scan_gps_sub_ifd(f, header, sub_entries)
        assert len(findings) == 3


# ---------------------------------------------------------------------------
# Per-handler integration tests
# ---------------------------------------------------------------------------

class TestExifGPSPerHandler:
    """Test that NDPI, SVS, and GenericTIFF handlers scan+anonymize EXIF/GPS sub-IFDs."""

    def _write_tiff_with_exif(self, tmp_path, ext, date_val=b'2024:06:15 10:30:00\x00'):
        """Helper: create a TIFF file with an EXIF sub-IFD containing a date."""
        main = [(256, 3, 1, 1024), (257, 3, 1, 768)]
        sub = [(36867, 2, len(date_val), date_val)]
        data = build_tiff_with_sub_ifd(main, sub, EXIF_IFD_POINTER_TAG)
        filepath = tmp_path / f'test{ext}'
        filepath.write_bytes(data)
        return filepath

    def _write_tiff_with_gps(self, tmp_path, ext):
        """Helper: create a TIFF file with a GPS sub-IFD."""
        lat_ref = b'N\x00'
        main = [(256, 3, 1, 1024), (257, 3, 1, 768)]
        sub = [(1, 2, len(lat_ref), lat_ref)]
        data = build_tiff_with_sub_ifd(main, sub, GPS_IFD_POINTER_TAG)
        filepath = tmp_path / f'test{ext}'
        filepath.write_bytes(data)
        return filepath

    def test_ndpi_scan_exif(self, tmp_path):
        fp = self._write_tiff_with_exif(tmp_path, '.ndpi')
        handler = NDPIHandler()
        result = handler.scan(fp)
        assert not result.is_clean
        assert any('EXIF' in f.tag_name for f in result.findings)

    def test_ndpi_anonymize_exif(self, tmp_path):
        fp = self._write_tiff_with_exif(tmp_path, '.ndpi')
        handler = NDPIHandler()
        cleared = handler.anonymize(fp)
        assert any('EXIF' in f.tag_name for f in cleared)
        # Re-scan should be clean (or at least no EXIF findings)
        result = handler.scan(fp)
        assert not any('EXIF' in f.tag_name for f in result.findings)

    def test_ndpi_scan_gps(self, tmp_path):
        fp = self._write_tiff_with_gps(tmp_path, '.ndpi')
        handler = NDPIHandler()
        result = handler.scan(fp)
        assert not result.is_clean
        assert any('GPS' in f.tag_name for f in result.findings)

    def test_ndpi_anonymize_gps(self, tmp_path):
        fp = self._write_tiff_with_gps(tmp_path, '.ndpi')
        handler = NDPIHandler()
        cleared = handler.anonymize(fp)
        assert any('GPS' in f.tag_name for f in cleared)
        result = handler.scan(fp)
        assert not any('GPS' in f.tag_name for f in result.findings)

    def test_svs_scan_exif(self, tmp_path):
        fp = self._write_tiff_with_exif(tmp_path, '.svs')
        handler = SVSHandler()
        result = handler.scan(fp)
        assert any('EXIF' in f.tag_name for f in result.findings)

    def test_svs_anonymize_exif(self, tmp_path):
        fp = self._write_tiff_with_exif(tmp_path, '.svs')
        handler = SVSHandler()
        handler.anonymize(fp)
        result = handler.scan(fp)
        assert not any('EXIF' in f.tag_name for f in result.findings)

    def test_generic_scan_exif(self, tmp_path):
        fp = self._write_tiff_with_exif(tmp_path, '.tif')
        handler = GenericTIFFHandler()
        result = handler.scan(fp)
        assert any('EXIF' in f.tag_name for f in result.findings)

    def test_generic_anonymize_exif(self, tmp_path):
        fp = self._write_tiff_with_exif(tmp_path, '.tif')
        handler = GenericTIFFHandler()
        handler.anonymize(fp)
        result = handler.scan(fp)
        assert not any('EXIF' in f.tag_name for f in result.findings)

    def test_generic_scan_gps(self, tmp_path):
        fp = self._write_tiff_with_gps(tmp_path, '.tif')
        handler = GenericTIFFHandler()
        result = handler.scan(fp)
        assert any('GPS' in f.tag_name for f in result.findings)

    def test_generic_anonymize_gps(self, tmp_path):
        fp = self._write_tiff_with_gps(tmp_path, '.tif')
        handler = GenericTIFFHandler()
        handler.anonymize(fp)
        result = handler.scan(fp)
        assert not any('GPS' in f.tag_name for f in result.findings)
