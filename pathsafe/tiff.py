"""Low-level TIFF/BigTIFF binary parser — stdlib only (struct module).

Handles both standard TIFF (magic 42) and BigTIFF (magic 43) formats,
with little-endian (II) and big-endian (MM) byte orders.

Ported from proven production code that successfully processed 3,101+ NDPI files.
"""

import struct
from pathlib import Path
from typing import BinaryIO, Dict, List, Optional, Tuple

# TIFF type definitions: {type_id: (element_size_bytes, struct_format_char)}
TIFF_TYPES: Dict[int, Tuple[int, str]] = {
    1: (1, 'B'),    # BYTE
    2: (1, 's'),    # ASCII
    3: (2, 'H'),    # SHORT
    4: (4, 'I'),    # LONG
    5: (8, 'II'),   # RATIONAL (num/denom)
    6: (1, 'b'),    # SBYTE
    7: (1, 's'),    # UNDEFINED
    8: (2, 'h'),    # SSHORT
    9: (4, 'i'),    # SLONG
    10: (8, 'ii'),  # SRATIONAL
    11: (4, 'f'),   # FLOAT
    12: (8, 'd'),   # DOUBLE
    16: (8, 'Q'),   # LONG8 (BigTIFF)
}

# Well-known TIFF tag names
TAG_NAMES: Dict[int, str] = {
    254: 'NewSubfileType', 256: 'ImageWidth', 257: 'ImageLength',
    258: 'BitsPerSample', 259: 'Compression', 262: 'PhotometricInterpretation',
    270: 'ImageDescription', 271: 'Make', 272: 'Model',
    273: 'StripOffsets', 278: 'RowsPerStrip', 279: 'StripByteCounts',
    282: 'XResolution', 283: 'YResolution', 296: 'ResolutionUnit',
    305: 'Software', 306: 'DateTime', 315: 'Artist', 316: 'HostComputer',
    324: 'TileOffsets', 325: 'TileByteCounts',
    330: 'SubIFDs',
    36867: 'DateTimeOriginal', 36868: 'DateTimeDigitized',
    # Hamamatsu NDPI-specific tags
    65420: 'NDPI_FORMAT_FLAG', 65421: 'NDPI_SOURCELENS',
    65422: 'NDPI_XOFFSET', 65423: 'NDPI_YOFFSET',
    65424: 'NDPI_ZOFFSET', 65425: 'NDPI_UNKNOWN_65425',
    65426: 'NDPI_JPEGQUALITY', 65427: 'NDPI_REFERENCE',
    65428: 'NDPI_IMGSIZE', 65429: 'NDPI_UNKNOWN_65429',
    65432: 'NDPI_UNKNOWN_65432', 65433: 'NDPI_UNKNOWN_65433',
    65439: 'NDPI_FOCUSPOINTS', 65440: 'NDPI_UNKNOWN_65440',
    65441: 'NDPI_UNKNOWN_65441', 65442: 'NDPI_UNKNOWN_65442',
    65449: 'NDPI_SCANNER_PROPS', 65457: 'NDPI_UNKNOWN_65457',
    65458: 'NDPI_UNKNOWN_65458', 65459: 'NDPI_UNKNOWN_65459',
    65468: 'NDPI_BARCODE', 65469: 'NDPI_UNKNOWN_65469',
    65476: 'NDPI_UNKNOWN_65476', 65477: 'NDPI_SCANPROFILE',
    65478: 'NDPI_UNKNOWN_65478', 65480: 'NDPI_BARCODE_TYPE',
}


class IFDEntry:
    """A single IFD (Image File Directory) entry."""
    __slots__ = ('tag_id', 'dtype', 'count', 'value_offset', 'entry_offset',
                 'is_inline')

    def __init__(self, tag_id: int, dtype: int, count: int,
                 value_offset: int, entry_offset: int, is_inline: bool):
        self.tag_id = tag_id
        self.dtype = dtype
        self.count = count
        self.value_offset = value_offset
        self.entry_offset = entry_offset
        self.is_inline = is_inline

    @property
    def tag_name(self) -> str:
        return TAG_NAMES.get(self.tag_id, f'Tag_{self.tag_id}')

    @property
    def total_size(self) -> int:
        elem_size = TIFF_TYPES.get(self.dtype, (1, 'B'))[0]
        return elem_size * self.count


class TIFFHeader:
    """Parsed TIFF file header."""
    __slots__ = ('endian', 'is_bigtiff', 'first_ifd_offset')

    def __init__(self, endian: str, is_bigtiff: bool, first_ifd_offset: int):
        self.endian = endian
        self.is_bigtiff = is_bigtiff
        self.first_ifd_offset = first_ifd_offset


def read_header(f: BinaryIO) -> Optional[TIFFHeader]:
    """Read and validate TIFF/BigTIFF header. Returns None if not a valid TIFF."""
    f.seek(0)
    bo = f.read(2)
    if bo == b'II':
        endian = '<'
    elif bo == b'MM':
        endian = '>'
    else:
        return None

    magic = struct.unpack(endian + 'H', f.read(2))[0]

    if magic == 42:
        # Standard TIFF
        ifd_offset = struct.unpack(endian + 'I', f.read(4))[0]
        return TIFFHeader(endian, False, ifd_offset)
    elif magic == 43:
        # BigTIFF
        bytesize = struct.unpack(endian + 'H', f.read(2))[0]
        if bytesize != 8:
            return None
        _reserved = f.read(2)
        ifd_offset = struct.unpack(endian + 'Q', f.read(8))[0]
        return TIFFHeader(endian, True, ifd_offset)
    else:
        return None


def read_ifd(f: BinaryIO, header: TIFFHeader,
             ifd_offset: int) -> Tuple[List[IFDEntry], int]:
    """Read all entries from an IFD. Returns (entries, next_ifd_offset)."""
    endian = header.endian
    f.seek(ifd_offset)

    if header.is_bigtiff:
        num_entries = struct.unpack(endian + 'Q', f.read(8))[0]
        entry_size = 20
        inline_threshold = 8
    else:
        num_entries = struct.unpack(endian + 'H', f.read(2))[0]
        entry_size = 12
        inline_threshold = 4

    entries = []
    for e in range(num_entries):
        entry_offset = f.tell()
        data = f.read(entry_size)
        if len(data) < entry_size:
            break

        if header.is_bigtiff:
            tag_id, dtype = struct.unpack(endian + 'HH', data[:4])
            count = struct.unpack(endian + 'Q', data[4:12])[0]
            elem_size = TIFF_TYPES.get(dtype, (1, 'B'))[0]
            total = elem_size * count
            if total <= 8:
                value_offset = entry_offset + 12
                is_inline = True
            else:
                value_offset = struct.unpack(endian + 'Q', data[12:20])[0]
                is_inline = False
        else:
            tag_id, dtype, count = struct.unpack(endian + 'HHI', data[:8])
            elem_size = TIFF_TYPES.get(dtype, (1, 'B'))[0]
            total = elem_size * count
            if total <= 4:
                value_offset = entry_offset + 8
                is_inline = True
            else:
                value_offset = struct.unpack(endian + 'I', data[8:12])[0]
                is_inline = False

        entries.append(IFDEntry(tag_id, dtype, count, value_offset,
                                entry_offset, is_inline))

    # Read next IFD offset
    if header.is_bigtiff:
        next_data = f.read(8)
        next_offset = struct.unpack(endian + 'Q', next_data)[0] if len(next_data) == 8 else 0
    else:
        next_data = f.read(4)
        next_offset = struct.unpack(endian + 'I', next_data)[0] if len(next_data) == 4 else 0

    return entries, next_offset


def read_tag_value_bytes(f: BinaryIO, entry: IFDEntry) -> bytes:
    """Read the raw bytes of a tag value."""
    f.seek(entry.value_offset)
    return f.read(entry.total_size)


def read_tag_string(f: BinaryIO, entry: IFDEntry) -> str:
    """Read a tag value as an ASCII string."""
    raw = read_tag_value_bytes(f, entry)
    return raw.rstrip(b'\x00').decode('ascii', errors='replace')


def read_tag_numeric(f: BinaryIO, header: TIFFHeader,
                     entry: IFDEntry) -> object:
    """Read a tag value as a numeric type (or list of numerics)."""
    if entry.dtype not in TIFF_TYPES:
        return None
    elem_size, fmt_char = TIFF_TYPES[entry.dtype]
    f.seek(entry.value_offset)

    if entry.count == 1 and fmt_char not in ('s',):
        fmt = header.endian + fmt_char
        data = f.read(struct.calcsize(fmt))
        if len(data) < struct.calcsize(fmt):
            return None
        return struct.unpack(fmt, data)[0]
    elif entry.count <= 10 and fmt_char not in ('s',):
        fmt = header.endian + fmt_char * entry.count
        data = f.read(struct.calcsize(fmt))
        if len(data) < struct.calcsize(fmt):
            return None
        return list(struct.unpack(fmt, data))
    else:
        return None


def find_tag_in_ifd(f: BinaryIO, header: TIFFHeader,
                    ifd_offset: int, target_tag: int) -> Optional[IFDEntry]:
    """Find a specific tag in an IFD. Returns the entry or None."""
    entries, _ = read_ifd(f, header, ifd_offset)
    for entry in entries:
        if entry.tag_id == target_tag:
            return entry
    return None


def find_tag_in_first_ifd(filepath: str,
                          target_tag: int) -> Tuple[Optional[int], Optional[int]]:
    """Find a tag's value offset and byte count from the FIRST IFD.

    Optimized shortcut for NDPI files where all pages share the same
    tag byte offset. Returns (value_offset, byte_count) or (None, None).
    """
    with open(filepath, 'rb') as f:
        header = read_header(f)
        if header is None:
            return None, None

        entry = find_tag_in_ifd(f, header, header.first_ifd_offset, target_tag)
        if entry is None:
            return None, None

        return entry.value_offset, entry.total_size


def iter_ifds(f: BinaryIO, header: TIFFHeader,
              max_pages: int = 100) -> List[Tuple[int, List[IFDEntry]]]:
    """Iterate through IFD chain. Returns list of (ifd_offset, entries)."""
    result = []
    offset = header.first_ifd_offset
    seen = set()
    count = 0

    while offset != 0 and count < max_pages:
        if offset in seen:
            break
        seen.add(offset)
        entries, next_offset = read_ifd(f, header, offset)
        result.append((offset, entries))
        offset = next_offset
        count += 1

    return result


def get_all_string_tags(f: BinaryIO, header: TIFFHeader,
                        ifd_offset: int) -> List[Tuple[IFDEntry, str]]:
    """Get all ASCII string tags from an IFD with their values."""
    entries, _ = read_ifd(f, header, ifd_offset)
    results = []
    for entry in entries:
        if entry.dtype == 2:  # ASCII
            value = read_tag_string(f, entry)
            results.append((entry, value))
    return results
