"""Tests for the compliance certificate report module."""

import json
import pytest
from pathlib import Path

from pathsafe.models import AnonymizationResult, BatchResult
from pathsafe.report import generate_certificate, _detect_format_from_ext


class TestGenerateCertificate:
    def _make_batch_result(self, n_files=1, findings=2, verified=True,
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

    def test_basic_structure(self):
        batch = self._make_batch_result()
        cert = generate_certificate(batch)
        assert 'pathsafe_version' in cert
        assert 'certificate_id' in cert
        assert 'generated_at' in cert
        assert 'mode' in cert
        assert 'summary' in cert
        assert 'measures' in cert
        assert 'files' in cert

    def test_summary_stats(self):
        batch = self._make_batch_result(n_files=3)
        cert = generate_certificate(batch)
        assert cert['summary']['total_files'] == 3
        assert cert['summary']['anonymized'] == 3
        assert cert['summary']['errors'] == 0
        assert cert['summary']['verified'] is True

    def test_file_records(self):
        batch = self._make_batch_result()
        cert = generate_certificate(batch)
        assert len(cert['files']) == 1
        record = cert['files'][0]
        assert record['filename'] == 'slide0.ndpi'
        assert record['findings_cleared'] == 2
        assert record['verified_clean'] is True
        assert record['format'] == 'ndpi'

    def test_error_in_file_record(self):
        batch = self._make_batch_result(error="Test error")
        cert = generate_certificate(batch)
        record = cert['files'][0]
        assert record['error'] == "Test error"

    def test_integrity_included(self):
        batch = self._make_batch_result(integrity=True)
        cert = generate_certificate(batch)
        record = cert['files'][0]
        assert record['image_integrity_verified'] is True

    def test_integrity_not_included_when_none(self):
        batch = self._make_batch_result(integrity=None)
        cert = generate_certificate(batch)
        record = cert['files'][0]
        assert 'image_integrity_verified' not in record

    def test_filename_phi_included(self):
        batch = self._make_batch_result(filename_phi=True)
        cert = generate_certificate(batch)
        record = cert['files'][0]
        assert record['filename_has_phi'] is True

    def test_measures_present(self):
        batch = self._make_batch_result()
        cert = generate_certificate(batch)
        measure_names = [m['measure'] for m in cert['measures']]
        assert 'Metadata tags cleared' in measure_names
        assert 'Post-anonymization verification' in measure_names
        assert 'Filename PHI detection' in measure_names

    def test_timestamp_measure(self):
        batch = self._make_batch_result()
        cert = generate_certificate(batch, timestamps_reset=True)
        measure_names = [m['measure'] for m in cert['measures']]
        assert 'Filesystem timestamps reset' in measure_names

    def test_no_timestamp_measure(self):
        batch = self._make_batch_result()
        cert = generate_certificate(batch, timestamps_reset=False)
        measure_names = [m['measure'] for m in cert['measures']]
        assert 'Filesystem timestamps reset' not in measure_names

    def test_integrity_measure_passed(self):
        batch = self._make_batch_result(integrity=True)
        cert = generate_certificate(batch)
        integrity_measures = [m for m in cert['measures']
                              if 'integrity' in m['measure'].lower()]
        assert len(integrity_measures) == 1
        assert integrity_measures[0]['status'] == 'passed'

    def test_integrity_measure_failed(self):
        batch = self._make_batch_result(integrity=False)
        cert = generate_certificate(batch)
        integrity_measures = [m for m in cert['measures']
                              if 'integrity' in m['measure'].lower()]
        assert len(integrity_measures) == 1
        assert integrity_measures[0]['status'] == 'failed'

    def test_write_to_file(self, tmp_path):
        batch = self._make_batch_result()
        cert_path = tmp_path / 'cert.json'
        cert = generate_certificate(batch, output_path=cert_path)
        assert cert_path.exists()
        data = json.loads(cert_path.read_text())
        assert data['pathsafe_version'] == cert['pathsafe_version']

    def test_creates_parent_directory(self, tmp_path):
        batch = self._make_batch_result()
        cert_path = tmp_path / 'nested' / 'dir' / 'cert.json'
        generate_certificate(batch, output_path=cert_path)
        assert cert_path.exists()

    def test_empty_batch(self):
        batch = BatchResult(total_files=0, total_time_seconds=0)
        cert = generate_certificate(batch)
        assert cert['summary']['total_files'] == 0
        assert cert['files'] == []
        assert cert['mode'] == 'unknown'


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
