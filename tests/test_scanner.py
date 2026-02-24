"""Tests for the PHI detection scanner."""

import pytest
from pathsafe.scanner import (
    scan_bytes_for_phi,
    scan_string_for_phi,
    scan_bytes_for_dates,
    is_date_anonymized,
)


class TestScanBytesForPHI:
    def test_detect_as_pattern(self):
        data = b'\x00\x00AS-24-123456\x00\x00'
        findings = scan_bytes_for_phi(data)
        assert len(findings) == 1
        assert findings[0][3] == 'Accession_AS'

    def test_detect_ac_pattern(self):
        data = b'some data AC-23-987654 more data'
        findings = scan_bytes_for_phi(data)
        assert len(findings) == 1
        assert findings[0][3] == 'Accession_AC'

    def test_detect_ch_pattern(self):
        data = b'header CH12345678 tail'
        findings = scan_bytes_for_phi(data)
        assert len(findings) == 1
        assert findings[0][3] == 'Accession_CH'

    def test_detect_padded_pattern(self):
        data = b'x00000AS12345x'
        findings = scan_bytes_for_phi(data)
        assert len(findings) == 1
        assert findings[0][3] == 'Accession_Padded'

    def test_skip_already_anonymized(self):
        data = b'\x00XXXXXXXXXXXX\x00'
        findings = scan_bytes_for_phi(data)
        assert len(findings) == 0

    def test_skip_offsets(self):
        data = b'AS-24-123456\x00'
        findings = scan_bytes_for_phi(data, skip_offsets={0})
        assert len(findings) == 0

    def test_no_false_positives(self):
        data = b'This is normal text with no PHI patterns at all.'
        findings = scan_bytes_for_phi(data)
        assert len(findings) == 0

    def test_multiple_findings(self):
        data = b'AS-24-111111\x00padding\x00AC-23-222222\x00'
        findings = scan_bytes_for_phi(data)
        assert len(findings) == 2


class TestScanStringForPHI:
    def test_detect_in_string(self):
        findings = scan_string_for_phi('Filename=AS-24-999999.svs')
        assert len(findings) == 1

    def test_clean_string(self):
        findings = scan_string_for_phi('AppMag = 40|MPP = 0.2520')
        assert len(findings) == 0


class TestScanDates:
    def test_detect_tiff_datetime(self):
        data = b'2024:06:15 10:30:00'
        findings = scan_bytes_for_dates(data)
        assert len(findings) == 1

    def test_skip_anonymized_date(self):
        data = b'1900:01:01 00:00:00'
        findings = scan_bytes_for_dates(data)
        assert len(findings) == 0


class TestIsDateAnonymized:
    def test_1900_sentinel(self):
        assert is_date_anonymized('1900:01:01 00:00:00')

    def test_zero_sentinel(self):
        assert is_date_anonymized('0000:00:00 00:00:00')

    def test_empty(self):
        assert is_date_anonymized('')
        assert is_date_anonymized('\x00\x00')

    def test_real_date(self):
        assert not is_date_anonymized('2024:06:15 10:30:00')
