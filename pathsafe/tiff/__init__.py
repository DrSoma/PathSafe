"""Low-level TIFF/BigTIFF binary parser package.

Re-exports all public names for backward compatibility -- existing
``from pathsafe.tiff import X`` statements continue to work.
"""

# --- parser.py: types, constants, header/IFD reading, tag value reading ---
from pathsafe.tiff.parser import (  # noqa: F401
    TIFF_TYPES,
    TAG_NAMES,
    EXIF_IFD_POINTER_TAG,
    GPS_IFD_POINTER_TAG,
    IFDEntry,
    TIFFHeader,
    read_header,
    read_ifd,
    read_tag_value_bytes,
    read_tag_string,
    read_tag_numeric,
    find_tag_in_ifd,
    find_tag_in_first_ifd,
    iter_ifds,
    get_all_string_tags,
    read_tag_long_array,
)

# --- blanking.py: image blanking, IFD unlinking, extra metadata ---
from pathsafe.tiff.blanking import (  # noqa: F401
    _BLANK_JPEG,
    _LEGACY_BLANK_JPEG,
    EXTRA_METADATA_TAGS,
    blank_ifd_image_data,
    unlink_ifd,
    get_ifd_image_size,
    is_ifd_image_blanked,
    get_ifd_image_data_size,
    scan_extra_metadata_tags,
    blank_extra_metadata_tag,
)

# --- hashing.py: image integrity hashing ---
from pathsafe.tiff.hashing import (  # noqa: F401
    compute_ifd_tile_hash,
    compute_image_hashes,
)

# --- sub_ifd.py: EXIF/GPS sub-IFD traversal ---
from pathsafe.tiff.sub_ifd import (  # noqa: F401
    GPS_TAG_NAMES,
    EXIF_SUB_IFD_PHI_TAGS,
    read_exif_sub_ifd,
    read_gps_sub_ifd,
    scan_exif_sub_ifd_tags,
    scan_gps_sub_ifd,
    blank_exif_sub_ifd_tags,
    blank_gps_sub_ifd,
)
