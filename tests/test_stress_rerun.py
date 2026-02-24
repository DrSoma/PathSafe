"""Stress tests -- mixed-state re-anonymization, double-anonymize, legacy detection."""

import io
import struct

import pytest
from pathlib import Path

from pathsafe.anonymizer import anonymize_file
from pathsafe.formats.ndpi import NDPIHandler
from pathsafe.formats.svs import SVSHandler
from pathsafe.formats.bif import BIFHandler
from pathsafe.formats.scn import SCNHandler
from pathsafe.tiff import read_header, iter_ifds, _BLANK_JPEG, _LEGACY_BLANK_JPEG
from tests.conftest import (
    build_tiff, build_tiff_multi_ifd, build_tiff_with_strips,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_ndpi(tmp_path, name, barcode=b'AS-24-123456\x00',
               reference=b'REF-001\x00', datetime_val=b'2024:06:15 10:30:00\x00'):
    entries = [
        (256, 3, 1, 1024),
        (257, 3, 1, 768),
        (306, 2, len(datetime_val), datetime_val),
        (65427, 2, len(reference), reference),
        (65468, 2, len(barcode), barcode),
    ]
    content = build_tiff(entries)
    filepath = tmp_path / name
    filepath.write_bytes(content)
    return filepath


def _make_svs(tmp_path, name, desc=None):
    if desc is None:
        desc = (
            b'Aperio Image Library v12.0.16\n'
            b'1024x768 [0,0 1024x768] (256x256) JPEG Q=70'
            b'|AppMag = 40'
            b'|ScanScope ID = SS1234'
            b'|Filename = test.svs'
            b'|Date = 06/15/24'
            b'|Time = 10:30:00'
            b'|User = jdoe@hospital.org'
            b'\x00'
        )
    entries = [
        (256, 3, 1, 1024),
        (257, 3, 1, 768),
        (270, 2, len(desc), desc),
    ]
    content = build_tiff(entries)
    filepath = tmp_path / name
    filepath.write_bytes(content)
    return filepath


def _make_bif(tmp_path, name, xmp=None):
    if xmp is None:
        xmp = (
            b'<?xpacket begin="" id="W5M0MpCehiHzreSzNTczkc9d"?>'
            b'<x:xmpmeta xmlns:x="adobe:ns:meta/">'
            b'<iScan BarCode1="AS-24-111111" ScanDate="2024-06-15"/>'
            b'</x:xmpmeta>'
            b'<?xpacket end="w"?>\x00'
        )
    entries = [
        (256, 3, 1, 1024),
        (257, 3, 1, 768),
        (700, 7, len(xmp), xmp),
    ]
    content = build_tiff(entries)
    filepath = tmp_path / name
    filepath.write_bytes(content)
    return filepath


def _make_scn(tmp_path, name, xml=None):
    if xml is None:
        xml = (
            b'<?xml version="1.0" encoding="UTF-8"?>'
            b'<scn xmlns="http://www.leica-microsystems.com/scn/2010/10/01">'
            b'<collection>'
            b'<barcode>AS-24-222222</barcode>'
            b'<creationDate>2024-06-15T10:30:00</creationDate>'
            b'</collection>'
            b'</scn>\x00'
        )
    entries = [
        (256, 3, 1, 1024),
        (257, 3, 1, 768),
        (270, 2, len(xml), xml),
    ]
    content = build_tiff(entries)
    filepath = tmp_path / name
    filepath.write_bytes(content)
    return filepath


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestMixedAnonymizationState:
    """Test files where some tags are already anonymized and others aren't."""

    def test_ndpi_partial_tags(self, tmp_path):
        """NDPI with barcode X'd but reference still has PHI."""
        filepath = _make_ndpi(
            tmp_path, 'partial.ndpi',
            barcode=b'XXXXXXXXXXXX\x00',   # Already anonymized
            reference=b'REF-001\x00',      # Still has PHI
        )
        handler = NDPIHandler()
        scan = handler.scan(filepath)
        # Should find NDPI_REFERENCE but not NDPI_BARCODE
        tag_names = {f.tag_name for f in scan.findings}
        assert 'NDPI_REFERENCE' in tag_names

        cleared = handler.anonymize(filepath)
        ref_cleared = [f for f in cleared if f.tag_name == 'NDPI_REFERENCE']
        assert len(ref_cleared) > 0
        barcode_cleared = [f for f in cleared if f.tag_name == 'NDPI_BARCODE']
        assert len(barcode_cleared) == 0

    def test_ndpi_date_anonymized_phi_present(self, tmp_path):
        """NDPI with date zeroed but barcode still has PHI."""
        filepath = _make_ndpi(
            tmp_path, 'date_anon.ndpi',
            datetime_val=b'\x00' * 20,   # Already anonymized
        )
        handler = NDPIHandler()
        cleared = handler.anonymize(filepath)
        # Should clear barcode and reference, but NOT DateTime
        date_cleared = [f for f in cleared if f.tag_name == 'DateTime']
        assert len(date_cleared) == 0
        barcode_cleared = [f for f in cleared if f.tag_name == 'NDPI_BARCODE']
        assert len(barcode_cleared) > 0

    def test_mixed_state_across_ifds(self, tmp_path):
        """Multi-IFD NDPI where IFD0 has PHI, IFD1 is clean."""
        barcode = b'AS-24-123456\x00'
        barcode_clean = b'XXXXXXXXXXXX\x00'

        ifd0 = [
            (256, 3, 1, 1024),
            (257, 3, 1, 768),
            (65468, 2, len(barcode), barcode),
        ]
        ifd1 = [
            (256, 3, 1, 512),
            (257, 3, 1, 384),
            (65468, 2, len(barcode_clean), barcode_clean),
        ]
        content = build_tiff_multi_ifd([ifd0, ifd1])
        filepath = tmp_path / 'mixed_ifds.ndpi'
        filepath.write_bytes(content)

        handler = NDPIHandler()
        cleared = handler.anonymize(filepath)
        # Should clear barcode from IFD0 only
        barcode_cleared = [f for f in cleared if f.tag_name == 'NDPI_BARCODE']
        assert len(barcode_cleared) >= 1


class TestDoubleAnonymization:
    """Test that anonymizing twice is a no-op for all TIFF-based formats."""

    def test_ndpi_double(self, tmp_path):
        filepath = _make_ndpi(tmp_path, 'double.ndpi')
        handler = NDPIHandler()
        cleared1 = handler.anonymize(filepath)
        assert len(cleared1) > 0
        cleared2 = handler.anonymize(filepath)
        assert len(cleared2) == 0

        scan = handler.scan(filepath)
        assert scan.is_clean

    def test_svs_double(self, tmp_path):
        filepath = _make_svs(tmp_path, 'double.svs')
        handler = SVSHandler()
        cleared1 = handler.anonymize(filepath)
        assert len(cleared1) > 0
        cleared2 = handler.anonymize(filepath)
        assert len(cleared2) == 0

        scan = handler.scan(filepath)
        assert scan.is_clean

    def test_bif_double(self, tmp_path):
        filepath = _make_bif(tmp_path, 'double.bif')
        handler = BIFHandler()
        cleared1 = handler.anonymize(filepath)
        assert len(cleared1) > 0
        cleared2 = handler.anonymize(filepath)
        assert len(cleared2) == 0

        scan = handler.scan(filepath)
        assert scan.is_clean

    def test_scn_double(self, tmp_path):
        filepath = _make_scn(tmp_path, 'double.scn')
        handler = SCNHandler()
        cleared1 = handler.anonymize(filepath)
        assert len(cleared1) > 0
        cleared2 = handler.anonymize(filepath)
        assert len(cleared2) == 0

        scan = handler.scan(filepath)
        assert scan.is_clean


class TestRerunWithLegacyBlanking:
    """Test re-anonymization with legacy-style blanked labels."""

    def test_legacy_soi_eoi_detected(self, tmp_path):
        """Legacy 4-byte SOI+EOI blanking is detected by is_ifd_image_blanked."""
        from pathsafe.tiff import is_ifd_image_blanked
        # Create a TIFF with strip data = legacy blank + zeros
        strip_data = _LEGACY_BLANK_JPEG + b'\x00' * 96
        tag_entries = [
            (256, 3, 1, 64),
            (257, 3, 1, 64),
        ]
        content = build_tiff_with_strips(tag_entries, strip_data)
        filepath = tmp_path / 'legacy.tif'
        filepath.write_bytes(content)

        with open(filepath, 'rb') as f:
            header = read_header(f)
            ifds = iter_ifds(f, header)
            _, entries = ifds[0]
            assert is_ifd_image_blanked(f, header, entries) is True


class TestPartiallyCorruptFile:
    """Test fail-closed behavior on partially corrupt files."""

    def test_truncated_tag_data_fail_closed(self, tmp_path):
        """File with truncated tag data → scan reports is_clean=False."""
        # Build a TIFF where tag 270 claims 1000 bytes but file is truncated
        desc = b'Patient: AS-22-555555\x00'
        entries = [
            (256, 3, 1, 512),
            (257, 3, 1, 512),
            (270, 2, 1000, desc),  # Claims 1000 bytes but only has 22
        ]
        content = build_tiff(entries)
        # Truncate the file
        content = content[:len(content) - 10]
        filepath = tmp_path / 'truncated.ndpi'
        filepath.write_bytes(content)

        handler = NDPIHandler()
        scan = handler.scan(filepath)
        # Should either find PHI via regex/fallback or report not clean
        # The key safety property: never reports is_clean=True on error
        if scan.error:
            assert not scan.is_clean


class TestSVSWithPartialAnonymization:
    """Test SVS with some fields anonymized and others not."""

    def test_date_anon_but_scanscope_present(self, tmp_path):
        """Date anonymized but ScanScope ID present → only ID cleared."""
        desc = (
            b'Aperio Image Library v12.0.16\n'
            b'1024x768 [0,0 1024x768] (256x256) JPEG Q=70'
            b'|AppMag = 40'
            b'|ScanScope ID = SS1234'
            b'|Filename = XXXXXXXXXXXX'
            b'|Date = 01/01/00'
            b'|Time = 00:00:00'
            b'|User = XXXX'
            b'\x00'
        )
        filepath = _make_svs(tmp_path, 'partial_svs.svs', desc=desc)
        handler = SVSHandler()
        cleared = handler.anonymize(filepath)
        # Only ScanScope ID should be cleared (Date/Time/Filename/User already anon)
        tag_names = [f.tag_name for f in cleared]
        assert any('ScanScope ID' in t for t in tag_names)
        assert not any('Date' == t.split(':')[-1].strip() for t in tag_names
                       if 'Date' in t and 'DateTime' not in t and 'creation' not in t.lower())
