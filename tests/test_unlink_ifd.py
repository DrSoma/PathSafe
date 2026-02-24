"""Tests for IFD unlinking — unlink_ifd() and handler integration."""

import struct
import pytest
from pathsafe.tiff import (
    read_header, read_ifd, iter_ifds, unlink_ifd,
    blank_ifd_image_data, is_ifd_image_blanked,
)
from tests.conftest import (
    build_tiff_multi_ifd, build_tiff_multi_ifd_with_strips,
    build_bigtiff_multi_ifd,
)


# ---------------------------------------------------------------------------
# Unit tests for unlink_ifd()
# ---------------------------------------------------------------------------

class TestUnlinkMiddleIFD:
    """Unlink the middle IFD from a 3-IFD chain."""

    def test_chain_skips_middle(self, tmp_path):
        dt1 = b'2024:01:01 00:00:00\x00'
        dt2 = b'2024:02:01 00:00:00\x00'
        dt3 = b'2024:03:01 00:00:00\x00'
        ifd0 = [(256, 3, 1, 100), (306, 2, len(dt1), dt1)]
        ifd1 = [(256, 3, 1, 200), (306, 2, len(dt2), dt2)]
        ifd2 = [(256, 3, 1, 300), (306, 2, len(dt3), dt3)]
        content = build_tiff_multi_ifd([ifd0, ifd1, ifd2])
        fp = tmp_path / 'three_ifd.tif'
        fp.write_bytes(content)

        # Read original chain to get offsets
        with open(fp, 'rb') as f:
            header = read_header(f)
            ifds = iter_ifds(f, header)
        assert len(ifds) == 3
        middle_offset = ifds[1][0]

        # Unlink the middle IFD
        with open(fp, 'r+b') as f:
            header = read_header(f)
            result = unlink_ifd(f, header, middle_offset)
        assert result is True

        # Verify chain now has 2 IFDs
        with open(fp, 'rb') as f:
            header = read_header(f)
            ifds = iter_ifds(f, header)
        assert len(ifds) == 2
        # First and third IFDs remain
        assert ifds[0][0] != middle_offset
        assert ifds[1][0] != middle_offset


class TestUnlinkFirstIFD:
    """Unlink the first IFD from a 3-IFD chain."""

    def test_header_points_to_second(self, tmp_path):
        dt1 = b'2024:01:01 00:00:00\x00'
        dt2 = b'2024:02:01 00:00:00\x00'
        dt3 = b'2024:03:01 00:00:00\x00'
        ifd0 = [(256, 3, 1, 100), (306, 2, len(dt1), dt1)]
        ifd1 = [(256, 3, 1, 200), (306, 2, len(dt2), dt2)]
        ifd2 = [(256, 3, 1, 300), (306, 2, len(dt3), dt3)]
        content = build_tiff_multi_ifd([ifd0, ifd1, ifd2])
        fp = tmp_path / 'three_ifd.tif'
        fp.write_bytes(content)

        with open(fp, 'rb') as f:
            header = read_header(f)
            ifds = iter_ifds(f, header)
        first_offset = ifds[0][0]
        second_offset = ifds[1][0]

        # Unlink first IFD
        with open(fp, 'r+b') as f:
            header = read_header(f)
            result = unlink_ifd(f, header, first_offset)
        assert result is True

        # Header should now point to second IFD
        with open(fp, 'rb') as f:
            header = read_header(f)
            assert header.first_ifd_offset == second_offset
            ifds = iter_ifds(f, header)
        assert len(ifds) == 2


class TestUnlinkLastIFD:
    """Unlink the last IFD from a 3-IFD chain."""

    def test_predecessor_next_is_zero(self, tmp_path):
        dt1 = b'2024:01:01 00:00:00\x00'
        dt2 = b'2024:02:01 00:00:00\x00'
        dt3 = b'2024:03:01 00:00:00\x00'
        ifd0 = [(256, 3, 1, 100), (306, 2, len(dt1), dt1)]
        ifd1 = [(256, 3, 1, 200), (306, 2, len(dt2), dt2)]
        ifd2 = [(256, 3, 1, 300), (306, 2, len(dt3), dt3)]
        content = build_tiff_multi_ifd([ifd0, ifd1, ifd2])
        fp = tmp_path / 'three_ifd.tif'
        fp.write_bytes(content)

        with open(fp, 'rb') as f:
            header = read_header(f)
            ifds = iter_ifds(f, header)
        last_offset = ifds[2][0]

        # Unlink last IFD
        with open(fp, 'r+b') as f:
            header = read_header(f)
            result = unlink_ifd(f, header, last_offset)
        assert result is True

        # Chain should now have 2 IFDs, second's next = 0
        with open(fp, 'rb') as f:
            header = read_header(f)
            ifds = iter_ifds(f, header)
        assert len(ifds) == 2
        # Read the second IFD's next pointer directly
        with open(fp, 'rb') as f:
            header = read_header(f)
            _, next_off = read_ifd(f, header, ifds[1][0])
        assert next_off == 0


class TestUnlinkAlreadyUnlinked:
    """Unlinking an already-unlinked IFD returns False."""

    def test_returns_false(self, tmp_path):
        dt1 = b'2024:01:01 00:00:00\x00'
        dt2 = b'2024:02:01 00:00:00\x00'
        ifd0 = [(256, 3, 1, 100), (306, 2, len(dt1), dt1)]
        ifd1 = [(256, 3, 1, 200), (306, 2, len(dt2), dt2)]
        content = build_tiff_multi_ifd([ifd0, ifd1])
        fp = tmp_path / 'two_ifd.tif'
        fp.write_bytes(content)

        with open(fp, 'rb') as f:
            header = read_header(f)
            ifds = iter_ifds(f, header)
        second_offset = ifds[1][0]

        # Unlink second IFD — first time succeeds
        with open(fp, 'r+b') as f:
            header = read_header(f)
            assert unlink_ifd(f, header, second_offset) is True

        # Second time — target is no longer in chain
        with open(fp, 'r+b') as f:
            header = read_header(f)
            assert unlink_ifd(f, header, second_offset) is False


class TestUnlinkBigTIFF:
    """Unlink IFD in BigTIFF format."""

    def test_unlink_middle_bigtiff(self, tmp_path):
        dt1 = b'2024:01:01 00:00:00\x00'
        dt2 = b'2024:02:01 00:00:00\x00'
        dt3 = b'2024:03:01 00:00:00\x00'
        ifd0 = [(256, 3, 1, 100), (306, 2, len(dt1), dt1)]
        ifd1 = [(256, 3, 1, 200), (306, 2, len(dt2), dt2)]
        ifd2 = [(256, 3, 1, 300), (306, 2, len(dt3), dt3)]
        content = build_bigtiff_multi_ifd([ifd0, ifd1, ifd2])
        fp = tmp_path / 'three_ifd.tif'
        fp.write_bytes(content)

        with open(fp, 'rb') as f:
            header = read_header(f)
            assert header.is_bigtiff
            ifds = iter_ifds(f, header)
        assert len(ifds) == 3
        middle_offset = ifds[1][0]

        with open(fp, 'r+b') as f:
            header = read_header(f)
            result = unlink_ifd(f, header, middle_offset)
        assert result is True

        with open(fp, 'rb') as f:
            header = read_header(f)
            ifds = iter_ifds(f, header)
        assert len(ifds) == 2

    def test_unlink_first_bigtiff(self, tmp_path):
        dt1 = b'2024:01:01 00:00:00\x00'
        dt2 = b'2024:02:01 00:00:00\x00'
        ifd0 = [(256, 3, 1, 100), (306, 2, len(dt1), dt1)]
        ifd1 = [(256, 3, 1, 200), (306, 2, len(dt2), dt2)]
        content = build_bigtiff_multi_ifd([ifd0, ifd1])
        fp = tmp_path / 'two_ifd.tif'
        fp.write_bytes(content)

        with open(fp, 'rb') as f:
            header = read_header(f)
            ifds = iter_ifds(f, header)
        first_offset = ifds[0][0]
        second_offset = ifds[1][0]

        with open(fp, 'r+b') as f:
            header = read_header(f)
            assert unlink_ifd(f, header, first_offset) is True

        with open(fp, 'rb') as f:
            header = read_header(f)
            assert header.first_ifd_offset == second_offset
            ifds = iter_ifds(f, header)
        assert len(ifds) == 1


# ---------------------------------------------------------------------------
# Handler integration tests — label/macro IFDs unlinked after anonymize
# ---------------------------------------------------------------------------

class TestNDPIUnlinksLabelMacro:
    """NDPI handler unlinks label/macro IFDs after blanking."""

    def _build_ndpi_with_label(self, tmp_path):
        """Build a synthetic NDPI with a main IFD and a macro (label) IFD."""
        barcode = b'AS-24-123456\x00'
        strip_data = b'\xFF\xD8\xFF\xE0' + b'\xAB' * 500  # Fake JPEG data

        # IFD0: main image (no strips for simplicity, has SOURCELENS = 0)
        ifd0_tags = [
            (256, 3, 1, 1024),
            (257, 3, 1, 768),
            (65468, 2, len(barcode), barcode),  # NDPI_BARCODE
        ]
        # IFD1: macro image (SOURCELENS = -1.0 float, has strip data)
        # -1.0 as FLOAT (type 11, 4 bytes): struct.pack('<f', -1.0) = b'\x00\x00\x80\xbf'
        sourcelens_val = struct.unpack('<I', struct.pack('<f', -1.0))[0]
        ifd1_tags = [
            (256, 3, 1, 128),
            (257, 3, 1, 96),
            (65421, 11, 1, sourcelens_val),  # NDPI_SOURCELENS = -1.0
        ]

        content = build_tiff_multi_ifd_with_strips(
            [(ifd0_tags, None), (ifd1_tags, strip_data)])
        fp = tmp_path / 'label_test.ndpi'
        fp.write_bytes(content)
        return fp

    def test_label_ifd_unlinked_after_anonymize(self, tmp_path):
        fp = self._build_ndpi_with_label(tmp_path)

        # Before: 2 IFDs
        with open(fp, 'rb') as f:
            header = read_header(f)
            ifds = iter_ifds(f, header)
        assert len(ifds) == 2

        from pathsafe.formats.ndpi import NDPIHandler
        handler = NDPIHandler()
        handler.anonymize(fp)

        # After: label IFD should be unlinked
        with open(fp, 'rb') as f:
            header = read_header(f)
            ifds = iter_ifds(f, header)
        assert len(ifds) == 1  # Only main IFD remains visible


class TestSVSUnlinksLabelMacro:
    """SVS handler unlinks label/macro IFDs after blanking."""

    def _build_svs_with_label(self, tmp_path):
        """Build SVS with a main IFD and label IFD."""
        desc_main = b'Aperio Image Library v12.0.16\n1024x768 (256x256) JPEG\x00'
        desc_label = b'label 128x96\x00'
        strip_data = b'\xFF\xD8\xFF\xE0' + b'\xAB' * 500

        ifd0_tags = [
            (256, 3, 1, 1024),
            (257, 3, 1, 768),
            (270, 2, len(desc_main), desc_main),
        ]
        ifd1_tags = [
            (256, 3, 1, 128),
            (257, 3, 1, 96),
            (270, 2, len(desc_label), desc_label),
        ]

        content = build_tiff_multi_ifd_with_strips(
            [(ifd0_tags, None), (ifd1_tags, strip_data)])
        fp = tmp_path / 'label_test.svs'
        fp.write_bytes(content)
        return fp

    def test_label_ifd_unlinked_after_anonymize(self, tmp_path):
        fp = self._build_svs_with_label(tmp_path)

        with open(fp, 'rb') as f:
            header = read_header(f)
            assert len(iter_ifds(f, header)) == 2

        from pathsafe.formats.svs import SVSHandler
        handler = SVSHandler()
        handler.anonymize(fp)

        with open(fp, 'rb') as f:
            header = read_header(f)
            ifds = iter_ifds(f, header)
        assert len(ifds) == 1


class TestBIFUnlinksLabelMacro:
    """BIF handler unlinks label/macro IFDs after blanking."""

    def _build_bif_with_label(self, tmp_path):
        """Build BIF with a main IFD and label IFD."""
        desc_label = b'Label Image\x00'
        strip_data = b'\xFF\xD8\xFF\xE0' + b'\xAB' * 500

        ifd0_tags = [
            (256, 3, 1, 1024),
            (257, 3, 1, 768),
        ]
        ifd1_tags = [
            (256, 3, 1, 128),
            (257, 3, 1, 96),
            (270, 2, len(desc_label), desc_label),
        ]

        content = build_tiff_multi_ifd_with_strips(
            [(ifd0_tags, None), (ifd1_tags, strip_data)])
        fp = tmp_path / 'label_test.bif'
        fp.write_bytes(content)
        return fp

    def test_label_ifd_unlinked_after_anonymize(self, tmp_path):
        fp = self._build_bif_with_label(tmp_path)

        with open(fp, 'rb') as f:
            header = read_header(f)
            assert len(iter_ifds(f, header)) == 2

        from pathsafe.formats.bif import BIFHandler
        handler = BIFHandler()
        handler.anonymize(fp)

        with open(fp, 'rb') as f:
            header = read_header(f)
            ifds = iter_ifds(f, header)
        assert len(ifds) == 1


class TestSCNUnlinksLabelMacro:
    """SCN handler unlinks label/macro IFDs after blanking."""

    def _build_scn_with_label(self, tmp_path):
        """Build SCN with a main IFD and label IFD."""
        desc_label = b'label 128x96\x00'
        strip_data = b'\xFF\xD8\xFF\xE0' + b'\xAB' * 500

        ifd0_tags = [
            (256, 3, 1, 1024),
            (257, 3, 1, 768),
        ]
        ifd1_tags = [
            (256, 3, 1, 128),
            (257, 3, 1, 96),
            (270, 2, len(desc_label), desc_label),
        ]

        content = build_tiff_multi_ifd_with_strips(
            [(ifd0_tags, None), (ifd1_tags, strip_data)])
        fp = tmp_path / 'label_test.scn'
        fp.write_bytes(content)
        return fp

    def test_label_ifd_unlinked_after_anonymize(self, tmp_path):
        fp = self._build_scn_with_label(tmp_path)

        with open(fp, 'rb') as f:
            header = read_header(f)
            assert len(iter_ifds(f, header)) == 2

        from pathsafe.formats.scn import SCNHandler
        handler = SCNHandler()
        handler.anonymize(fp)

        with open(fp, 'rb') as f:
            header = read_header(f)
            ifds = iter_ifds(f, header)
        assert len(ifds) == 1


class TestRerunUnlinksOldBlanked:
    """Re-running anonymize on an old (blanked-but-not-unlinked) file unlinks the IFD."""

    def test_rerun_unlinks(self, tmp_path):
        """Simulate old-style blanking (no unlink), then re-anonymize to unlink."""
        desc_label = b'label 128x96\x00'
        strip_data = b'\xFF\xD8\xFF\xE0' + b'\xAB' * 500

        ifd0_tags = [
            (256, 3, 1, 1024),
            (257, 3, 1, 768),
        ]
        ifd1_tags = [
            (256, 3, 1, 128),
            (257, 3, 1, 96),
            (270, 2, len(desc_label), desc_label),
        ]

        content = build_tiff_multi_ifd_with_strips(
            [(ifd0_tags, None), (ifd1_tags, strip_data)])
        fp = tmp_path / 'old_blanked.svs'
        fp.write_bytes(content)

        # Old-style blanking: blank the image but don't unlink
        with open(fp, 'r+b') as f:
            header = read_header(f)
            ifds = iter_ifds(f, header)
            assert len(ifds) == 2
            _, label_entries = ifds[1]
            blanked = blank_ifd_image_data(f, header, label_entries)
            assert blanked > 0

        # Verify it's blanked but still linked (2 IFDs)
        with open(fp, 'rb') as f:
            header = read_header(f)
            ifds = iter_ifds(f, header)
            assert len(ifds) == 2
            _, label_entries = ifds[1]
            assert is_ifd_image_blanked(f, header, label_entries)

        # Re-anonymize — should unlink the already-blanked label
        from pathsafe.formats.svs import SVSHandler
        handler = SVSHandler()
        handler.anonymize(fp)

        # Now only 1 IFD should be visible
        with open(fp, 'rb') as f:
            header = read_header(f)
            ifds = iter_ifds(f, header)
        assert len(ifds) == 1


class TestScanAfterUnlink:
    """After anonymize+unlink, scan reports clean (no label findings)."""

    def test_scan_clean_after_unlink(self, tmp_path):
        desc_label = b'label 128x96\x00'
        strip_data = b'\xFF\xD8\xFF\xE0' + b'\xAB' * 500

        ifd0_tags = [
            (256, 3, 1, 1024),
            (257, 3, 1, 768),
        ]
        ifd1_tags = [
            (256, 3, 1, 128),
            (257, 3, 1, 96),
            (270, 2, len(desc_label), desc_label),
        ]

        content = build_tiff_multi_ifd_with_strips(
            [(ifd0_tags, None), (ifd1_tags, strip_data)])
        fp = tmp_path / 'scan_test.svs'
        fp.write_bytes(content)

        from pathsafe.formats.svs import SVSHandler
        handler = SVSHandler()

        # Before: scan finds label
        result = handler.scan(fp)
        label_findings = [f for f in result.findings if f.tag_name == 'LabelImage']
        assert len(label_findings) > 0

        # Anonymize (blanks + unlinks)
        handler.anonymize(fp)

        # After: scan should find no label
        result = handler.scan(fp)
        label_findings = [f for f in result.findings if f.tag_name == 'LabelImage']
        assert len(label_findings) == 0
