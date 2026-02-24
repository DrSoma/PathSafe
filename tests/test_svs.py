"""Tests for the SVS format handler."""

import pytest
from pathsafe.formats.svs import SVSHandler, _parse_tag270


@pytest.fixture
def handler():
    return SVSHandler()


class TestSVSCanHandle:
    def test_svs_extension(self, handler, tmp_path):
        assert handler.can_handle(tmp_path / 'slide.svs')
        assert handler.can_handle(tmp_path / 'SLIDE.SVS')

    def test_non_svs(self, handler, tmp_path):
        assert not handler.can_handle(tmp_path / 'slide.ndpi')
        assert not handler.can_handle(tmp_path / 'slide.tif')


class TestParseTag270:
    def test_parse_fields(self):
        value = ('Aperio Image Library v12.0.16\n'
                 '1024x768 JPEG|AppMag = 40|ScanScope ID = SS1234'
                 '|Filename = test.svs|Date = 06/15/24|Time = 10:30:00'
                 '|User = admin|MPP = 0.2520')
        fields = _parse_tag270(value)
        assert fields['AppMag'] == '40'
        assert fields['ScanScope ID'] == 'SS1234'
        assert fields['Filename'] == 'test.svs'
        assert fields['Date'] == '06/15/24'
        assert fields['Time'] == '10:30:00'
        assert fields['User'] == 'admin'
        assert fields['MPP'] == '0.2520'

    def test_empty_value(self):
        fields = _parse_tag270('')
        assert fields == {}


class TestSVSScan:
    def test_detect_phi(self, handler, tmp_svs):
        result = handler.scan(tmp_svs)
        assert not result.is_clean
        assert result.format == 'svs'
        tag_names = {f.tag_name for f in result.findings}
        assert any('ScanScope ID' in t for t in tag_names)
        assert any('Filename' in t for t in tag_names)
        assert any('Date' in t for t in tag_names)
        assert any('Time' in t for t in tag_names)
        assert any('User' in t for t in tag_names)


class TestSVSAnonymize:
    def test_anonymize_all_fields(self, handler, tmp_svs):
        # Verify PHI present
        result = handler.scan(tmp_svs)
        assert not result.is_clean

        # Anonymize
        cleared = handler.anonymize(tmp_svs)
        assert len(cleared) > 0

        # Verify clean
        result = handler.scan(tmp_svs)
        assert result.is_clean

    def test_idempotent(self, handler, tmp_svs):
        cleared1 = handler.anonymize(tmp_svs)
        cleared2 = handler.anonymize(tmp_svs)
        assert len(cleared1) > 0
        assert len(cleared2) == 0


class TestSVSInfo:
    def test_get_info(self, handler, tmp_svs):
        info = handler.get_format_info(tmp_svs)
        assert info['format'] == 'svs'
        assert info['file_size'] > 0
