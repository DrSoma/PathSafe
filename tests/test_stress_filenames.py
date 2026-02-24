"""Stress tests -- Unicode and special filenames, filename PHI detection."""

import pytest
from pathlib import Path

from pathsafe.scanner import scan_filename_for_phi
from pathsafe.anonymizer import anonymize_file, collect_wsi_files
from tests.conftest import build_tiff


def _make_tiff(path):
    """Write a minimal TIFF with PHI to the given path."""
    barcode = b'AS-24-123456\x00'
    entries = [
        (256, 3, 1, 1024),
        (257, 3, 1, 768),
        (65468, 2, len(barcode), barcode),
    ]
    content = build_tiff(entries)
    path.write_bytes(content)
    return path


def _make_clean_tiff(path):
    """Write a minimal clean TIFF to the given path."""
    entries = [
        (256, 3, 1, 1024),
        (257, 3, 1, 768),
    ]
    content = build_tiff(entries)
    path.write_bytes(content)
    return path


class TestUnicodeFilenames:
    """Test scan_filename_for_phi with various Unicode names."""

    def test_accented_filename(self):
        """Accented characters (e.g., Ñoño) with accession number."""
        findings = scan_filename_for_phi(Path('Ñoño-AS-24-123456.ndpi'))
        labels = [f[3] for f in findings]
        assert 'Accession_AS' in labels

    def test_cjk_filename(self):
        """CJK characters with accession number."""
        findings = scan_filename_for_phi(Path('患者_AS-24-123456.ndpi'))
        labels = [f[3] for f in findings]
        assert 'Accession_AS' in labels

    def test_spaces_and_parens(self):
        """Spaces and parentheses with accession number."""
        findings = scan_filename_for_phi(Path('slide (copy) AS-24-123456.ndpi'))
        labels = [f[3] for f in findings]
        assert 'Accession_AS' in labels

    def test_long_255_char_name(self):
        """255-character filename with accession number at end."""
        name = 'x' * 230 + '_AS-24-123456.ndpi'
        findings = scan_filename_for_phi(Path(name))
        labels = [f[3] for f in findings]
        assert 'Accession_AS' in labels

    def test_unicode_only_clean(self):
        """Unicode-only filename (no accession pattern) → clean."""
        findings = scan_filename_for_phi(Path('標本画像_検体.ndpi'))
        assert len(findings) == 0

    def test_emoji_clean(self):
        """Emoji in filename (no accession pattern) → clean."""
        findings = scan_filename_for_phi(Path('🔬slide_sample🧬.ndpi'))
        assert len(findings) == 0

    def test_arabic_with_phi(self):
        """Arabic text with accession number."""
        findings = scan_filename_for_phi(Path('مريض-SP-23-78901.ndpi'))
        labels = [f[3] for f in findings]
        assert 'Accession_SP' in labels

    def test_mixed_script_clean(self):
        """Mixed scripts without PHI patterns → clean."""
        findings = scan_filename_for_phi(Path('τεστ_тест_テスト.ndpi'))
        assert len(findings) == 0


class TestUnicodeFilenamePipeline:
    """Test full anonymize pipeline with Unicode filenames."""

    def test_anonymize_unicode_filename_reports_phi(self, tmp_path):
        """Full anonymize with Unicode filename reports filename_has_phi."""
        filepath = _make_tiff(tmp_path / 'Ñoño-AS-24-123456.ndpi')
        result = anonymize_file(filepath)
        assert result.error is None
        assert result.filename_has_phi is True

    def test_anonymize_unicode_clean_filename(self, tmp_path):
        """Unicode filename without PHI → filename_has_phi=False."""
        filepath = _make_tiff(tmp_path / '検体サンプル.ndpi')
        result = anonymize_file(filepath)
        assert result.error is None
        assert result.filename_has_phi is False

    def test_collect_wsi_files_unicode(self, tmp_path):
        """collect_wsi_files finds Unicode-named files."""
        _make_tiff(tmp_path / 'Ñoño-slide.ndpi')
        _make_tiff(tmp_path / '患者_slide.ndpi')
        _make_clean_tiff(tmp_path / 'normal.ndpi')

        files = collect_wsi_files(tmp_path)
        assert len(files) == 3
        names = {f.name for f in files}
        assert 'Ñoño-slide.ndpi' in names
        assert '患者_slide.ndpi' in names
