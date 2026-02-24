"""Tests for the SCN format handler."""

import pytest
from pathsafe.formats.scn import SCNHandler


@pytest.fixture
def handler():
    return SCNHandler()


class TestSCNCanHandle:
    def test_scn_extension(self, handler, tmp_scn):
        assert handler.can_handle(tmp_scn)

    def test_uppercase_extension(self, handler, tmp_path):
        from tests.conftest import build_tiff
        f = tmp_path / 'SLIDE.SCN'
        f.write_bytes(build_tiff([(256, 3, 1, 100)]))
        assert handler.can_handle(f)

    def test_non_scn(self, handler, tmp_path):
        assert not handler.can_handle(tmp_path / 'slide.svs')
        assert not handler.can_handle(tmp_path / 'slide.bif')

    def test_invalid_tiff(self, handler, tmp_path):
        f = tmp_path / 'bad.scn'
        f.write_bytes(b'NOT A TIFF FILE')
        assert not handler.can_handle(f)


class TestSCNScan:
    def test_detect_xml_barcode(self, handler, tmp_scn):
        result = handler.scan(tmp_scn)
        assert not result.is_clean
        assert result.format == 'scn'
        tag_names = {f.tag_name for f in result.findings}
        assert any('barcode' in t for t in tag_names)

    def test_detect_xml_creation_date(self, handler, tmp_scn):
        result = handler.scan(tmp_scn)
        tag_names = {f.tag_name for f in result.findings}
        assert any('creationDate' in t for t in tag_names)

    def test_detect_datetime(self, handler, tmp_scn):
        result = handler.scan(tmp_scn)
        tag_names = {f.tag_name for f in result.findings}
        assert any('DateTime' in t for t in tag_names)

    def test_clean_file(self, handler, tmp_scn_clean):
        result = handler.scan(tmp_scn_clean)
        assert result.is_clean

    def test_scan_error_fail_closed(self, handler, tmp_scn, monkeypatch):
        """Scan error returns is_clean=False (fail-closed)."""
        def _raise(*args, **kwargs):
            raise IOError("Test error")
        monkeypatch.setattr(handler, '_scan_xml_metadata', _raise)
        result = handler.scan(tmp_scn)
        assert not result.is_clean
        assert result.error is not None


class TestSCNAnonymize:
    def test_anonymize_clears_phi(self, handler, tmp_scn):
        result = handler.scan(tmp_scn)
        assert not result.is_clean

        cleared = handler.anonymize(tmp_scn)
        assert len(cleared) > 0

        result = handler.scan(tmp_scn)
        assert result.is_clean

    def test_anonymize_already_clean(self, handler, tmp_scn_clean):
        cleared = handler.anonymize(tmp_scn_clean)
        assert len(cleared) == 0

    def test_idempotent(self, handler, tmp_scn):
        cleared1 = handler.anonymize(tmp_scn)
        cleared2 = handler.anonymize(tmp_scn)
        assert len(cleared1) > 0
        assert len(cleared2) == 0


class TestSCNInfo:
    def test_get_info(self, handler, tmp_scn):
        info = handler.get_format_info(tmp_scn)
        assert info['format'] == 'scn'
        assert info['file_size'] > 0
        assert info['byte_order'] in ('little-endian', 'big-endian')
