"""Tests for the generic TIFF fallback handler."""

import pytest
from pathsafe.formats.generic_tiff import GenericTIFFHandler
from tests.conftest import build_tiff


@pytest.fixture
def handler():
    return GenericTIFFHandler()


class TestGenericTIFFCanHandle:
    def test_tif_extension(self, handler, tmp_tiff_with_phi):
        assert handler.can_handle(tmp_tiff_with_phi)

    def test_tiff_extension(self, handler, tmp_path):
        f = tmp_path / 'slide.tiff'
        f.write_bytes(build_tiff([(256, 3, 1, 100)]))
        assert handler.can_handle(f)

    def test_svs_extension(self, handler, tmp_svs):
        """GenericTIFFHandler accepts SVS as a TIFF variant."""
        assert handler.can_handle(tmp_svs)

    def test_non_tiff_extension(self, handler, tmp_path):
        assert not handler.can_handle(tmp_path / 'slide.dcm')
        assert not handler.can_handle(tmp_path / 'slide.mrxs')
        assert not handler.can_handle(tmp_path / 'slide.txt')

    def test_invalid_magic(self, handler, tmp_path):
        f = tmp_path / 'bad.tif'
        f.write_bytes(b'NOT A TIFF FILE')
        assert not handler.can_handle(f)


class TestGenericTIFFScan:
    def test_detect_phi_in_string(self, handler, tmp_tiff_with_phi):
        result = handler.scan(tmp_tiff_with_phi)
        assert not result.is_clean
        assert result.format == 'tiff'
        assert len(result.findings) > 0

    def test_detect_date(self, handler, tmp_path):
        desc = b'2024:06:15 10:30:00\x00'
        entries = [
            (256, 3, 1, 512),
            (257, 3, 1, 512),
            (306, 2, len(desc), desc),
        ]
        f = tmp_path / 'datetest.tif'
        f.write_bytes(build_tiff(entries))
        result = handler.scan(f)
        assert not result.is_clean

    def test_clean_file(self, handler, tmp_tiff_clean):
        result = handler.scan(tmp_tiff_clean)
        assert result.is_clean
        assert len(result.findings) == 0

    def test_invalid_tiff_fail_closed(self, handler, tmp_path):
        """Invalid TIFF returns is_clean=False (fail-closed)."""
        f = tmp_path / 'invalid.tif'
        f.write_bytes(b'II' + b'\x63\x00' + b'\x00\x00\x00\x00')  # magic=99
        result = handler.scan(f)
        assert not result.is_clean
        assert result.error is not None

    def test_scan_exception_fail_closed(self, handler, tmp_tiff_with_phi, monkeypatch):
        """Scan error returns is_clean=False."""
        import pathsafe.formats.generic_tiff as gt_mod
        def _raise(*args, **kwargs):
            raise IOError("Forced test error")
        monkeypatch.setattr(gt_mod, 'iter_ifds', _raise)
        result = handler.scan(tmp_tiff_with_phi)
        assert not result.is_clean
        assert result.error is not None

    def test_filename_phi_detected(self, handler, tmp_path):
        """Files with PHI in filename are detected."""
        desc = b'clean data\x00'
        entries = [
            (256, 3, 1, 512),
            (257, 3, 1, 512),
            (270, 2, len(desc), desc),
        ]
        f = tmp_path / 'AS-24-123456.tif'
        f.write_bytes(build_tiff(entries))
        result = handler.scan(f)
        tag_names = {finding.tag_name for finding in result.findings}
        assert any('Filename' in t for t in tag_names)


class TestGenericTIFFAnonymize:
    def test_anonymize_clears_phi(self, handler, tmp_tiff_with_phi):
        result = handler.scan(tmp_tiff_with_phi)
        assert not result.is_clean

        cleared = handler.anonymize(tmp_tiff_with_phi)
        assert len(cleared) > 0

        result = handler.scan(tmp_tiff_with_phi)
        assert result.is_clean

    def test_anonymize_clean_file(self, handler, tmp_tiff_clean):
        cleared = handler.anonymize(tmp_tiff_clean)
        assert len(cleared) == 0

    def test_idempotent(self, handler, tmp_tiff_with_phi):
        cleared1 = handler.anonymize(tmp_tiff_with_phi)
        cleared2 = handler.anonymize(tmp_tiff_with_phi)
        assert len(cleared1) > 0
        assert len(cleared2) == 0


class TestGenericTIFFInfo:
    def test_get_info(self, handler, tmp_tiff_with_phi):
        info = handler.get_format_info(tmp_tiff_with_phi)
        assert info['format'] == 'tiff'
        assert info['file_size'] > 0
        assert info['byte_order'] in ('little-endian', 'big-endian')

    def test_get_info_invalid(self, handler, tmp_path):
        f = tmp_path / 'bad.tif'
        f.write_bytes(b'NOT A TIFF')
        info = handler.get_format_info(f)
        assert info['format'] == 'tiff'
        assert info['file_size'] > 0
