"""Generic TIFF fallback handler.

Scans all string tags across ALL IFDs for PHI patterns.
Used as a fallback when no specific handler matches.
"""

import os
import time
from pathlib import Path
from typing import Dict, List

from pathsafe.formats.base import FormatHandler
from pathsafe.models import PHIFinding, ScanResult
from pathsafe.scanner import (
    DEFAULT_SCAN_SIZE,
    scan_bytes_for_phi,
    scan_string_for_phi,
    is_date_anonymized,
)
from pathsafe.tiff import (
    read_header,
    read_ifd,
    read_tag_string,
    read_tag_value_bytes,
    get_all_string_tags,
    iter_ifds,
    scan_extra_metadata_tags,
    blank_extra_metadata_tag,
    blank_ifd_image_data,
    is_ifd_image_blanked,
    get_ifd_image_size,
    get_ifd_image_data_size,
    unlink_ifd,
    read_exif_sub_ifd,
    read_gps_sub_ifd,
    scan_exif_sub_ifd_tags,
    scan_gps_sub_ifd,
    blank_exif_sub_ifd_tags,
    blank_gps_sub_ifd,
    EXTRA_METADATA_TAGS,
    EXIF_SUB_IFD_PHI_TAGS,
    GPS_TAG_NAMES,
    TAG_NAMES,
)

# Tags known to potentially contain PHI in generic TIFF files
GENERIC_PHI_STRING_TAGS = {270, 271, 272, 305, 315, 316}
GENERIC_DATE_TAGS = {306, 36867, 36868}
TIFF_EXTENSIONS = {'.tif', '.tiff', '.svs', '.ndpi', '.scn', '.bif', '.vms'}


class GenericTIFFHandler(FormatHandler):
    """Fallback handler for TIFF-based files not matched by specific handlers."""

    format_name = "tiff"

    def can_handle(self, filepath: Path) -> bool:
        if filepath.suffix.lower() not in TIFF_EXTENSIONS:
            return False
        # Verify TIFF magic bytes
        try:
            with open(filepath, 'rb') as f:
                bo = f.read(2)
                if bo not in (b'II', b'MM'):
                    return False
                import struct
                magic = struct.unpack(('<' if bo == b'II' else '>') + 'H', f.read(2))[0]
                return magic in (42, 43)
        except (OSError, Exception):
            return False

    def scan(self, filepath: Path) -> ScanResult:
        """Scan a generic TIFF file for PHI in string tags."""
        t0 = time.monotonic()
        file_size = os.path.getsize(filepath)
        findings: List[PHIFinding] = []

        try:
            with open(filepath, 'rb') as f:
                header = read_header(f)
                if header is None:
                    elapsed = (time.monotonic() - t0) * 1000
                    return ScanResult(
                        filepath=filepath, format="tiff", is_clean=False,
                        scan_time_ms=elapsed, file_size=file_size,
                        error="Not a valid TIFF file",
                    )

                # Scan all IFDs for string tags and extra metadata
                seen = set()
                seen_extra = set()
                for ifd_offset, entries in iter_ifds(f, header):
                    for entry in entries:
                        if entry.value_offset in seen:
                            continue
                        if entry.dtype == 2:  # ASCII string tags
                            seen.add(entry.value_offset)
                            value = read_tag_string(f, entry)
                            if not value:
                                continue
                            # Check for PHI patterns in string values
                            str_findings = scan_string_for_phi(value)
                            for char_off, length, matched, label in str_findings:
                                findings.append(PHIFinding(
                                    offset=entry.value_offset + char_off,
                                    length=length,
                                    tag_id=entry.tag_id,
                                    tag_name=TAG_NAMES.get(entry.tag_id, f'Tag_{entry.tag_id}'),
                                    value_preview=matched[:50],
                                    source='tiff_tag',
                                ))
                            # Check date tags
                            if entry.tag_id in GENERIC_DATE_TAGS:
                                if not is_date_anonymized(value):
                                    findings.append(PHIFinding(
                                        offset=entry.value_offset,
                                        length=entry.total_size,
                                        tag_id=entry.tag_id,
                                        tag_name=TAG_NAMES.get(entry.tag_id, f'Tag_{entry.tag_id}'),
                                        value_preview=value[:30],
                                        source='tiff_tag',
                                    ))

                    # Scan extra metadata (XMP, EXIF UserComment, Artist, etc.)
                    # Uses separate seen set so tags are flagged independently
                    for entry, value in scan_extra_metadata_tags(f, header, entries):
                        if entry.value_offset in seen_extra:
                            continue
                        seen_extra.add(entry.value_offset)
                        findings.append(PHIFinding(
                            offset=entry.value_offset,
                            length=entry.total_size,
                            tag_id=entry.tag_id,
                            tag_name=EXTRA_METADATA_TAGS[entry.tag_id],
                            value_preview=value[:50],
                            source='tiff_tag',
                        ))

                    # Label/macro detection via tag 270 ImageDescription
                    for entry in entries:
                        if entry.tag_id == 270 and entry.dtype == 2:
                            desc = read_tag_string(f, entry).lower()
                            img_type = None
                            if 'label' in desc:
                                img_type = 'LabelImage'
                            elif 'macro' in desc:
                                img_type = 'MacroImage'
                            if img_type and not is_ifd_image_blanked(f, header, entries):
                                w, h = get_ifd_image_size(header, entries, f)
                                data_size = get_ifd_image_data_size(header, entries, f)
                                if data_size > 0:
                                    findings.append(PHIFinding(
                                        offset=ifd_offset,
                                        length=data_size,
                                        tag_id=None,
                                        tag_name=img_type,
                                        value_preview=(
                                            f'{img_type} {w}x{h} '
                                            f'({data_size / 1024:.0f}KB)'),
                                        source='image_content',
                                    ))
                            break

                    # EXIF sub-IFD scanning
                    exif_result = read_exif_sub_ifd(f, header, entries)
                    if exif_result is not None:
                        _, sub_entries = exif_result
                        for sub_entry, value in scan_exif_sub_ifd_tags(f, header, sub_entries):
                            if sub_entry.value_offset not in seen_extra:
                                seen_extra.add(sub_entry.value_offset)
                                findings.append(PHIFinding(
                                    offset=sub_entry.value_offset,
                                    length=sub_entry.total_size,
                                    tag_id=sub_entry.tag_id,
                                    tag_name=f'EXIF:{EXIF_SUB_IFD_PHI_TAGS[sub_entry.tag_id]}',
                                    value_preview=value[:50],
                                    source='tiff_tag',
                                ))

                    # GPS sub-IFD scanning
                    gps_result = read_gps_sub_ifd(f, header, entries)
                    if gps_result is not None:
                        _, sub_entries = gps_result
                        for sub_entry, preview in scan_gps_sub_ifd(f, header, sub_entries):
                            if sub_entry.value_offset not in seen_extra:
                                seen_extra.add(sub_entry.value_offset)
                                findings.append(PHIFinding(
                                    offset=sub_entry.value_offset,
                                    length=sub_entry.total_size,
                                    tag_id=sub_entry.tag_id,
                                    tag_name=f'GPS:{GPS_TAG_NAMES.get(sub_entry.tag_id, f"Tag_{sub_entry.tag_id}")}',
                                    value_preview=preview[:50],
                                    source='tiff_tag',
                                ))

            # Regex safety scan
            with open(filepath, 'rb') as f:
                data = f.read(DEFAULT_SCAN_SIZE)
            raw_findings = scan_bytes_for_phi(data)
            for offset, length, matched, label in raw_findings:
                val = matched.decode('ascii', errors='replace')
                findings.append(PHIFinding(
                    offset=offset, length=length, tag_id=None,
                    tag_name=f'regex:{label}', value_preview=val[:50],
                    source='regex_scan',
                ))

            # Filename PHI check
            findings += self.scan_filename(filepath)

        except Exception as e:
            elapsed = (time.monotonic() - t0) * 1000
            return ScanResult(
                filepath=filepath, format="tiff", findings=findings,
                is_clean=False, scan_time_ms=elapsed,
                file_size=file_size, error=str(e),
            )

        elapsed = (time.monotonic() - t0) * 1000
        return ScanResult(
            filepath=filepath, format="tiff", findings=findings,
            is_clean=len(findings) == 0, scan_time_ms=elapsed,
            file_size=file_size,
        )

    def anonymize(self, filepath: Path) -> List[PHIFinding]:
        """Anonymize PHI in a generic TIFF file."""
        cleared: List[PHIFinding] = []

        seen = set()
        seen_extra = set()
        with open(filepath, 'r+b') as f:
            header = read_header(f)
            if header is None:
                return cleared

            for ifd_offset, entries in iter_ifds(f, header):
                # Label/macro blanking FIRST — must read tag 270 before
                # string tag loop overwrites it
                for entry in entries:
                    if entry.tag_id == 270 and entry.dtype == 2:
                        desc = read_tag_string(f, entry).lower()
                        img_type = None
                        if 'label' in desc:
                            img_type = 'LabelImage'
                        elif 'macro' in desc:
                            img_type = 'MacroImage'
                        if img_type:
                            if is_ifd_image_blanked(f, header, entries):
                                unlink_ifd(f, header, ifd_offset)
                            else:
                                w, h = get_ifd_image_size(header, entries, f)
                                blanked = blank_ifd_image_data(f, header, entries)
                                if blanked > 0:
                                    unlink_ifd(f, header, ifd_offset)
                                    cleared.append(PHIFinding(
                                        offset=ifd_offset,
                                        length=blanked,
                                        tag_id=None,
                                        tag_name=img_type,
                                        value_preview=(
                                            f'blanked {img_type} {w}x{h} '
                                            f'({blanked / 1024:.0f}KB)'),
                                        source='image_content',
                                    ))
                        break

                for entry in entries:
                    if entry.value_offset in seen:
                        continue
                    if entry.dtype == 2:  # ASCII string tags
                        seen.add(entry.value_offset)
                        value = read_tag_string(f, entry)
                        str_findings = scan_string_for_phi(value)
                        if str_findings:
                            # Overwrite entire tag value with X's + null
                            replacement = b'X' * (entry.total_size - 1) + b'\x00'
                            f.seek(entry.value_offset)
                            f.write(replacement)
                            for _, _, matched, label in str_findings:
                                cleared.append(PHIFinding(
                                    offset=entry.value_offset,
                                    length=entry.total_size,
                                    tag_id=entry.tag_id,
                                    tag_name=TAG_NAMES.get(entry.tag_id, f'Tag_{entry.tag_id}'),
                                    value_preview=matched[:50],
                                    source='tiff_tag',
                                ))

                        if entry.tag_id in GENERIC_DATE_TAGS:
                            if value and not is_date_anonymized(value):
                                f.seek(entry.value_offset)
                                f.write(b'\x00' * entry.total_size)
                                cleared.append(PHIFinding(
                                    offset=entry.value_offset,
                                    length=entry.total_size,
                                    tag_id=entry.tag_id,
                                    tag_name=TAG_NAMES.get(entry.tag_id, f'Tag_{entry.tag_id}'),
                                    value_preview=value[:30],
                                    source='tiff_tag',
                                ))

                # Extra metadata tags (XMP, EXIF UserComment, Artist, etc.)
                # Uses separate seen set so tags are blanked independently
                for entry, value in scan_extra_metadata_tags(f, header, entries):
                    if entry.value_offset in seen_extra:
                        continue
                    seen_extra.add(entry.value_offset)
                    blank_extra_metadata_tag(f, entry)
                    cleared.append(PHIFinding(
                        offset=entry.value_offset,
                        length=entry.total_size,
                        tag_id=entry.tag_id,
                        tag_name=EXTRA_METADATA_TAGS[entry.tag_id],
                        value_preview=value[:50],
                        source='tiff_tag',
                    ))

                # Blank EXIF sub-IFD PHI tags
                exif_result = read_exif_sub_ifd(f, header, entries)
                if exif_result is not None:
                    _, sub_entries = exif_result
                    for sub_entry, value in scan_exif_sub_ifd_tags(f, header, sub_entries):
                        if sub_entry.value_offset not in seen_extra:
                            seen_extra.add(sub_entry.value_offset)
                            f.seek(sub_entry.value_offset)
                            f.write(b'\x00' * sub_entry.total_size)
                            cleared.append(PHIFinding(
                                offset=sub_entry.value_offset,
                                length=sub_entry.total_size,
                                tag_id=sub_entry.tag_id,
                                tag_name=f'EXIF:{EXIF_SUB_IFD_PHI_TAGS[sub_entry.tag_id]}',
                                value_preview=value[:50],
                                source='tiff_tag',
                            ))

                # Blank GPS sub-IFD entirely
                gps_result = read_gps_sub_ifd(f, header, entries)
                if gps_result is not None:
                    _, sub_entries = gps_result
                    for sub_entry, preview in scan_gps_sub_ifd(f, header, sub_entries):
                        if sub_entry.value_offset not in seen_extra:
                            seen_extra.add(sub_entry.value_offset)
                            f.seek(sub_entry.value_offset)
                            f.write(b'\x00' * sub_entry.total_size)
                            cleared.append(PHIFinding(
                                offset=sub_entry.value_offset,
                                length=sub_entry.total_size,
                                tag_id=sub_entry.tag_id,
                                tag_name=f'GPS:{GPS_TAG_NAMES.get(sub_entry.tag_id, f"Tag_{sub_entry.tag_id}")}',
                                value_preview=preview[:50],
                                source='tiff_tag',
                            ))

        # Regex safety pass
        with open(filepath, 'rb') as f:
            data = f.read(DEFAULT_SCAN_SIZE)
        raw_findings = scan_bytes_for_phi(data, skip_offsets={c.offset for c in cleared})
        if raw_findings:
            with open(filepath, 'r+b') as f:
                for offset, length, matched, label in raw_findings:
                    val = matched.decode('ascii', errors='replace')
                    f.seek(offset)
                    f.write(b'X' * length)
                    cleared.append(PHIFinding(
                        offset=offset, length=length, tag_id=None,
                        tag_name=f'regex:{label}', value_preview=val[:50],
                        source='regex_scan',
                    ))

        return cleared

    def get_format_info(self, filepath: Path) -> Dict:
        """Get generic TIFF file metadata."""
        info = {
            'format': 'tiff',
            'filename': filepath.name,
            'file_size': os.path.getsize(filepath),
        }
        try:
            with open(filepath, 'rb') as f:
                header = read_header(f)
                if header:
                    info['byte_order'] = 'little-endian' if header.endian == '<' else 'big-endian'
                    info['is_bigtiff'] = header.is_bigtiff
                    entries, _ = read_ifd(f, header, header.first_ifd_offset)
                    info['first_ifd_tags'] = len(entries)
                    for entry in entries:
                        if entry.dtype == 2 and entry.tag_id in (271, 272, 305):
                            info[entry.tag_name.lower()] = read_tag_string(f, entry)
        except Exception as e:
            info['error'] = str(e)
        return info
