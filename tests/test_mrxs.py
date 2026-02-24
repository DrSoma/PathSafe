"""Tests for the MRXS format handler."""

import pytest
from pathsafe.formats.mrxs import MRXSHandler


@pytest.fixture
def handler():
    return MRXSHandler()


class TestMRXSCanHandle:
    def test_mrxs_extension(self, handler, tmp_mrxs):
        assert handler.can_handle(tmp_mrxs)

    def test_uppercase_extension(self, handler, tmp_path):
        f = tmp_path / 'SLIDE.MRXS'
        f.write_bytes(b'x')
        assert handler.can_handle(f)

    def test_non_mrxs(self, handler, tmp_path):
        assert not handler.can_handle(tmp_path / 'slide.svs')
        assert not handler.can_handle(tmp_path / 'slide.ndpi')


class TestMRXSScan:
    def test_detect_slidedat_phi(self, handler, tmp_mrxs):
        result = handler.scan(tmp_mrxs)
        assert not result.is_clean
        assert result.format == 'mrxs'
        tag_names = {f.tag_name for f in result.findings}
        assert any('SLIDE_ID' in t for t in tag_names)
        assert any('SLIDE_NAME' in t for t in tag_names)
        assert any('SLIDE_BARCODE' in t for t in tag_names)

    def test_detect_creation_datetime(self, handler, tmp_mrxs):
        result = handler.scan(tmp_mrxs)
        tag_names = {f.tag_name for f in result.findings}
        assert any('SLIDE_CREATIONDATETIME' in t for t in tag_names)

    def test_clean_file(self, handler, tmp_mrxs_clean):
        result = handler.scan(tmp_mrxs_clean)
        assert result.is_clean

    def test_no_companion_directory(self, handler, tmp_mrxs_no_companion):
        result = handler.scan(tmp_mrxs_no_companion)
        assert not result.is_clean
        assert result.error is not None
        assert 'companion' in result.error.lower() or 'directory' in result.error.lower()

    def test_scan_error_fail_closed(self, handler, tmp_path, monkeypatch):
        """Scan errors return is_clean=False (fail-closed)."""
        filepath = tmp_path / 'error_slide.mrxs'
        filepath.write_bytes(b'x')
        data_dir = tmp_path / 'error_slide'
        data_dir.mkdir()
        slidedat = data_dir / 'Slidedat.ini'
        slidedat.write_text('[GENERAL]\nSLIDE_ID=12345\n')

        # Monkey-patch to force an exception
        def _raise(*args, **kwargs):
            raise IOError("Test error")
        monkeypatch.setattr(handler, '_scan_slidedat', _raise)
        result = handler.scan(filepath)
        assert not result.is_clean
        assert result.error is not None


class TestMRXSAnonymize:
    def test_anonymize_clears_phi(self, handler, tmp_mrxs):
        result = handler.scan(tmp_mrxs)
        assert not result.is_clean

        cleared = handler.anonymize(tmp_mrxs)
        assert len(cleared) > 0

        result = handler.scan(tmp_mrxs)
        assert result.is_clean

    def test_anonymize_already_clean(self, handler, tmp_mrxs_clean):
        cleared = handler.anonymize(tmp_mrxs_clean)
        assert len(cleared) == 0

    def test_idempotent(self, handler, tmp_mrxs):
        cleared1 = handler.anonymize(tmp_mrxs)
        cleared2 = handler.anonymize(tmp_mrxs)
        assert len(cleared1) > 0
        assert len(cleared2) == 0

    def test_no_companion_returns_empty(self, handler, tmp_mrxs_no_companion):
        cleared = handler.anonymize(tmp_mrxs_no_companion)
        assert len(cleared) == 0


class TestMRXSAnonymizeSlidedat:
    def test_slidedat_fields_replaced(self, handler, tmp_mrxs):
        handler.anonymize(tmp_mrxs)

        # Read back and check
        import configparser
        data_dir = tmp_mrxs.parent / tmp_mrxs.stem
        config = configparser.ConfigParser()
        config.optionxform = str
        config.read(str(data_dir / 'Slidedat.ini'))

        # SLIDE_ID should be X's
        slide_id = config.get('GENERAL', 'SLIDE_ID').strip()
        assert all(c == 'X' for c in slide_id)

        # SLIDE_CREATIONDATETIME should be sentinel
        dt = config.get('GENERAL', 'SLIDE_CREATIONDATETIME').strip()
        assert dt == '19000101000000'


class TestMRXSInfo:
    def test_get_info(self, handler, tmp_mrxs):
        info = handler.get_format_info(tmp_mrxs)
        assert info['format'] == 'mrxs'
        assert info['file_size'] > 0
        assert 'data_directory' in info

    def test_get_info_no_companion(self, handler, tmp_mrxs_no_companion):
        info = handler.get_format_info(tmp_mrxs_no_companion)
        assert info['format'] == 'mrxs'
        assert 'error' in info
