"""CLI integration tests -- end-to-end via click.testing.CliRunner.

Tests the actual CLI commands (scan, anonymize, verify, info) including
argument parsing, output formatting, exit codes, and error handling.

All tests use synthetic temporary files -- no original WSI images are touched.
"""

import json
import shutil
import pytest
from pathlib import Path
from click.testing import CliRunner

from pathsafe.cli import main
from tests.conftest import build_tiff


@pytest.fixture
def runner():
    return CliRunner()


# ──────────────────────────────────────────────────────────────────
# scan command
# ──────────────────────────────────────────────────────────────────

class TestScanCLI:
    def test_scan_single_file(self, runner, tmp_ndpi):
        result = runner.invoke(main, ['scan', str(tmp_ndpi)])
        assert result.exit_code == 0
        assert 'finding' in result.output.lower()

    def test_scan_directory(self, runner, tmp_ndpi, tmp_svs, tmp_path):
        indir = tmp_path / 'scandir'
        indir.mkdir()
        shutil.copy2(str(tmp_ndpi), str(indir / 'slide.ndpi'))
        shutil.copy2(str(tmp_svs), str(indir / 'slide.svs'))

        result = runner.invoke(main, ['scan', str(indir)])
        assert result.exit_code == 0
        assert '2 file(s)' in result.output

    def test_scan_verbose(self, runner, tmp_ndpi):
        result = runner.invoke(main, ['scan', '--verbose', str(tmp_ndpi)])
        assert result.exit_code == 0

    def test_scan_format_filter(self, runner, tmp_ndpi, tmp_svs, tmp_path):
        indir = tmp_path / 'scandir'
        indir.mkdir()
        shutil.copy2(str(tmp_ndpi), str(indir / 'slide.ndpi'))
        shutil.copy2(str(tmp_svs), str(indir / 'slide.svs'))

        result = runner.invoke(main, ['scan', '--format', 'ndpi', str(indir)])
        assert result.exit_code == 0
        assert '1 file(s)' in result.output

    def test_scan_json_output(self, runner, tmp_ndpi, tmp_path):
        json_out = tmp_path / 'scan_results.json'
        result = runner.invoke(main, ['scan', '--json-out', str(json_out),
                                       str(tmp_ndpi)])
        assert result.exit_code == 0
        assert json_out.exists()
        data = json.loads(json_out.read_text())
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]['is_clean'] is False

    def test_scan_clean_file(self, runner, tmp_ndpi_clean):
        result = runner.invoke(main, ['scan', '--verbose', str(tmp_ndpi_clean)])
        assert result.exit_code == 0
        assert 'clean' in result.output.lower()

    def test_scan_no_files_found(self, runner, tmp_path):
        empty = tmp_path / 'empty'
        empty.mkdir()
        result = runner.invoke(main, ['scan', str(empty)])
        assert result.exit_code == 0
        assert 'no wsi files' in result.output.lower()


# ──────────────────────────────────────────────────────────────────
# anonymize command
# ──────────────────────────────────────────────────────────────────

class TestAnonymizeCLI:
    def test_copy_mode(self, runner, tmp_ndpi, tmp_path):
        outdir = tmp_path / 'output'
        result = runner.invoke(main, ['anonymize', '--output', str(outdir),
                                       str(tmp_ndpi)])
        assert result.exit_code == 0
        assert 'cleared' in result.output.lower() or 'clean' in result.output.lower()
        # Output file should exist
        output_files = list(outdir.glob('*.ndpi'))
        assert len(output_files) == 1

    def test_inplace_mode(self, runner, tmp_ndpi):
        result = runner.invoke(main, ['anonymize', '--in-place', str(tmp_ndpi)])
        assert result.exit_code == 0

    def test_dry_run(self, runner, tmp_ndpi):
        original = tmp_ndpi.read_bytes()
        result = runner.invoke(main, ['anonymize', '--dry-run', str(tmp_ndpi)])
        assert result.exit_code == 0
        assert 'dry run' in result.output.lower()
        # File should not be modified
        assert tmp_ndpi.read_bytes() == original

    def test_no_output_no_inplace_errors(self, runner, tmp_ndpi):
        """Must specify --output or --in-place."""
        result = runner.invoke(main, ['anonymize', str(tmp_ndpi)])
        assert result.exit_code == 1
        assert 'error' in result.output.lower()

    def test_with_certificate(self, runner, tmp_ndpi, tmp_path):
        outdir = tmp_path / 'output'
        cert_path = tmp_path / 'cert.json'
        result = runner.invoke(main, [
            'anonymize', '--output', str(outdir),
            '--certificate', str(cert_path),
            str(tmp_ndpi)])
        assert result.exit_code == 0
        assert cert_path.exists()
        data = json.loads(cert_path.read_text())
        assert 'pathsafe_version' in data

    def test_no_verify(self, runner, tmp_ndpi, tmp_path):
        outdir = tmp_path / 'output'
        result = runner.invoke(main, [
            'anonymize', '--output', str(outdir),
            '--no-verify', str(tmp_ndpi)])
        assert result.exit_code == 0

    def test_format_filter(self, runner, tmp_ndpi, tmp_svs, tmp_path):
        indir = tmp_path / 'input'
        indir.mkdir()
        shutil.copy2(str(tmp_ndpi), str(indir / 'slide.ndpi'))
        shutil.copy2(str(tmp_svs), str(indir / 'slide.svs'))

        outdir = tmp_path / 'output'
        result = runner.invoke(main, [
            'anonymize', '--output', str(outdir),
            '--format', 'ndpi', str(indir)])
        assert result.exit_code == 0
        assert '1 file(s)' in result.output

    def test_with_log_file(self, runner, tmp_ndpi, tmp_path):
        outdir = tmp_path / 'output'
        log_path = tmp_path / 'anon.log'
        result = runner.invoke(main, [
            'anonymize', '--output', str(outdir),
            '--log', str(log_path),
            str(tmp_ndpi)])
        assert result.exit_code == 0
        assert log_path.exists()
        log_content = log_path.read_text()
        assert len(log_content) > 0

    def test_anonymize_directory(self, runner, tmp_ndpi, tmp_svs, tmp_path):
        indir = tmp_path / 'input'
        indir.mkdir()
        shutil.copy2(str(tmp_ndpi), str(indir / 'slide.ndpi'))
        shutil.copy2(str(tmp_svs), str(indir / 'slide.svs'))

        outdir = tmp_path / 'output'
        result = runner.invoke(main, [
            'anonymize', '--output', str(outdir), str(indir)])
        assert result.exit_code == 0
        assert 'total' in result.output.lower()

    def test_no_reset_timestamps(self, runner, tmp_ndpi, tmp_path):
        outdir = tmp_path / 'output'
        result = runner.invoke(main, [
            'anonymize', '--output', str(outdir),
            '--no-reset-timestamps', str(tmp_ndpi)])
        assert result.exit_code == 0


# ──────────────────────────────────────────────────────────────────
# verify command
# ──────────────────────────────────────────────────────────────────

class TestVerifyCLI:
    def test_verify_clean_file(self, runner, tmp_ndpi_clean):
        result = runner.invoke(main, ['verify', str(tmp_ndpi_clean)])
        assert result.exit_code == 0
        assert 'clean' in result.output.lower()

    def test_verify_dirty_file(self, runner, tmp_ndpi):
        result = runner.invoke(main, ['verify', str(tmp_ndpi)])
        assert result.exit_code == 1
        assert 'phi' in result.output.lower()

    def test_verify_verbose(self, runner, tmp_ndpi):
        result = runner.invoke(main, ['verify', '--verbose', str(tmp_ndpi)])
        assert result.exit_code == 1

    def test_verify_format_filter(self, runner, tmp_ndpi, tmp_svs, tmp_path):
        indir = tmp_path / 'vdir'
        indir.mkdir()
        shutil.copy2(str(tmp_ndpi), str(indir / 'slide.ndpi'))
        shutil.copy2(str(tmp_svs), str(indir / 'slide.svs'))

        result = runner.invoke(main, ['verify', '--format', 'ndpi', str(indir)])
        # Should only verify the NDPI file
        assert '1 file(s)' in result.output

    def test_verify_no_files(self, runner, tmp_path):
        empty = tmp_path / 'empty'
        empty.mkdir()
        result = runner.invoke(main, ['verify', str(empty)])
        assert 'no wsi files' in result.output.lower()

    def test_verify_after_anonymize(self, runner, tmp_ndpi, tmp_path):
        outdir = tmp_path / 'output'
        runner.invoke(main, ['anonymize', '--output', str(outdir),
                              str(tmp_ndpi)])
        output_file = list(outdir.glob('*.ndpi'))[0]
        result = runner.invoke(main, ['verify', str(output_file)])
        assert result.exit_code == 0
        assert 'clean' in result.output.lower()


# ──────────────────────────────────────────────────────────────────
# info command
# ──────────────────────────────────────────────────────────────────

class TestInfoCLI:
    def test_info_ndpi(self, runner, tmp_ndpi):
        result = runner.invoke(main, ['info', str(tmp_ndpi)])
        assert result.exit_code == 0
        assert 'ndpi' in result.output.lower()
        assert 'format' in result.output.lower()

    def test_info_svs(self, runner, tmp_svs):
        result = runner.invoke(main, ['info', str(tmp_svs)])
        assert result.exit_code == 0
        assert 'svs' in result.output.lower()

    def test_info_directory_errors(self, runner, tmp_path):
        result = runner.invoke(main, ['info', str(tmp_path)])
        assert result.exit_code == 1
        assert 'error' in result.output.lower()


# ──────────────────────────────────────────────────────────────────
# version
# ──────────────────────────────────────────────────────────────────

class TestVersionCLI:
    def test_version(self, runner):
        result = runner.invoke(main, ['--version'])
        assert result.exit_code == 0
        assert 'pathsafe' in result.output.lower()
