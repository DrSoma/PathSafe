"""Roche/Ventana BIF format handler.

Handles PHI detection and anonymization for BIF (BigTIFF) files, including:
- XMP tag (700): XML metadata with iScan element containing barcodes,
  scan dates, unique IDs, base filename
- Standard TIFF tags: DateTime (306), Software (305), etc.
- Label/macro images: IFDs with ImageDescription "Label Image" or
  "Label_Image" (Ventana naming convention)

BIF structure:
  Single BigTIFF file with pyramidal tiled image + associated images.
  XMP metadata contains <iScan> element with vendor attributes.
"""

import os
import re
import time
from pathlib import Path
from typing import BinaryIO, Dict, List, Optional

from pathsafe.formats.tiff_base import TiffFormatHandler
from pathsafe.models import PHIFinding, ScanResult
from pathsafe.tiff import (
    read_header,
    read_tag_string,
    read_tag_value_bytes,
    iter_ifds,
)

# XMP attributes in <iScan> that contain PHI
XMP_PHI_ATTRIBUTES = {
    'BarCode1', 'BarCode2', 'BarCodeType1', 'BarCodeType2',
    'ScanDate', 'ScanTime', 'BaseFileName',
    'UniqueID', 'DeviceSerialNumber', 'OperatorID',
    # Additional Ventana iScan attributes that may contain PHI
    'PatientName', 'CaseID', 'SampleID',
    'LabelText', 'Comment', 'Description',
}

DATE_TAGS = {
    306: 'DateTime',
    36867: 'DateTimeOriginal',
    36868: 'DateTimeDigitized',
}


class BIFHandler(TiffFormatHandler):
    """Format handler for Roche/Ventana BIF files."""

    format_name = "bif"
    extra_metadata_exclude_tags = {270, 700}

    def can_handle(self, filepath: Path) -> bool:
        if filepath.suffix.lower() != '.bif':
            return False
        try:
            with open(filepath, 'rb') as f:
                header = read_header(f)
                return header is not None
        except OSError:
            return False

    def scan(self, filepath: Path) -> ScanResult:
        """Scan BIF file for PHI -- read-only."""
        t0 = time.monotonic()
        file_size = os.path.getsize(filepath)
        findings: List[PHIFinding] = []

        try:
            findings += self._scan_xmp(filepath)
            findings += self._scan_datetime_tags(filepath)
            findings += self._scan_extra_metadata(filepath)
            findings += self._scan_label_macro(filepath)
            findings += self._scan_regex(filepath)
            findings += self.scan_filename(filepath)
        except Exception as e:
            elapsed = (time.monotonic() - t0) * 1000
            return ScanResult(
                filepath=filepath, format="bif", findings=findings,
                is_clean=False, scan_time_ms=elapsed,
                file_size=file_size, error=str(e),
            )

        elapsed = (time.monotonic() - t0) * 1000
        return ScanResult(
            filepath=filepath, format="bif", findings=findings,
            is_clean=len(findings) == 0, scan_time_ms=elapsed,
            file_size=file_size,
        )

    def anonymize(self, filepath: Path) -> List[PHIFinding]:
        """Anonymize PHI in a BIF file in-place."""
        cleared: List[PHIFinding] = []
        cleared += self._anonymize_xmp(filepath)
        cleared += self._anonymize_datetime_tags(filepath)
        cleared += self._anonymize_extra_metadata(filepath)
        cleared += self._blank_label_macro(filepath)
        cleared += self._anonymize_regex(filepath, {f.offset for f in cleared})
        return cleared

    def get_format_info(self, filepath: Path) -> Dict:
        """Get BIF file metadata."""
        info = {
            'format': 'bif',
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

    # --- BIF-specific overrides ---

    def _detect_label_macro_type(self, f: BinaryIO, entries: List) -> Optional[str]:
        """BIF also detects 'thumbnail' images in tag 270."""
        for entry in entries:
            if entry.tag_id == 270:
                desc = read_tag_string(f, entry).lower()
                if 'label' in desc:
                    return 'LabelImage'
                elif 'macro' in desc:
                    return 'MacroImage'
                elif 'thumbnail' in desc:
                    return 'ThumbnailImage'
                return None
        return None

    # --- Internal methods (BIF-specific) ---

    def _scan_xmp(self, filepath: Path) -> List[PHIFinding]:
        """Scan XMP tag (700) for PHI in <iScan> attributes across all IFDs."""
        findings = []
        seen = set()
        with open(filepath, 'rb') as f:
            header = read_header(f)
            if header is None:
                return findings

            for _, entries in iter_ifds(f, header):
                for entry in entries:
                    if entry.tag_id == 700 and entry.value_offset not in seen:
                        seen.add(entry.value_offset)
                        raw = read_tag_value_bytes(f, entry)
                        xmp_text = raw.decode('utf-8', errors='replace')
                        for attr in XMP_PHI_ATTRIBUTES:
                            pattern = re.compile(
                                rf'{attr}\s*=\s*"([^"]*)"', re.IGNORECASE)
                            for m in pattern.finditer(xmp_text):
                                val = m.group(1).strip()
                                if val and not _is_xmp_anonymized(val):
                                    findings.append(PHIFinding(
                                        offset=entry.value_offset,
                                        length=entry.total_size,
                                        tag_id=700,
                                        tag_name=f'XMP:iScan:{attr}',
                                        value_preview=f'{attr}={val[:40]}',
                                        source='tiff_tag',
                                    ))
                        break  # Only one tag 700 per IFD
        return findings

    def _anonymize_xmp(self, filepath: Path) -> List[PHIFinding]:
        """Anonymize PHI in XMP tag by replacing attribute values across all IFDs."""
        cleared = []
        seen = set()
        with open(filepath, 'r+b') as f:
            header = read_header(f)
            if header is None:
                return cleared

            for _, entries in iter_ifds(f, header):
                for entry in entries:
                    if entry.tag_id == 700 and entry.value_offset not in seen:
                        seen.add(entry.value_offset)
                        raw = read_tag_value_bytes(f, entry)
                        xmp_text = raw.decode('utf-8', errors='replace')
                        modified = False

                        for attr in XMP_PHI_ATTRIBUTES:
                            pattern = re.compile(
                                rf'({attr}\s*=\s*")([^"]*?)(")', re.IGNORECASE)

                            def _replace(m):
                                val = m.group(2)
                                if val and not _is_xmp_anonymized(val):
                                    return m.group(1) + 'X' * len(val) + m.group(3)
                                return m.group(0)

                            new_text, count = pattern.subn(_replace, xmp_text)
                            if count > 0 and new_text != xmp_text:
                                xmp_text = new_text
                                modified = True
                                cleared.append(PHIFinding(
                                    offset=entry.value_offset,
                                    length=entry.total_size,
                                    tag_id=700,
                                    tag_name=f'XMP:iScan:{attr}',
                                    value_preview=f'{attr} anonymized',
                                    source='tiff_tag',
                                ))

                        if modified:
                            new_bytes = xmp_text.encode('utf-8', errors='replace')
                            if len(new_bytes) < entry.total_size:
                                new_bytes += b'\x00' * (entry.total_size - len(new_bytes))
                            else:
                                new_bytes = new_bytes[:entry.total_size]
                            f.seek(entry.value_offset)
                            f.write(new_bytes)
                        break  # Only one tag 700 per IFD
        return cleared


def _is_xmp_anonymized(value: str) -> bool:
    """Check if an XMP attribute value has already been anonymized."""
    if not value:
        return True
    if all(c == 'X' for c in value):
        return True
    return False
