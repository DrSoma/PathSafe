"""Low-level TIFF/BigTIFF binary parser -- stdlib only (struct module).

Handles both standard TIFF (magic 42) and BigTIFF (magic 43) formats,
with little-endian (II) and big-endian (MM) byte orders.

Ported from proven production code that successfully processed 3,101+ NDPI files.
"""

import hashlib
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
    17: (8, 'q'),   # SLONG8 (BigTIFF, signed)
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
    65441: 'NDPI_CAPTUREMODE', 65442: 'NDPI_SERIAL_NUMBER',
    65449: 'NDPI_SCANNER_PROPS', 65457: 'NDPI_UNKNOWN_65457',
    65458: 'NDPI_UNKNOWN_65458', 65459: 'NDPI_UNKNOWN_65459',
    65468: 'NDPI_BARCODE', 65469: 'NDPI_UNKNOWN_65469',
    65476: 'NDPI_UNKNOWN_65476', 65477: 'NDPI_SCANPROFILE',
    65478: 'NDPI_UNKNOWN_65478', 65480: 'NDPI_BARCODE_TYPE',
}

# EXIF/GPS sub-IFD pointer tags
EXIF_IFD_POINTER_TAG = 34665
GPS_IFD_POINTER_TAG = 34853

# GPS tag names (tags 0-31)
GPS_TAG_NAMES: Dict[int, str] = {
    0: 'GPSVersionID', 1: 'GPSLatitudeRef', 2: 'GPSLatitude',
    3: 'GPSLongitudeRef', 4: 'GPSLongitude', 5: 'GPSAltitudeRef',
    6: 'GPSAltitude', 7: 'GPSTimeStamp', 8: 'GPSSatellites',
    9: 'GPSStatus', 10: 'GPSMeasureMode', 11: 'GPSDOP',
    12: 'GPSSpeedRef', 13: 'GPSSpeed', 14: 'GPSTrackRef',
    15: 'GPSTrack', 16: 'GPSImgDirectionRef', 17: 'GPSImgDirection',
    18: 'GPSMapDatum', 19: 'GPSDestLatitudeRef', 20: 'GPSDestLatitude',
    21: 'GPSDestLongitudeRef', 22: 'GPSDestLongitude', 23: 'GPSDestBearingRef',
    24: 'GPSDestBearing', 25: 'GPSDestDistanceRef', 26: 'GPSDestDistance',
    27: 'GPSProcessingMethod', 28: 'GPSAreaInformation', 29: 'GPSDateStamp',
    30: 'GPSDifferential', 31: 'GPSHPositioningError',
}

# EXIF sub-IFD tags that contain PHI (dates, free text, unique IDs)
EXIF_SUB_IFD_PHI_TAGS: Dict[int, str] = {
    36867: 'DateTimeOriginal',
    36868: 'DateTimeDigitized',
    37510: 'UserComment',
    37520: 'SubSecTime',
    37521: 'SubSecTimeOriginal',
    37522: 'SubSecTimeDigitized',
    42016: 'ImageUniqueID',
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

    # Maximum plausible tag count per IFD.  Real WSI IFDs have <200 tags;
    # anything vastly beyond that indicates the IFD pointer landed in image
    # data and the "tag count" is garbage bytes.
    MAX_IFD_ENTRIES = 1000

    if header.is_bigtiff:
        data = f.read(8)
        if len(data) < 8:
            return [], 0
        num_entries = struct.unpack(endian + 'Q', data)[0]
        if num_entries > MAX_IFD_ENTRIES:
            return [], 0
        entry_size = 20
        inline_threshold = 8
    else:
        data = f.read(2)
        if len(data) < 2:
            return [], 0
        num_entries = struct.unpack(endian + 'H', data)[0]
        if num_entries > MAX_IFD_ENTRIES:
            return [], 0
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
              max_pages: int = 500) -> List[Tuple[int, List[IFDEntry]]]:
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
        if not entries:
            break  # Corrupt IFD (e.g. absurd tag count) -- stop chain
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


def read_tag_long_array(f: BinaryIO, header: TIFFHeader,
                        entry: IFDEntry) -> List[int]:
    """Read a tag value as a list of integers.

    Used for StripOffsets, StripByteCounts, TileOffsets, TileByteCounts.
    """
    if entry.dtype not in TIFF_TYPES:
        return []
    elem_size, fmt_char = TIFF_TYPES[entry.dtype]
    if fmt_char in ('s',):
        return []
    f.seek(entry.value_offset)
    fmt = header.endian + fmt_char * entry.count
    size = struct.calcsize(fmt)
    data = f.read(size)
    if len(data) < size:
        return []
    return list(struct.unpack(fmt, data))


# Minimal valid JPEG: a 1x1 white pixel with full JFIF headers, quantization
# tables, Huffman tables, and scan data (630 bytes).  All JPEG decoders
# (including libjpeg used by OpenSlide) can parse this, unlike the bare
# SOI+EOI (FFD8FFD9) which many decoders reject as "no image".
# We pad the remaining strip/tile bytes with zeros after writing this.
_BLANK_JPEG = (
    b'\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01'
    b'\x00\x01\x00\x00'
    # JPEG COM marker: positively identifies PathSafe-blanked images
    b'\xff\xfe\x00\x0aPATHSAFE'
    b'\xff\xdb\x00C\x00' + b'\xff' * 64
    + b'\xff\xdb\x00C\x01' + b'\xff' * 64
    + b'\xff\xc0\x00\x11\x08\x00\x01\x00\x01\x03\x01"\x00\x02\x11\x01\x03\x11\x01'
    b'\xff\xc4\x00\x1f\x00\x00\x01\x05\x01\x01\x01\x01\x01\x01\x00\x00'
    b'\x00\x00\x00\x00\x00\x00\x01\x02\x03\x04\x05\x06\x07\x08\x09\x0a\x0b'
    b'\xff\xc4\x00\xb5\x10\x00\x02\x01\x03\x03\x02\x04\x03\x05\x05\x04'
    b'\x04\x00\x00\x01}\x01\x02\x03\x00\x04\x11\x05\x12!1A\x06\x13Qa'
    b'\x07"q\x142\x81\x91\xa1\x08#B\xb1\xc1\x15R\xd1\xf0$3br\x82'
    b'\x09\x0a\x16\x17\x18\x19\x1a%&\'()*456789:CDEFGHIJSTUVWXY'
    b'Zcdefghijstuvwxyz\x83\x84\x85\x86\x87\x88\x89\x8a\x92\x93\x94'
    b'\x95\x96\x97\x98\x99\x9a\xa2\xa3\xa4\xa5\xa6\xa7\xa8\xa9\xaa\xb2'
    b'\xb3\xb4\xb5\xb6\xb7\xb8\xb9\xba\xc2\xc3\xc4\xc5\xc6\xc7\xc8\xc9'
    b'\xca\xd2\xd3\xd4\xd5\xd6\xd7\xd8\xd9\xda\xe1\xe2\xe3\xe4\xe5\xe6'
    b'\xe7\xe8\xe9\xea\xf1\xf2\xf3\xf4\xf5\xf6\xf7\xf8\xf9\xfa'
    b'\xff\xc4\x00\x1f\x01\x00\x03\x01\x01\x01\x01\x01\x01\x01\x01\x01'
    b'\x00\x00\x00\x00\x00\x00\x01\x02\x03\x04\x05\x06\x07\x08\x09\x0a\x0b'
    b'\xff\xc4\x00\xb5\x11\x00\x02\x01\x02\x04\x04\x03\x04\x07\x05\x04'
    b'\x04\x00\x01\x02w\x00\x01\x02\x03\x11\x04\x05!1\x06\x12AQ\x07aq'
    b'\x13"2\x81\x08\x14B\x91\xa1\xb1\xc1\x09#3R\xf0\x15br\xd1\x0a'
    b'\x16$4\xe1%\xf1\x17\x18\x19\x1a&\'()*56789:CDEFGHIJSTUVWXY'
    b'Zcdefghijstuvwxyz\x82\x83\x84\x85\x86\x87\x88\x89\x8a\x92\x93'
    b'\x94\x95\x96\x97\x98\x99\x9a\xa2\xa3\xa4\xa5\xa6\xa7\xa8\xa9\xaa'
    b'\xb2\xb3\xb4\xb5\xb6\xb7\xb8\xb9\xba\xc2\xc3\xc4\xc5\xc6\xc7\xc8'
    b'\xc9\xca\xd2\xd3\xd4\xd5\xd6\xd7\xd8\xd9\xda\xe2\xe3\xe4\xe5\xe6'
    b'\xe7\xe8\xe9\xea\xf2\xf3\xf4\xf5\xf6\xf7\xf8\xf9\xfa'
    b'\xff\xda\x00\x0c\x03\x01\x00\x02\x11\x03\x11\x00?\x00\x92\x8a(\xa0\x0f'
    b'\xff\xd9'
)

# Legacy 4-byte blank (SOI + EOI) -- used for detecting files blanked by
# older PathSafe versions that wrote only these 4 bytes.
_LEGACY_BLANK_JPEG = b'\xFF\xD8\xFF\xD9'


def blank_ifd_image_data(f: BinaryIO, header: TIFFHeader,
                         entries: List[IFDEntry]) -> int:
    """Overwrite all image strip/tile data in an IFD with blank bytes.

    Writes a minimal valid JPEG header followed by zeros to each
    strip/tile, preserving TIFF structure while destroying pixel content.
    Returns total bytes blanked.
    """
    offset_entry = None
    count_entry = None

    for entry in entries:
        if entry.tag_id == 273:    # StripOffsets
            offset_entry = entry
        elif entry.tag_id == 279:  # StripByteCounts
            count_entry = entry
        elif entry.tag_id == 324:  # TileOffsets
            if offset_entry is None:
                offset_entry = entry
        elif entry.tag_id == 325:  # TileByteCounts
            if count_entry is None:
                count_entry = entry

    if offset_entry is None or count_entry is None:
        return 0

    offsets = read_tag_long_array(f, header, offset_entry)
    counts = read_tag_long_array(f, header, count_entry)

    if len(offsets) != len(counts):
        return 0

    total_blanked = 0
    for off, cnt in zip(offsets, counts):
        if cnt > 0:
            f.seek(off)
            if cnt >= len(_BLANK_JPEG):
                f.write(_BLANK_JPEG)
                f.write(b'\x00' * (cnt - len(_BLANK_JPEG)))
            else:
                f.write(b'\x00' * cnt)
            total_blanked += cnt

    return total_blanked


def unlink_ifd(f: BinaryIO, header: TIFFHeader,
               target_ifd_offset: int) -> bool:
    """Unlink an IFD from the TIFF IFD chain.

    Rewrites the predecessor's next-IFD pointer to skip the target IFD,
    making it unreachable to TIFF readers. The orphaned IFD's physical
    data remains in the file but is invisible to any conforming reader.

    Args:
        f: Open file handle in r+b mode.
        header: Parsed TIFF header.
        target_ifd_offset: File offset of the IFD to unlink.

    Returns:
        True if the IFD was found and unlinked, False if not in chain.
    """
    endian = header.endian

    # Read the target IFD to get its next_offset
    target_entries, target_next = read_ifd(f, header, target_ifd_offset)
    if not target_entries and target_next == 0:
        # Could not read target IFD at all
        return False

    # Case 1: Target is the first IFD -- rewrite the file header
    if header.first_ifd_offset == target_ifd_offset:
        if header.is_bigtiff:
            f.seek(8)
            f.write(struct.pack(endian + 'Q', target_next))
        else:
            f.seek(4)
            f.write(struct.pack(endian + 'I', target_next))
        header.first_ifd_offset = target_next
        return True

    # Case 2: Walk the chain to find the predecessor
    seen = set()
    pred_offset = header.first_ifd_offset

    while pred_offset != 0:
        if pred_offset in seen:
            break  # Circular chain protection
        seen.add(pred_offset)

        pred_entries, pred_next = read_ifd(f, header, pred_offset)

        if pred_next == target_ifd_offset:
            # Found the predecessor -- rewrite its next-pointer
            num_entries = len(pred_entries)
            if header.is_bigtiff:
                next_ptr_offset = pred_offset + 8 + (num_entries * 20)
                f.seek(next_ptr_offset)
                f.write(struct.pack(endian + 'Q', target_next))
            else:
                next_ptr_offset = pred_offset + 2 + (num_entries * 12)
                f.seek(next_ptr_offset)
                f.write(struct.pack(endian + 'I', target_next))
            return True

        pred_offset = pred_next

    # Target not found in chain (already unlinked or invalid)
    return False


def get_ifd_image_size(header: TIFFHeader,
                       entries: List[IFDEntry], f: BinaryIO) -> Tuple[int, int]:
    """Get image width and height from an IFD's tags. Returns (width, height)."""
    width = 0
    height = 0
    for entry in entries:
        if entry.tag_id == 256:  # ImageWidth
            val = read_tag_numeric(f, header, entry)
            if val is not None:
                width = val
        elif entry.tag_id == 257:  # ImageLength
            val = read_tag_numeric(f, header, entry)
            if val is not None:
                height = val
    return width, height


def is_ifd_image_blanked(f: BinaryIO, header: TIFFHeader,
                         entries: List[IFDEntry]) -> bool:
    """Check if the image data in an IFD has been blanked.

    Detects both current format (630-byte minimal JPEG + zeros) and
    legacy format (4-byte SOI+EOI + zeros) written by older versions.
    """
    offset_entry = None
    count_entry = None
    for entry in entries:
        if entry.tag_id == 273:    # StripOffsets
            offset_entry = entry
        elif entry.tag_id == 279:  # StripByteCounts
            count_entry = entry
        elif entry.tag_id == 324:  # TileOffsets
            if offset_entry is None:
                offset_entry = entry
        elif entry.tag_id == 325:  # TileByteCounts
            if count_entry is None:
                count_entry = entry

    if offset_entry is None or count_entry is None:
        return False

    offsets = read_tag_long_array(f, header, offset_entry)
    counts = read_tag_long_array(f, header, count_entry)
    if not offsets or not counts:
        return False

    first_off = offsets[0]
    first_cnt = counts[0]
    if first_cnt < 8:
        return False

    f.seek(first_off)
    head = f.read(min(first_cnt, 32))

    # All zeros = blanked
    if head == b'\x00' * len(head):
        return True

    # Must start with JPEG SOI marker
    if head[:2] != b'\xFF\xD8':
        return False

    # Positive identification: PATHSAFE marker in JPEG COM segment
    if b'PATHSAFE' in head:
        return True

    # Legacy format: SOI + EOI (FFD8FFD9) + zeros
    if head[:4] == _LEGACY_BLANK_JPEG and head[4:8] == b'\x00' * 4:
        return True

    # Pre-marker format: minimal JPEG (no PATHSAFE marker) + zeros.
    # A real macro/label image has dense JPEG data throughout, so check
    # for zeros right after our known JPEG length.
    if first_cnt > len(_BLANK_JPEG) + 8:
        f.seek(first_off + len(_BLANK_JPEG))
        trail = f.read(8)
        if trail == b'\x00' * len(trail):
            return True

    return False


# Tags that may contain PHI in any TIFF-based format
# These are scanned across NDPI, SVS, and generic TIFF handlers
EXTRA_METADATA_TAGS = {
    270: 'ImageDescription', # May contain patient/case info (scanned by SVS/NDPI handlers too)
    305: 'Software',         # Scanner software version -- device fingerprint
    315: 'Artist',           # Operator/photographer name
    316: 'HostComputer',     # Institution hostname -- site identifier
    700: 'XMP',              # XML metadata blob (creator, dates, etc.)
    33432: 'Copyright',      # May contain institutional or personal names
    33723: 'IPTC',           # IPTC/IIM metadata (byline, caption, etc.)
    34675: 'ICCProfile',     # ICC color profile -- may contain device serial numbers
    37510: 'UserComment',    # EXIF free-text comment
    42016: 'ImageUniqueID',  # Linkable unique identifier
}


def scan_extra_metadata_tags(f: BinaryIO, header: TIFFHeader,
                              entries: List[IFDEntry],
                              exclude_tags: set = None) -> List[Tuple[IFDEntry, str]]:
    """Scan IFD entries for extra metadata tags that may contain PHI.

    Args:
        exclude_tags: Set of tag IDs to skip (e.g., {270} if handler already checks it).

    Returns list of (entry, value_preview) for tags that have non-empty content.
    Used by NDPI, SVS, and generic TIFF handlers as an extra safety check.
    """
    if exclude_tags is None:
        exclude_tags = set()
    findings = []
    for entry in entries:
        if entry.tag_id not in EXTRA_METADATA_TAGS or entry.tag_id in exclude_tags:
            continue
        # Only check string (ASCII) or undefined (EXIF) types
        if entry.dtype not in (2, 7):
            continue
        raw = read_tag_value_bytes(f, entry)
        if not raw or raw == b'\x00' * len(raw):
            continue
        # Check if already anonymized (all X's + null)
        stripped = raw.rstrip(b'\x00')
        if stripped and all(b == ord('X') for b in stripped):
            continue
        # For XMP (tag 700), check if it's an XML blob with potentially identifying content
        value = stripped.decode('utf-8', errors='replace')[:200]
        if value.strip():
            findings.append((entry, value))
    return findings


def blank_extra_metadata_tag(f: BinaryIO, entry: IFDEntry) -> int:
    """Overwrite an extra metadata tag with null bytes. Returns bytes blanked."""
    f.seek(entry.value_offset)
    f.write(b'\x00' * entry.total_size)
    return entry.total_size


def get_ifd_image_data_size(header: TIFFHeader,
                            entries: List[IFDEntry],
                            f: BinaryIO) -> int:
    """Get total size of image data (strips or tiles) in an IFD."""
    count_entry = None
    for entry in entries:
        if entry.tag_id == 279:    # StripByteCounts
            count_entry = entry
            break
        elif entry.tag_id == 325:  # TileByteCounts
            count_entry = entry

    if count_entry is None:
        return 0

    counts = read_tag_long_array(f, header, count_entry)
    return sum(counts)


def compute_ifd_tile_hash(f: BinaryIO, header: TIFFHeader,
                          entries: List[IFDEntry]) -> Optional[str]:
    """Compute SHA-256 hash of all tile/strip data in an IFD.

    Streams data through the hash in 64 KB chunks for constant memory usage.
    Returns hex digest, or None if no tile/strip data in this IFD.
    """
    offset_entry = None
    count_entry = None

    for entry in entries:
        if entry.tag_id == 273:    # StripOffsets
            offset_entry = entry
        elif entry.tag_id == 279:  # StripByteCounts
            count_entry = entry
        elif entry.tag_id == 324:  # TileOffsets
            if offset_entry is None:
                offset_entry = entry
        elif entry.tag_id == 325:  # TileByteCounts
            if count_entry is None:
                count_entry = entry

    if offset_entry is None or count_entry is None:
        return None

    offsets = read_tag_long_array(f, header, offset_entry)
    counts = read_tag_long_array(f, header, count_entry)

    if len(offsets) != len(counts) or not offsets:
        return None

    h = hashlib.sha256()
    chunk_size = 65536  # 64 KB

    for off, cnt in zip(offsets, counts):
        if cnt <= 0:
            continue
        f.seek(off)
        remaining = cnt
        while remaining > 0:
            to_read = min(chunk_size, remaining)
            data = f.read(to_read)
            if not data:
                break
            h.update(data)
            remaining -= len(data)

    return h.hexdigest()


def compute_image_hashes(filepath) -> Dict[int, str]:
    """Compute per-IFD tile data SHA-256 hashes for a TIFF file.

    Args:
        filepath: Path to the TIFF file.

    Returns:
        Dict mapping IFD offset to SHA-256 hex digest.
        Empty dict if the file is not a valid TIFF.
    """
    result = {}
    try:
        with open(str(filepath), 'rb') as f:
            header = read_header(f)
            if header is None:
                return result

            for ifd_offset, entries in iter_ifds(f, header):
                digest = compute_ifd_tile_hash(f, header, entries)
                if digest is not None:
                    result[ifd_offset] = digest
    except (OSError, struct.error):
        pass
    return result


# ---------------------------------------------------------------------------
# EXIF / GPS sub-IFD traversal
# ---------------------------------------------------------------------------

def read_exif_sub_ifd(f: BinaryIO, header: TIFFHeader,
                      entries: List[IFDEntry]) -> Optional[Tuple[int, List[IFDEntry]]]:
    """Find tag 34665 (ExifIFDPointer) and read the sub-IFD it points to.

    Returns (sub_ifd_offset, sub_entries) or None if tag not present / invalid.
    """
    for entry in entries:
        if entry.tag_id == EXIF_IFD_POINTER_TAG:
            sub_offset = read_tag_numeric(f, header, entry)
            if sub_offset is None or sub_offset == 0:
                return None
            try:
                sub_entries, _ = read_ifd(f, header, int(sub_offset))
                if sub_entries:
                    return (int(sub_offset), sub_entries)
            except (struct.error, OSError):
                pass
            return None
    return None


def read_gps_sub_ifd(f: BinaryIO, header: TIFFHeader,
                     entries: List[IFDEntry]) -> Optional[Tuple[int, List[IFDEntry]]]:
    """Find tag 34853 (GPSInfoIFDPointer) and read the sub-IFD it points to.

    Returns (sub_ifd_offset, sub_entries) or None if tag not present / invalid.
    """
    for entry in entries:
        if entry.tag_id == GPS_IFD_POINTER_TAG:
            sub_offset = read_tag_numeric(f, header, entry)
            if sub_offset is None or sub_offset == 0:
                return None
            try:
                sub_entries, _ = read_ifd(f, header, int(sub_offset))
                if sub_entries:
                    return (int(sub_offset), sub_entries)
            except (struct.error, OSError):
                pass
            return None
    return None


def scan_exif_sub_ifd_tags(f: BinaryIO, header: TIFFHeader,
                           entries: List[IFDEntry]) -> List[Tuple[IFDEntry, str]]:
    """Scan EXIF sub-IFD entries for PHI (dates, UserComment, ImageUniqueID).

    Args:
        entries: The entries of the EXIF sub-IFD (not the main IFD).

    Returns list of (entry, value_preview) for tags with non-empty, non-anonymized content.
    """
    findings = []
    for entry in entries:
        if entry.tag_id not in EXIF_SUB_IFD_PHI_TAGS:
            continue
        raw = read_tag_value_bytes(f, entry)
        if not raw or raw == b'\x00' * len(raw):
            continue
        stripped = raw.rstrip(b'\x00')
        if stripped and all(b == ord('X') for b in stripped):
            continue
        value = stripped.decode('utf-8', errors='replace')[:200]
        if value.strip():
            findings.append((entry, value))
    return findings


def scan_gps_sub_ifd(f: BinaryIO, header: TIFFHeader,
                     entries: List[IFDEntry]) -> List[Tuple[IFDEntry, str]]:
    """Scan ALL GPS sub-IFD entries -- every GPS tag is PHI (location data).

    Returns list of (entry, preview_string) for tags with non-zero content.
    """
    findings = []
    for entry in entries:
        raw = read_tag_value_bytes(f, entry)
        if not raw or raw == b'\x00' * len(raw):
            continue
        # For RATIONAL types (lat/lon), show numeric preview
        if entry.dtype in (5, 10):  # RATIONAL / SRATIONAL
            val = read_tag_numeric(f, header, entry)
            if val is not None:
                preview = f'{GPS_TAG_NAMES.get(entry.tag_id, f"GPSTag_{entry.tag_id}")}={val}'
            else:
                preview = GPS_TAG_NAMES.get(entry.tag_id, f'GPSTag_{entry.tag_id}')
        elif entry.dtype == 2:  # ASCII
            preview = raw.rstrip(b'\x00').decode('ascii', errors='replace')[:50]
        else:
            preview = GPS_TAG_NAMES.get(entry.tag_id, f'GPSTag_{entry.tag_id}')
        findings.append((entry, preview))
    return findings


def blank_exif_sub_ifd_tags(f: BinaryIO, header: TIFFHeader,
                            entries: List[IFDEntry]) -> int:
    """Blank PHI tags in an EXIF sub-IFD. Returns total bytes blanked."""
    total = 0
    for entry in entries:
        if entry.tag_id not in EXIF_SUB_IFD_PHI_TAGS:
            continue
        raw = read_tag_value_bytes(f, entry)
        if not raw or raw == b'\x00' * len(raw):
            continue
        stripped = raw.rstrip(b'\x00')
        if stripped and all(b == ord('X') for b in stripped):
            continue
        f.seek(entry.value_offset)
        f.write(b'\x00' * entry.total_size)
        total += entry.total_size
    return total


def blank_gps_sub_ifd(f: BinaryIO, header: TIFFHeader,
                      entries: List[IFDEntry]) -> int:
    """Zero out ALL GPS tag values. Returns total bytes blanked."""
    total = 0
    for entry in entries:
        raw = read_tag_value_bytes(f, entry)
        if not raw or raw == b'\x00' * len(raw):
            continue
        f.seek(entry.value_offset)
        f.write(b'\x00' * entry.total_size)
        total += entry.total_size
    return total
