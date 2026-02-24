"""Aperio SVS format handler.

Handles PHI detection and anonymization for SVS files, including:
- Tag 270 (ImageDescription): pipe-delimited key=value metadata
  containing ScanScope ID, Filename, Date, Time, User
- Tag 306 (DateTime): scan date/time
- Tags 36867/36868 (DateTimeOriginal/Digitized): EXIF dates
- Regex safety scan of first 100KB for accession patterns

SVS ImageDescription format:
  "Aperio Image Library vX.X.X\n
   WxH [x,y WxH] (tWxtH) compression|Key1 = Value1|Key2 = Value2|..."

PHI fields in ImageDescription:
  ScanScope ID, Filename, Date, Time, User
"""

import os
import re
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from pathsafe.formats.base import FormatHandler
from pathsafe.models import PHIFinding, ScanResult
from pathsafe.scanner import (
    DEFAULT_SCAN_SIZE,
    scan_bytes_for_phi,
    is_date_anonymized,
)
from pathsafe.tiff import (
    read_header,
    read_ifd,
    read_tag_string,
    read_tag_value_bytes,
    iter_ifds,
    blank_ifd_image_data,
    is_ifd_image_blanked,
    get_ifd_image_size,
    get_ifd_image_data_size,
    scan_extra_metadata_tags,
    blank_extra_metadata_tag,
    EXTRA_METADATA_TAGS,
    TAG_NAMES,
)

# Fields in SVS tag 270 that contain PHI
SVS_PHI_FIELDS = {'ScanScope ID', 'Filename', 'Date', 'Time', 'User'}

# Date/time sentinel values indicating already anonymized
ANON_DATE = '01/01/00'
ANON_TIME = '00:00:00'

DATE_TAGS = {
    306: 'DateTime',
    36867: 'DateTimeOriginal',
    36868: 'DateTimeDigitized',
}


class SVSHandler(FormatHandler):
    """Format handler for Aperio SVS files."""

    format_name = "svs"

    def can_handle(self, filepath: Path) -> bool:
        return filepath.suffix.lower() == '.svs'

    def scan(self, filepath: Path) -> ScanResult:
        """Scan SVS file for PHI — read-only."""
        t0 = time.monotonic()
        file_size = os.path.getsize(filepath)
        findings: List[PHIFinding] = []

        try:
            findings = self._scan_tag270(filepath)
            findings += self._scan_date_tags(filepath)
            findings += self._scan_extra_metadata(filepath)
            findings += self._scan_label_macro(filepath)
            tag270_offsets = {f.offset for f in findings}
            findings += self._scan_regex(filepath, skip_offsets=tag270_offsets)
        except Exception as e:
            elapsed = (time.monotonic() - t0) * 1000
            return ScanResult(
                filepath=filepath, format="svs", findings=findings,
                is_clean=len(findings) == 0, scan_time_ms=elapsed,
                file_size=file_size, error=str(e),
            )

        elapsed = (time.monotonic() - t0) * 1000
        return ScanResult(
            filepath=filepath, format="svs", findings=findings,
            is_clean=len(findings) == 0, scan_time_ms=elapsed,
            file_size=file_size,
        )

    def anonymize(self, filepath: Path) -> List[PHIFinding]:
        """Anonymize PHI in an SVS file in-place."""
        cleared: List[PHIFinding] = []
        cleared += self._anonymize_tag270(filepath)
        cleared += self._anonymize_date_tags(filepath)
        cleared += self._anonymize_extra_metadata(filepath)
        cleared += self._blank_label_macro(filepath)
        cleared += self._anonymize_regex(filepath, {f.offset for f in cleared})
        return cleared

    def get_format_info(self, filepath: Path) -> Dict:
        """Get SVS file metadata."""
        info = {
            'format': 'svs',
            'filename': filepath.name,
            'file_size': os.path.getsize(filepath),
        }
        try:
            with open(filepath, 'rb') as f:
                header = read_header(f)
                if header is None:
                    info['error'] = 'Not a valid TIFF file'
                    return info

                info['byte_order'] = 'little-endian' if header.endian == '<' else 'big-endian'
                info['is_bigtiff'] = header.is_bigtiff

                entries, _ = read_ifd(f, header, header.first_ifd_offset)
                info['first_ifd_tags'] = len(entries)

                # Parse tag 270 for non-PHI metadata
                for entry in entries:
                    if entry.tag_id == 270:
                        value = read_tag_string(f, entry)
                        fields = _parse_tag270(value)
                        for key in ('AppMag', 'MPP', 'ICC Profile'):
                            if key in fields:
                                info[key.lower().replace(' ', '_')] = fields[key]
                        # First line has the library version and dimensions
                        first_line = value.split('\n')[0] if '\n' in value else value.split('|')[0]
                        info['description_header'] = first_line.strip()[:100]
                    elif entry.dtype == 2 and entry.tag_id in (271, 272, 305):
                        info[entry.tag_name.lower()] = read_tag_string(f, entry)

                # Count pages
                page_count = 1
                offset = header.first_ifd_offset
                seen = {offset}
                _, next_offset = read_ifd(f, header, offset)
                while next_offset != 0 and page_count < 200:
                    if next_offset in seen:
                        break
                    seen.add(next_offset)
                    _, next_offset = read_ifd(f, header, next_offset)
                    page_count += 1
                info['page_count'] = page_count

        except Exception as e:
            info['error'] = str(e)
        return info

    # --- Internal methods ---

    def _scan_tag270(self, filepath: Path) -> List[PHIFinding]:
        """Scan tag 270 ImageDescription for PHI fields."""
        findings = []
        with open(filepath, 'rb') as f:
            header = read_header(f)
            if header is None:
                return findings

            entries, _ = read_ifd(f, header, header.first_ifd_offset)
            for entry in entries:
                if entry.tag_id == 270:
                    value = read_tag_string(f, entry)
                    fields = _parse_tag270(value)
                    for field_name in SVS_PHI_FIELDS:
                        if field_name not in fields:
                            continue
                        field_val = fields[field_name]
                        if _is_field_anonymized(field_name, field_val):
                            continue
                        findings.append(PHIFinding(
                            offset=entry.value_offset,
                            length=entry.total_size,
                            tag_id=270,
                            tag_name=f'ImageDescription:{field_name}',
                            value_preview=f'{field_name}={field_val[:40]}',
                            source='tiff_tag',
                        ))
        return findings

    def _scan_date_tags(self, filepath: Path) -> List[PHIFinding]:
        """Scan DateTime tags for PHI."""
        findings = []
        with open(filepath, 'rb') as f:
            header = read_header(f)
            if header is None:
                return findings

            entries, _ = read_ifd(f, header, header.first_ifd_offset)
            for entry in entries:
                if entry.tag_id in DATE_TAGS:
                    value = read_tag_string(f, entry)
                    if value and not is_date_anonymized(value):
                        findings.append(PHIFinding(
                            offset=entry.value_offset,
                            length=entry.total_size,
                            tag_id=entry.tag_id,
                            tag_name=DATE_TAGS[entry.tag_id],
                            value_preview=value[:30],
                            source='tiff_tag',
                        ))
        return findings

    def _scan_extra_metadata(self, filepath: Path) -> List[PHIFinding]:
        """Scan extra metadata tags (XMP, EXIF UserComment, Artist, etc.)."""
        findings = []
        with open(filepath, 'rb') as f:
            header = read_header(f)
            if header is None:
                return findings
            entries, _ = read_ifd(f, header, header.first_ifd_offset)
            for entry, value in scan_extra_metadata_tags(f, header, entries):
                findings.append(PHIFinding(
                    offset=entry.value_offset,
                    length=entry.total_size,
                    tag_id=entry.tag_id,
                    tag_name=EXTRA_METADATA_TAGS[entry.tag_id],
                    value_preview=value[:50],
                    source='tiff_tag',
                ))
        return findings

    def _anonymize_extra_metadata(self, filepath: Path) -> List[PHIFinding]:
        """Anonymize extra metadata tags."""
        cleared = []
        with open(filepath, 'r+b') as f:
            header = read_header(f)
            if header is None:
                return cleared
            entries, _ = read_ifd(f, header, header.first_ifd_offset)
            for entry, value in scan_extra_metadata_tags(f, header, entries):
                blank_extra_metadata_tag(f, entry)
                cleared.append(PHIFinding(
                    offset=entry.value_offset,
                    length=entry.total_size,
                    tag_id=entry.tag_id,
                    tag_name=EXTRA_METADATA_TAGS[entry.tag_id],
                    value_preview=value[:50],
                    source='tiff_tag',
                ))
        return cleared

    def _scan_regex(self, filepath: Path,
                    skip_offsets: set = None) -> List[PHIFinding]:
        """Regex safety scan of header bytes."""
        with open(filepath, 'rb') as f:
            data = f.read(DEFAULT_SCAN_SIZE)

        raw_findings = scan_bytes_for_phi(data, skip_offsets=skip_offsets)
        findings = []
        for offset, length, matched, label in raw_findings:
            value = matched.decode('ascii', errors='replace')
            findings.append(PHIFinding(
                offset=offset, length=length, tag_id=None,
                tag_name=f'regex:{label}', value_preview=value[:50],
                source='regex_scan',
            ))
        return findings

    def _scan_label_macro(self, filepath: Path) -> List[PHIFinding]:
        """Detect label and macro images that may contain photographed PHI."""
        findings = []
        with open(filepath, 'rb') as f:
            header = read_header(f)
            if header is None:
                return findings

            for ifd_offset, entries in iter_ifds(f, header):
                for entry in entries:
                    if entry.tag_id == 270:
                        desc = read_tag_string(f, entry).lower()
                        img_type = None
                        if 'label' in desc:
                            img_type = 'LabelImage'
                        elif 'macro' in desc:
                            img_type = 'MacroImage'

                        if img_type:
                            # Skip if already blanked
                            if is_ifd_image_blanked(f, header, entries):
                                break
                            w, h = get_ifd_image_size(header, entries, f)
                            data_size = get_ifd_image_data_size(
                                header, entries, f)
                            if data_size > 0:
                                findings.append(PHIFinding(
                                    offset=ifd_offset,
                                    length=data_size,
                                    tag_id=None,
                                    tag_name=img_type,
                                    value_preview=(
                                        f'{img_type} {w}x{h} '
                                        f'({data_size/1024:.0f}KB)'),
                                    source='image_content',
                                ))
                        break  # Only check tag 270 per IFD
        return findings

    def _blank_label_macro(self, filepath: Path) -> List[PHIFinding]:
        """Blank label and macro image data."""
        cleared = []
        with open(filepath, 'r+b') as f:
            header = read_header(f)
            if header is None:
                return cleared

            for ifd_offset, entries in iter_ifds(f, header):
                for entry in entries:
                    if entry.tag_id == 270:
                        desc = read_tag_string(f, entry).lower()
                        img_type = None
                        if 'label' in desc:
                            img_type = 'LabelImage'
                        elif 'macro' in desc:
                            img_type = 'MacroImage'

                        if img_type:
                            if is_ifd_image_blanked(f, header, entries):
                                break
                            w, h = get_ifd_image_size(header, entries, f)
                            blanked = blank_ifd_image_data(
                                f, header, entries)
                            if blanked > 0:
                                cleared.append(PHIFinding(
                                    offset=ifd_offset,
                                    length=blanked,
                                    tag_id=None,
                                    tag_name=img_type,
                                    value_preview=(
                                        f'blanked {img_type} {w}x{h} '
                                        f'({blanked/1024:.0f}KB)'),
                                    source='image_content',
                                ))
                        break
        return cleared

    def _anonymize_tag270(self, filepath: Path) -> List[PHIFinding]:
        """Anonymize PHI fields in tag 270 ImageDescription."""
        cleared = []
        with open(filepath, 'r+b') as f:
            header = read_header(f)
            if header is None:
                return cleared

            entries, _ = read_ifd(f, header, header.first_ifd_offset)
            for entry in entries:
                if entry.tag_id == 270:
                    raw = read_tag_value_bytes(f, entry)
                    value = raw.rstrip(b'\x00').decode('ascii', errors='replace')
                    fields = _parse_tag270(value)

                    modified = False
                    new_value = value
                    for field_name in SVS_PHI_FIELDS:
                        if field_name not in fields:
                            continue
                        field_val = fields[field_name]
                        if _is_field_anonymized(field_name, field_val):
                            continue

                        # Replace field value with X's of same length
                        anon_val = _anonymize_field(field_name, field_val)
                        new_value = new_value.replace(
                            f'{field_name} = {field_val}',
                            f'{field_name} = {anon_val}',
                            1,
                        )
                        modified = True
                        cleared.append(PHIFinding(
                            offset=entry.value_offset,
                            length=entry.total_size,
                            tag_id=270,
                            tag_name=f'ImageDescription:{field_name}',
                            value_preview=f'{field_name}={field_val[:40]}',
                            source='tiff_tag',
                        ))

                    if modified:
                        new_bytes = new_value.encode('ascii', errors='replace')
                        # Pad/truncate to original size
                        if len(new_bytes) < entry.total_size:
                            new_bytes += b'\x00' * (entry.total_size - len(new_bytes))
                        else:
                            new_bytes = new_bytes[:entry.total_size - 1] + b'\x00'
                        f.seek(entry.value_offset)
                        f.write(new_bytes)
        return cleared

    def _anonymize_date_tags(self, filepath: Path) -> List[PHIFinding]:
        """Anonymize DateTime tags."""
        cleared = []
        with open(filepath, 'r+b') as f:
            header = read_header(f)
            if header is None:
                return cleared

            entries, _ = read_ifd(f, header, header.first_ifd_offset)
            for entry in entries:
                if entry.tag_id in DATE_TAGS:
                    value = read_tag_string(f, entry)
                    if value and not is_date_anonymized(value):
                        f.seek(entry.value_offset)
                        f.write(b'\x00' * entry.total_size)
                        cleared.append(PHIFinding(
                            offset=entry.value_offset,
                            length=entry.total_size,
                            tag_id=entry.tag_id,
                            tag_name=DATE_TAGS[entry.tag_id],
                            value_preview=value[:30],
                            source='tiff_tag',
                        ))
        return cleared

    def _anonymize_regex(self, filepath: Path,
                         skip_offsets: set) -> List[PHIFinding]:
        """Regex safety scan + anonymize stragglers."""
        with open(filepath, 'rb') as f:
            data = f.read(DEFAULT_SCAN_SIZE)

        raw_findings = scan_bytes_for_phi(data, skip_offsets=skip_offsets)
        if not raw_findings:
            return []

        cleared = []
        with open(filepath, 'r+b') as f:
            for offset, length, matched, label in raw_findings:
                value = matched.decode('ascii', errors='replace')
                f.seek(offset)
                f.write(b'X' * length)
                cleared.append(PHIFinding(
                    offset=offset, length=length, tag_id=None,
                    tag_name=f'regex:{label}', value_preview=value[:50],
                    source='regex_scan',
                ))
        return cleared


def _parse_tag270(value: str) -> Dict[str, str]:
    """Parse SVS tag 270 ImageDescription into key=value dict.

    Format: "Header line\nDimensions compression|Key1 = Val1|Key2 = Val2|..."
    """
    fields = {}
    # Split on pipe delimiter
    parts = value.split('|')
    for part in parts[1:]:  # Skip the header/dimensions part
        if '=' in part:
            key, _, val = part.partition('=')
            fields[key.strip()] = val.strip()
    return fields


def _is_field_anonymized(field_name: str, value: str) -> bool:
    """Check if a field value has already been anonymized."""
    if not value or value.strip() == '':
        return True
    if all(c == 'X' for c in value):
        return True
    if field_name == 'Date' and value == ANON_DATE:
        return True
    if field_name == 'Time' and value == ANON_TIME:
        return True
    return False


def _anonymize_field(field_name: str, value: str) -> str:
    """Generate anonymized replacement for a field value.

    Uses X's for string fields, sentinel values for date/time.
    """
    if field_name == 'Date':
        return ANON_DATE
    if field_name == 'Time':
        return ANON_TIME
    return 'X' * len(value)
