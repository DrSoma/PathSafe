"""Tests for the verification module."""

import pytest
from pathsafe.verify import verify_file, verify_batch


class TestVerifyFile:
    def test_clean_file(self, tmp_ndpi_clean):
        result = verify_file(tmp_ndpi_clean)
        assert result.is_clean
        assert result.error is None

    def test_dirty_file(self, tmp_ndpi):
        result = verify_file(tmp_ndpi)
        assert not result.is_clean
        assert len(result.findings) > 0

    def test_svs_clean_after_anonymize(self, tmp_svs):
        from pathsafe.formats.svs import SVSHandler
        handler = SVSHandler()
        handler.anonymize(tmp_svs)
        result = verify_file(tmp_svs)
        assert result.is_clean

    def test_ndpi_clean_after_anonymize(self, tmp_ndpi):
        from pathsafe.formats.ndpi import NDPIHandler
        handler = NDPIHandler()
        handler.anonymize(tmp_ndpi)
        result = verify_file(tmp_ndpi)
        assert result.is_clean


class TestVerifyBatch:
    def test_verify_batch_clean(self, tmp_ndpi_clean):
        results = verify_batch(tmp_ndpi_clean)
        assert len(results) == 1
        assert results[0].is_clean

    def test_verify_batch_dirty(self, tmp_ndpi):
        results = verify_batch(tmp_ndpi)
        assert len(results) == 1
        assert not results[0].is_clean

    def test_verify_batch_directory(self, tmp_ndpi, tmp_svs):
        results = verify_batch(tmp_ndpi.parent)
        assert len(results) >= 2

    def test_verify_batch_progress(self, tmp_ndpi_clean):
        calls = []

        def on_progress(index, total, filepath, result):
            calls.append((index, total))

        results = verify_batch(tmp_ndpi_clean, progress_callback=on_progress)
        assert len(calls) == 1

    def test_verify_batch_format_filter(self, tmp_ndpi, tmp_svs):
        results = verify_batch(tmp_ndpi.parent, format_filter='ndpi')
        for result in results:
            assert result.filepath.suffix.lower() == '.ndpi'
