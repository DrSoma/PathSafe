"""Tests for the transfer module -- basic tests with mocked subprocess.

Tests TransferConfig creation, rsync command building, and clear error
messages when rsync is not installed.
"""

from unittest.mock import MagicMock, patch

import pytest

from pathsafe.transfer import (
    TransferConfig,
    _build_rsync_cmd,
    _parse_remote,
    _require_rsync,
    transfer_batch,
    verify_transfer,
)


# ---------------------------------------------------------------------------
# TransferConfig creation and validation
# ---------------------------------------------------------------------------


class TestTransferConfig:
    def test_basic_config(self):
        config = TransferConfig(remote="user@host:/data/slides/")
        assert config.remote == "user@host:/data/slides/"
        assert config.ssh_key is None
        assert config.bwlimit is None
        assert config.dry_run is False
        assert config.verify is True

    def test_config_with_all_options(self, tmp_path):
        key_file = tmp_path / "id_rsa"
        key_file.write_text("fake key")

        config = TransferConfig(
            remote="user@host:/data/",
            ssh_key=key_file,
            bwlimit=5000,
            dry_run=True,
            verify=False,
        )
        assert config.ssh_key == key_file
        assert config.bwlimit == 5000
        assert config.dry_run is True
        assert config.verify is False


# ---------------------------------------------------------------------------
# Remote string parsing
# ---------------------------------------------------------------------------


class TestParseRemote:
    def test_user_host_path(self):
        host, path = _parse_remote("user@host:/data/slides/")
        assert host == "user@host"
        assert path == "/data/slides/"

    def test_host_path_only(self):
        host, path = _parse_remote("myserver:/backup/")
        assert host == "myserver"
        assert path == "/backup/"

    def test_invalid_no_colon(self):
        with pytest.raises(ValueError, match="Invalid remote format"):
            _parse_remote("invalid_remote_string")


# ---------------------------------------------------------------------------
# Rsync command building
# ---------------------------------------------------------------------------


class TestBuildRsyncCmd:
    @patch("pathsafe.transfer._require_rsync", return_value="/usr/bin/rsync")
    def test_basic_command(self, mock_rsync, tmp_path):
        source = tmp_path / "output"
        source.mkdir()

        config = TransferConfig(remote="user@host:/data/")
        cmd = _build_rsync_cmd(source, config)

        assert cmd[0] == "/usr/bin/rsync"
        assert "-avz" in cmd
        assert "--progress" in cmd
        assert "--partial" in cmd
        assert "user@host:/data/" in cmd
        assert cmd[-2].endswith("/")  # source dir trailing slash

    @patch("pathsafe.transfer._require_rsync", return_value="/usr/bin/rsync")
    def test_command_with_bwlimit(self, mock_rsync, tmp_path):
        source = tmp_path / "output"
        source.mkdir()

        config = TransferConfig(remote="user@host:/data/", bwlimit=1000)
        cmd = _build_rsync_cmd(source, config)

        assert "--bwlimit=1000" in cmd

    @patch("pathsafe.transfer._require_rsync", return_value="/usr/bin/rsync")
    def test_command_with_dry_run(self, mock_rsync, tmp_path):
        source = tmp_path / "output"
        source.mkdir()

        config = TransferConfig(remote="user@host:/data/", dry_run=True)
        cmd = _build_rsync_cmd(source, config)

        assert "--dry-run" in cmd

    @patch("pathsafe.transfer._require_rsync", return_value="/usr/bin/rsync")
    def test_command_with_ssh_key(self, mock_rsync, tmp_path):
        source = tmp_path / "output"
        source.mkdir()
        key_file = tmp_path / "id_rsa"
        key_file.write_text("fake key")

        config = TransferConfig(
            remote="user@host:/data/",
            ssh_key=key_file,
        )
        cmd = _build_rsync_cmd(source, config)

        # Find the -e flag and check SSH key is included
        assert "-e" in cmd
        e_idx = cmd.index("-e")
        ssh_arg = cmd[e_idx + 1]
        assert str(key_file) in ssh_arg


# ---------------------------------------------------------------------------
# Rsync missing gives clear error
# ---------------------------------------------------------------------------


class TestRsyncMissing:
    @patch("shutil.which", return_value=None)
    def test_require_rsync_raises(self, mock_which):
        with pytest.raises(RuntimeError, match="rsync is not installed"):
            _require_rsync()

    @patch("shutil.which", return_value=None)
    def test_transfer_batch_rsync_missing(self, mock_which, tmp_path):
        """transfer_batch should raise when rsync is not on PATH."""
        source = tmp_path / "output"
        source.mkdir()
        (source / "slide.ndpi").write_bytes(b"fake data")

        config = TransferConfig(remote="user@host:/data/")

        with pytest.raises(RuntimeError, match="rsync"):
            transfer_batch(source, config)


# ---------------------------------------------------------------------------
# Transfer batch with mock subprocess
# ---------------------------------------------------------------------------


class TestTransferBatch:
    @patch("pathsafe.transfer._require_rsync", return_value="/usr/bin/rsync")
    @patch("pathsafe.transfer._require_ssh", return_value="/usr/bin/ssh")
    def test_transfer_empty_directory(self, mock_ssh, mock_rsync, tmp_path):
        source = tmp_path / "empty_output"
        source.mkdir()

        config = TransferConfig(remote="user@host:/data/", verify=False)
        result = transfer_batch(source, config)

        assert result.files_transferred == 0
        assert result.verified is True

    def test_transfer_source_not_exists(self, tmp_path):
        config = TransferConfig(remote="user@host:/data/")
        with pytest.raises(FileNotFoundError):
            transfer_batch(tmp_path / "nonexistent", config)

    @patch("pathsafe.transfer._require_rsync", return_value="/usr/bin/rsync")
    @patch("subprocess.Popen")
    def test_transfer_with_progress(self, mock_popen, mock_rsync, tmp_path):
        source = tmp_path / "output"
        source.mkdir()
        (source / "slide.ndpi").write_bytes(b"fake data")

        # Mock the subprocess
        mock_proc = MagicMock()
        mock_proc.stdout.readline = MagicMock(side_effect=[""])
        mock_proc.stdout.__iter__ = MagicMock(return_value=iter([]))
        mock_proc.stderr = MagicMock()
        mock_proc.stderr.read.return_value = ""
        mock_proc.returncode = 0
        mock_proc.wait.return_value = 0
        mock_popen.return_value = mock_proc

        config = TransferConfig(remote="user@host:/data/", verify=False)

        progress_calls = []

        def on_progress(files_done, total_files, pct):
            progress_calls.append((files_done, total_files, pct))

        result = transfer_batch(source, config, progress_callback=on_progress)

        assert result.errors == [] or len(result.errors) == 0
        assert mock_popen.called


# ---------------------------------------------------------------------------
# Verify transfer
# ---------------------------------------------------------------------------


class TestVerifyTransfer:
    @patch("pathsafe.transfer._require_ssh", return_value="/usr/bin/ssh")
    @patch("pathsafe.transfer._remote_sha256", return_value=None)
    def test_verify_fails_when_remote_unreachable(self, mock_remote, mock_ssh, tmp_path):
        source = tmp_path / "output"
        source.mkdir()
        (source / "slide.ndpi").write_bytes(b"test data for hashing")

        config = TransferConfig(remote="user@host:/data/")
        results = verify_transfer(source, config)

        # Remote unreachable means verification fails
        assert "slide.ndpi" in results
        assert results["slide.ndpi"] is False
