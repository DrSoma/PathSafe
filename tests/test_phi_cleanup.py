"""Tests for PHI leak prevention cleanup in anonymizer.py.

Covers the critical code path where anonymize_file() cleans up
unanonymized copies when the format handler's anonymize() method
fails mid-way, preventing PHI from leaking into the output directory.
"""

from pathlib import Path
from unittest.mock import patch

from pathsafe.anonymizer import anonymize_file
from tests.conftest import build_tiff


class TestCopyModeCleanupOnAnonymizeFailure:
    """Test that failed anonymization in copy mode removes the unanonymized copy."""

    def _make_tiff_with_phi(self, tmp_path: Path, name: str = "phi_slide.tif") -> Path:
        """Create a synthetic TIFF with known PHI in a tag."""
        phi_value = b"Patient: John Smith MRN-12345\x00"
        entries = [
            (256, 3, 1, 512),  # ImageWidth
            (257, 3, 1, 512),  # ImageLength
            (270, 2, len(phi_value), phi_value),  # ImageDescription with PHI
        ]
        content = build_tiff(entries)
        filepath = tmp_path / name
        filepath.write_bytes(content)
        return filepath

    def test_output_removed_on_anonymize_exception(self, tmp_path):
        """When handler.anonymize() raises, the unanonymized copy must be deleted."""
        src = self._make_tiff_with_phi(tmp_path, "source.tif")
        out_dir = tmp_path / "output"
        out = out_dir / "source.tif"

        with patch("pathsafe.anonymizer.get_handler") as mock_get:
            mock_handler = mock_get.return_value
            mock_handler.anonymize.side_effect = RuntimeError(
                "Simulated crash during anonymization"
            )
            mock_handler.can_handle.return_value = True

            result = anonymize_file(src, output_path=out)

        # The result must report an error
        assert result.error is not None
        assert "Simulated crash" in result.error or "crash" in result.error.lower()

        # The output file must NOT exist -- it was an unanonymized copy
        assert not out.exists(), "Unanonymized copy was not cleaned up after anonymize() failure"

        # No files should remain in the output directory
        if out_dir.exists():
            remaining = list(out_dir.iterdir())
            assert len(remaining) == 0, f"Unexpected files remain in output dir: {remaining}"

    def test_original_untouched_on_anonymize_exception(self, tmp_path):
        """The source file must remain intact when copy-mode anonymization fails."""
        src = self._make_tiff_with_phi(tmp_path, "original.tif")
        original_bytes = src.read_bytes()
        out = tmp_path / "output" / "original.tif"

        with patch("pathsafe.anonymizer.get_handler") as mock_get:
            mock_handler = mock_get.return_value
            mock_handler.anonymize.side_effect = OSError("Disk I/O error")
            mock_handler.can_handle.return_value = True

            anonymize_file(src, output_path=out)

        # Source must be unchanged
        assert src.read_bytes() == original_bytes

    def test_result_mode_is_copy(self, tmp_path):
        """Result.mode should be 'copy' even when cleanup happens."""
        src = self._make_tiff_with_phi(tmp_path)
        out = tmp_path / "output" / src.name

        with patch("pathsafe.anonymizer.get_handler") as mock_get:
            mock_handler = mock_get.return_value
            mock_handler.anonymize.side_effect = ValueError("bad data")
            mock_handler.can_handle.return_value = True

            result = anonymize_file(src, output_path=out)

        assert result.mode == "copy"
        assert result.error is not None


class TestMRXSCompanionDirectoryCleanup:
    """Test that MRXS companion directory is also cleaned up on failure."""

    def test_mrxs_companion_dir_removed_on_failure(self, tmp_path):
        """When anonymize() fails on an MRXS file in copy mode,
        both the .mrxs copy and its companion data directory must be deleted."""
        # Create source MRXS file and its companion directory
        src = tmp_path / "src" / "slide.mrxs"
        src.parent.mkdir(parents=True, exist_ok=True)
        src.write_bytes(b"MIRAX\x00")

        companion_src = tmp_path / "src" / "slide"
        companion_src.mkdir()
        slidedat = companion_src / "Slidedat.ini"
        slidedat.write_text(
            "[GENERAL]\n"
            "SLIDE_ID = 12345\n"
            "SLIDE_NAME = Patient Smith\n"
            "SLIDE_BARCODE = AS-24-333333\n",
            encoding="utf-8",
        )

        out_dir = tmp_path / "output"
        out = out_dir / "slide.mrxs"

        with patch("pathsafe.anonymizer.get_handler") as mock_get:
            mock_handler = mock_get.return_value
            mock_handler.anonymize.side_effect = RuntimeError(
                "Simulated MRXS anonymization failure"
            )
            mock_handler.can_handle.return_value = True

            result = anonymize_file(src, output_path=out)

        assert result.error is not None

        # The .mrxs copy must not exist
        assert not out.exists(), "MRXS copy was not cleaned up"

        # The companion directory copy must not exist either
        companion_out = out_dir / "slide"
        assert not companion_out.exists(), "MRXS companion directory copy was not cleaned up"

    def test_mrxs_companion_cleanup_handles_missing_dir(self, tmp_path):
        """Cleanup should not fail if the companion directory was never copied."""
        src = tmp_path / "src" / "solo.mrxs"
        src.parent.mkdir(parents=True, exist_ok=True)
        src.write_bytes(b"MIRAX\x00")
        # No companion directory for this MRXS

        out = tmp_path / "output" / "solo.mrxs"

        with patch("pathsafe.anonymizer.get_handler") as mock_get:
            mock_handler = mock_get.return_value
            mock_handler.anonymize.side_effect = RuntimeError("fail")
            mock_handler.can_handle.return_value = True

            result = anonymize_file(src, output_path=out)

        # Should complete without secondary exceptions
        assert result.error is not None
        assert not out.exists()


class TestInPlaceModeNoCleanup:
    """Verify that in-place mode does NOT delete the source on failure."""

    def test_inplace_mode_preserves_file_on_error(self, tmp_path):
        """In-place mode: the source file must survive even if anonymize() fails."""
        phi_value = b"Patient: Jane Doe\x00"
        entries = [
            (256, 3, 1, 256),
            (257, 3, 1, 256),
            (270, 2, len(phi_value), phi_value),
        ]
        content = build_tiff(entries)
        src = tmp_path / "inplace.tif"
        src.write_bytes(content)
        src.read_bytes()

        with patch("pathsafe.anonymizer.get_handler") as mock_get:
            mock_handler = mock_get.return_value
            mock_handler.anonymize.side_effect = RuntimeError("crash")
            mock_handler.can_handle.return_value = True

            result = anonymize_file(src, output_path=None)

        assert result.error is not None
        assert result.mode == "inplace"
        # The file must still exist (not deleted -- cleanup only applies to copy mode)
        assert src.exists()


class TestCleanupWithPartialCopy:
    """Test cleanup when the copy was partially written before failure."""

    def test_partial_copy_cleaned_up(self, tmp_path):
        """Even if the copy was partially written, cleanup must remove it."""
        # Create a source file large enough to be meaningful
        phi_value = b"Patient: SECRET DATA 12345\x00"
        entries = [
            (256, 3, 1, 1024),
            (257, 3, 1, 1024),
            (270, 2, len(phi_value), phi_value),
        ]
        content = build_tiff(entries)
        src = tmp_path / "partial.tif"
        src.write_bytes(content)

        out = tmp_path / "output" / "partial.tif"

        with patch("pathsafe.anonymizer.get_handler") as mock_get:
            mock_handler = mock_get.return_value
            mock_handler.anonymize.side_effect = MemoryError("Out of memory during anonymization")
            mock_handler.can_handle.return_value = True

            result = anonymize_file(src, output_path=out)

        assert result.error is not None
        assert not out.exists(), "Partially-anonymized copy was not cleaned up after MemoryError"
