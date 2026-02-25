"""Tests for the CLI interface."""

import json
import pytest
import pathsafe
from click.testing import CliRunner
from pathsafe.cli import main


@pytest.fixture
def runner():
    return CliRunner()


class TestVersion:
    def test_version(self, runner):
        result = runner.invoke(main, ['--version'])
        assert result.exit_code == 0
        assert pathsafe.__version__ in result.output


class TestScanCommand:
    def test_scan_ndpi(self, runner, tmp_ndpi):
        result = runner.invoke(main, ['scan', str(tmp_ndpi), '--verbose'])
        assert result.exit_code == 0
        assert 'finding' in result.output.lower()

    def test_scan_clean(self, runner, tmp_ndpi_clean):
        result = runner.invoke(main, ['scan', str(tmp_ndpi_clean), '--verbose'])
        assert result.exit_code == 0
        assert 'clean' in result.output.lower()

    def test_scan_json_output(self, runner, tmp_ndpi, tmp_path):
        json_file = tmp_path / 'results.json'
        result = runner.invoke(main, [
            'scan', str(tmp_ndpi), '--json-out', str(json_file)])
        assert result.exit_code == 0
        data = json.loads(json_file.read_text())
        assert len(data) == 1
        assert not data[0]['is_clean']

    def test_scan_directory(self, runner, tmp_ndpi):
        result = runner.invoke(main, ['scan', str(tmp_ndpi.parent)])
        assert result.exit_code == 0


class TestAnonymizeCommand:
    def test_requires_output_or_inplace(self, runner, tmp_ndpi):
        result = runner.invoke(main, ['anonymize', str(tmp_ndpi)])
        assert result.exit_code == 1
        assert 'must specify' in result.output.lower()

    def test_copy_mode(self, runner, tmp_ndpi, tmp_path):
        out_dir = tmp_path / 'output'
        result = runner.invoke(main, [
            'anonymize', str(tmp_ndpi), '--output', str(out_dir)])
        assert result.exit_code == 0
        assert 'anonymized' in result.output.lower()
        assert (out_dir / tmp_ndpi.name).exists()

    def test_inplace_mode(self, runner, tmp_ndpi):
        result = runner.invoke(main, [
            'anonymize', str(tmp_ndpi), '--in-place'])
        assert result.exit_code == 0

    def test_dry_run(self, runner, tmp_ndpi, tmp_path):
        out_dir = tmp_path / 'dry_output'
        result = runner.invoke(main, [
            'anonymize', str(tmp_ndpi), '--output', str(out_dir), '--dry-run'])
        assert result.exit_code == 0
        assert 'dry run' in result.output.lower()

    def test_certificate(self, runner, tmp_ndpi, tmp_path):
        out_dir = tmp_path / 'cert_output'
        cert_file = tmp_path / 'cert.json'
        result = runner.invoke(main, [
            'anonymize', str(tmp_ndpi),
            '--output', str(out_dir),
            '--certificate', str(cert_file)])
        assert result.exit_code == 0
        cert = json.loads(cert_file.read_text())
        assert cert['pathsafe_version'] == pathsafe.__version__
        assert cert['summary']['total_files'] == 1

    def test_workers(self, runner, tmp_ndpi, tmp_path):
        out_dir = tmp_path / 'parallel_output'
        result = runner.invoke(main, [
            'anonymize', str(tmp_ndpi),
            '--output', str(out_dir), '--workers', '2'])
        assert result.exit_code == 0


class TestAnonymizeTimestamps:
    def test_reset_timestamps(self, runner, tmp_ndpi, tmp_path):
        out_dir = tmp_path / 'ts_output'
        result = runner.invoke(main, [
            'anonymize', str(tmp_ndpi), '--output', str(out_dir),
            '--reset-timestamps'])
        assert result.exit_code == 0
        output_file = out_dir / tmp_ndpi.name
        assert output_file.exists()
        stat = output_file.stat()
        assert stat.st_mtime == 0
        assert stat.st_atime == 0

    def test_reset_timestamps_by_default(self, runner, tmp_ndpi, tmp_path):
        out_dir = tmp_path / 'nots_output'
        result = runner.invoke(main, [
            'anonymize', str(tmp_ndpi), '--output', str(out_dir)])
        assert result.exit_code == 0
        output_file = out_dir / tmp_ndpi.name
        assert output_file.stat().st_mtime == 0

    def test_no_reset_timestamps_flag(self, runner, tmp_ndpi, tmp_path):
        out_dir = tmp_path / 'nots_output2'
        result = runner.invoke(main, [
            'anonymize', str(tmp_ndpi), '--output', str(out_dir),
            '--no-reset-timestamps'])
        assert result.exit_code == 0
        output_file = out_dir / tmp_ndpi.name
        assert output_file.stat().st_mtime > 0


class TestCertificateMeasures:
    def test_certificate_includes_measures(self, runner, tmp_ndpi, tmp_path):
        out_dir = tmp_path / 'cert_measures'
        cert_file = tmp_path / 'cert_measures.json'
        result = runner.invoke(main, [
            'anonymize', str(tmp_ndpi),
            '--output', str(out_dir),
            '--certificate', str(cert_file)])
        assert result.exit_code == 0
        assert cert_file.exists()
        data = json.loads(cert_file.read_text())
        assert 'measures' in data
        assert data['summary']['total_files'] == 1
        measure_names = [m['measure'] for m in data['measures']]
        assert 'Filesystem timestamps reset' in measure_names

    def test_certificate_timestamps_measure(self, runner, tmp_ndpi, tmp_path):
        out_dir = tmp_path / 'cert_ts'
        cert_file = tmp_path / 'cert_ts.json'
        result = runner.invoke(main, [
            'anonymize', str(tmp_ndpi),
            '--output', str(out_dir),
            '--certificate', str(cert_file)])
        assert result.exit_code == 0
        data = json.loads(cert_file.read_text())
        ts_measure = [m for m in data['measures']
                      if 'timestamp' in m['measure'].lower()][0]
        assert ts_measure['status'] == 'applied'

    def test_certificate_not_generated_on_dry_run(self, runner, tmp_ndpi, tmp_path):
        out_dir = tmp_path / 'cert_dry'
        cert_file = tmp_path / 'cert_dry.json'
        result = runner.invoke(main, [
            'anonymize', str(tmp_ndpi),
            '--output', str(out_dir),
            '--dry-run',
            '--certificate', str(cert_file)])
        assert result.exit_code == 0
        assert not cert_file.exists()

    def test_all_flags_combined(self, runner, tmp_ndpi, tmp_path):
        out_dir = tmp_path / 'combined'
        cert_file = tmp_path / 'combined_cert.json'
        result = runner.invoke(main, [
            'anonymize', str(tmp_ndpi),
            '--output', str(out_dir),
            '--certificate', str(cert_file)])
        assert result.exit_code == 0
        output_file = out_dir / tmp_ndpi.name
        assert output_file.stat().st_mtime == 0
        assert cert_file.exists()
        data = json.loads(cert_file.read_text())
        assert 'measures' in data


class TestVerifyCommand:
    def test_verify_clean(self, runner, tmp_ndpi_clean):
        result = runner.invoke(main, ['verify', str(tmp_ndpi_clean)])
        assert result.exit_code == 0
        assert 'clean' in result.output.lower()

    def test_verify_dirty(self, runner, tmp_ndpi):
        result = runner.invoke(main, ['verify', str(tmp_ndpi)])
        assert result.exit_code == 1
        assert 'phi' in result.output.lower()


class TestInfoCommand:
    def test_info_ndpi(self, runner, tmp_ndpi):
        result = runner.invoke(main, ['info', str(tmp_ndpi)])
        assert result.exit_code == 0
        assert 'ndpi' in result.output.lower()

    def test_info_svs(self, runner, tmp_svs):
        result = runner.invoke(main, ['info', str(tmp_svs)])
        assert result.exit_code == 0
        assert 'svs' in result.output.lower()

    def test_info_directory_rejected(self, runner, tmp_path):
        result = runner.invoke(main, ['info', str(tmp_path)])
        assert result.exit_code == 1
