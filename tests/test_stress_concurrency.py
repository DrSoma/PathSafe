"""Stress tests — batch concurrency, thread pool edge cases, partial failures."""

import pytest
from pathlib import Path

from pathsafe.anonymizer import anonymize_batch, scan_batch, collect_wsi_files
from tests.conftest import build_tiff


def _make_ndpi(tmp_path, name, phi=True):
    """Create a synthetic NDPI file for batch testing."""
    if phi:
        barcode = b'AS-24-123456\x00'
    else:
        barcode = b'XXXXXXXXXXXX\x00'
    entries = [
        (256, 3, 1, 1024),
        (257, 3, 1, 768),
        (65468, 2, len(barcode), barcode),
    ]
    content = build_tiff(entries)
    filepath = tmp_path / name
    filepath.write_bytes(content)
    return filepath


def _make_svs(tmp_path, name):
    """Create a synthetic SVS file for batch testing."""
    desc = (
        b'Aperio Image Library v12.0.16\n'
        b'1024x768 [0,0 1024x768] (256x256) JPEG Q=70'
        b'|ScanScope ID = SS1234'
        b'|Filename = test.svs'
        b'|Date = 06/15/24'
        b'|Time = 10:30:00'
        b'\x00'
    )
    entries = [
        (256, 3, 1, 1024),
        (257, 3, 1, 768),
        (270, 2, len(desc), desc),
    ]
    content = build_tiff(entries)
    filepath = tmp_path / name
    filepath.write_bytes(content)
    return filepath


def _make_bif(tmp_path, name):
    """Create a synthetic BIF file for batch testing."""
    xmp = (
        b'<?xpacket begin="" id="W5M0MpCehiHzreSzNTczkc9d"?>'
        b'<x:xmpmeta xmlns:x="adobe:ns:meta/">'
        b'<iScan BarCode1="AS-24-111111" ScanDate="2024-06-15"/>'
        b'</x:xmpmeta>'
        b'<?xpacket end="w"?>\x00'
    )
    entries = [
        (256, 3, 1, 1024),
        (257, 3, 1, 768),
        (700, 7, len(xmp), xmp),
    ]
    content = build_tiff(entries)
    filepath = tmp_path / name
    filepath.write_bytes(content)
    return filepath


def _make_scn(tmp_path, name):
    """Create a synthetic SCN file for batch testing."""
    xml = (
        b'<?xml version="1.0" encoding="UTF-8"?>'
        b'<scn xmlns="http://www.leica-microsystems.com/scn/2010/10/01">'
        b'<collection>'
        b'<barcode>AS-24-222222</barcode>'
        b'</collection>'
        b'</scn>\x00'
    )
    entries = [
        (256, 3, 1, 1024),
        (257, 3, 1, 768),
        (270, 2, len(xml), xml),
    ]
    content = build_tiff(entries)
    filepath = tmp_path / name
    filepath.write_bytes(content)
    return filepath


class TestBatchWorkerEdgeCases:
    """Test thread pool behavior with unusual worker/file counts."""

    def test_workers_exceed_files(self, tmp_path):
        """workers=4 with only 1 file — should still process correctly."""
        _make_ndpi(tmp_path, 'single.ndpi')
        result = anonymize_batch(tmp_path, workers=4)
        assert result.total_files == 1
        assert result.files_anonymized == 1
        assert result.files_errored == 0

    def test_many_workers_few_files(self, tmp_path):
        """workers=8 with only 3 files — should still work."""
        for i in range(3):
            _make_ndpi(tmp_path, f'slide_{i}.ndpi')
        result = anonymize_batch(tmp_path, workers=8)
        assert result.total_files == 3
        assert result.files_anonymized == 3

    def test_sequential_fallback_single_file(self, tmp_path):
        """workers=4 with total=1 uses sequential path (workers>1 but total<=1)."""
        _make_ndpi(tmp_path, 'solo.ndpi')
        result = anonymize_batch(tmp_path, workers=4)
        assert result.total_files == 1
        assert result.files_anonymized == 1


class TestProgressCallback:
    """Test progress callback behavior."""

    def test_callback_args(self, tmp_path):
        """Callback receives (index, total, filepath, result)."""
        _make_ndpi(tmp_path, 'test.ndpi')
        calls = []

        def cb(index, total, filepath, result):
            calls.append((index, total, filepath, result))

        anonymize_batch(tmp_path, progress_callback=cb, workers=1)
        assert len(calls) == 1
        idx, total, fp, res = calls[0]
        assert idx == 1
        assert total == 1
        assert fp.suffix == '.ndpi'
        assert res.error is None

    def test_parallel_callback_totals(self, tmp_path):
        """Parallel callbacks should all report correct total."""
        for i in range(5):
            _make_ndpi(tmp_path, f'slide_{i}.ndpi')
        calls = []

        def cb(index, total, filepath, result):
            calls.append((index, total))

        anonymize_batch(tmp_path, progress_callback=cb, workers=3)
        assert len(calls) == 5
        assert all(total == 5 for _, total in calls)

    def test_callback_exception_propagates(self, tmp_path):
        """A callback that raises should propagate (not silently swallowed)."""
        _make_ndpi(tmp_path, 'test.ndpi')

        def bad_cb(index, total, filepath, result):
            raise ValueError("callback crash")

        with pytest.raises(ValueError, match="callback crash"):
            anonymize_batch(tmp_path, progress_callback=bad_cb, workers=1)


class TestMixedFormatBatch:
    """Test batch processing with multiple format types."""

    def test_mixed_formats_parallel(self, tmp_path):
        """NDPI + SVS + BIF + SCN in parallel with workers=4."""
        _make_ndpi(tmp_path, 'slide.ndpi')
        _make_svs(tmp_path, 'slide.svs')
        _make_bif(tmp_path, 'slide.bif')
        _make_scn(tmp_path, 'slide.scn')
        result = anonymize_batch(tmp_path, workers=4)
        assert result.total_files == 4
        assert result.files_errored == 0
        assert result.files_anonymized == 4


class TestPartialFailureBatch:
    """Test batch with mix of valid and corrupt files."""

    def test_partial_success(self, tmp_path):
        """2 valid + 1 corrupt file — expect partial success."""
        _make_ndpi(tmp_path, 'good1.ndpi')
        _make_ndpi(tmp_path, 'good2.ndpi')
        # Create a corrupt file (invalid TIFF header)
        corrupt = tmp_path / 'bad.ndpi'
        corrupt.write_bytes(b'\x00' * 10)
        result = anonymize_batch(tmp_path, workers=2)
        assert result.total_files == 3
        assert result.files_anonymized == 2
        # Corrupt file is either errored or "clean" (no PHI found in garbled data)
        assert result.files_errored + result.files_already_clean >= 1


class TestSequentialBatches:
    """Test running batch twice on the same directory."""

    def test_second_run_sees_clean(self, tmp_path):
        """Second run should see files as already_clean."""
        for i in range(3):
            _make_ndpi(tmp_path, f'slide_{i}.ndpi')
        result1 = anonymize_batch(tmp_path, workers=2)
        assert result1.files_anonymized == 3

        result2 = anonymize_batch(tmp_path, workers=2)
        assert result2.files_already_clean == 3
        assert result2.files_anonymized == 0
