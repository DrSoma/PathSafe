"""Tests for the deidentifier orchestration module."""

from unittest.mock import patch

from pathsafe.deidentifier import (
    collect_wsi_files,
    deidentify_batch,
    deidentify_file,
    scan_batch,
)


class TestDeidentifyFileCopyMode:
    def test_copy_mode_creates_output(self, tmp_ndpi, tmp_path):
        out = tmp_path / "output" / tmp_ndpi.name
        result = deidentify_file(tmp_ndpi, output_path=out)
        assert result.error is None
        assert result.mode == "copy"
        assert out.exists()

    def test_copy_mode_preserves_original(self, tmp_ndpi, tmp_path):
        original_bytes = tmp_ndpi.read_bytes()
        out = tmp_path / "output" / tmp_ndpi.name
        deidentify_file(tmp_ndpi, output_path=out)
        assert tmp_ndpi.read_bytes() == original_bytes

    def test_copy_mode_deidentifies_output(self, tmp_ndpi, tmp_path):
        out = tmp_path / "output" / tmp_ndpi.name
        result = deidentify_file(tmp_ndpi, output_path=out)
        assert result.findings_cleared > 0


class TestDeidentifyFileInPlace:
    def test_inplace_mode(self, tmp_ndpi):
        result = deidentify_file(tmp_ndpi, output_path=None)
        assert result.error is None
        assert result.mode == "inplace"
        assert result.findings_cleared > 0


class TestDeidentifyFileDryRun:
    def test_dry_run_no_modification(self, tmp_ndpi, tmp_path):
        original_bytes = tmp_ndpi.read_bytes()
        out = tmp_path / "output" / tmp_ndpi.name
        result = deidentify_file(tmp_ndpi, output_path=out, dry_run=True)
        assert result.error is None
        assert result.findings_cleared > 0
        assert tmp_ndpi.read_bytes() == original_bytes
        assert not out.exists()  # No output created in dry run


class TestDeidentifyFileMissing:
    def test_missing_file(self, tmp_path):
        missing = tmp_path / "nonexistent.ndpi"
        result = deidentify_file(missing)
        assert result.error is not None
        assert "not found" in result.error.lower()


class TestDeidentifyFileVerification:
    def test_verification_always_runs(self, tmp_ndpi):
        """Verify=True runs verification even for files with findings."""
        result = deidentify_file(tmp_ndpi, verify=True)
        assert result.verified

    def test_verification_runs_on_clean_file(self, tmp_ndpi_clean):
        """Verify=True runs even when no findings to clear."""
        result = deidentify_file(tmp_ndpi_clean, verify=True)
        assert result.verified

    def test_verification_disabled(self, tmp_ndpi):
        result = deidentify_file(tmp_ndpi, verify=False)
        assert not result.verified


class TestDeidentifyFileCleanup:
    def test_cleanup_on_error_copy_mode(self, tmp_ndpi, tmp_path):
        """Failed deidentification in copy mode deletes the undeidentified copy."""
        out = tmp_path / "output" / tmp_ndpi.name

        # Mock handler.deidentify to raise
        with patch("pathsafe.deidentifier.get_handler") as mock_get:
            mock_handler = mock_get.return_value
            mock_handler.deidentify.side_effect = RuntimeError("Test failure")
            mock_handler.can_handle.return_value = True
            result = deidentify_file(tmp_ndpi, output_path=out)

        assert result.error is not None
        assert not out.exists()  # Undeidentified copy was cleaned up


class TestDeidentifyFileFilenamePHI:
    def test_filename_phi_detected(self, tmp_ndpi_phi_filename, tmp_path):
        out = tmp_path / "output" / tmp_ndpi_phi_filename.name
        result = deidentify_file(tmp_ndpi_phi_filename, output_path=out)
        assert result.filename_has_phi

    def test_clean_filename(self, tmp_ndpi, tmp_path):
        out = tmp_path / "output" / tmp_ndpi.name
        result = deidentify_file(tmp_ndpi, output_path=out)
        assert not result.filename_has_phi


class TestDeidentifyFileTimestamps:
    def test_reset_timestamps(self, tmp_ndpi, tmp_path):
        out = tmp_path / "output" / tmp_ndpi.name
        result = deidentify_file(tmp_ndpi, output_path=out, reset_timestamps=True)
        assert result.error is None
        stat = out.stat()
        assert stat.st_mtime == 0
        assert stat.st_atime == 0

    def test_no_reset_timestamps(self, tmp_ndpi, tmp_path):
        out = tmp_path / "output" / tmp_ndpi.name
        result = deidentify_file(tmp_ndpi, output_path=out, reset_timestamps=False)
        assert result.error is None
        assert out.stat().st_mtime > 0


class TestDeidentifyFileIntegrity:
    def test_integrity_verified_for_tiff(self, tmp_path):
        """Image integrity verified for TIFF files with strip data."""
        from tests.conftest import build_tiff_with_strips

        strip_data = b"\xab\xcd" * 50
        tag_entries = [
            (256, 3, 1, 64),
            (257, 3, 1, 64),
        ]
        content = build_tiff_with_strips(tag_entries, strip_data)
        src = tmp_path / "src.tif"
        src.write_bytes(content)
        out = tmp_path / "out.tif"
        result = deidentify_file(src, output_path=out, verify_integrity=True)
        assert result.error is None
        # For a file with no PHI to deidentify, strip data is unchanged
        assert result.image_integrity_verified is True

    def test_integrity_not_checked_when_disabled(self, tmp_ndpi, tmp_path):
        out = tmp_path / "output" / tmp_ndpi.name
        result = deidentify_file(tmp_ndpi, output_path=out, verify_integrity=False)
        assert result.image_integrity_verified is None


class TestCollectWSIFiles:
    def test_single_file(self, tmp_ndpi):
        files = collect_wsi_files(tmp_ndpi)
        assert len(files) == 1
        assert files[0] == tmp_ndpi

    def test_directory(self, tmp_ndpi, tmp_svs):
        # Both are in tmp_path subdir
        files = collect_wsi_files(tmp_ndpi.parent)
        names = {f.name for f in files}
        assert tmp_ndpi.name in names
        assert tmp_svs.name in names

    def test_format_filter(self, tmp_ndpi, tmp_svs):
        files = collect_wsi_files(tmp_ndpi.parent, format_filter="ndpi")
        names = {f.name for f in files}
        assert tmp_ndpi.name in names
        assert tmp_svs.name not in names

    def test_empty_directory(self, tmp_path):
        files = collect_wsi_files(tmp_path)
        assert len(files) == 0


class TestDeidentifyBatch:
    def test_batch_sequential(self, tmp_ndpi, tmp_path):
        out_dir = tmp_path / "output"
        batch = deidentify_batch(tmp_ndpi.parent, output_dir=out_dir, workers=1)
        assert batch.total_files >= 1
        assert batch.files_errored == 0

    def test_batch_progress_callback(self, tmp_ndpi, tmp_path):
        out_dir = tmp_path / "output"
        calls = []

        def on_progress(index, total, filepath, result):
            calls.append((index, total))

        deidentify_batch(tmp_ndpi, output_dir=out_dir, progress_callback=on_progress)
        assert len(calls) == 1
        assert calls[0] == (1, 1)

    def test_batch_format_filter(self, tmp_ndpi, tmp_svs, tmp_path):
        out_dir = tmp_path / "output"
        batch = deidentify_batch(
            tmp_ndpi.parent, output_dir=out_dir, format_filter="ndpi", workers=1
        )
        # Should only process NDPI files
        for result in batch.results:
            assert result.source_path.suffix.lower() == ".ndpi"


class TestScanBatch:
    def test_scan_batch(self, tmp_ndpi):
        results = scan_batch(tmp_ndpi)
        assert len(results) == 1
        filepath, scan_result = results[0]
        assert not scan_result.is_clean

    def test_scan_batch_directory(self, tmp_ndpi, tmp_svs):
        results = scan_batch(tmp_ndpi.parent)
        assert len(results) >= 2

    def test_scan_batch_empty(self, tmp_path):
        results = scan_batch(tmp_path)
        assert len(results) == 0

    def test_scan_batch_parallel(self, tmp_ndpi):
        results = scan_batch(tmp_ndpi, workers=2)
        assert len(results) == 1
