"""Tests for symlink rejection in anonymize_file() and collect_wsi_files().

Validates that PathSafe refuses to process symlinked source files and
refuses to write to symlinked output paths, preventing path traversal
attacks via symbolic links.
"""

import os

import pytest

from pathsafe.anonymizer import anonymize_file, collect_wsi_files
from tests.conftest import build_tiff


@pytest.fixture
def real_ndpi(tmp_path):
    """Create a real (non-symlinked) NDPI file with PHI for symlink tests."""
    barcode = b"AS-24-123456\x00"
    entries = [
        (256, 3, 1, 1024),
        (257, 3, 1, 768),
        (65468, 2, len(barcode), barcode),
    ]
    content = build_tiff(entries)
    filepath = tmp_path / "real_slide.ndpi"
    filepath.write_bytes(content)
    return filepath


class TestSymlinkSourceRejection:
    """anonymize_file() must reject symlinked source files."""

    def test_rejects_symlinked_source_file(self, tmp_path, real_ndpi):
        """A symlink pointing at a valid NDPI file is rejected."""
        symlink_path = tmp_path / "link_to_slide.ndpi"
        os.symlink(str(real_ndpi), str(symlink_path))

        result = anonymize_file(symlink_path)
        assert result.error is not None
        assert "symlink" in result.error.lower()

    def test_rejects_symlinked_source_inplace_mode(self, tmp_path, real_ndpi):
        """In-place mode also rejects symlinked source files."""
        symlink_path = tmp_path / "link_inplace.ndpi"
        os.symlink(str(real_ndpi), str(symlink_path))

        result = anonymize_file(symlink_path, output_path=None)
        assert result.error is not None
        assert "symlink" in result.error.lower()


class TestSymlinkOutputRejection:
    """anonymize_file() must reject symlinked output paths."""

    def test_rejects_symlinked_output_path(self, tmp_path, real_ndpi):
        """A symlink as the output_path is rejected before any copy."""
        # Create a symlink that points to a different directory
        target_dir = tmp_path / "target_dir"
        target_dir.mkdir()
        symlink_output = tmp_path / "output_link.ndpi"
        os.symlink(str(target_dir / "escaped.ndpi"), str(symlink_output))

        result = anonymize_file(real_ndpi, output_path=symlink_output)
        assert result.error is not None
        assert "symlink" in result.error.lower()

    def test_rejects_symlinked_output_existing_target(self, tmp_path, real_ndpi):
        """Even if the symlink target exists, a symlinked output is rejected."""
        # Create a real file and symlink pointing to it
        other_file = tmp_path / "other.ndpi"
        other_file.write_bytes(b"\x00" * 100)
        symlink_output = tmp_path / "sym_output.ndpi"
        os.symlink(str(other_file), str(symlink_output))

        result = anonymize_file(real_ndpi, output_path=symlink_output)
        assert result.error is not None
        assert "symlink" in result.error.lower()


class TestCollectWSIFilesSymlinks:
    """collect_wsi_files() must skip symlinked files."""

    def test_skips_symlinked_files_in_directory(self, tmp_path, real_ndpi):
        """Symlinked files inside a directory are skipped during collection."""
        scan_dir = tmp_path / "scan_dir"
        scan_dir.mkdir()

        # Create a real file in scan_dir
        real_file = scan_dir / "real.ndpi"
        real_file.write_bytes(real_ndpi.read_bytes())

        # Create a symlink in scan_dir pointing to the fixture
        symlink_file = scan_dir / "linked.ndpi"
        os.symlink(str(real_ndpi), str(symlink_file))

        files = collect_wsi_files(scan_dir)
        # Only the real file should be collected
        assert len(files) == 1
        assert files[0].name == "real.ndpi"

    def test_skips_single_symlinked_file(self, tmp_path, real_ndpi):
        """A single symlinked file passed directly is skipped."""
        symlink_file = tmp_path / "single_link.ndpi"
        os.symlink(str(real_ndpi), str(symlink_file))

        files = collect_wsi_files(symlink_file)
        assert files == []

    def test_collects_real_files_alongside_symlinks(self, tmp_path, real_ndpi):
        """Real files are collected even when symlinks are present in the same dir."""
        scan_dir = tmp_path / "mixed_dir"
        scan_dir.mkdir()

        # Create two real files
        for name in ["slide_a.ndpi", "slide_b.ndpi"]:
            f = scan_dir / name
            f.write_bytes(real_ndpi.read_bytes())

        # Create two symlinks
        for name in ["sym_a.ndpi", "sym_b.ndpi"]:
            s = scan_dir / name
            os.symlink(str(real_ndpi), str(s))

        files = collect_wsi_files(scan_dir)
        names = {f.name for f in files}
        assert names == {"slide_a.ndpi", "slide_b.ndpi"}
        assert len(files) == 2
