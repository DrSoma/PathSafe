"""Low-level TIFF/BigTIFF binary parser package.

Re-exports all public names for backward compatibility -- existing
``from pathsafe.tiff import X`` statements continue to work.
"""

from __future__ import annotations

# --- blanking.py: image blanking, IFD unlinking, extra metadata ---
from pathsafe.tiff.blanking import (  # noqa: F401
    _BLANK_JPEG,
    _LEGACY_BLANK_JPEG,
    EXTRA_METADATA_TAGS,
    blank_extra_metadata_tag,
    blank_ifd_image_data,
    get_ifd_image_data_size,
    get_ifd_image_size,
    is_ifd_image_blanked,
    scan_extra_metadata_tags,
    unlink_ifd,
)

# --- hashing.py: image integrity hashing ---
from pathsafe.tiff.hashing import (  # noqa: F401
    compute_ifd_tile_hash,
    compute_image_hashes,
)

# --- parser.py: types, constants, header/IFD reading, tag value reading ---
from pathsafe.tiff.parser import (  # noqa: F401
    EXIF_IFD_POINTER_TAG,
    GPS_IFD_POINTER_TAG,
    TAG_NAMES,
    TIFF_TYPES,
    IFDEntry,
    TIFFHeader,
    find_tag_in_first_ifd,
    find_tag_in_ifd,
    get_all_string_tags,
    iter_ifds,
    read_header,
    read_ifd,
    read_tag_long_array,
    read_tag_numeric,
    read_tag_string,
    read_tag_value_bytes,
)

# --- sub_ifd.py: EXIF/GPS sub-IFD traversal, SubIFD (tag 330) traversal ---
from pathsafe.tiff.sub_ifd import (  # noqa: F401
    EXIF_SUB_IFD_PHI_TAGS,
    GPS_TAG_NAMES,
    MAX_SUB_IFD_DEPTH,
    SUB_IFD_TAG,
    blank_exif_sub_ifd_tags,
    blank_gps_sub_ifd,
    blank_sub_ifds,
    read_exif_sub_ifd,
    read_gps_sub_ifd,
    read_sub_ifds,
    scan_exif_sub_ifd_tags,
    scan_gps_sub_ifd,
    scan_sub_ifds,
)
