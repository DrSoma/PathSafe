"""Tests for the NDPI format handler."""

import pytest
from pathsafe.formats.ndpi import NDPIHandler


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
