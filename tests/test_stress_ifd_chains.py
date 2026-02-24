"""Stress tests -- large IFD chains (10-20 IFDs), unlink operations, circular detection."""

import io
import struct

import pytest

from pathsafe.tiff import read_header, iter_ifds, read_ifd, unlink_ifd
from tests.conftest import build_tiff_multi_ifd, build_bigtiff_multi_ifd


def _make_ifd_entries(index):
    """Create minimal IFD entries for chain tests."""
    return [
        (256, 3, 1, 64 * (index + 1)),  # ImageWidth -- unique per IFD
        (257, 3, 1, 64),                 # ImageLength
    ]


class TestLargeIFDChainIteration:
    """Test iter_ifds() at real-world scale (10-20 IFDs)."""

    def test_15_ifd_chain(self):
        """15-IFD chain traverses fully."""
        ifd_list = [_make_ifd_entries(i) for i in range(15)]
        data = build_tiff_multi_ifd(ifd_list)
        f = io.BytesIO(data)
        header = read_header(f)
        ifds = iter_ifds(f, header)
        assert len(ifds) == 15

    def test_20_ifd_chain(self):
        """20-IFD chain traverses fully."""
        ifd_list = [_make_ifd_entries(i) for i in range(20)]
        data = build_tiff_multi_ifd(ifd_list)
        f = io.BytesIO(data)
        header = read_header(f)
        ifds = iter_ifds(f, header)
        assert len(ifds) == 20

    def test_ifd_entries_preserved(self):
        """Each IFD in a 15-chain has correct ImageWidth value."""
        ifd_list = [_make_ifd_entries(i) for i in range(15)]
        data = build_tiff_multi_ifd(ifd_list)
        f = io.BytesIO(data)
        header = read_header(f)
        ifds = iter_ifds(f, header)
        for i, (_, entries) in enumerate(ifds):
            width_entry = [e for e in entries if e.tag_id == 256][0]
            # Read inline value
            f.seek(width_entry.value_offset)
            val = struct.unpack('<H', f.read(2))[0]
            assert val == 64 * (i + 1)


class TestUnlinkMiddleInLargeChain:
    """Test unlinking a middle IFD from large chains."""

    def test_unlink_ifd_7_from_15_chain(self, tmp_path):
        """Unlink IFD #7 from 15-chain, verify 14 remain."""
        ifd_list = [_make_ifd_entries(i) for i in range(15)]
        data = build_tiff_multi_ifd(ifd_list)
        filepath = tmp_path / 'chain15.tif'
        filepath.write_bytes(data)

        with open(filepath, 'r+b') as f:
            header = read_header(f)
            ifds_before = iter_ifds(f, header)
            assert len(ifds_before) == 15
            target_offset = ifds_before[7][0]

            result = unlink_ifd(f, header, target_offset)
            assert result is True

            # Re-read header (first_ifd_offset may have changed)
            header = read_header(f)
            ifds_after = iter_ifds(f, header)
            assert len(ifds_after) == 14


class TestUnlinkMultipleSequentially:
    """Test unlinking multiple IFDs one-by-one."""

    def test_unlink_three_from_15_chain(self, tmp_path):
        """Unlink IFDs 12, 7, 3 from 15-chain sequentially."""
        ifd_list = [_make_ifd_entries(i) for i in range(15)]
        data = build_tiff_multi_ifd(ifd_list)
        filepath = tmp_path / 'chain15.tif'
        filepath.write_bytes(data)

        with open(filepath, 'r+b') as f:
            header = read_header(f)
            ifds = iter_ifds(f, header)
            offsets_to_unlink = [ifds[12][0], ifds[7][0], ifds[3][0]]

            for offset in offsets_to_unlink:
                result = unlink_ifd(f, header, offset)
                assert result is True
                header = read_header(f)

            ifds_after = iter_ifds(f, header)
            assert len(ifds_after) == 12

    def test_unlink_every_other_from_10_chain(self, tmp_path):
        """Unlink every other IFD (indices 1,3,5,7,9) from 10-chain."""
        ifd_list = [_make_ifd_entries(i) for i in range(10)]
        data = build_tiff_multi_ifd(ifd_list)
        filepath = tmp_path / 'chain10.tif'
        filepath.write_bytes(data)

        with open(filepath, 'r+b') as f:
            header = read_header(f)
            ifds = iter_ifds(f, header)
            # Unlink from end to preserve earlier offsets
            for idx in [9, 7, 5, 3, 1]:
                target = ifds[idx][0]
                unlink_ifd(f, header, target)
                header = read_header(f)
                ifds = iter_ifds(f, header)

            ifds_after = iter_ifds(f, header)
            assert len(ifds_after) == 5


class TestUnlinkAllIFDs:
    """Test unlinking all IFDs from a chain."""

    def test_unlink_all_5(self, tmp_path):
        """Unlink all 5 IFDs one-by-one until header points to 0."""
        ifd_list = [_make_ifd_entries(i) for i in range(5)]
        data = build_tiff_multi_ifd(ifd_list)
        filepath = tmp_path / 'chain5.tif'
        filepath.write_bytes(data)

        with open(filepath, 'r+b') as f:
            header = read_header(f)

            for _ in range(5):
                ifds = iter_ifds(f, header)
                if not ifds:
                    break
                # Always unlink the first IFD
                unlink_ifd(f, header, ifds[0][0])
                header = read_header(f)

            ifds_after = iter_ifds(f, header)
            assert len(ifds_after) == 0
            assert header.first_ifd_offset == 0


class TestBigTIFFLargeChain:
    """Test BigTIFF with large IFD chains."""

    def test_10_ifd_bigtiff_chain(self):
        """10-IFD BigTIFF chain traverses fully."""
        ifd_list = [_make_ifd_entries(i) for i in range(10)]
        data = build_bigtiff_multi_ifd(ifd_list)
        f = io.BytesIO(data)
        header = read_header(f)
        assert header.is_bigtiff
        ifds = iter_ifds(f, header)
        assert len(ifds) == 10

    def test_unlink_middle_bigtiff(self, tmp_path):
        """Unlink middle IFD from 10-IFD BigTIFF chain."""
        ifd_list = [_make_ifd_entries(i) for i in range(10)]
        data = build_bigtiff_multi_ifd(ifd_list)
        filepath = tmp_path / 'bigtiff_chain.tif'
        filepath.write_bytes(data)

        with open(filepath, 'r+b') as f:
            header = read_header(f)
            ifds = iter_ifds(f, header)
            target = ifds[5][0]

            result = unlink_ifd(f, header, target)
            assert result is True

            header = read_header(f)
            ifds_after = iter_ifds(f, header)
            assert len(ifds_after) == 9


class TestCircularChainDetection:
    """Test that iter_ifds() handles circular IFD chains gracefully."""

    def test_circular_chain_terminates(self, tmp_path):
        """IFD #9 points back to IFD #4 -- verify iter_ifds terminates."""
        # Build a normal 10-IFD chain first
        ifd_list = [_make_ifd_entries(i) for i in range(10)]
        data = build_tiff_multi_ifd(ifd_list)
        filepath = tmp_path / 'circular.tif'
        filepath.write_bytes(data)

        # Manually patch IFD #9's next pointer to point to IFD #4's offset
        with open(filepath, 'r+b') as f:
            header = read_header(f)
            ifds = iter_ifds(f, header)
            ifd4_offset = ifds[4][0]
            ifd9_offset = ifds[9][0]

            # Read IFD #9 to find its next-pointer location
            entries_9, _ = read_ifd(f, header, ifd9_offset)
            next_ptr_offset = ifd9_offset + 2 + len(entries_9) * 12
            f.seek(next_ptr_offset)
            f.write(struct.pack('<I', ifd4_offset))

        # iter_ifds should terminate without infinite loop
        with open(filepath, 'rb') as f:
            header = read_header(f)
            ifds = iter_ifds(f, header)
            # Should see exactly 10 IFDs (0-9), then circular detection stops
            assert len(ifds) == 10
