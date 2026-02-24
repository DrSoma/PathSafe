"""Extended tests for the PHI detection scanner -- all pattern types."""

import pytest
from pathsafe.scanner import (
    scan_bytes_for_phi,
    scan_string_for_phi,
    scan_bytes_for_dates,
    scan_filename_for_phi,
    is_date_anonymized,
)


class TestScanBytesAccessionPatterns:
    """Test all accession number pattern types in byte scanning."""

    def test_sp_pattern(self):
        data = b'prefix SP-23-12345 suffix'
        findings = scan_bytes_for_phi(data)
        assert any(f[3] == 'Accession_SP' for f in findings)

    def test_ap_pattern(self):
        data = b'prefix AP-24-67890 suffix'
        findings = scan_bytes_for_phi(data)
        assert any(f[3] == 'Accession_AP' for f in findings)

    def test_cy_pattern(self):
        data = b'prefix CY-22-11111 suffix'
        findings = scan_bytes_for_phi(data)
        assert any(f[3] == 'Accession_CY' for f in findings)

    def test_h_pattern(self):
        data = b'prefix H-23-44444 suffix'
        findings = scan_bytes_for_phi(data)
        assert any(f[3] == 'Accession_H' for f in findings)

    def test_s_pattern(self):
        data = b'prefix S-24-55555 suffix'
        findings = scan_bytes_for_phi(data)
        assert any(f[3] == 'Accession_S' for f in findings)

    def test_h_no_false_positive_with_prefix(self):
        """H- pattern requires no preceding uppercase letter."""
        data = b'CATCH-23-44444'
        findings = scan_bytes_for_phi(data)
        assert not any(f[3] == 'Accession_H' for f in findings)

    def test_s_no_false_positive_with_prefix(self):
        """S- pattern requires no preceding uppercase letter."""
        data = b'BOSS-24-55555'
        findings = scan_bytes_for_phi(data)
        assert not any(f[3] == 'Accession_S' for f in findings)


class TestScanBytes4DigitYearPatterns:
    """Test 4-digit year accession variants."""

    def test_as4_pattern(self):
        data = b'AS-2024-12345\x00'
        findings = scan_bytes_for_phi(data)
        assert any(f[3] == 'Accession_AS4' for f in findings)

    def test_ac4_pattern(self):
        data = b'AC-2023-67890\x00'
        findings = scan_bytes_for_phi(data)
        assert any(f[3] == 'Accession_AC4' for f in findings)

    def test_sp4_pattern(self):
        data = b'SP-2022-11111\x00'
        findings = scan_bytes_for_phi(data)
        assert any(f[3] == 'Accession_SP4' for f in findings)

    def test_ap4_pattern(self):
        data = b'AP-2024-22222\x00'
        findings = scan_bytes_for_phi(data)
        assert any(f[3] == 'Accession_AP4' for f in findings)

    def test_cy4_pattern(self):
        data = b'CY-2024-33333\x00'
        findings = scan_bytes_for_phi(data)
        assert any(f[3] == 'Accession_CY4' for f in findings)

    def test_invalid_year_prefix(self):
        """4-digit year must start with 19 or 20."""
        data = b'AS-1899-12345\x00'
        findings = scan_bytes_for_phi(data)
        assert not any('AS4' in f[3] for f in findings)


class TestScanBytesMRNAndSpecial:
    """Test MRN, SSN, and DOB patterns."""

    def test_mrn_dash(self):
        data = b'MRN-12345678\x00'
        findings = scan_bytes_for_phi(data)
        assert any(f[3] == 'MRN_Pattern' for f in findings)

    def test_mrn_colon(self):
        data = b'MRN:12345678\x00'
        findings = scan_bytes_for_phi(data)
        assert any(f[3] == 'MRN_Pattern' for f in findings)

    def test_mrn_space(self):
        data = b'MRN 12345678\x00'
        findings = scan_bytes_for_phi(data)
        assert any(f[3] == 'MRN_Pattern' for f in findings)

    def test_mrn_no_separator(self):
        data = b'MRN12345678\x00'
        findings = scan_bytes_for_phi(data)
        assert any(f[3] == 'MRN_Pattern' for f in findings)

    def test_ssn_pattern(self):
        data = b'ssn 123-45-6789 end'
        findings = scan_bytes_for_phi(data)
        assert any(f[3] == 'SSN_Pattern' for f in findings)

    def test_ssn_no_false_positive_embedded(self):
        """SSN pattern must not match within larger digit sequences."""
        data = b'1123-45-67890'
        findings = scan_bytes_for_phi(data)
        assert not any(f[3] == 'SSN_Pattern' for f in findings)

    def test_dob_dash(self):
        data = b'DOB-19800115\x00'
        findings = scan_bytes_for_phi(data)
        assert any(f[3] == 'DOB_Pattern' for f in findings)

    def test_dob_slash(self):
        data = b'DOB 1980/01/15\x00'
        findings = scan_bytes_for_phi(data)
        assert any(f[3] == 'DOB_Pattern' for f in findings)

    def test_dob_underscore(self):
        data = b'DOB_20010315\x00'
        findings = scan_bytes_for_phi(data)
        assert any(f[3] == 'DOB_Pattern' for f in findings)


class TestScanStringPatterns:
    """Test string-level PHI scanning."""

    def test_sp_in_string(self):
        findings = scan_string_for_phi('Accession=SP-22-12345')
        assert any(f[3] == 'Accession_SP' for f in findings)

    def test_mrn_in_string(self):
        findings = scan_string_for_phi('MRN-12345678')
        assert any(f[3] == 'MRN_Pattern' for f in findings)

    def test_ssn_in_string(self):
        findings = scan_string_for_phi('SSN: 123-45-6789')
        assert any(f[3] == 'SSN_Pattern' for f in findings)

    def test_dob_in_string(self):
        findings = scan_string_for_phi('DOB19800315')
        assert any(f[3] == 'DOB_Pattern' for f in findings)


class TestScanBytesForDatesExtended:
    """Test additional date patterns."""

    def test_slash_date(self):
        data = b'scanned 2024/06/15 at lab'
        findings = scan_bytes_for_dates(data)
        assert len(findings) == 1
        assert findings[0][3] == 'DateTime_Slash'

    def test_iso_date(self):
        data = b'date: 2024-06-15 done'
        findings = scan_bytes_for_dates(data)
        assert len(findings) == 1
        assert findings[0][3] == 'DateTime_ISO'

    def test_skip_anonymized_slash_date(self):
        data = b'date 1900/01/01'
        findings = scan_bytes_for_dates(data)
        assert len(findings) == 0

    def test_skip_anonymized_iso_date(self):
        data = b'date 1900-01-01'
        findings = scan_bytes_for_dates(data)
        assert len(findings) == 0


class TestScanFilenameForPHI:
    """Test filename PHI detection."""

    def test_accession_in_filename(self):
        findings = scan_filename_for_phi('/path/to/AS-24-123456.ndpi')
        assert len(findings) >= 1
        assert any(f[3] == 'Accession_AS' for f in findings)

    def test_mrn_in_filename(self):
        findings = scan_filename_for_phi('/data/MRN12345678_slide.svs')
        assert any(f[3] == 'MRN_Pattern' for f in findings)

    def test_clean_filename(self):
        findings = scan_filename_for_phi('/data/slide001.ndpi')
        assert len(findings) == 0

    def test_dob_in_filename(self):
        findings = scan_filename_for_phi('/data/DOB19800315_tissue.tif')
        assert any(f[3] == 'DOB_Pattern' for f in findings)

    def test_multiple_phi_in_filename(self):
        findings = scan_filename_for_phi('/data/AS-24-123456_MRN12345678.ndpi')
        assert len(findings) >= 2


class TestIsDateAnonymizedExtended:
    """Extended date anonymization checks."""

    def test_all_nulls(self):
        assert is_date_anonymized('\x00\x00\x00')

    def test_spaces_only(self):
        assert is_date_anonymized('   ')

    def test_mixed_nulls_spaces(self):
        assert is_date_anonymized(' \x00 ')
