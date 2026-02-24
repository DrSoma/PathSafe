"""Leica SCN format handler.

Handles PHI detection and anonymization for SCN (BigTIFF) files, including:
- ImageDescription tag (270): XML metadata in Leica namespace containing
  barcode, creationDate, device info
- Standard TIFF tags: DateTime (306), Software (305), etc.
- Label/macro images: stored as separate TIFF IFDs

SCN structure:
  Single BigTIFF file with pyramidal tiled image + associated images.
  ImageDescription contains XML with Leica-specific namespace.
"""

import os
import re
import time
from pathlib import Path
from typing import Dict, List, Optional

from pathsafe.formats.tiff_base import TiffFormatHandler
from pathsafe.models import PHIFinding, ScanResult
from pathsafe.tiff import (
    read_header,
    read_tag_value_bytes,
    iter_ifds,
)

# XML elements/attributes in Leica SCN ImageDescription that contain PHI
SCN_PHI_ELEMENTS = {
    'barcode', 'creationDate', 'device', 'model', 'version',
    'slideName', 'description', 'user', 'operator',
    'institution', 'uniqueID', 'serialNumber',
    'acquisitionDate', 'acquisitionTime',
}

DATE_TAGS = {
    306: 'DateTime',
    36867: 'DateTimeOriginal',
    36868: 'DateTimeDigitized',
}


class SCNHandler(TiffFormatHandler):
    """Format handler for Leica SCN files."""

    format_name = "scn"
    extra_metadata_exclude_tags = {270}

    def can_handle(self, filepath: Path) -> bool:
        if filepath.suffix.lower() != '.scn':
            return False
        try:
            with open(filepath, 'rb') as f:
                header = read_header(f)
                return header is not None
        except OSError:
            return False

    def scan(self, filepath: Path) -> ScanResult:
        """Scan SCN file for PHI -- read-only."""
        t0 = time.monotonic()
        file_size = os.path.getsize(filepath)
        findings: List[PHIFinding] = []

        try:
            findings += self._scan_xml_metadata(filepath)
            findings += self._scan_datetime_tags(filepath)
            findings += self._scan_extra_metadata(filepath)
            findings += self._scan_label_macro(filepath)
            findings += self._scan_regex(filepath)
            findings += self.scan_filename(filepath)
        except Exception as e:
            elapsed = (time.monotonic() - t0) * 1000
            return ScanResult(
                filepath=filepath, format="scn", findings=findings,
                is_clean=False, scan_time_ms=elapsed,
                file_size=file_size, error=str(e),
            )

        elapsed = (time.monotonic() - t0) * 1000
        return ScanResult(
            filepath=filepath, format="scn", findings=findings,
            is_clean=len(findings) == 0, scan_time_ms=elapsed,
            file_size=file_size,
        )

    def anonymize(self, filepath: Path) -> List[PHIFinding]:
        """Anonymize PHI in an SCN file in-place."""
        cleared: List[PHIFinding] = []
        cleared += self._anonymize_xml_metadata(filepath)
        cleared += self._anonymize_datetime_tags(filepath)
        cleared += self._anonymize_extra_metadata(filepath)
        cleared += self._blank_label_macro(filepath)
        cleared += self._anonymize_regex(filepath, {f.offset for f in cleared})
        return cleared

    def get_format_info(self, filepath: Path) -> Dict:
        """Get SCN file metadata."""
        info = {
            'format': 'scn',
            'filename': filepath.name,
            'file_size': os.path.getsize(filepath),
        }
        try:
            with open(filepath, 'rb') as f:
                header = read_header(f)
                if header:
                    info['byte_order'] = 'little-endian' if header.endian == '<' else 'big-endian'
                    info['is_bigtiff'] = header.is_bigtiff
                    ifd_count = len(iter_ifds(f, header))
                    info['page_count'] = ifd_count
        except Exception as e:
            info['error'] = str(e)
        return info

    # --- Internal methods (SCN-specific) ---

    def _scan_xml_metadata(self, filepath: Path) -> List[PHIFinding]:
        """Scan ImageDescription XML for PHI elements across all IFDs."""
        findings = []
        seen = set()
        with open(filepath, 'rb') as f:
            header = read_header(f)
            if header is None:
                return findings

            for _, entries in iter_ifds(f, header):
                for entry in entries:
                    if entry.tag_id == 270 and entry.value_offset not in seen:
                        seen.add(entry.value_offset)
                        raw = read_tag_value_bytes(f, entry)
                        xml_text = raw.rstrip(b'\x00').decode('utf-8', errors='replace')

                        if '<' not in xml_text:
                            break  # Not XML

                        for elem_name in SCN_PHI_ELEMENTS:
                            # Match <element>value</element> pattern
                            pattern = re.compile(
                                rf'<{elem_name}[^>]*>([^<]+)</{elem_name}>',
                                re.IGNORECASE)
                            for m in pattern.finditer(xml_text):
                                val = m.group(1).strip()
                                if val and not _is_scn_anonymized(val):
                                    findings.append(PHIFinding(
                                        offset=entry.value_offset,
                                        length=entry.total_size,
                                        tag_id=270,
                                        tag_name=f'SCN:XML:{elem_name}',
                                        value_preview=f'{elem_name}={val[:40]}',
                                        source='tiff_tag',
                                    ))

                            # Match attribute= pattern (e.g., barcode="...")
                            pattern2 = re.compile(
                                rf'{elem_name}\s*=\s*"([^"]*)"', re.IGNORECASE)
                            for m in pattern2.finditer(xml_text):
                                # Skip matches inside XML processing instructions (<?...?>)
                                prefix = xml_text[:m.start()]
                                if prefix.rfind('<?') > prefix.rfind('?>'):
                                    continue
                                val = m.group(1).strip()
                                if val and not _is_scn_anonymized(val):
                                    findings.append(PHIFinding(
                                        offset=entry.value_offset,
                                        length=entry.total_size,
                                        tag_id=270,
                                        tag_name=f'SCN:XML:{elem_name}',
                                        value_preview=f'{elem_name}={val[:40]}',
                                        source='tiff_tag',
                                    ))
                        break  # Only one tag 270 per IFD
        return findings

    def _anonymize_xml_metadata(self, filepath: Path) -> List[PHIFinding]:
        """Anonymize PHI in ImageDescription XML across all IFDs."""
        cleared = []
        seen = set()
        with open(filepath, 'r+b') as f:
            header = read_header(f)
            if header is None:
                return cleared

            for _, entries in iter_ifds(f, header):
                for entry in entries:
                    if entry.tag_id == 270 and entry.value_offset not in seen:
                        seen.add(entry.value_offset)
                        raw = read_tag_value_bytes(f, entry)
                        xml_text = raw.rstrip(b'\x00').decode('utf-8', errors='replace')

                        if '<' not in xml_text:
                            break

                        modified = False
                        for elem_name in SCN_PHI_ELEMENTS:
                            # Replace element content
                            pattern = re.compile(
                                rf'(<{elem_name}[^>]*>)([^<]+)(</{elem_name}>)',
                                re.IGNORECASE)

                            def _replace_elem(m):
                                val = m.group(2)
                                if val.strip() and not _is_scn_anonymized(val.strip()):
                                    return m.group(1) + 'X' * len(val) + m.group(3)
                                return m.group(0)

                            new_text, count = pattern.subn(_replace_elem, xml_text)
                            if count > 0 and new_text != xml_text:
                                xml_text = new_text
                                modified = True
                                cleared.append(PHIFinding(
                                    offset=entry.value_offset,
                                    length=entry.total_size,
                                    tag_id=270,
                                    tag_name=f'SCN:XML:{elem_name}',
                                    value_preview=f'{elem_name} anonymized',
                                    source='tiff_tag',
                                ))

                            # Replace attribute values
                            pattern2 = re.compile(
                                rf'({elem_name}\s*=\s*")([^"]*?)(")',
                                re.IGNORECASE)

                            def _replace_attr(m):
                                # Skip matches inside XML processing instructions (<?...?>)
                                prefix = xml_text[:m.start()]
                                if prefix.rfind('<?') > prefix.rfind('?>'):
                                    return m.group(0)
                                val = m.group(2)
                                if val and not _is_scn_anonymized(val):
                                    return m.group(1) + 'X' * len(val) + m.group(3)
                                return m.group(0)

                            new_text, count = pattern2.subn(_replace_attr, xml_text)
                            if count > 0 and new_text != xml_text:
                                xml_text = new_text
                                modified = True

                        if modified:
                            new_bytes = xml_text.encode('utf-8', errors='replace')
                            if len(new_bytes) < entry.total_size:
                                new_bytes += b'\x00' * (entry.total_size - len(new_bytes))
                            else:
                                new_bytes = new_bytes[:entry.total_size]
                            f.seek(entry.value_offset)
                            f.write(new_bytes)
                        break  # Only one tag 270 per IFD
        return cleared


def _is_scn_anonymized(value: str) -> bool:
    """Check if an SCN XML value has already been anonymized."""
    if not value:
        return True
    if all(c == 'X' for c in value):
        return True
    return False
