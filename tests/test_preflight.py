"""Tests for pre-flight validation."""

import os
import stat
from pathlib import Path

from pathsafe.anonymizer import preflight_check


class TestPreflightCheck:
    """Pre-flight validation tests."""

    def test_valid_output_dir(self, tmp_path):
        """Valid output directory → ok=True."""
        src = tmp_path / "slide.ndpi"
        src.write_bytes(b'\x00' * 1024)
        out_dir = tmp_path / "output"
        out_dir.mkdir()

        result = preflight_check([src], output_dir=out_dir)
        assert result.ok is True
        assert result.errors == []

    def test_nonexistent_creatable_dir(self, tmp_path):
        """Nonexistent but creatable directory → ok=True with warning."""
        src = tmp_path / "slide.ndpi"
        src.write_bytes(b'\x00' * 1024)
        out_dir = tmp_path / "new_output"

        result = preflight_check([src], output_dir=out_dir)
        assert result.ok is True
        assert any('will be created' in w for w in result.warnings)

    def test_read_only_dir(self, tmp_path):
        """Read-only output directory → ok=False with error."""
        src = tmp_path / "slide.ndpi"
        src.write_bytes(b'\x00' * 1024)
        out_dir = tmp_path / "readonly"
        out_dir.mkdir()
        out_dir.chmod(stat.S_IRUSR | stat.S_IXUSR)

        try:
            result = preflight_check([src], output_dir=out_dir)
            assert result.ok is False
            assert any('not writable' in e for e in result.errors)
        finally:
            # Restore permissions for cleanup
            out_dir.chmod(stat.S_IRWXU)

    def test_no_files(self):
        """Empty file list → ok=False."""
        result = preflight_check([], output_dir=Path("/tmp/test"))
        assert result.ok is False
        assert any('No files' in e for e in result.errors)

    def test_inplace_mode(self, tmp_path):
        """In-place mode (no output_dir) → ok=True."""
        src = tmp_path / "slide.ndpi"
        src.write_bytes(b'\x00' * 1024)

        result = preflight_check([src], output_dir=None)
        assert result.ok is True

    def test_estimated_size(self, tmp_path):
        """Estimated size is computed from files."""
        f1 = tmp_path / "a.ndpi"
        f2 = tmp_path / "b.ndpi"
        f1.write_bytes(b'\x00' * 1000)
        f2.write_bytes(b'\x00' * 2000)

        result = preflight_check([f1, f2], output_dir=tmp_path)
        assert result.estimated_size_bytes == 3000

    def test_output_path_is_file(self, tmp_path):
        """Output path is an existing file, not directory → error."""
        src = tmp_path / "slide.ndpi"
        src.write_bytes(b'\x00' * 1024)
        bad_out = tmp_path / "output_file"
        bad_out.write_text("not a directory")

        result = preflight_check([src], output_dir=bad_out)
        assert result.ok is False
        assert any('not a directory' in e for e in result.errors)
