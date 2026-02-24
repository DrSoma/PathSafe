"""Hamamatsu NDPI format handler.

Handles PHI detection and anonymization for NDPI files, including:
- Tag 65468 (NDPI_BARCODE): accession numbers
- Tag 65427 (NDPI_REFERENCE): reference strings
- Tag 65449 (NDPI_SCANNER_PROPS): scanner properties with dates and serials
- Tag 306 (DateTime): scan date/time
- Tags 36867/36868 (DateTimeOriginal/Digitized): EXIF dates
- Regex safety scan of first 100KB for accession patterns

All IFDs are scanned with seen_offsets dedup — most NDPI pages share
the same tag byte offset, but some tags may differ across IFDs.

Corrupt file fallback: if TIFF structure is invalid, falls back to raw
binary search of the entire header.

Proven on 3,101+ NDPI files across 9 LungAI batches.
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
    is_date_anonymized,
)
from pathsafe.tiff import (
    IFDEntry,
    read_header,
    read_ifd,
    read_tag_string,
    read_tag_value_bytes,
    read_tag_numeric,
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

# NDPI tags that may contain PHI
PHI_TAGS = {
    65468: 'NDPI_BARCODE',
    65427: 'NDPI_REFERENCE',
    65442: 'NDPI_SERIAL_NUMBER',
}

DATE_TAGS = {
    306: 'DateTime',
    36867: 'DateTimeOriginal',
    36868: 'DateTimeDigitized',
}

ALL_PHI_TAGS = {**PHI_TAGS, **DATE_TAGS}

# Tag 65449 (NDPI_SCANNER_PROPS): key=value property map
# These keys contain dates or serial numbers that are indirect identifiers
NDPI_SCANNER_PROPS_TAG = 65449
SCANNER_PROPS_PHI_KEYS = {
    'Created',          # Scan date (e.g., "2022/04/28")
    'Updated',          # Modification date
    'NDP.S/N',          # Scanner serial number
    'Macro.S/N',        # Macro camera serial number
    'Firmware.Version',  # Device fingerprint
}
# Dynamic substrings: any key containing these words is treated as PHI
_SCANNER_PROPS_DYNAMIC_SUBSTRINGS = {'User', 'Name', 'Operator'}

# NDPI_SOURCELENS values for special (non-slide) images
NDPI_SOURCELENS_TAG = 65421
NDPI_MACRO_LENS = -1.0   # Map/overview image
NDPI_BARCODE_LENS = -2.0  # Barcode area image


class NDPIHandler(FormatHandler):
    """Format handler for Hamamatsu NDPI files."""

    format_name = "ndpi"

    def can_handle(self, filepath: Path) -> bool:
        return filepath.suffix.lower() == '.ndpi'

    def scan(self, filepath: Path) -> ScanResult:
        """Scan NDPI file for PHI — read-only."""
        t0 = time.monotonic()
        file_size = os.path.getsize(filepath)
        findings: List[PHIFinding] = []

        try:
            tag_findings = self._scan_tags(filepath)
            label_findings = self._scan_label_macro(filepath)
            companion_findings = self._scan_companion_files(filepath)
            tag_offsets = {f.offset for f in tag_findings}
            regex_findings = self._scan_regex(filepath, skip_offsets=tag_offsets)
            filename_findings = self.scan_filename(filepath)
            findings = tag_findings + label_findings + companion_findings + regex_findings + filename_findings
        except Exception as e:
            # Try fallback on corrupt files
            try:
                findings = self._scan_fallback(filepath)
            except Exception:
                pass
            if not findings:
                # Could not scan properly — do NOT report as clean
                elapsed = (time.monotonic() - t0) * 1000
                return ScanResult(
                    filepath=filepath, format="ndpi", findings=[],
                    is_clean=False, scan_time_ms=elapsed,
                    file_size=file_size, error=str(e),
                )

        elapsed = (time.monotonic() - t0) * 1000
        return ScanResult(
            filepath=filepath, format="ndpi", findings=findings,
            is_clean=len(findings) == 0, scan_time_ms=elapsed,
            file_size=file_size,
        )

    def anonymize(self, filepath: Path) -> List[PHIFinding]:
        """Anonymize PHI in an NDPI file in-place."""
        cleared: List[PHIFinding] = []

        try:
            cleared += self._anonymize_tags(filepath)
        except Exception:
            # Fallback for corrupt TIFF structure — regex-based anonymization
            cleared += self._anonymize_fallback(filepath)

        # Label/macro blanking must always be attempted, even if tag
        # anonymization failed above — labels contain photographed PHI
        try:
            cleared += self._blank_label_macro(filepath)
        except Exception:
            pass  # Label blanking failed — file may have corrupt IFD structure

        cleared += self._anonymize_companion_files(filepath)
        cleared += self._anonymize_regex(filepath, {f.offset for f in cleared})
        return cleared

    def get_format_info(self, filepath: Path) -> Dict:
        """Get NDPI file metadata."""
        info = {
            'format': 'ndpi',
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

                entries, next_offset = read_ifd(f, header, header.first_ifd_offset)
                info['first_ifd_tags'] = len(entries)

                # Count pages
                page_count = 1
                offset = next_offset
                seen = {header.first_ifd_offset}
                while offset != 0 and page_count < 200:
                    if offset in seen:
                        break
                    seen.add(offset)
                    _, next_offset = read_ifd(f, header, offset)
                    page_count += 1
                    offset = next_offset
                info['page_count'] = page_count

                # Read key string tags
                for entry in entries:
                    if entry.dtype == 2 and entry.tag_id in (271, 272, 305):
                        info[entry.tag_name.lower()] = read_tag_string(f, entry)

        except Exception as e:
            info['error'] = str(e)

        return info

    # --- Internal methods ---

    def _scan_tags(self, filepath: Path) -> List[PHIFinding]:
        """Scan NDPI TIFF tags for PHI across ALL IFDs.

        Uses seen_offsets dedup because NDPI files often share tag byte
        offsets across IFDs, but some tags may have distinct offsets in
        different IFDs (especially on newer scanner firmware).
        """
        findings = []
        seen_offsets = set()
        with open(filepath, 'rb') as f:
            header = read_header(f)
            if header is None:
                raise ValueError(f"Not a valid TIFF file: {filepath}")

            for _, entries in iter_ifds(f, header):
                for entry in entries:
                    if entry.value_offset in seen_offsets:
                        continue
                    if entry.tag_id in PHI_TAGS:
                        seen_offsets.add(entry.value_offset)
                        value = read_tag_string(f, entry)
                        if value and value != 'X' * len(value):
                            findings.append(PHIFinding(
                                offset=entry.value_offset,
                                length=entry.total_size,
                                tag_id=entry.tag_id,
                                tag_name=PHI_TAGS[entry.tag_id],
                                value_preview=value[:50],
                                source='tiff_tag',
                            ))
                    elif entry.tag_id in DATE_TAGS:
                        seen_offsets.add(entry.value_offset)
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
                    elif entry.tag_id == NDPI_SCANNER_PROPS_TAG:
                        seen_offsets.add(entry.value_offset)
                        findings += self._scan_scanner_props(f, entry)

                # Scan extra metadata tags (XMP, EXIF UserComment, Artist, etc.)
                for entry, value in scan_extra_metadata_tags(f, header, entries):
                    if entry.value_offset in seen_offsets:
                        continue
                    seen_offsets.add(entry.value_offset)
                    findings.append(PHIFinding(
                        offset=entry.value_offset,
                        length=entry.total_size,
                        tag_id=entry.tag_id,
                        tag_name=EXTRA_METADATA_TAGS[entry.tag_id],
                        value_preview=value[:50],
                        source='tiff_tag',
                    ))
        return findings

    def _scan_scanner_props(self, f, entry: IFDEntry) -> List[PHIFinding]:
        """Scan NDPI_SCANNER_PROPS (tag 65449) for PHI key-value pairs."""
        findings = []
        value = read_tag_string(f, entry)
        if not value:
            return findings

        for line in value.split('\n'):
            if '=' not in line:
                continue
            key, _, val = line.partition('=')
            key = key.strip()
            val = val.strip()
            if _is_scanner_prop_phi(key) and val and val != 'X' * len(val):
                findings.append(PHIFinding(
                    offset=entry.value_offset,
                    length=entry.total_size,
                    tag_id=NDPI_SCANNER_PROPS_TAG,
                    tag_name=f'NDPI_SCANNER_PROPS:{key}',
                    value_preview=val[:40],
                    source='tiff_tag',
                ))
        return findings

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

    def _scan_fallback(self, filepath: Path) -> List[PHIFinding]:
        """Fallback scan when TIFF structure is corrupt."""
        with open(filepath, 'rb') as f:
            data = f.read(DEFAULT_SCAN_SIZE)

        raw_findings = scan_bytes_for_phi(data)
        findings = []
        for offset, length, matched, label in raw_findings:
            value = matched.decode('ascii', errors='replace')
            findings.append(PHIFinding(
                offset=offset, length=length, tag_id=None,
                tag_name=f'fallback:{label}', value_preview=value[:50],
                source='regex_scan',
            ))
        return findings

    def _scan_label_macro(self, filepath: Path) -> List[PHIFinding]:
        """Detect macro and barcode images that may contain photographed PHI.

        NDPI_SOURCELENS (tag 65421) identifies special pages:
          -1.0 = macro/overview image
          -2.0 = barcode area image
        """
        findings = []
        with open(filepath, 'rb') as f:
            header = read_header(f)
            if header is None:
                return findings

            for ifd_offset, entries in iter_ifds(f, header):
                for entry in entries:
                    if entry.tag_id == NDPI_SOURCELENS_TAG:
                        lens = read_tag_numeric(f, header, entry)
                        if lens is None:
                            break
                        lens_f = float(lens)
                        img_type = None
                        if lens_f == NDPI_MACRO_LENS:
                            img_type = 'MacroImage'
                        elif lens_f == NDPI_BARCODE_LENS:
                            img_type = 'LabelImage'

                        if img_type:
                            # Skip if already blanked
                            if is_ifd_image_blanked(f, header, entries):
                                break
                            w, h = get_ifd_image_size(
                                header, entries, f)
                            data_size = get_ifd_image_data_size(
                                header, entries, f)
                            if data_size > 0:
                                findings.append(PHIFinding(
                                    offset=ifd_offset,
                                    length=data_size,
                                    tag_id=NDPI_SOURCELENS_TAG,
                                    tag_name=img_type,
                                    value_preview=(
                                        f'{img_type} {w}x{h} '
                                        f'({data_size/1024:.0f}KB)'),
                                    source='image_content',
                                ))
                        break
        return findings

    def _blank_label_macro(self, filepath: Path) -> List[PHIFinding]:
        """Blank macro and barcode image data."""
        cleared = []
        with open(filepath, 'r+b') as f:
            header = read_header(f)
            if header is None:
                return cleared

            for ifd_offset, entries in iter_ifds(f, header):
                for entry in entries:
                    if entry.tag_id == NDPI_SOURCELENS_TAG:
                        lens = read_tag_numeric(f, header, entry)
                        if lens is None:
                            break
                        lens_f = float(lens)
                        img_type = None
                        if lens_f == NDPI_MACRO_LENS:
                            img_type = 'MacroImage'
                        elif lens_f == NDPI_BARCODE_LENS:
                            img_type = 'LabelImage'

                        if img_type:
                            if is_ifd_image_blanked(f, header, entries):
                                break
                            w, h = get_ifd_image_size(
                                header, entries, f)
                            blanked = blank_ifd_image_data(
                                f, header, entries)
                            if blanked > 0:
                                cleared.append(PHIFinding(
                                    offset=ifd_offset,
                                    length=blanked,
                                    tag_id=NDPI_SOURCELENS_TAG,
                                    tag_name=img_type,
                                    value_preview=(
                                        f'blanked {img_type} {w}x{h} '
                                        f'({blanked/1024:.0f}KB)'),
                                    source='image_content',
                                ))
                        break
        return cleared

    def _anonymize_tags(self, filepath: Path) -> List[PHIFinding]:
        """Anonymize TIFF tags containing PHI across ALL IFDs.

        Uses seen_offsets dedup to avoid double-writing shared tag data.
        """
        cleared = []
        seen_offsets = set()
        with open(filepath, 'r+b') as f:
            header = read_header(f)
            if header is None:
                return cleared

            for _, entries in iter_ifds(f, header):
                for entry in entries:
                    if entry.value_offset in seen_offsets:
                        continue
                    if entry.tag_id in PHI_TAGS:
                        seen_offsets.add(entry.value_offset)
                        current = read_tag_value_bytes(f, entry)
                        replacement = b'X' * (entry.total_size - 1) + b'\x00'
                        if current == replacement:
                            continue
                        value = current.rstrip(b'\x00').decode('ascii', errors='replace')
                        f.seek(entry.value_offset)
                        f.write(replacement)
                        cleared.append(PHIFinding(
                            offset=entry.value_offset,
                            length=entry.total_size,
                            tag_id=entry.tag_id,
                            tag_name=PHI_TAGS[entry.tag_id],
                            value_preview=value[:50],
                            source='tiff_tag',
                        ))
                    elif entry.tag_id in DATE_TAGS:
                        seen_offsets.add(entry.value_offset)
                        current = read_tag_value_bytes(f, entry)
                        value = current.rstrip(b'\x00').decode('ascii', errors='replace')
                        if is_date_anonymized(value):
                            continue
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
                    elif entry.tag_id == NDPI_SCANNER_PROPS_TAG:
                        seen_offsets.add(entry.value_offset)
                        cleared += self._anonymize_scanner_props(f, entry)

                # Blank extra metadata tags (XMP, EXIF UserComment, Artist, etc.)
                for entry, value in scan_extra_metadata_tags(f, header, entries):
                    if entry.value_offset in seen_offsets:
                        continue
                    seen_offsets.add(entry.value_offset)
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

    def _anonymize_scanner_props(self, f, entry: IFDEntry) -> List[PHIFinding]:
        """Anonymize PHI keys in NDPI_SCANNER_PROPS (tag 65449)."""
        cleared = []
        raw = read_tag_value_bytes(f, entry)
        value = raw.rstrip(b'\x00').decode('ascii', errors='replace')
        if not value:
            return cleared

        modified = False
        new_lines = []
        for line in value.split('\n'):
            if '=' not in line:
                new_lines.append(line)
                continue
            key, _, val = line.partition('=')
            key_stripped = key.strip()
            val_stripped = val.strip()
            if _is_scanner_prop_phi(key_stripped) and val_stripped and val_stripped != 'X' * len(val_stripped):
                anon_val = 'X' * len(val_stripped)
                new_lines.append(f'{key}={anon_val}')
                modified = True
                cleared.append(PHIFinding(
                    offset=entry.value_offset,
                    length=entry.total_size,
                    tag_id=NDPI_SCANNER_PROPS_TAG,
                    tag_name=f'NDPI_SCANNER_PROPS:{key_stripped}',
                    value_preview=val_stripped[:40],
                    source='tiff_tag',
                ))
            else:
                new_lines.append(line)

        if modified:
            new_bytes = '\n'.join(new_lines).encode('ascii', errors='replace')
            # Pad to original size
            if len(new_bytes) < entry.total_size:
                new_bytes += b'\x00' * (entry.total_size - len(new_bytes))
            else:
                new_bytes = new_bytes[:entry.total_size - 1] + b'\x00'
            f.seek(entry.value_offset)
            f.write(new_bytes)
        return cleared

    def _anonymize_regex(self, filepath: Path,
                         skip_offsets: set) -> List[PHIFinding]:
        """Regex safety scan + anonymize any stragglers."""
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

    def _anonymize_fallback(self, filepath: Path) -> List[PHIFinding]:
        """Fallback anonymization for corrupt TIFF files."""
        with open(filepath, 'rb') as f:
            data = f.read(DEFAULT_SCAN_SIZE)

        raw_findings = scan_bytes_for_phi(data)
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
                    tag_name=f'fallback:{label}', value_preview=value[:50],
                    source='regex_scan',
                ))
        return cleared

    def _scan_companion_files(self, filepath: Path) -> List[PHIFinding]:
        """Detect companion files that may contain PHI.

        Hamamatsu scanners produce several companion file types:
        - .ndpa: XML annotation files (patient IDs, case numbers, timestamps)
        - .ndpis: slide show / annotation session files
        - _N.ndpa: per-user annotation files (e.g., slide.ndpi_1.ndpa)
        """
        findings = []
        for companion in _find_companion_files(filepath):
            findings.append(PHIFinding(
                offset=0, length=os.path.getsize(companion),
                tag_id=None,
                tag_name=f'CompanionFile:{companion.suffix.lstrip(".")}',
                value_preview=f'{companion.name} (may contain PHI)',
                source='companion_file',
            ))
        return findings

    def _anonymize_companion_files(self, filepath: Path) -> List[PHIFinding]:
        """Delete companion files that contain PHI."""
        cleared = []
        for companion in _find_companion_files(filepath):
            size = os.path.getsize(companion)
            companion.unlink()
            cleared.append(PHIFinding(
                offset=0, length=size, tag_id=None,
                tag_name=f'CompanionFile:{companion.suffix.lstrip(".")}',
                value_preview=f'deleted {companion.name}',
                source='companion_file',
            ))
        return cleared


def _is_scanner_prop_phi(key: str) -> bool:
    """Check if a scanner property key is a PHI indicator."""
    if key in SCANNER_PROPS_PHI_KEYS:
        return True
    return any(sub in key for sub in _SCANNER_PROPS_DYNAMIC_SUBSTRINGS)


def _find_companion_files(filepath: Path) -> List[Path]:
    """Find all companion files for an NDPI file.

    Searches for:
    - slide.ndpi.ndpa (primary annotations)
    - slide.ndpi_1.ndpa, slide.ndpi_2.ndpa, ... (per-user annotations)
    - slide.ndpi.ndpis (slide show sessions)
    """
    companions = []
    parent = filepath.parent
    name = filepath.name  # e.g., "slide.ndpi"

    # Exact companion: slide.ndpi.ndpa, slide.ndpi.ndpis
    for ext in ('.ndpa', '.ndpis'):
        candidate = parent / (name + ext)
        if candidate.exists():
            companions.append(candidate)

    # Multi-annotation: slide.ndpi_1.ndpa, slide.ndpi_2.ndpa, ...
    for candidate in sorted(parent.glob(f'{name}_*.ndpa')):
        companions.append(candidate)

    return companions
