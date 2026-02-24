"""Round-trip consistency tests — structural validity after anonymization.

Verifies that anonymized files remain structurally valid: TIFF header intact,
IFDs parseable, dimensions preserved, strip/tile data intact for main images,
byte order preserved.

All tests use synthetic temporary files — no original WSI images are touched.
"""

import struct
import pytest
from pathlib import Path

from pathsafe.tiff import (
    read_header, iter_ifds, read_tag_string, read_tag_numeric,
    compute_ifd_tile_hash, compute_image_hashes,
    is_ifd_image_blanked, get_ifd_image_size,
)
from pathsafe.formats import get_handler
from pathsafe.anonymizer import anonymize_file
from tests.conftest import build_tiff, build_tiff_with_strips, build_tiff_multi_ifd


class TestNDPIRoundTrip:
    """NDPI files remain valid TIFF after anonymization."""

    def test_header_preserved(self, tmp_ndpi):
        with open(tmp_ndpi, 'rb') as f:
            before = read_header(f)

        handler = get_handler(tmp_ndpi)
        handler.anonymize(tmp_ndpi)

        with open(tmp_ndpi, 'rb') as f:
            after = read_header(f)

        assert after is not None
        assert after.endian == before.endian
        assert after.is_bigtiff == before.is_bigtiff
        assert after.first_ifd_offset == before.first_ifd_offset

    def test_ifd_parseable(self, tmp_ndpi):
        handler = get_handler(tmp_ndpi)
        handler.anonymize(tmp_ndpi)

        with open(tmp_ndpi, 'rb') as f:
            header = read_header(f)
            ifds = iter_ifds(f, header)
            assert len(ifds) >= 1
            for _, entries in ifds:
                assert len(entries) > 0

    def test_dimensions_preserved(self, tmp_ndpi):
        with open(tmp_ndpi, 'rb') as f:
            header = read_header(f)
            ifds = iter_ifds(f, header)
            before_dims = []
            for _, entries in ifds:
                w, h = get_ifd_image_size(header, entries, f)
                before_dims.append((w, h))

        handler = get_handler(tmp_ndpi)
        handler.anonymize(tmp_ndpi)

        with open(tmp_ndpi, 'rb') as f:
            header = read_header(f)
            ifds = iter_ifds(f, header)
            after_dims = []
            for _, entries in ifds:
                w, h = get_ifd_image_size(header, entries, f)
                after_dims.append((w, h))

        assert before_dims == after_dims

    def test_format_info_works_after_anonymize(self, tmp_ndpi):
        handler = get_handler(tmp_ndpi)
        handler.anonymize(tmp_ndpi)
        info = handler.get_format_info(tmp_ndpi)
        assert info['format'] == 'ndpi'
        assert info['file_size'] > 0


class TestSVSRoundTrip:
    """SVS files remain valid TIFF after anonymization."""

    def test_header_preserved(self, tmp_svs):
        with open(tmp_svs, 'rb') as f:
            before = read_header(f)

        handler = get_handler(tmp_svs)
        handler.anonymize(tmp_svs)

        with open(tmp_svs, 'rb') as f:
            after = read_header(f)

        assert after is not None
        assert after.endian == before.endian

    def test_ifd_parseable(self, tmp_svs):
        handler = get_handler(tmp_svs)
        handler.anonymize(tmp_svs)

        with open(tmp_svs, 'rb') as f:
            header = read_header(f)
            ifds = iter_ifds(f, header)
            assert len(ifds) >= 1

    def test_format_info_works(self, tmp_svs):
        handler = get_handler(tmp_svs)
        handler.anonymize(tmp_svs)
        info = handler.get_format_info(tmp_svs)
        assert info['format'] == 'svs'
        assert info['file_size'] > 0


class TestBIFRoundTrip:
    """BIF files remain valid TIFF after anonymization."""

    def test_header_preserved(self, tmp_bif):
        handler = get_handler(tmp_bif)
        handler.anonymize(tmp_bif)

        with open(tmp_bif, 'rb') as f:
            header = read_header(f)
        assert header is not None

    def test_ifd_parseable(self, tmp_bif):
        handler = get_handler(tmp_bif)
        handler.anonymize(tmp_bif)

        with open(tmp_bif, 'rb') as f:
            header = read_header(f)
            ifds = iter_ifds(f, header)
            assert len(ifds) >= 1


class TestSCNRoundTrip:
    """SCN files remain valid TIFF after anonymization."""

    def test_header_preserved(self, tmp_scn):
        handler = get_handler(tmp_scn)
        handler.anonymize(tmp_scn)

        with open(tmp_scn, 'rb') as f:
            header = read_header(f)
        assert header is not None

    def test_xml_structure_preserved(self, tmp_scn):
        """XML in ImageDescription should still be well-formed after anonymization."""
        handler = get_handler(tmp_scn)
        handler.anonymize(tmp_scn)

        with open(tmp_scn, 'rb') as f:
            header = read_header(f)
            ifds = iter_ifds(f, header)
            for _, entries in ifds:
                for entry in entries:
                    if entry.tag_id == 270:
                        value = read_tag_string(f, entry)
                        if '<' in value:
                            # Basic well-formedness check
                            assert '<?xml' in value or '<scn' in value
                            assert '</scn>' in value


class TestMRXSRoundTrip:
    """MRXS companion files remain valid after anonymization."""

    def test_slidedat_still_parseable(self, tmp_mrxs):
        handler = get_handler(tmp_mrxs)
        handler.anonymize(tmp_mrxs)

        slidedat = tmp_mrxs.parent / tmp_mrxs.stem / 'Slidedat.ini'
        assert slidedat.exists()
        content = slidedat.read_text()
        assert '[GENERAL]' in content
        assert 'SLIDE_ID' in content


class TestGenericTIFFRoundTrip:
    """Generic TIFF files remain valid after anonymization."""

    def test_header_preserved(self, tmp_tiff_with_phi):
        handler = get_handler(tmp_tiff_with_phi)
        handler.anonymize(tmp_tiff_with_phi)

        with open(tmp_tiff_with_phi, 'rb') as f:
            header = read_header(f)
        assert header is not None

    def test_dimensions_preserved(self, tmp_tiff_with_phi):
        with open(tmp_tiff_with_phi, 'rb') as f:
            header = read_header(f)
            ifds = iter_ifds(f, header)
            before_dims = [(get_ifd_image_size(header, e, f)) for _, e in ifds]

        handler = get_handler(tmp_tiff_with_phi)
        handler.anonymize(tmp_tiff_with_phi)

        with open(tmp_tiff_with_phi, 'rb') as f:
            header = read_header(f)
            ifds = iter_ifds(f, header)
            after_dims = [(get_ifd_image_size(header, e, f)) for _, e in ifds]

        assert before_dims == after_dims


class TestStripDataIntegrity:
    """Strip/tile data preserved for main image IFDs after anonymization."""

    def test_strip_data_unchanged(self, tmp_path):
        """Strip data hash should match before and after anonymization
        when the strip data itself has no PHI."""
        strip_data = b'\xAB\xCD\xEF' * 100
        desc = b'some metadata with date 2024:06:15\x00'
        tag_entries = [
            (256, 3, 1, 64),
            (257, 3, 1, 64),
            (270, 2, len(desc), desc),
        ]
        f = tmp_path / 'strip_integrity.tif'
        f.write_bytes(build_tiff_with_strips(tag_entries, strip_data))

        # Hash before
        pre_hashes = compute_image_hashes(f)
        assert len(pre_hashes) > 0

        # Anonymize (metadata cleared, strip data untouched)
        handler = get_handler(f)
        handler.anonymize(f)

        # Hash after
        post_hashes = compute_image_hashes(f)
        assert len(post_hashes) > 0

        # Compare
        for ifd_offset in pre_hashes:
            assert ifd_offset in post_hashes
            assert pre_hashes[ifd_offset] == post_hashes[ifd_offset], \
                f"Strip data hash mismatch at IFD offset {ifd_offset}"

    def test_strip_data_hash_deterministic(self, tmp_tiff_with_strips):
        """Same file hashed twice should produce identical results."""
        h1 = compute_image_hashes(tmp_tiff_with_strips)
        h2 = compute_image_hashes(tmp_tiff_with_strips)
        assert h1 == h2


class TestMultiIFDRoundTrip:
    """Multi-IFD files remain valid after anonymization."""

    def test_all_ifds_parseable(self, tmp_tiff_multi_ifd):
        handler = get_handler(tmp_tiff_multi_ifd)
        handler.anonymize(tmp_tiff_multi_ifd)

        with open(tmp_tiff_multi_ifd, 'rb') as f:
            header = read_header(f)
            ifds = iter_ifds(f, header)
            assert len(ifds) == 2
            for _, entries in ifds:
                assert len(entries) > 0

    def test_both_ifds_datetime_cleared(self, tmp_tiff_multi_ifd):
        """Both IFDs should have DateTime cleared."""
        handler = get_handler(tmp_tiff_multi_ifd)
        handler.anonymize(tmp_tiff_multi_ifd)

        with open(tmp_tiff_multi_ifd, 'rb') as f:
            header = read_header(f)
            ifds = iter_ifds(f, header)
            for _, entries in ifds:
                for entry in entries:
                    if entry.tag_id == 306:  # DateTime
                        value = read_tag_string(f, entry)
                        assert value.strip('\x00') == '', \
                            f"DateTime not cleared: '{value}'"


class TestByteOrderRoundTrip:
    """Byte order preserved through anonymization."""

    def test_little_endian_preserved(self, tmp_path):
        desc = b'AS-24-111222\x00'
        entries = [(256, 3, 1, 512), (270, 2, len(desc), desc)]
        f = tmp_path / 'le.tif'
        f.write_bytes(build_tiff(entries, endian='<'))

        handler = get_handler(f)
        handler.anonymize(f)

        with open(f, 'rb') as fh:
            header = read_header(fh)
        assert header.endian == '<'

    def test_big_endian_preserved(self, tmp_path):
        desc = b'AS-24-111222\x00'
        entries = [(256, 3, 1, 512), (270, 2, len(desc), desc)]
        f = tmp_path / 'be.tif'
        f.write_bytes(build_tiff(entries, endian='>'))

        handler = get_handler(f)
        handler.anonymize(f)

        with open(f, 'rb') as fh:
            header = read_header(fh)
        assert header.endian == '>'


class TestFileSize:
    """File size should not change after anonymization (in-place modification)."""

    def test_ndpi_size_unchanged(self, tmp_ndpi):
        size_before = tmp_ndpi.stat().st_size
        handler = get_handler(tmp_ndpi)
        handler.anonymize(tmp_ndpi)
        size_after = tmp_ndpi.stat().st_size
        assert size_before == size_after

    def test_svs_size_unchanged(self, tmp_svs):
        size_before = tmp_svs.stat().st_size
        handler = get_handler(tmp_svs)
        handler.anonymize(tmp_svs)
        size_after = tmp_svs.stat().st_size
        assert size_before == size_after

    def test_bif_size_unchanged(self, tmp_bif):
        size_before = tmp_bif.stat().st_size
        handler = get_handler(tmp_bif)
        handler.anonymize(tmp_bif)
        size_after = tmp_bif.stat().st_size
        assert size_before == size_after

    def test_scn_size_unchanged(self, tmp_scn):
        size_before = tmp_scn.stat().st_size
        handler = get_handler(tmp_scn)
        handler.anonymize(tmp_scn)
        size_after = tmp_scn.stat().st_size
        assert size_before == size_after

    def test_generic_tiff_size_unchanged(self, tmp_tiff_with_phi):
        size_before = tmp_tiff_with_phi.stat().st_size
        handler = get_handler(tmp_tiff_with_phi)
        handler.anonymize(tmp_tiff_with_phi)
        size_after = tmp_tiff_with_phi.stat().st_size
        assert size_before == size_after
