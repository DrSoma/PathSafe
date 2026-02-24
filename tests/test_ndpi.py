"""Tests for the NDPI format handler."""

import pytest
from pathsafe.formats.ndpi import NDPIHandler, NDPI_PRIVATE_TAG_RANGE, _NDPI_HANDLED_TAGS
from tests.conftest import build_tiff


@pytest.fixture
def handler():
    return NDPIHandler()


class TestNDPICanHandle:
    def test_ndpi_extension(self, handler, tmp_path):
        assert handler.can_handle(tmp_path / 'slide.ndpi')
        assert handler.can_handle(tmp_path / 'SLIDE.NDPI')

    def test_non_ndpi(self, handler, tmp_path):
        assert not handler.can_handle(tmp_path / 'slide.svs')
        assert not handler.can_handle(tmp_path / 'slide.tif')


class TestNDPIScan:
    def test_detect_phi(self, handler, tmp_ndpi):
        result = handler.scan(tmp_ndpi)
        assert not result.is_clean
        assert result.format == 'ndpi'
        # Should find barcode (tag 65468) and potentially datetime
        tag_names = {f.tag_name for f in result.findings}
        assert 'NDPI_BARCODE' in tag_names

    def test_clean_file(self, handler, tmp_ndpi_clean):
        result = handler.scan(tmp_ndpi_clean)
        assert result.is_clean
        assert len(result.findings) == 0

    def test_regex_fallback(self, handler, tmp_ndpi_with_regex_phi):
        result = handler.scan(tmp_ndpi_with_regex_phi)
        assert not result.is_clean
        assert any('regex' in f.tag_name for f in result.findings)


class TestNDPIAnonymize:
    def test_anonymize_barcode(self, handler, tmp_ndpi):
        # Verify PHI exists
        result = handler.scan(tmp_ndpi)
        assert not result.is_clean

        # Anonymize
        cleared = handler.anonymize(tmp_ndpi)
        assert len(cleared) > 0

        # Verify clean
        result = handler.scan(tmp_ndpi)
        assert result.is_clean

    def test_anonymize_already_clean(self, handler, tmp_ndpi_clean):
        cleared = handler.anonymize(tmp_ndpi_clean)
        assert len(cleared) == 0

    def test_idempotent(self, handler, tmp_ndpi):
        # Anonymize twice
        cleared1 = handler.anonymize(tmp_ndpi)
        cleared2 = handler.anonymize(tmp_ndpi)
        assert len(cleared1) > 0
        assert len(cleared2) == 0  # Second pass should find nothing


class TestNDPIInfo:
    def test_get_info(self, handler, tmp_ndpi):
        info = handler.get_format_info(tmp_ndpi)
        assert info['format'] == 'ndpi'
        assert info['file_size'] > 0
        assert info['byte_order'] in ('little-endian', 'big-endian')


class TestNDPIPrivateTags:
    """Test NDPI private tag sweep (65420-65480 range)."""

    def test_scan_detects_unhandled_string_tag(self, tmp_path):
        """Unhandled NDPI private tag with string data is detected."""
        scan_profile = b'Profile data with serial ABC\x00'
        entries = [
            (256, 3, 1, 1024),
            (257, 3, 1, 768),
            (65477, 2, len(scan_profile), scan_profile),  # NDPI_SCANPROFILE
        ]
        data = build_tiff(entries)
        fp = tmp_path / 'private_tags.ndpi'
        fp.write_bytes(data)

        handler = NDPIHandler()
        result = handler.scan(fp)
        assert not result.is_clean
        assert any(f.tag_id == 65477 for f in result.findings)

    def test_scan_detects_barcode_type(self, tmp_path):
        """NDPI_BARCODE_TYPE (65480) with string content is detected."""
        barcode_type = b'QR-Code\x00'
        entries = [
            (256, 3, 1, 1024),
            (257, 3, 1, 768),
            (65480, 2, len(barcode_type), barcode_type),
        ]
        data = build_tiff(entries)
        fp = tmp_path / 'barcode_type.ndpi'
        fp.write_bytes(data)

        handler = NDPIHandler()
        result = handler.scan(fp)
        assert any(f.tag_id == 65480 for f in result.findings)

    def test_scan_detects_unknown_private_tag(self, tmp_path):
        """Unknown tag 65479 (not in exclusion list) with string data is detected."""
        unknown_val = b'Some scanner metadata\x00'
        entries = [
            (256, 3, 1, 1024),
            (257, 3, 1, 768),
            (65479, 2, len(unknown_val), unknown_val),
        ]
        data = build_tiff(entries)
        fp = tmp_path / 'unknown_tag.ndpi'
        fp.write_bytes(data)

        handler = NDPIHandler()
        result = handler.scan(fp)
        assert any(f.tag_id == 65479 for f in result.findings)

    def test_numeric_tags_not_flagged(self, tmp_path):
        """Numeric-typed NDPI private tags are not flagged."""
        entries = [
            (256, 3, 1, 1024),
            (257, 3, 1, 768),
            (65422, 12, 1, 0),  # NDPI_XOFFSET (DOUBLE, numeric)
        ]
        data = build_tiff(entries)
        fp = tmp_path / 'numeric_tag.ndpi'
        fp.write_bytes(data)

        handler = NDPIHandler()
        result = handler.scan(fp)
        # Should not flag numeric-only private tags
        assert not any(f.tag_id == 65422 for f in result.findings)

    def test_handled_tags_not_doubled(self, tmp_path):
        """Already-handled tags (65421, 65427, etc.) are not double-reported."""
        reference = b'REF-001\x00'
        entries = [
            (256, 3, 1, 1024),
            (257, 3, 1, 768),
            (65427, 2, len(reference), reference),  # NDPI_REFERENCE -- handled explicitly
        ]
        data = build_tiff(entries)
        fp = tmp_path / 'handled_tag.ndpi'
        fp.write_bytes(data)

        handler = NDPIHandler()
        result = handler.scan(fp)
        # 65427 should appear exactly once (from the explicit PHI_TAGS check)
        count_65427 = sum(1 for f in result.findings if f.tag_id == 65427)
        assert count_65427 == 1

    def test_anonymize_blanks_private_tags(self, tmp_path):
        """Anonymize blanks unhandled private string tags."""
        scan_profile = b'Profile data with serial ABC\x00'
        entries = [
            (256, 3, 1, 1024),
            (257, 3, 1, 768),
            (65477, 2, len(scan_profile), scan_profile),
        ]
        data = build_tiff(entries)
        fp = tmp_path / 'blank_private.ndpi'
        fp.write_bytes(data)

        handler = NDPIHandler()
        cleared = handler.anonymize(fp)
        assert any(f.tag_id == 65477 for f in cleared)

        # Re-scan should be clean
        result = handler.scan(fp)
        assert not any(f.tag_id == 65477 for f in result.findings)

    def test_already_blanked_private_tag_skipped(self, tmp_path):
        """Private tags that are already all-zeros are not flagged."""
        zeroed = b'\x00' * 20
        entries = [
            (256, 3, 1, 1024),
            (257, 3, 1, 768),
            (65477, 2, len(zeroed), zeroed),
        ]
        data = build_tiff(entries)
        fp = tmp_path / 'zeroed_private.ndpi'
        fp.write_bytes(data)

        handler = NDPIHandler()
        result = handler.scan(fp)
        assert not any(f.tag_id == 65477 for f in result.findings)

    def test_constants_consistency(self):
        """All _NDPI_HANDLED_TAGS are within the private tag range."""
        for tag in _NDPI_HANDLED_TAGS:
            assert tag in NDPI_PRIVATE_TAG_RANGE
