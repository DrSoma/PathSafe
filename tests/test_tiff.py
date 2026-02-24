"""Tests for the TIFF/BigTIFF binary parser."""

import struct
import pytest
from pathsafe.tiff import (
    read_header, read_ifd, find_tag_in_first_ifd,
    read_tag_string, read_tag_value_bytes, TAG_NAMES,
)
from tests.conftest import build_tiff


class TestReadHeader:
    def test_little_endian_tiff(self, tmp_path):
        content = build_tiff([], endian='<')
        f = tmp_path / 'le.tif'
        f.write_bytes(content)
        with open(f, 'rb') as fh:
            header = read_header(fh)
        assert header is not None
        assert header.endian == '<'
        assert not header.is_bigtiff

    def test_big_endian_tiff(self, tmp_path):
        content = build_tiff([], endian='>')
        f = tmp_path / 'be.tif'
        f.write_bytes(content)
        with open(f, 'rb') as fh:
            header = read_header(fh)
        assert header is not None
        assert header.endian == '>'

    def test_invalid_file(self, tmp_path):
        f = tmp_path / 'bad.tif'
        f.write_bytes(b'NOT A TIFF FILE')
        with open(f, 'rb') as fh:
            header = read_header(fh)
        assert header is None

    def test_wrong_magic(self, tmp_path):
        f = tmp_path / 'bad_magic.tif'
        f.write_bytes(b'II' + struct.pack('<H', 99) + b'\x00' * 4)
        with open(f, 'rb') as fh:
            header = read_header(fh)
        assert header is None


class TestReadIFD:
    def test_read_entries(self, tmp_ndpi):
        with open(tmp_ndpi, 'rb') as f:
            header = read_header(f)
            entries, next_offset = read_ifd(f, header, header.first_ifd_offset)
        assert len(entries) == 5
        assert next_offset == 0
        tag_ids = {e.tag_id for e in entries}
        assert 65468 in tag_ids
        assert 306 in tag_ids

    def test_tag_names(self, tmp_ndpi):
        with open(tmp_ndpi, 'rb') as f:
            header = read_header(f)
            entries, _ = read_ifd(f, header, header.first_ifd_offset)
        barcode_entry = [e for e in entries if e.tag_id == 65468][0]
        assert barcode_entry.tag_name == 'NDPI_BARCODE'


class TestFindTag:
    def test_find_existing_tag(self, tmp_ndpi):
        offset, size = find_tag_in_first_ifd(str(tmp_ndpi), 65468)
        assert offset is not None
        assert size is not None
        assert size == 13  # 'AS-24-123456\0'

    def test_find_missing_tag(self, tmp_ndpi):
        offset, size = find_tag_in_first_ifd(str(tmp_ndpi), 99999)
        assert offset is None
        assert size is None

    def test_find_in_invalid_file(self, tmp_path):
        f = tmp_path / 'bad.ndpi'
        f.write_bytes(b'NOT A TIFF')
        offset, size = find_tag_in_first_ifd(str(f), 65468)
        assert offset is None
        assert size is None


class TestReadTagValues:
    def test_read_string(self, tmp_ndpi):
        with open(tmp_ndpi, 'rb') as f:
            header = read_header(f)
            entries, _ = read_ifd(f, header, header.first_ifd_offset)
            barcode = [e for e in entries if e.tag_id == 65468][0]
            value = read_tag_string(f, barcode)
        assert value == 'AS-24-123456'

    def test_read_raw_bytes(self, tmp_ndpi):
        with open(tmp_ndpi, 'rb') as f:
            header = read_header(f)
            entries, _ = read_ifd(f, header, header.first_ifd_offset)
            barcode = [e for e in entries if e.tag_id == 65468][0]
            raw = read_tag_value_bytes(f, barcode)
        assert raw == b'AS-24-123456\x00'
