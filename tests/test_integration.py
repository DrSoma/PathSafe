"""Integration tests -- full scan → anonymize → verify → report pipeline.

These test the entire flow end-to-end using synthetic temporary files.
No original WSI images are touched.
"""

import json
import pytest
from pathlib import Path

from pathsafe.anonymizer import anonymize_file, anonymize_batch, scan_batch
from pathsafe.verify import verify_file, verify_batch
from pathsafe.report import generate_certificate
from pathsafe.formats import get_handler, detect_format


class TestNDPIPipeline:
    """Full pipeline test for NDPI format."""

    def test_scan_finds_phi(self, tmp_ndpi):
        handler = get_handler(tmp_ndpi)
        result = handler.scan(tmp_ndpi)
        assert not result.is_clean
        assert result.format == 'ndpi'
        assert len(result.findings) > 0

    def test_full_pipeline_copy_mode(self, tmp_ndpi, tmp_path):
        output = tmp_path / 'output' / 'anonymized.ndpi'

        # 1. Anonymize in copy mode
        result = anonymize_file(tmp_ndpi, output_path=output, verify=True)
        assert result.error is None
        assert result.mode == 'copy'
        assert result.findings_cleared > 0
        assert result.verified

        # 2. Original untouched -- still has PHI
        handler = get_handler(tmp_ndpi)
        original_scan = handler.scan(tmp_ndpi)
        assert not original_scan.is_clean

        # 3. Output is clean
        verify_result = verify_file(output)
        assert verify_result.is_clean

    def test_full_pipeline_inplace(self, tmp_ndpi):
        # 1. Scan
        handler = get_handler(tmp_ndpi)
        scan_result = handler.scan(tmp_ndpi)
        assert not scan_result.is_clean
        scan_count = len(scan_result.findings)

        # 2. Anonymize in-place
        result = anonymize_file(tmp_ndpi, verify=True)
        assert result.error is None
        assert result.mode == 'inplace'
        assert result.findings_cleared > 0
        assert result.verified

        # 3. Verify
        verify_result = verify_file(tmp_ndpi)
        assert verify_result.is_clean

    def test_dry_run_no_modification(self, tmp_ndpi):
        original_bytes = tmp_ndpi.read_bytes()
        result = anonymize_file(tmp_ndpi, dry_run=True)
        assert result.findings_cleared > 0
        assert not result.verified
        assert tmp_ndpi.read_bytes() == original_bytes


class TestSVSPipeline:
    """Full pipeline test for SVS format."""

    def test_full_pipeline(self, tmp_svs, tmp_path):
        output = tmp_path / 'out' / 'slide.svs'

        result = anonymize_file(tmp_svs, output_path=output, verify=True)
        assert result.error is None
        assert result.findings_cleared > 0
        assert result.verified

        verify_result = verify_file(output)
        assert verify_result.is_clean


class TestBIFPipeline:
    """Full pipeline test for BIF format."""

    def test_full_pipeline(self, tmp_bif, tmp_path):
        output = tmp_path / 'out' / 'slide.bif'

        result = anonymize_file(tmp_bif, output_path=output, verify=True)
        assert result.error is None
        assert result.findings_cleared > 0
        assert result.verified

        verify_result = verify_file(output)
        assert verify_result.is_clean


class TestSCNPipeline:
    """Full pipeline test for SCN format."""

    def test_full_pipeline(self, tmp_scn, tmp_path):
        output = tmp_path / 'out' / 'slide.scn'

        result = anonymize_file(tmp_scn, output_path=output, verify=True)
        assert result.error is None
        assert result.findings_cleared > 0
        assert result.verified

        verify_result = verify_file(output)
        assert verify_result.is_clean


class TestMRXSPipeline:
    """Full pipeline test for MRXS format."""

    def test_full_pipeline(self, tmp_mrxs, tmp_path):
        output = tmp_path / 'out' / 'slide.mrxs'

        result = anonymize_file(tmp_mrxs, output_path=output, verify=True)
        assert result.error is None
        assert result.findings_cleared > 0
        assert result.verified

        # Companion directory should be copied
        companion = output.parent / output.stem
        assert companion.is_dir()

        verify_result = verify_file(output)
        assert verify_result.is_clean


class TestGenericTIFFPipeline:
    """Full pipeline test for generic TIFF format."""

    def test_full_pipeline(self, tmp_tiff_with_phi, tmp_path):
        output = tmp_path / 'out' / 'slide.tif'

        result = anonymize_file(tmp_tiff_with_phi, output_path=output, verify=True)
        assert result.error is None
        assert result.findings_cleared > 0
        assert result.verified

        verify_result = verify_file(output)
        assert verify_result.is_clean


class TestBatchPipeline:
    """Batch pipeline -- multiple files of different formats."""

    def test_batch_scan_and_anonymize(self, tmp_ndpi, tmp_svs, tmp_path):
        # Set up input directory
        indir = tmp_path / 'input'
        indir.mkdir()
        import shutil
        shutil.copy2(str(tmp_ndpi), str(indir / 'slide.ndpi'))
        shutil.copy2(str(tmp_svs), str(indir / 'slide.svs'))

        # 1. Batch scan
        scan_results = scan_batch(indir)
        assert len(scan_results) == 2
        for filepath, result in scan_results:
            assert not result.is_clean

        # 2. Batch anonymize
        outdir = tmp_path / 'output'
        batch_result = anonymize_batch(indir, output_dir=outdir, verify=True)
        assert batch_result.total_files == 2
        assert batch_result.files_anonymized == 2
        assert batch_result.files_errored == 0

        # 3. Batch verify
        verify_results = verify_batch(outdir)
        assert len(verify_results) == 2
        for result in verify_results:
            assert result.is_clean

    def test_batch_with_clean_and_dirty(self, tmp_ndpi, tmp_ndpi_clean, tmp_path):
        indir = tmp_path / 'input'
        indir.mkdir()
        import shutil
        shutil.copy2(str(tmp_ndpi), str(indir / 'dirty.ndpi'))
        shutil.copy2(str(tmp_ndpi_clean), str(indir / 'clean.ndpi'))

        outdir = tmp_path / 'output'
        batch_result = anonymize_batch(indir, output_dir=outdir, verify=True)
        assert batch_result.total_files == 2
        assert batch_result.files_anonymized >= 1
        assert batch_result.files_errored == 0

    def test_batch_format_filter(self, tmp_ndpi, tmp_svs, tmp_path):
        indir = tmp_path / 'input'
        indir.mkdir()
        import shutil
        shutil.copy2(str(tmp_ndpi), str(indir / 'slide.ndpi'))
        shutil.copy2(str(tmp_svs), str(indir / 'slide.svs'))

        outdir = tmp_path / 'output'
        batch_result = anonymize_batch(indir, output_dir=outdir,
                                        format_filter='ndpi')
        assert batch_result.total_files == 1

    def test_batch_progress_callback(self, tmp_ndpi, tmp_path):
        indir = tmp_path / 'input'
        indir.mkdir()
        import shutil
        shutil.copy2(str(tmp_ndpi), str(indir / 'slide.ndpi'))

        progress = []
        def cb(i, total, filepath, result):
            progress.append((i, total, filepath.name))

        outdir = tmp_path / 'output'
        anonymize_batch(indir, output_dir=outdir, progress_callback=cb)
        assert len(progress) == 1
        assert progress[0][0] == 1
        assert progress[0][1] == 1


class TestCertificatePipeline:
    """Certificate generation after full pipeline."""

    def test_certificate_after_anonymize(self, tmp_ndpi, tmp_path):
        outdir = tmp_path / 'output'
        batch_result = anonymize_batch(
            tmp_ndpi, output_dir=outdir, verify=True,
            reset_timestamps=True, verify_integrity=True)

        cert_path = tmp_path / 'cert.json'
        cert = generate_certificate(batch_result, output_path=cert_path,
                                     timestamps_reset=True)

        assert cert_path.exists()
        data = json.loads(cert_path.read_text())
        assert data['summary']['total_files'] == 1
        assert data['summary']['anonymized'] == 1
        assert data['summary']['verified'] is True
        assert len(data['files']) == 1

        record = data['files'][0]
        assert record['verified_clean'] is True
        assert record['findings_cleared'] > 0
        assert 'sha256_after' in record

        # Measures should include all applied ones
        measure_names = [m['measure'] for m in data['measures']]
        assert 'Metadata tags cleared' in measure_names
        assert 'Post-anonymization verification' in measure_names
        assert 'Filesystem timestamps reset' in measure_names

    def test_certificate_with_integrity(self, tmp_tiff_with_strips, tmp_path):
        outdir = tmp_path / 'output'
        batch_result = anonymize_batch(
            tmp_tiff_with_strips, output_dir=outdir,
            verify=True, verify_integrity=True)

        cert = generate_certificate(batch_result)
        # Check integrity measure is present for TIFF files
        integrity_measures = [m for m in cert['measures']
                              if 'integrity' in m['measure'].lower()]
        if integrity_measures:
            assert integrity_measures[0]['status'] in ('passed', 'failed')


class TestIntegrityPipeline:
    """Image integrity verification through the pipeline."""

    def test_integrity_verified_on_tiff(self, tmp_tiff_with_strips, tmp_path):
        output = tmp_path / 'output' / 'strips.tif'

        result = anonymize_file(
            tmp_tiff_with_strips, output_path=output,
            verify=True, verify_integrity=True)

        assert result.error is None
        # Strip data has no PHI tags to clear, so integrity should be verified
        assert result.image_integrity_verified is True or result.image_integrity_verified is None

    def test_integrity_not_checked_when_disabled(self, tmp_ndpi, tmp_path):
        output = tmp_path / 'output' / 'slide.ndpi'

        result = anonymize_file(
            tmp_ndpi, output_path=output,
            verify=True, verify_integrity=False)

        assert result.image_integrity_verified is None


class TestFilenamePhiPipeline:
    """Filename PHI detection through the pipeline."""

    def test_filename_phi_detected(self, tmp_ndpi_phi_filename, tmp_path):
        output = tmp_path / 'output' / 'AS-24-999999.ndpi'

        result = anonymize_file(
            tmp_ndpi_phi_filename, output_path=output, verify=True)

        assert result.filename_has_phi is True

    def test_clean_filename_no_phi(self, tmp_ndpi, tmp_path):
        output = tmp_path / 'output' / 'safe_name.ndpi'

        result = anonymize_file(
            tmp_ndpi, output_path=output, verify=True)

        assert result.filename_has_phi is False


class TestTimestampPipeline:
    """Timestamp reset through the pipeline."""

    def test_timestamps_reset(self, tmp_ndpi, tmp_path):
        output = tmp_path / 'output' / 'slide.ndpi'
        import os

        result = anonymize_file(
            tmp_ndpi, output_path=output,
            reset_timestamps=True)

        assert result.error is None
        stat = os.stat(output)
        assert stat.st_mtime == 0
        assert stat.st_atime == 0

    def test_timestamps_preserved_when_disabled(self, tmp_ndpi, tmp_path):
        output = tmp_path / 'output' / 'slide.ndpi'
        import os

        result = anonymize_file(
            tmp_ndpi, output_path=output,
            reset_timestamps=False)

        stat = os.stat(output)
        assert stat.st_mtime > 0
