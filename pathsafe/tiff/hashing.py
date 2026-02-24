"""TIFF image data hashing for integrity verification."""

import hashlib
import struct
from pathlib import Path
from typing import BinaryIO, Dict, List, Optional

from pathsafe.tiff.parser import (
    IFDEntry,
    TIFFHeader,
    read_header,
    read_tag_long_array,
    iter_ifds,
)


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
