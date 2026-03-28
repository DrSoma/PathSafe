"""Tests for the copy-mode staging workflow in anonymize_file().

Validates that the staging file (.pathsafe_pending) is used during
copy-mode anonymization and is properly renamed to the final output
path, with no intermediate files left behind.
"""

import pytest

from pathsafe.anonymizer import anonymize_file
from tests.conftest import build_tiff


@pytest.fixture
def source_ndpi(tmp_path):
    """Create a source NDPI file with PHI for copy-mode tests."""
    barcode = b"AS-24-123456\x00"
    reference = b"REF-001\x00"
    entries = [
        (256, 3, 1, 1024),
        (257, 3, 1, 768),
        (65427, 2, len(reference), reference),
        (65468, 2, len(barcode), barcode),
    ]
    content = build_tiff(entries)
    filepath = tmp_path / "input" / "source_slide.ndpi"
    filepath.parent.mkdir(parents=True, exist_ok=True)
    filepath.write_bytes(content)
    return filepath


@pytest.fixture
def source_svs(tmp_path):
    """Create a source SVS file with PHI for copy-mode tests."""
    desc = (
        b"Aperio Image Library v12.0.16\n"
        b"1024x768 [0,0 1024x768] (256x256) JPEG Q=70"
        b"|Filename = AS-24-999999.svs"
        b"|Date = 06/15/24"
        b"|User = jdoe@hospital.org"
        b"\x00"
    )
    entries = [
        (256, 3, 1, 1024),
        (257, 3, 1, 768),
        (270, 2, len(desc), desc),
    ]
    content = build_tiff(entries)
    filepath = tmp_path / "input" / "source_slide.svs"
    filepath.parent.mkdir(parents=True, exist_ok=True)
    filepath.write_bytes(content)
    return filepath


class TestStagingFileCleanup:
    """After successful copy-mode anonymize, no staging files should remain."""

    def test_no_pending_file_after_copy_mode(self, tmp_path, source_ndpi):
        """The .pathsafe_pending staging file is removed after success."""
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        output_path = output_dir / "anon_slide.ndpi"

        result = anonymize_file(source_ndpi, output_path=output_path)
        assert result.error is None

        # Check no .pathsafe_pending files remain
        pending_files = list(output_dir.glob("*.pathsafe_pending*"))
        assert pending_files == [], f"Staging files left behind: {pending_files}"

    def test_final_output_file_exists(self, tmp_path, source_ndpi):
        """The final output file exists at the specified path after success."""
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        output_path = output_dir / "anon_slide.ndpi"

        result = anonymize_file(source_ndpi, output_path=output_path)
        assert result.error is None
        assert output_path.exists()
        assert output_path.stat().st_size > 0

    def test_no_pending_file_svs(self, tmp_path, source_svs):
        """Staging cleanup also works for SVS format."""
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        output_path = output_dir / "anon_slide.svs"

        result = anonymize_file(source_svs, output_path=output_path)
        assert result.error is None

        pending_files = list(output_dir.glob("*.pathsafe_pending*"))
        assert pending_files == []
        assert output_path.exists()


class TestStagingExtensionPreservation:
    """The staging file must preserve the original extension."""

    def test_staging_preserves_ndpi_extension(self, tmp_path, source_ndpi):
        """Staging file for .ndpi should be stem.pathsafe_pending.ndpi."""
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        output_path = output_dir / "slide.ndpi"

        # The staging file name is derived from the output path:
        #   stem + '.pathsafe_pending' + suffix
        expected_staging = output_dir / "slide.pathsafe_pending.ndpi"

        # Run the anonymization -- afterwards, staging should be gone
        result = anonymize_file(source_ndpi, output_path=output_path)
        assert result.error is None

        # The staging file should have been renamed to the final path
        assert not expected_staging.exists(), (
            "Staging file still exists after successful anonymization"
        )
        assert output_path.exists()
        # Verify the extension is .ndpi, not .pathsafe_pending
        assert output_path.suffix == ".ndpi"

    def test_staging_preserves_svs_extension(self, tmp_path, source_svs):
        """Staging file for .svs should be stem.pathsafe_pending.svs."""
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        output_path = output_dir / "slide.svs"

        result = anonymize_file(source_svs, output_path=output_path)
        assert result.error is None
        assert output_path.exists()
        assert output_path.suffix == ".svs"


class TestMRXSStagingWorkflow:
    """MRXS companion directory is renamed alongside the staging file."""

    @pytest.fixture
    def source_mrxs(self, tmp_path):
        """Create a source MRXS file with companion directory."""
        input_dir = tmp_path / "input"
        input_dir.mkdir()

        mrxs_file = input_dir / "test_slide.mrxs"
        mrxs_file.write_bytes(b"MIRAX\x00")

        companion = input_dir / "test_slide"
        companion.mkdir()
        slidedat = companion / "Slidedat.ini"
        slidedat.write_text(
            "[GENERAL]\n"
            "SLIDE_ID = 12345\n"
            "SLIDE_NAME = Patient Smith\n"
            "SLIDE_BARCODE = AS-24-333333\n"
            "SLIDE_CREATIONDATETIME = 20240615120000\n"
            "OBJECTIVE_MAGNIFICATION = 40\n"
            "[HIERARCHICAL]\n"
            "NONHIER_COUNT = 0\n",
            encoding="utf-8",
        )
        return mrxs_file

    def test_mrxs_companion_dir_renamed_with_staging(self, tmp_path, source_mrxs):
        """After copy-mode anonymize, the companion dir uses the final stem."""
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        output_path = output_dir / "anon_slide.mrxs"

        result = anonymize_file(source_mrxs, output_path=output_path)
        assert result.error is None

        # Final output file should exist
        assert output_path.exists()

        # Companion directory should use the final stem, not the staging stem
        final_companion = output_dir / "anon_slide"
        staging_companion = output_dir / "anon_slide.pathsafe_pending"
        assert final_companion.is_dir(), f"Expected companion dir at {final_companion}"
        assert not staging_companion.exists(), (
            f"Staging companion dir still exists at {staging_companion}"
        )

    def test_mrxs_no_pending_files_remain(self, tmp_path, source_mrxs):
        """No .pathsafe_pending files or dirs remain after MRXS anonymization."""
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        output_path = output_dir / "anon_slide.mrxs"

        result = anonymize_file(source_mrxs, output_path=output_path)
        assert result.error is None

        # Check for any lingering staging artifacts
        pending = list(output_dir.glob("*pathsafe_pending*"))
        assert pending == [], f"Staging artifacts remain: {pending}"
