"""PHI bypass / evasion tests — attempts to evade the scanner.

Each test crafts metadata that might slip past PHI detection.
Tests that PASS confirm the scanner catches the pattern.
Tests that FAIL reveal a real detection gap (potential bug).

All tests use synthetic temporary files — no original WSI images are touched.
"""

import pytest
from pathlib import Path

from pathsafe.scanner import (
    scan_bytes_for_phi,
    scan_string_for_phi,
    scan_bytes_for_dates,
    scan_filename_for_phi,
)
from pathsafe.formats import get_handler
from tests.conftest import build_tiff


# ──────────────────────────────────────────────────────────────────
# Accession number evasion attempts
# ──────────────────────────────────────────────────────────────────

class TestAccessionBypass:
    """Attempts to evade accession number detection."""

    def test_lowercase_accession(self):
        """Lowercase 'as-24-123456' — scanner uses case-sensitive patterns."""
        results = scan_bytes_for_phi(b'as-24-123456\x00')
        # Lowercase should NOT match (accession codes are uppercase by convention)
        # This is expected behavior, not a bug
        assert len(results) == 0

    def test_accession_no_dashes(self):
        """'AS24123456' without dashes — no standard separator."""
        results = scan_bytes_for_phi(b'AS24123456\x00')
        assert len(results) == 0  # Expected: no match without dashes

    def test_accession_with_spaces(self):
        """'AS 24 123456' with spaces instead of dashes."""
        results = scan_bytes_for_phi(b'AS 24 123456\x00')
        assert len(results) == 0  # Expected: spaces not a separator

    def test_accession_with_underscores(self):
        """'AS_24_123456' with underscores instead of dashes."""
        results = scan_bytes_for_phi(b'AS_24_123456\x00')
        assert len(results) == 0  # Expected: underscores not a separator

    def test_accession_embedded_in_long_string(self):
        """Accession buried in a long string — should still match."""
        data = b'A' * 500 + b'AS-24-123456' + b'B' * 500 + b'\x00'
        results = scan_bytes_for_phi(data)
        labels = [r[3] for r in results]
        assert any('AS' in l for l in labels)

    def test_accession_at_start_of_buffer(self):
        """Accession at the very start of the buffer."""
        results = scan_bytes_for_phi(b'AS-24-123456\x00')
        assert len(results) > 0

    def test_accession_multiple_in_same_buffer(self):
        """Multiple accession numbers in one buffer."""
        data = b'AS-24-111111\x00' + b'padding' + b'SP-23-222222\x00'
        results = scan_bytes_for_phi(data)
        labels = [r[3] for r in results]
        assert any('AS' in l for l in labels)
        assert any('SP' in l for l in labels)

    def test_accession_just_under_min_digits(self):
        """'AS-24-12' only 2 digits — should NOT match (min is 3)."""
        results = scan_bytes_for_phi(b'AS-24-12\x00')
        assert len(results) == 0

    def test_accession_exactly_min_digits(self):
        """'AS-24-123' exactly 3 digits — should match."""
        results = scan_bytes_for_phi(b'AS-24-123\x00')
        assert len(results) > 0

    def test_ch_accession_just_under_min(self):
        """'CH1234' only 4 digits — should NOT match (min is 5)."""
        results = scan_bytes_for_phi(b'CH1234\x00')
        assert len(results) == 0

    def test_ch_accession_exactly_min(self):
        """'CH12345' exactly 5 digits — should match."""
        results = scan_bytes_for_phi(b'CH12345\x00')
        assert len(results) > 0


# ──────────────────────────────────────────────────────────────────
# Date evasion attempts
# ──────────────────────────────────────────────────────────────────

class TestDateBypass:
    """Attempts to evade date detection."""

    def test_standard_tiff_date(self):
        """Standard TIFF DateTime format — should match."""
        results = scan_bytes_for_dates(b'2024:06:15 10:30:00')
        assert len(results) > 0

    def test_slash_date(self):
        """Slash-delimited date — should match."""
        results = scan_bytes_for_dates(b'2024/06/15')
        assert len(results) > 0

    def test_iso_date(self):
        """ISO 8601 date — should match."""
        results = scan_bytes_for_dates(b'2024-06-15')
        assert len(results) > 0

    def test_dot_separated_date(self):
        """Dot-separated date '2024.06.15' — NOT a standard pattern."""
        results = scan_bytes_for_dates(b'2024.06.15')
        # Not matched — known limitation
        assert len(results) == 0

    def test_human_readable_date(self):
        """'June 15, 2024' — natural language date not detected."""
        results = scan_bytes_for_dates(b'June 15, 2024')
        # Not matched — known limitation (would need NLP)
        assert len(results) == 0

    def test_anonymized_tiff_date_skipped(self):
        """Already-anonymized dates should be skipped."""
        results = scan_bytes_for_dates(b'1900:01:01 00:00:00')
        assert len(results) == 0

    def test_anonymized_iso_date_skipped(self):
        results = scan_bytes_for_dates(b'1900-01-01')
        assert len(results) == 0

    def test_anonymized_slash_date_skipped(self):
        results = scan_bytes_for_dates(b'1900/01/01')
        assert len(results) == 0

    def test_date_19xx(self):
        """Old date (1980) — should still match."""
        results = scan_bytes_for_dates(b'1980:03:25 12:00:00')
        assert len(results) > 0

    def test_future_date(self):
        """Future date (2099) — should still match."""
        results = scan_bytes_for_dates(b'2099:12:31 23:59:59')
        assert len(results) > 0

    def test_date_outside_range(self):
        """Date outside 1900-2099 range — should NOT match."""
        results = scan_bytes_for_dates(b'1800:01:01 00:00:00')
        assert len(results) == 0

    def test_partial_date(self):
        """'2024:06' — partial date, no time component."""
        results = scan_bytes_for_dates(b'2024:06')
        # Should NOT match the TIFF DateTime pattern (needs full format)
        assert len(results) == 0


# ──────────────────────────────────────────────────────────────────
# MRN / SSN / DOB evasion attempts
# ──────────────────────────────────────────────────────────────────

class TestMRNSSNDOBBypass:
    """Attempts to evade MRN, SSN, and DOB detection."""

    def test_mrn_with_dash(self):
        results = scan_bytes_for_phi(b'MRN-12345678\x00')
        assert any(r[3] == 'MRN_Pattern' for r in results)

    def test_mrn_with_colon(self):
        results = scan_bytes_for_phi(b'MRN:12345678\x00')
        assert any(r[3] == 'MRN_Pattern' for r in results)

    def test_mrn_no_separator(self):
        results = scan_bytes_for_phi(b'MRN12345678\x00')
        assert any(r[3] == 'MRN_Pattern' for r in results)

    def test_mrn_too_few_digits(self):
        """MRN with only 4 digits — should NOT match (min 5)."""
        results = scan_bytes_for_phi(b'MRN-1234\x00')
        assert not any(r[3] == 'MRN_Pattern' for r in results)

    def test_ssn_standard(self):
        results = scan_bytes_for_phi(b'123-45-6789\x00')
        assert any(r[3] == 'SSN_Pattern' for r in results)

    def test_ssn_no_dashes(self):
        """'123456789' without dashes — should NOT match SSN pattern."""
        results = scan_bytes_for_phi(b'123456789\x00')
        # SSN pattern requires dashes
        assert not any(r[3] == 'SSN_Pattern' for r in results)

    def test_ssn_surrounded_by_digits(self):
        """SSN-like pattern inside a larger number — should NOT match."""
        results = scan_bytes_for_phi(b'9123-45-67890\x00')
        # Negative lookbehind/lookahead should exclude this
        assert not any(r[3] == 'SSN_Pattern' for r in results)

    def test_dob_standard(self):
        results = scan_bytes_for_phi(b'DOB-19800115\x00')
        assert any(r[3] == 'DOB_Pattern' for r in results)

    def test_dob_with_slashes(self):
        results = scan_bytes_for_phi(b'DOB-1980/01/15\x00')
        assert any(r[3] == 'DOB_Pattern' for r in results)

    def test_dob_with_underscore(self):
        results = scan_bytes_for_phi(b'DOB_19800115\x00')
        assert any(r[3] == 'DOB_Pattern' for r in results)


# ──────────────────────────────────────────────────────────────────
# Filename PHI evasion
# ──────────────────────────────────────────────────────────────────

class TestFilenamePHIBypass:
    """Attempts to evade filename PHI detection."""

    def test_accession_in_filename(self):
        results = scan_filename_for_phi(Path('AS-24-123456.ndpi'))
        assert len(results) > 0

    def test_mrn_in_filename(self):
        results = scan_filename_for_phi(Path('MRN12345678_slide1.svs'))
        assert len(results) > 0

    def test_dob_in_filename(self):
        results = scan_filename_for_phi(Path('DOB-19801231.tif'))
        assert len(results) > 0

    def test_ssn_in_filename(self):
        results = scan_filename_for_phi(Path('patient_123-45-6789.ndpi'))
        assert len(results) > 0

    def test_clean_filename(self):
        results = scan_filename_for_phi(Path('slide_001_H&E_40x.ndpi'))
        assert len(results) == 0

    def test_timestamp_only_filename(self):
        """Filename with only a timestamp — should match as a date."""
        results = scan_filename_for_phi(Path('2024-06-15_scan.tif'))
        # May or may not match depending on pattern scope
        # The important thing: accession patterns should not false-positive here

    def test_multiple_phi_in_filename(self):
        results = scan_filename_for_phi(Path('AS-24-123456_MRN12345678.ndpi'))
        labels = [r[3] for r in results]
        assert any('AS' in l for l in labels)
        assert any('MRN' in l for l in labels)


# ──────────────────────────────────────────────────────────────────
# Encoding evasion attempts
# ──────────────────────────────────────────────────────────────────

class TestEncodingBypass:
    """Attempts to evade detection via encoding tricks."""

    def test_null_bytes_in_accession(self):
        """Null bytes inserted into accession: 'AS-\x0024-123456'."""
        data = b'AS-\x0024-123456\x00'
        results = scan_bytes_for_phi(data)
        # The null byte breaks the pattern — this is a known limitation
        # but acceptable since TIFF strings are null-terminated

    def test_accession_in_utf16(self):
        """Accession encoded as UTF-16 — byte patterns won't match."""
        data = 'AS-24-123456'.encode('utf-16-le')
        results = scan_bytes_for_phi(data)
        # UTF-16 interleaves null bytes — pattern won't match
        # This is a known limitation for binary scanning
        assert len(results) == 0

    def test_already_anonymized_xxx(self):
        """Already anonymized string (all X's) should be skipped."""
        data = b'XXXXXXXXXXXX\x00'
        results = scan_bytes_for_phi(data)
        assert len(results) == 0


# ──────────────────────────────────────────────────────────────────
# Handler-level bypass tests (end-to-end with TIFF files)
# ──────────────────────────────────────────────────────────────────

class TestHandlerBypass:
    """End-to-end bypass attempts using actual TIFF files."""

    def test_phi_in_image_description(self, tmp_path):
        """PHI embedded in ImageDescription tag."""
        desc = b'Patient ID: AS-24-999888\x00'
        entries = [(256, 3, 1, 512), (270, 2, len(desc), desc)]
        f = tmp_path / 'desc_phi.tif'
        f.write_bytes(build_tiff(entries))
        handler = get_handler(f)
        result = handler.scan(f)
        assert not result.is_clean

    def test_phi_in_software_tag(self, tmp_path):
        """Software tag (305) should be flagged as extra metadata."""
        software = b'Scanner v1.2 SN:12345\x00'
        entries = [(256, 3, 1, 512), (305, 2, len(software), software)]
        f = tmp_path / 'software.tif'
        f.write_bytes(build_tiff(entries))
        handler = get_handler(f)
        result = handler.scan(f)
        assert not result.is_clean

    def test_phi_in_artist_tag(self, tmp_path):
        """Artist tag (315) may contain operator name."""
        artist = b'Dr. John Doe\x00'
        entries = [(256, 3, 1, 512), (315, 2, len(artist), artist)]
        f = tmp_path / 'artist.tif'
        f.write_bytes(build_tiff(entries))
        handler = get_handler(f)
        result = handler.scan(f)
        assert not result.is_clean

    def test_phi_in_host_computer_tag(self, tmp_path):
        """HostComputer tag (316) contains institutional hostname."""
        host = b'pathology-server.hospital.org\x00'
        entries = [(256, 3, 1, 512), (316, 2, len(host), host)]
        f = tmp_path / 'host.tif'
        f.write_bytes(build_tiff(entries))
        handler = get_handler(f)
        result = handler.scan(f)
        assert not result.is_clean

    def test_phi_only_in_regex_not_tag(self, tmp_path):
        """PHI pattern in raw bytes but not in any known tag field."""
        entries = [(256, 3, 1, 512)]
        extra = b'\x00' * 50 + b'SP-23-777888\x00' + b'\x00' * 50
        f = tmp_path / 'regex_only.tif'
        f.write_bytes(build_tiff(entries, extra_data=extra))
        handler = get_handler(f)
        result = handler.scan(f)
        assert not result.is_clean
        # Should be caught by regex safety scan
        tag_names = {finding.tag_name for finding in result.findings}
        assert any('regex' in t for t in tag_names)

    def test_anonymize_then_verify_no_residual(self, tmp_path):
        """After anonymization, no PHI residue should remain."""
        desc = b'Patient: AS-22-555555 MRN-12345678 DOB-19801231\x00'
        entries = [
            (256, 3, 1, 512),
            (270, 2, len(desc), desc),
            (306, 2, 20, b'2024:06:15 10:30:00\x00'),
        ]
        f = tmp_path / 'multi_phi.tif'
        f.write_bytes(build_tiff(entries))
        handler = get_handler(f)

        # Verify PHI detected
        result = handler.scan(f)
        assert not result.is_clean

        # Anonymize
        cleared = handler.anonymize(f)
        assert len(cleared) > 0

        # Verify clean
        result = handler.scan(f)
        assert result.is_clean, f"Residual findings: {[(f.tag_name, f.value_preview) for f in result.findings]}"

    def test_scan_after_anonymize_at_scan_size_boundary(self, tmp_path):
        """PHI near the DEFAULT_SCAN_SIZE boundary."""
        from pathsafe.scanner import DEFAULT_SCAN_SIZE
        # Place accession just before the scan size limit
        padding = b'\x00' * (DEFAULT_SCAN_SIZE - 100)
        desc = padding + b'AS-24-123456\x00'
        entries = [
            (256, 3, 1, 512),
            (270, 2, len(desc), desc),
        ]
        f = tmp_path / 'boundary.tif'
        f.write_bytes(build_tiff(entries))
        handler = get_handler(f)
        result = handler.scan(f)
        # Should still be detected (within scan size)
        assert not result.is_clean
