"""TIFF image data blanking and extra metadata handling."""

from __future__ import annotations

import logging
import struct
from typing import BinaryIO


logger = logging.getLogger(__name__)

from pathsafe.tiff.parser import (  # noqa: E402
    IFDEntry,
    TIFFHeader,
    read_ifd,
    read_tag_long_array,
    read_tag_numeric,
    read_tag_value_bytes,
)


# Minimal valid JPEG: a 1x1 white pixel with full JFIF headers, quantization
# tables, Huffman tables, and scan data (426 bytes).  All JPEG decoders
# (including libjpeg used by OpenSlide) can parse this, unlike the bare
# SOI+EOI (FFD8FFD9) which many decoders reject as "no image".
# We pad the remaining strip/tile bytes with zeros after writing this.
_BLANK_JPEG = (
    b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01"
    b"\x00\x01\x00\x00"
    # JPEG COM marker: positively identifies PathSafe-blanked images
    b"\xff\xfe\x00\x0aPATHSAFE"
    b"\xff\xdb\x00C\x00"
    + b"\xff" * 64
    + b"\xff\xdb\x00C\x01"
    + b"\xff" * 64
    + b'\xff\xc0\x00\x11\x08\x00\x01\x00\x01\x03\x01"\x00\x02\x11\x01\x03\x11\x01'
    b"\xff\xc4\x00\x1f\x00\x00\x01\x05\x01\x01\x01\x01\x01\x01\x00\x00"
    b"\x00\x00\x00\x00\x00\x00\x01\x02\x03\x04\x05\x06\x07\x08\x09\x0a\x0b"
    b"\xff\xc4\x00\xb5\x10\x00\x02\x01\x03\x03\x02\x04\x03\x05\x05\x04"
    b"\x04\x00\x00\x01}\x01\x02\x03\x00\x04\x11\x05\x12!1A\x06\x13Qa"
    b'\x07"q\x142\x81\x91\xa1\x08#B\xb1\xc1\x15R\xd1\xf0$3br\x82'
    b"\x09\x0a\x16\x17\x18\x19\x1a%&'()*456789:CDEFGHIJSTUVWXY"
    b"Zcdefghijstuvwxyz\x83\x84\x85\x86\x87\x88\x89\x8a\x92\x93\x94"
    b"\x95\x96\x97\x98\x99\x9a\xa2\xa3\xa4\xa5\xa6\xa7\xa8\xa9\xaa\xb2"
    b"\xb3\xb4\xb5\xb6\xb7\xb8\xb9\xba\xc2\xc3\xc4\xc5\xc6\xc7\xc8\xc9"
    b"\xca\xd2\xd3\xd4\xd5\xd6\xd7\xd8\xd9\xda\xe1\xe2\xe3\xe4\xe5\xe6"
    b"\xe7\xe8\xe9\xea\xf1\xf2\xf3\xf4\xf5\xf6\xf7\xf8\xf9\xfa"
    b"\xff\xda\x00\x0c\x03\x01\x00\x02\x11\x03\x11\x00?\x00\x92\x8a(\xa0\x0f"
    b"\xff\xd9"
)

# Legacy 4-byte blank (SOI + EOI) -- used for detecting files blanked by
# older PathSafe versions that wrote only these 4 bytes.
_LEGACY_BLANK_JPEG = b"\xff\xd8\xff\xd9"

# Tags that may contain PHI in any TIFF-based format
# These are scanned across NDPI, SVS, and generic TIFF handlers
EXTRA_METADATA_TAGS = {
    270: "ImageDescription",  # May contain patient/case info (scanned by SVS/NDPI handlers too)
    305: "Software",  # Scanner software version -- device fingerprint
    315: "Artist",  # Operator/photographer name
    316: "HostComputer",  # Institution hostname -- site identifier
    700: "XMP",  # XML metadata blob (creator, dates, etc.)
    33432: "Copyright",  # May contain institutional or personal names
    33723: "IPTC",  # IPTC/IIM metadata (byline, caption, etc.)
    34675: "ICCProfile",  # ICC color profile -- may contain device serial numbers
    37500: "MakerNote",  # EXIF vendor-specific blob -- may contain device identifiers
    37510: "UserComment",  # EXIF free-text comment
    42016: "ImageUniqueID",  # Linkable unique identifier
}


def blank_ifd_image_data(f: BinaryIO, header: TIFFHeader, entries: list[IFDEntry]) -> int:
    """Overwrite all image strip/tile data in an IFD with blank bytes.

    Writes a minimal valid JPEG header followed by zeros to each
    strip/tile, preserving TIFF structure while destroying pixel content.
    Returns total bytes blanked.
    """
    offset_entry = None
    count_entry = None

    for entry in entries:
        if entry.tag_id == 273:  # StripOffsets
            offset_entry = entry
        elif entry.tag_id == 279:  # StripByteCounts
            count_entry = entry
        elif entry.tag_id == 324 and offset_entry is None:  # TileOffsets
            offset_entry = entry
        elif entry.tag_id == 325 and count_entry is None:  # TileByteCounts
            count_entry = entry

    if offset_entry is None or count_entry is None:
        return 0

    offsets = read_tag_long_array(f, header, offset_entry)
    counts = read_tag_long_array(f, header, count_entry)

    if len(offsets) != len(counts):
        return 0

    total_blanked = 0
    for off, cnt in zip(offsets, counts, strict=False):
        if cnt > 0:
            f.seek(off)
            if cnt >= len(_BLANK_JPEG):
                f.write(_BLANK_JPEG)
                f.write(b"\x00" * (cnt - len(_BLANK_JPEG)))
            else:
                f.write(b"\x00" * cnt)
            total_blanked += cnt

    return total_blanked


def unlink_ifd(f: BinaryIO, header: TIFFHeader, target_ifd_offset: int) -> bool:
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
        logger.debug("unlink_ifd: cannot read target IFD at offset %d", target_ifd_offset)
        return False

    # Case 1: Target is the first IFD -- rewrite the file header
    if header.first_ifd_offset == target_ifd_offset:
        if header.is_bigtiff:
            f.seek(8)
            f.write(struct.pack(endian + "Q", target_next))
        else:
            f.seek(4)
            f.write(struct.pack(endian + "I", target_next))
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
                f.write(struct.pack(endian + "Q", target_next))
            else:
                next_ptr_offset = pred_offset + 2 + (num_entries * 12)
                f.seek(next_ptr_offset)
                f.write(struct.pack(endian + "I", target_next))
            return True

        pred_offset = pred_next

    # Target not found in chain (already unlinked or invalid)
    logger.debug("unlink_ifd: target offset %d not found in IFD chain", target_ifd_offset)
    return False


def get_ifd_image_size(header: TIFFHeader, entries: list[IFDEntry], f: BinaryIO) -> tuple[int, int]:
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


# Upper bound on strips/tiles we will inspect when deciding if an IFD is
# blanked.  Label/macro images have at most a few thousand strips; a
# full-resolution pyramid level has tens of thousands of tiles.  Above this
# bound we never certify an IFD as "blanked": it is not a label/macro, and the
# image-integrity check (which calls this to decide what to hash) should treat
# such IFDs as real image data rather than skip them.
MAX_STRIPS_TO_VERIFY = 8192


def _rest_is_zero(f: BinaryIO, start: int, end: int) -> bool:
    """Return True if the file bytes in [start, end) are all zero.

    Streams in chunks and exits at the first non-zero byte, so a strip that
    holds pixel data exits fast; a genuinely blanked strip is read in full.
    A truncated read (fewer bytes than expected) returns False -- we cannot
    confirm the region is zero, so we conservatively treat it as not blanked.
    """
    if end <= start:
        return True
    f.seek(start)
    remaining = end - start
    while remaining > 0:
        chunk = f.read(min(remaining, 65536))
        if not chunk:
            return False  # truncated -- cannot confirm zero
        if chunk.strip(b"\x00"):
            return False  # found a non-zero (pixel) byte
        remaining -= len(chunk)
    return True


def _is_strip_blanked(f: BinaryIO, off: int, cnt: int) -> bool:
    """Return True if the single strip/tile at (off, cnt) holds blanked content.

    A blanked strip is an optional recognised blank-JPEG marker followed by
    zeros all the way to the end (``blank_ifd_image_data`` writes _BLANK_JPEG
    then zero-pads, or all zeros for strips smaller than _BLANK_JPEG).  The
    ENTIRE strip after any marker must be zero -- a strip that merely looks
    blank in its first bytes but holds pixel data later is NOT blanked.
    Recognises the legacy SOI+EOI and pre-marker minimal-JPEG forms too.
    """
    if cnt <= 0:
        return True  # no pixel data present to leak

    f.seek(off)
    head = f.read(min(cnt, 64))
    if not head:
        return False

    # An optional leading blank-JPEG marker; everything after it must be zeros.
    if head[:2] == b"\xff\xd8":
        if cnt >= len(_BLANK_JPEG) and b"PATHSAFE" in head:  # current: minimal JPEG + PATHSAFE COM
            # The current blank is _BLANK_JPEG verbatim followed by zeros. Verify
            # the FULL marker bytes (not just the head), so a forged strip with a
            # PATHSAFE-looking head but pixel data in the marker body cannot pass.
            f.seek(off)
            if f.read(len(_BLANK_JPEG)) != _BLANK_JPEG:
                return False
            return _rest_is_zero(f, off + len(_BLANK_JPEG), off + cnt)
        if head[:4] == _LEGACY_BLANK_JPEG and head[4:8] == b"\x00" * 4:  # legacy SOI+EOI + zeros
            return _rest_is_zero(f, off + 8, off + cnt)
        # Any other JPEG content is NOT certified blanked: we cannot verify its
        # body is free of pixel data (the body bytes are unknown), so it is
        # treated conservatively as un-blanked and will be re-blanked.  (Files
        # blanked by an older pre-PATHSAFE-marker version fall here and are
        # simply re-blanked into the current verifiable form -- harmless.)
        return False

    # No JPEG marker -- the entire strip must be zeros.
    return _rest_is_zero(f, off, off + cnt)


def is_ifd_image_blanked(f: BinaryIO, header: TIFFHeader, entries: list[IFDEntry]) -> bool:
    """Check whether EVERY image strip/tile in an IFD has been blanked.

    Inspects all strips/tiles (a bounded read per strip), not just the first:
    a label/macro whose first strip was blanked but whose later strips still
    hold pixel data is NOT blanked.  Recognises the current (minimal JPEG +
    PATHSAFE marker + zeros), legacy (SOI+EOI + zeros), and all-zeros forms.
    """
    offset_entry = None
    count_entry = None
    for entry in entries:
        if entry.tag_id == 273:  # StripOffsets
            offset_entry = entry
        elif entry.tag_id == 279:  # StripByteCounts
            count_entry = entry
        elif entry.tag_id == 324 and offset_entry is None:  # TileOffsets
            offset_entry = entry
        elif entry.tag_id == 325 and count_entry is None:  # TileByteCounts
            count_entry = entry

    if offset_entry is None or count_entry is None:
        return False

    # Bound the work: a many-stripped/tiled IFD is a pyramid level, never a
    # label/macro -- do not certify it as blanked (and don't read all its tiles).
    if offset_entry.count > MAX_STRIPS_TO_VERIFY or count_entry.count > MAX_STRIPS_TO_VERIFY:
        return False

    offsets = read_tag_long_array(f, header, offset_entry)
    counts = read_tag_long_array(f, header, count_entry)
    if not offsets or not counts or len(offsets) != len(counts):
        return False

    # Blanked only if EVERY strip/tile is blanked.
    return all(_is_strip_blanked(f, off, cnt) for off, cnt in zip(offsets, counts, strict=False))


def get_ifd_image_data_size(header: TIFFHeader, entries: list[IFDEntry], f: BinaryIO) -> int:
    """Get total size of image data (strips or tiles) in an IFD."""
    count_entry = None
    for entry in entries:
        if entry.tag_id == 279:  # StripByteCounts
            count_entry = entry
            break
        elif entry.tag_id == 325:  # TileByteCounts
            count_entry = entry

    if count_entry is None:
        return 0

    counts = read_tag_long_array(f, header, count_entry)
    return sum(counts)


def scan_extra_metadata_tags(
    f: BinaryIO, header: TIFFHeader, entries: list[IFDEntry], exclude_tags: set[int] | None = None
) -> list[tuple[IFDEntry, str]]:
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
        if not raw or raw == b"\x00" * len(raw):
            continue
        # Check if already deidentified (all X's + null)
        stripped = raw.rstrip(b"\x00")
        if stripped and all(b == ord("X") for b in stripped):
            continue
        # For XMP (tag 700), check if it's an XML blob with potentially identifying content
        value = stripped.decode("utf-8", errors="replace")[:200]
        if value.strip():
            findings.append((entry, value))
    return findings


def blank_extra_metadata_tag(f: BinaryIO, entry: IFDEntry) -> int:
    """Overwrite an extra metadata tag with null bytes. Returns bytes blanked."""
    f.seek(entry.value_offset)
    f.write(b"\x00" * entry.total_size)
    return entry.total_size
