"""Generic TIFF fallback handler.

Scans all string tags across ALL IFDs for PHI patterns.
Used as a fallback when no specific handler matches.
"""

import os
import time
from pathlib import Path
from typing import Dict, List

from pathsafe.formats.tiff_base import TiffFormatHandler
from pathsafe.models import PHIFinding, ScanResult
from pathsafe.scanner import (
    scan_string_for_phi,
    is_date_anonymized,
)
from pathsafe.tiff import (
    read_header,
    read_ifd,
    read_tag_string,
    iter_ifds,
    TAG_NAMES,
)

# Tags known to potentially contain PHI in generic TIFF files
GENERIC_PHI_STRING_TAGS = {270, 271, 272, 305, 315, 316}
GENERIC_DATE_TAGS = {306, 36867, 36868}
TIFF_EXTENSIONS = {'.tif', '.tiff', '.svs', '.ndpi', '.scn', '.bif', '.vms'}


class GenericTIFFHandler(TiffFormatHandler):
    """Fallback handler for TIFF-based files not matched by specific handlers."""

    format_name = "tiff"
    # No exclusions -- scan all extra metadata tags
    extra_metadata_exclude_tags = set()

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

                # Scan all IFDs for string tags (GenericTIFF-specific)
                seen = set()
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

            # Extra metadata + EXIF/GPS (from base class)
            findings += self._scan_extra_metadata(filepath)

            # Label/macro (from base class)
            findings += self._scan_label_macro(filepath)

            # Regex safety scan (from base class)
            findings += self._scan_regex(filepath)

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

        # Label/macro blanking FIRST (from base class) -- must read tag 270
        # before string tag loop overwrites it
        cleared += self._blank_label_macro(filepath)

        # String tags (GenericTIFF-specific)
        cleared += self._anonymize_string_tags(filepath)

        # Extra metadata + EXIF/GPS (from base class)
        cleared += self._anonymize_extra_metadata(filepath)

        # Regex safety pass (from base class)
        cleared += self._anonymize_regex(filepath, {c.offset for c in cleared})

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

    # --- Internal methods (GenericTIFF-specific) ---

    def _anonymize_string_tags(self, filepath: Path) -> List[PHIFinding]:
        """Anonymize PHI found in ASCII string tags across all IFDs."""
        cleared: List[PHIFinding] = []
        seen = set()
        with open(filepath, 'r+b') as f:
            header = read_header(f)
            if header is None:
                return cleared

            for ifd_offset, entries in iter_ifds(f, header):
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
        return cleared
