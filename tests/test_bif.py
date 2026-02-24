"""Tests for the BIF format handler."""

import pytest
from pathsafe.formats.bif import BIFHandler


@pytest.fixture
def handler():
    return BIFHandler()


class TestBIFCanHandle:
    def test_bif_extension(self, handler, tmp_bif):
        assert handler.can_handle(tmp_bif)

    def test_uppercase_extension(self, handler, tmp_path):
        from tests.conftest import build_tiff
        f = tmp_path / 'SLIDE.BIF'
        f.write_bytes(build_tiff([(256, 3, 1, 100)]))
        assert handler.can_handle(f)

    def test_non_bif(self, handler, tmp_path):
        assert not handler.can_handle(tmp_path / 'slide.svs')
        assert not handler.can_handle(tmp_path / 'slide.ndpi')

    def test_invalid_tiff(self, handler, tmp_path):
        f = tmp_path / 'bad.bif'
        f.write_bytes(b'NOT A TIFF FILE')
        assert not handler.can_handle(f)


class TestBIFScan:
    def test_detect_xmp_phi(self, handler, tmp_bif):
        result = handler.scan(tmp_bif)
        assert not result.is_clean
        assert result.format == 'bif'
        tag_names = {f.tag_name for f in result.findings}
        assert any('BarCode1' in t for t in tag_names)

    def test_detect_datetime(self, handler, tmp_bif):
        result = handler.scan(tmp_bif)
        tag_names = {f.tag_name for f in result.findings}
        assert any('DateTime' in t for t in tag_names)

    def test_detect_operator(self, handler, tmp_bif):
        result = handler.scan(tmp_bif)
        tag_names = {f.tag_name for f in result.findings}
        assert any('OperatorID' in t for t in tag_names)

    def test_clean_file(self, handler, tmp_bif_clean):
        result = handler.scan(tmp_bif_clean)
        assert result.is_clean
        assert len(result.findings) == 0

    def test_scan_error_fail_closed(self, handler, tmp_bif, monkeypatch):
        """Scan error returns is_clean=False (fail-closed)."""
        def _raise(*args, **kwargs):
            raise IOError("Test error")
        monkeypatch.setattr(handler, '_scan_xmp', _raise)
        result = handler.scan(tmp_bif)
        assert not result.is_clean
        assert result.error is not None


class TestBIFAnonymize:
    def test_anonymize_xmp(self, handler, tmp_bif):
        result = handler.scan(tmp_bif)
        assert not result.is_clean

        cleared = handler.anonymize(tmp_bif)
        assert len(cleared) > 0

        result = handler.scan(tmp_bif)
        assert result.is_clean

    def test_anonymize_already_clean(self, handler, tmp_bif_clean):
        cleared = handler.anonymize(tmp_bif_clean)
        assert len(cleared) == 0

    def test_idempotent(self, handler, tmp_bif):
        cleared1 = handler.anonymize(tmp_bif)
        cleared2 = handler.anonymize(tmp_bif)
        assert len(cleared1) > 0
        assert len(cleared2) == 0


class TestBIFInfo:
    def test_get_info(self, handler, tmp_bif):
        info = handler.get_format_info(tmp_bif)
        assert info['format'] == 'bif'
        assert info['file_size'] > 0
        assert info['byte_order'] in ('little-endian', 'big-endian')
