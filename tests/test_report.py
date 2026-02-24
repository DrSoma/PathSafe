"""Tests for the compliance certificate report module."""

import json
import pytest
from pathlib import Path

from pathsafe.models import AnonymizationResult, BatchResult
from pathsafe.report import (
    generate_certificate, generate_pdf_certificate, generate_scan_report,
    _detect_format_from_ext, friendly_tag_name,
)


def _make_batch_result(n_files=1, findings=2, verified=True,
                       mode='copy', error=None, integrity=None,
                       filename_phi=False):
    """Create a synthetic BatchResult for testing."""
    results = []
    for i in range(n_files):
        r = AnonymizationResult(
            source_path=Path(f'/input/slide{i}.ndpi'),
            output_path=Path(f'/output/slide{i}.ndpi'),
            mode=mode,
            findings_cleared=findings,
            verified=verified,
            anonymization_time_ms=100.0,
            image_integrity_verified=integrity,
            filename_has_phi=filename_phi,
            error=error,
        )
        results.append(r)

    batch = BatchResult(
        results=results,
        total_files=n_files,
        files_anonymized=n_files if not error else 0,
        files_already_clean=0,
        files_errored=n_files if error else 0,
        total_time_seconds=1.5,
    )
    return batch


class TestGenerateCertificate:
    def test_basic_structure(self):
        batch = _make_batch_result()
        cert = generate_certificate(batch)
        assert 'pathsafe_version' in cert
        assert 'certificate_id' in cert
        assert 'generated_at' in cert
        assert 'mode' in cert
        assert 'summary' in cert
        assert 'measures' in cert
        assert 'files' in cert

    def test_summary_stats(self):
        batch = _make_batch_result(n_files=3)
        cert = generate_certificate(batch)
        assert cert['summary']['total_files'] == 3
        assert cert['summary']['anonymized'] == 3
        assert cert['summary']['errors'] == 0
        assert cert['summary']['verified'] is True

    def test_file_records(self):
        batch = _make_batch_result()
        cert = generate_certificate(batch)
        assert len(cert['files']) == 1
        record = cert['files'][0]
        assert record['filename'] == 'slide0.ndpi'
        assert record['findings_cleared'] == 2
        assert record['verified_clean'] is True
        assert record['format'] == 'ndpi'

    def test_error_in_file_record(self):
        batch = _make_batch_result(error="Test error")
        cert = generate_certificate(batch)
        record = cert['files'][0]
        assert record['error'] == "Test error"

    def test_integrity_included(self):
        batch = _make_batch_result(integrity=True)
        cert = generate_certificate(batch)
        record = cert['files'][0]
        assert record['image_integrity_verified'] is True

    def test_integrity_not_included_when_none(self):
        batch = _make_batch_result(integrity=None)
        cert = generate_certificate(batch)
        record = cert['files'][0]
        assert 'image_integrity_verified' not in record

    def test_filename_phi_included(self):
        batch = _make_batch_result(filename_phi=True)
        cert = generate_certificate(batch)
        record = cert['files'][0]
        assert record['filename_has_phi'] is True

    def test_measures_present(self):
        batch = _make_batch_result()
        cert = generate_certificate(batch)
        measure_names = [m['measure'] for m in cert['measures']]
        assert 'Metadata tags cleared' in measure_names
        assert 'Post-anonymization verification' in measure_names

    def test_timestamp_measure(self):
        batch = _make_batch_result()
        cert = generate_certificate(batch, timestamps_reset=True)
        measure_names = [m['measure'] for m in cert['measures']]
        assert 'Filesystem timestamps reset' in measure_names

    def test_no_timestamp_measure(self):
        batch = _make_batch_result()
        cert = generate_certificate(batch, timestamps_reset=False)
        measure_names = [m['measure'] for m in cert['measures']]
        assert 'Filesystem timestamps reset' not in measure_names

    def test_integrity_measure_passed(self):
        batch = _make_batch_result(integrity=True)
        cert = generate_certificate(batch)
        integrity_measures = [m for m in cert['measures']
                              if 'integrity' in m['measure'].lower()]
        assert len(integrity_measures) == 1
        assert integrity_measures[0]['status'] == 'passed'

    def test_integrity_measure_failed(self):
        batch = _make_batch_result(integrity=False)
        cert = generate_certificate(batch)
        integrity_measures = [m for m in cert['measures']
                              if 'integrity' in m['measure'].lower()]
        assert len(integrity_measures) == 1
        assert integrity_measures[0]['status'] == 'failed'

    def test_write_to_file(self, tmp_path):
        batch = _make_batch_result()
        cert_path = tmp_path / 'cert.json'
        cert = generate_certificate(batch, output_path=cert_path)
        assert cert_path.exists()
        data = json.loads(cert_path.read_text())
        assert data['pathsafe_version'] == cert['pathsafe_version']

    def test_creates_parent_directory(self, tmp_path):
        batch = _make_batch_result()
        cert_path = tmp_path / 'nested' / 'dir' / 'cert.json'
        generate_certificate(batch, output_path=cert_path)
        assert cert_path.exists()

    def test_empty_batch(self):
        batch = BatchResult(total_files=0, total_time_seconds=0)
        cert = generate_certificate(batch)
        assert cert['summary']['total_files'] == 0
        assert cert['files'] == []
        assert cert['mode'] == 'unknown'


class TestGeneratePdfCertificate:
    """Tests for standalone PDF certificate generation."""

    def test_pdf_created(self, tmp_path):
        batch = _make_batch_result()
        cert = generate_certificate(batch)
        pdf_path = tmp_path / 'cert.pdf'
        result = generate_pdf_certificate(cert, pdf_path)
        assert pdf_path.exists()
        assert result == pdf_path

    def test_pdf_magic_bytes(self, tmp_path):
        batch = _make_batch_result()
        cert = generate_certificate(batch)
        pdf_path = tmp_path / 'cert.pdf'
        generate_pdf_certificate(cert, pdf_path)
        data = pdf_path.read_bytes()
        assert data[:5] == b'%PDF-'

    def test_pdf_has_substantial_content(self, tmp_path):
        batch = _make_batch_result()
        cert = generate_certificate(batch)
        pdf_path = tmp_path / 'cert.pdf'
        generate_pdf_certificate(cert, pdf_path)
        # PDF with tables/text should be meaningfully larger than a blank page
        assert pdf_path.stat().st_size > 500

    def test_parent_directory_created(self, tmp_path):
        batch = _make_batch_result()
        cert = generate_certificate(batch)
        pdf_path = tmp_path / 'deep' / 'nested' / 'cert.pdf'
        generate_pdf_certificate(cert, pdf_path)
        assert pdf_path.exists()

    def test_multi_file_batch(self, tmp_path):
        batch = _make_batch_result(n_files=5)
        cert = generate_certificate(batch)
        pdf_path = tmp_path / 'multi.pdf'
        generate_pdf_certificate(cert, pdf_path)
        assert pdf_path.exists()
        assert pdf_path.stat().st_size > 0

    def test_filename_phi_warning_renders(self, tmp_path):
        batch = _make_batch_result(filename_phi=True)
        cert = generate_certificate(batch)
        pdf_path = tmp_path / 'phi.pdf'
        generate_pdf_certificate(cert, pdf_path)
        # Should produce a larger PDF than one without warnings
        batch_no_phi = _make_batch_result(filename_phi=False)
        cert_no_phi = generate_certificate(batch_no_phi)
        pdf_no_phi = tmp_path / 'no_phi.pdf'
        generate_pdf_certificate(cert_no_phi, pdf_no_phi)
        assert pdf_path.stat().st_size > pdf_no_phi.stat().st_size

    def test_error_files_render(self, tmp_path):
        batch = _make_batch_result(error="Corrupted file")
        cert = generate_certificate(batch)
        pdf_path = tmp_path / 'err.pdf'
        generate_pdf_certificate(cert, pdf_path)
        assert pdf_path.exists()
        assert pdf_path.stat().st_size > 500

    def test_empty_batch(self, tmp_path):
        batch = BatchResult(total_files=0, total_time_seconds=0)
        cert = generate_certificate(batch)
        pdf_path = tmp_path / 'empty.pdf'
        generate_pdf_certificate(cert, pdf_path)
        assert pdf_path.exists()
        assert pdf_path.stat().st_size > 0

    def test_header_renders(self, tmp_path):
        batch = _make_batch_result()
        cert = generate_certificate(batch)
        pdf_path = tmp_path / 'header.pdf'
        generate_pdf_certificate(cert, pdf_path)
        assert pdf_path.exists()
        assert pdf_path.stat().st_size > 500

    def test_integrity_renders(self, tmp_path):
        batch = _make_batch_result(integrity=True)
        cert = generate_certificate(batch)
        pdf_path = tmp_path / 'integrity.pdf'
        generate_pdf_certificate(cert, pdf_path)
        assert pdf_path.exists()
        assert pdf_path.stat().st_size > 500


class TestGenerateCertificateWithPdf:
    """Tests for the pdf=True integration in generate_certificate()."""

    def test_json_and_pdf_both_created(self, tmp_path):
        batch = _make_batch_result()
        cert_path = tmp_path / 'cert.json'
        generate_certificate(batch, output_path=cert_path)
        assert cert_path.exists()
        pdf_path = cert_path.with_suffix('.pdf')
        assert pdf_path.exists()

    def test_pdf_false_skips_pdf(self, tmp_path):
        batch = _make_batch_result()
        cert_path = tmp_path / 'cert.json'
        generate_certificate(batch, output_path=cert_path, pdf=False)
        assert cert_path.exists()
        pdf_path = cert_path.with_suffix('.pdf')
        assert not pdf_path.exists()

    def test_no_output_path_with_pdf_true(self):
        batch = _make_batch_result()
        # Should not crash when output_path is None and pdf=True
        cert = generate_certificate(batch, pdf=True)
        assert 'certificate_id' in cert

    def test_pdf_companion_has_same_stem(self, tmp_path):
        batch = _make_batch_result()
        cert_path = tmp_path / 'my_certificate.json'
        generate_certificate(batch, output_path=cert_path)
        pdf_path = tmp_path / 'my_certificate.pdf'
        assert pdf_path.exists()


class TestDetectFormatFromExt:
    def test_ndpi(self):
        assert _detect_format_from_ext(Path('slide.ndpi')) == 'ndpi'

    def test_svs(self):
        assert _detect_format_from_ext(Path('slide.svs')) == 'svs'

    def test_tif(self):
        assert _detect_format_from_ext(Path('slide.tif')) == 'tiff'

    def test_tiff(self):
        assert _detect_format_from_ext(Path('slide.tiff')) == 'tiff'

    def test_mrxs(self):
        assert _detect_format_from_ext(Path('slide.mrxs')) == 'mrxs'

    def test_bif(self):
        assert _detect_format_from_ext(Path('slide.bif')) == 'bif'

    def test_scn(self):
        assert _detect_format_from_ext(Path('slide.scn')) == 'scn'

    def test_dcm(self):
        assert _detect_format_from_ext(Path('slide.dcm')) == 'dicom'

    def test_dicom(self):
        assert _detect_format_from_ext(Path('slide.dicom')) == 'dicom'

    def test_unknown(self):
        assert _detect_format_from_ext(Path('slide.xyz')) == 'unknown'


# ---------------------------------------------------------------------------
# Scan report tests
# ---------------------------------------------------------------------------

def _make_scan_data(n_files=3, phi_files=1, errors=0, findings_per_phi=2):
    """Build a scan_data dict for testing generate_scan_report()."""
    results = []
    clean_count = n_files - phi_files - errors

    for i in range(clean_count):
        results.append({
            'filepath': f'/data/clean_slide{i}.ndpi',
            'is_clean': True,
            'error': None,
            'findings': [],
        })

    for i in range(phi_files):
        results.append({
            'filepath': f'/data/phi_slide{i}.ndpi',
            'is_clean': False,
            'error': None,
            'findings': [
                {'tag_name': f'Tag{j}', 'value_preview': f'value{j}***'}
                for j in range(findings_per_phi)
            ],
        })

    for i in range(errors):
        results.append({
            'filepath': f'/data/error_slide{i}.ndpi',
            'is_clean': False,
            'error': f'Read error on slide {i}',
            'findings': [],
        })

    return {
        'total': n_files,
        'clean': clean_count,
        'phi_files': phi_files,
        'phi_findings': phi_files * findings_per_phi,
        'errors': errors,
        'results': results,
    }


class TestGenerateScanReport:
    """Tests for the PDF scan report generation."""

    def test_pdf_created(self, tmp_path):
        data = _make_scan_data()
        pdf_path = tmp_path / 'scan.pdf'
        result = generate_scan_report(data, pdf_path)
        assert pdf_path.exists()
        assert result == pdf_path

    def test_pdf_magic_bytes(self, tmp_path):
        data = _make_scan_data()
        pdf_path = tmp_path / 'scan.pdf'
        generate_scan_report(data, pdf_path)
        assert pdf_path.read_bytes()[:5] == b'%PDF-'

    def test_parent_directory_created(self, tmp_path):
        data = _make_scan_data()
        pdf_path = tmp_path / 'deep' / 'nested' / 'scan.pdf'
        generate_scan_report(data, pdf_path)
        assert pdf_path.exists()

    def test_clean_only_renders(self, tmp_path):
        data = _make_scan_data(n_files=5, phi_files=0, errors=0)
        pdf_path = tmp_path / 'clean.pdf'
        generate_scan_report(data, pdf_path)
        assert pdf_path.exists()
        assert pdf_path.stat().st_size > 500

    def test_phi_findings_renders_larger(self, tmp_path):
        clean_data = _make_scan_data(n_files=3, phi_files=0, errors=0)
        phi_data = _make_scan_data(n_files=3, phi_files=2, errors=0,
                                   findings_per_phi=5)
        clean_pdf = tmp_path / 'clean.pdf'
        phi_pdf = tmp_path / 'phi.pdf'
        generate_scan_report(clean_data, clean_pdf)
        generate_scan_report(phi_data, phi_pdf)
        assert phi_pdf.stat().st_size > clean_pdf.stat().st_size

    def test_error_files_render(self, tmp_path):
        data = _make_scan_data(n_files=3, phi_files=0, errors=2)
        pdf_path = tmp_path / 'errors.pdf'
        generate_scan_report(data, pdf_path)
        assert pdf_path.exists()
        assert pdf_path.stat().st_size > 500

    def test_empty_scan_renders(self, tmp_path):
        data = {
            'total': 0, 'clean': 0, 'phi_files': 0,
            'phi_findings': 0, 'errors': 0, 'results': [],
        }
        pdf_path = tmp_path / 'empty.pdf'
        generate_scan_report(data, pdf_path)
        assert pdf_path.exists()
        assert pdf_path.stat().st_size > 0

    def test_multi_file_batch(self, tmp_path):
        data = _make_scan_data(n_files=20, phi_files=5, errors=2,
                               findings_per_phi=3)
        pdf_path = tmp_path / 'multi.pdf'
        generate_scan_report(data, pdf_path)
        assert pdf_path.exists()
        assert pdf_path.stat().st_size > 500


# ---------------------------------------------------------------------------
# Institution name tests
# ---------------------------------------------------------------------------

class TestInstitutionInScanReport:
    """Tests for institution name rendering in scan report PDFs."""

    def test_institution_renders_larger_pdf(self, tmp_path):
        data = _make_scan_data()
        pdf_with = tmp_path / 'with_inst.pdf'
        pdf_without = tmp_path / 'without_inst.pdf'
        generate_scan_report(data, pdf_with,
                             institution="Memorial General Hospital")
        generate_scan_report(data, pdf_without)
        assert pdf_with.stat().st_size > pdf_without.stat().st_size

    def test_empty_institution_same_as_omitted(self, tmp_path):
        data = _make_scan_data()
        pdf_empty = tmp_path / 'empty_inst.pdf'
        pdf_default = tmp_path / 'default.pdf'
        generate_scan_report(data, pdf_empty, institution="")
        generate_scan_report(data, pdf_default)
        assert pdf_empty.stat().st_size == pdf_default.stat().st_size

    def test_institution_pdf_valid(self, tmp_path):
        data = _make_scan_data()
        pdf_path = tmp_path / 'inst.pdf'
        generate_scan_report(data, pdf_path,
                             institution="University Hospital Zurich")
        assert pdf_path.read_bytes()[:5] == b'%PDF-'


class TestInstitutionInCertificate:
    """Tests for institution name in certificate JSON and PDF."""

    def test_institution_in_json(self):
        batch = _make_batch_result()
        cert = generate_certificate(batch, institution="City Hospital")
        assert cert['institution'] == "City Hospital"

    def test_institution_empty_default(self):
        batch = _make_batch_result()
        cert = generate_certificate(batch)
        assert cert['institution'] == ""

    def test_institution_renders_larger_pdf(self, tmp_path):
        batch = _make_batch_result()
        cert_with = generate_certificate(batch,
                                         institution="Memorial Hospital")
        cert_without = generate_certificate(batch)
        pdf_with = tmp_path / 'with_inst.pdf'
        pdf_without = tmp_path / 'without_inst.pdf'
        generate_pdf_certificate(cert_with, pdf_with,
                                 institution="Memorial Hospital")
        generate_pdf_certificate(cert_without, pdf_without)
        assert pdf_with.stat().st_size > pdf_without.stat().st_size

    def test_empty_institution_same_as_omitted(self, tmp_path):
        batch = _make_batch_result()
        cert = generate_certificate(batch)
        pdf_empty = tmp_path / 'empty_inst.pdf'
        pdf_default = tmp_path / 'default.pdf'
        generate_pdf_certificate(cert, pdf_empty, institution="")
        generate_pdf_certificate(cert, pdf_default)
        assert pdf_empty.stat().st_size == pdf_default.stat().st_size

    def test_institution_pdf_valid(self, tmp_path):
        batch = _make_batch_result()
        cert = generate_certificate(batch,
                                    institution="Johns Hopkins")
        pdf_path = tmp_path / 'inst.pdf'
        generate_pdf_certificate(cert, pdf_path,
                                 institution="Johns Hopkins")
        assert pdf_path.read_bytes()[:5] == b'%PDF-'

    def test_json_and_pdf_with_institution(self, tmp_path):
        batch = _make_batch_result()
        cert_path = tmp_path / 'cert.json'
        cert = generate_certificate(batch, output_path=cert_path,
                                    institution="Test Hospital")
        assert cert_path.exists()
        assert cert_path.with_suffix('.pdf').exists()
        data = json.loads(cert_path.read_text())
        assert data['institution'] == "Test Hospital"


# ---------------------------------------------------------------------------
# friendly_tag_name tests
# ---------------------------------------------------------------------------

class TestFriendlyTagName:
    """Tests for friendly_tag_name() — human-readable tag labels."""

    def test_direct_lookup(self):
        assert friendly_tag_name('NDPI_BARCODE') == 'Barcode'
        assert friendly_tag_name('MacroImage') == 'Macro Image'
        assert friendly_tag_name('DateTime') == 'Date/Time'
        assert friendly_tag_name('ICCProfile') == 'ICC Color Profile'

    def test_exif_prefix(self):
        assert friendly_tag_name('EXIF:DateTimeOriginal') == 'EXIF: Date/Time Original'
        assert friendly_tag_name('EXIF:UserComment') == 'EXIF: User Comment'

    def test_gps_prefix(self):
        assert friendly_tag_name('GPS:GPSLatitudeRef') == 'GPS: LatitudeRef'
        assert friendly_tag_name('GPS:GPSDateStamp') == 'GPS: DateStamp'

    def test_scanner_props_prefix(self):
        assert friendly_tag_name('NDPI_SCANNER_PROPS:Created') == 'Scanner: Created'
        assert friendly_tag_name('NDPI_SCANNER_PROPS:NDP.S/N') == 'Scanner: NDP.S/N'

    def test_regex_prefix(self):
        assert friendly_tag_name('regex:accession_specimen') == 'Pattern: accession_specimen'
        assert friendly_tag_name('fallback:date_iso') == 'Pattern: date_iso'

    def test_ndpi_tag_fallback(self):
        assert friendly_tag_name('NDPI_Tag_65465') == 'NDPI Tag 65465'
        assert friendly_tag_name('NDPI_UNKNOWN_65457') == 'NDPI Tag 65457'

    def test_generic_tag_fallback(self):
        assert friendly_tag_name('Tag_12345') == 'Tag 12345'

    def test_unknown_passthrough(self):
        assert friendly_tag_name('SomethingNew') == 'SomethingNew'
