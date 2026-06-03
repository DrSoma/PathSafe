"""Fix C regression: in-place de-identification stages to a temp file and
atomically swaps it onto the original, instead of writing the (possibly
locked / cloud-synced / networked) original directly.

Guards:
- in-place actually removes PHI bytes from the original and leaves no orphan;
- a leftover staging file (a crashed run's full-PHI copy) is never re-ingested;
- multi-file MRXS is still de-identified directly in place (no staging swap).
"""

import os

import pytest

import pathsafe.deidentifier as D
from pathsafe.deidentifier import (
    PENDING_MARKER,
    collect_wsi_files,
    deidentify_batch,
    deidentify_file,
)
from tests.conftest import build_tiff


def _svs_with_phi(path):
    desc = (
        b"Aperio Image Library v12.0.16\n"
        b"1024x768 [0,0 1024x768] (256x256) JPEG Q=70"
        b"|Filename = AS-24-999999.svs"
        b"|User = jdoe@hospital.org"
        b"\x00"
    )
    entries = [(256, 3, 1, 1024), (257, 3, 1, 768), (270, 2, len(desc), desc)]
    path.write_bytes(build_tiff(entries))
    return path


def _ndpi_with_phi(path):
    barcode = b"AS-24-555555\x00"
    entries = [(256, 3, 1, 1024), (257, 3, 1, 768), (65468, 2, len(barcode), barcode)]
    path.write_bytes(build_tiff(entries))
    return path


class TestInPlaceStaging:
    def test_inplace_removes_phi_bytes_and_leaves_no_orphan(self, tmp_path):
        fp = _svs_with_phi(tmp_path / "slide.svs")
        assert b"AS-24-999999" in fp.read_bytes()  # PHI present before

        result = deidentify_file(fp, output_path=None)
        assert result.error is None
        assert result.mode == "inplace"
        assert result.findings_cleared > 0

        data = fp.read_bytes()
        assert b"AS-24-999999" not in data  # PHI gone from the ORIGINAL path
        assert b"jdoe@hospital.org" not in data
        assert list(tmp_path.glob("*" + PENDING_MARKER + "*")) == []  # no orphan

    def test_staging_orphan_not_collected_in_directory(self, tmp_path):
        orphan = tmp_path / ("slide" + PENDING_MARKER + ".svs")
        orphan.write_bytes(build_tiff([(256, 3, 1, 16), (257, 3, 1, 16)]))
        real = _svs_with_phi(tmp_path / "real.svs")

        collected = collect_wsi_files(tmp_path)
        assert orphan not in collected
        assert real in collected

    def test_staging_orphan_skipped_as_single_file(self, tmp_path):
        orphan = tmp_path / ("slide" + PENDING_MARKER + ".svs")
        orphan.write_bytes(build_tiff([(256, 3, 1, 16), (257, 3, 1, 16)]))
        assert collect_wsi_files(orphan) == []


class TestMRXSInPlaceStaysDirect:
    def test_mrxs_inplace_no_staging_swap(self, tmp_path):
        mrxs = tmp_path / "test_slide.mrxs"
        mrxs.write_bytes(b"MIRAX\x00")
        companion = tmp_path / "test_slide"
        companion.mkdir()
        (companion / "Slidedat.ini").write_text(
            "[GENERAL]\n"
            "SLIDE_ID = 12345\n"
            "SLIDE_NAME = Patient Smith\n"
            "SLIDE_BARCODE = AS-24-333333\n"
            "OBJECTIVE_MAGNIFICATION = 40\n"
            "[HIERARCHICAL]\n"
            "NONHIER_COUNT = 0\n",
            encoding="utf-8",
        )

        result = deidentify_file(mrxs, output_path=None)
        assert result.error is None
        assert result.mode == "inplace"
        # MRXS is de-identified directly in place -- no staging file/dir created.
        assert list(tmp_path.glob("*" + PENDING_MARKER + "*")) == []
        # Companion directory preserved (not consumed by a swap).
        assert (companion / "Slidedat.ini").exists()


class TestMRXSDetectorRobustness:
    """A single-file slide that coincidentally sits next to a directory named
    like its stem must NOT be mistaken for a multi-file MRXS slide (which would
    skip staging and revert in-place to writing the original directly)."""

    def test_svs_with_sibling_dir_still_stages(self, tmp_path):
        fp = _svs_with_phi(tmp_path / "slide.svs")
        ino_before = fp.stat().st_ino

        trap = tmp_path / "slide"  # coincidental sibling dir matching the stem
        trap.mkdir()
        trap_file = trap / "unrelated.txt"
        trap_file.write_text("keep me")
        os.utime(trap_file, (100_000, 100_000))

        result = deidentify_file(fp, output_path=None, reset_timestamps=True)
        assert result.error is None
        assert b"AS-24-999999" not in fp.read_bytes()  # PHI removed
        # Staging path was used (atomic swap -> new inode), not a direct write.
        assert fp.stat().st_ino != ino_before
        # The unrelated sibling dir was NOT treated as an MRXS companion:
        assert trap_file.read_text() == "keep me"
        assert trap_file.stat().st_mtime != 0  # timestamps not reset
        assert list(tmp_path.glob("*" + PENDING_MARKER + "*")) == []


class TestStagingCleanupOnInterrupt:
    def test_keyboardinterrupt_cleans_staging_and_leaves_original(self, tmp_path, monkeypatch):
        fp = _svs_with_phi(tmp_path / "slide.svs")
        original = fp.read_bytes()

        class _Boom:
            def deidentify(self, _p):
                raise KeyboardInterrupt()

        monkeypatch.setattr(D, "get_handler", lambda _fp: _Boom())

        with pytest.raises(KeyboardInterrupt):
            deidentify_file(fp, output_path=None)

        # The PHI-bearing staging copy must be cleaned up on interrupt...
        assert list(tmp_path.glob("*" + PENDING_MARKER + "*")) == []
        # ...and the original left byte-identical (never written in in-place mode).
        assert fp.read_bytes() == original

    def test_keyboardinterrupt_during_hashing_cleans_staging(self, tmp_path, monkeypatch):
        # An interrupt during the verify_integrity "hashing tiles" phase (which
        # runs on the PHI-bearing staging copy) must still clean it up.
        fp = _svs_with_phi(tmp_path / "slide.svs")
        original = fp.read_bytes()

        def _boom(_p):
            raise KeyboardInterrupt()

        monkeypatch.setattr("pathsafe.tiff.compute_image_hashes", _boom)

        with pytest.raises(KeyboardInterrupt):
            deidentify_file(fp, output_path=None, verify_integrity=True)

        assert list(tmp_path.glob("*" + PENDING_MARKER + "*")) == []
        assert fp.read_bytes() == original  # original untouched


class TestStaleOrphanSweep:
    def test_batch_sweeps_stale_orphan(self, tmp_path):
        real = _svs_with_phi(tmp_path / "real.svs")
        orphan = tmp_path / ("crashed" + PENDING_MARKER + ".svs")
        orphan.write_bytes(real.read_bytes())  # a crashed run's full-PHI copy
        assert orphan.exists()

        deidentify_batch(tmp_path, output_dir=None)

        assert not orphan.exists()  # swept before processing
        assert b"AS-24-999999" not in real.read_bytes()  # real slide de-identified

    def test_legit_name_with_marker_substring_is_collected(self, tmp_path):
        # A real slide whose name merely contains the marker substring (not as a
        # whole dotted component) must still be collected, not skipped.
        legit = _svs_with_phi(tmp_path / ("CASE" + PENDING_MARKER + "_2024.svs"))
        assert legit in collect_wsi_files(tmp_path)


class TestNDPICompanionHandling:
    """NDPI has .ndpa/.ndpis annotation sidecars (PHI) that the handler finds by
    the slide's own name and DELETES. Such slides must be de-identified directly
    in place (no staging), or staging would orphan the real PHI sidecars."""

    def test_inplace_with_ndpa_sidecar_deletes_sidecar(self, tmp_path):
        ndpi = _ndpi_with_phi(tmp_path / "slide.ndpi")
        sidecar = tmp_path / "slide.ndpi.ndpa"
        sidecar.write_text("<annotations><patient>MRN-7788991</patient></annotations>")
        assert sidecar.exists()

        result = deidentify_file(ndpi, output_path=None)
        assert result.error is None
        assert result.mode == "inplace"
        # The PHI annotation sidecar is removed (not orphaned by a staging rename).
        assert not sidecar.exists()
        assert b"AS-24-555555" not in ndpi.read_bytes()  # barcode PHI cleared
        assert list(tmp_path.glob("*" + PENDING_MARKER + "*")) == []

    def test_inplace_without_sidecar_is_staged(self, tmp_path):
        ndpi = _ndpi_with_phi(tmp_path / "slide.ndpi")
        ino_before = ndpi.stat().st_ino

        result = deidentify_file(ndpi, output_path=None)
        assert result.error is None
        assert b"AS-24-555555" not in ndpi.read_bytes()
        # No companion sidecars -> staged (atomic swap -> new inode).
        assert ndpi.stat().st_ino != ino_before
        assert list(tmp_path.glob("*" + PENDING_MARKER + "*")) == []
