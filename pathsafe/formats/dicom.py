"""DICOM WSI format handler.

Handles PHI detection and anonymization for DICOM whole-slide image files.
Requires pydicom (optional dependency: pip install pathsafe[dicom]).

DICOM WSI structure:
- Multiple .dcm files per slide (one per pyramid level + associated images)
- Files linked by Series Instance UID
- PHI stored in standard DICOM tags (Patient module, Study module, etc.)

This handler processes individual .dcm files. For multi-file WSI slides,
each file in the series should be processed separately — they all contain
the same PHI tags.
"""

import os
import time
from pathlib import Path
from typing import Dict, List, Optional

from pathsafe.formats.base import FormatHandler
from pathsafe.models import PHIFinding, ScanResult

try:
    import pydicom
    from pydicom.tag import Tag
    HAS_PYDICOM = True
except ImportError:
    HAS_PYDICOM = False

# VL Whole Slide Microscopy Image Storage SOP Class UID
WSI_SOP_CLASS_UID = "1.2.840.10008.5.1.4.1.1.77.1.6"

# Tags to BLANK (Type 2: replace with empty/dummy value, keep tag present)
TAGS_TO_BLANK = {
    (0x0010, 0x0010): ('PatientName', 'PN'),
    (0x0010, 0x0020): ('PatientID', 'LO'),
    (0x0010, 0x0030): ('PatientBirthDate', 'DA'),
    (0x0010, 0x0032): ('PatientBirthTime', 'TM'),
    (0x0010, 0x0040): ('PatientSex', 'CS'),
    (0x0008, 0x0050): ('AccessionNumber', 'SH'),
    (0x0020, 0x0010): ('StudyID', 'SH'),
    (0x0008, 0x0020): ('StudyDate', 'DA'),
    (0x0008, 0x0030): ('StudyTime', 'TM'),
    (0x0008, 0x0080): ('InstitutionName', 'LO'),
    (0x0008, 0x0090): ('ReferringPhysicianName', 'PN'),
    (0x0008, 0x0023): ('ContentDate', 'DA'),
    (0x0008, 0x0033): ('ContentTime', 'TM'),
}

# Tags to DELETE entirely (Type 3: optional, remove)
TAGS_TO_DELETE = {
    (0x0010, 0x1000): 'OtherPatientIDs',
    (0x0010, 0x1001): 'OtherPatientNames',
    (0x0010, 0x1040): 'PatientAddress',
    (0x0010, 0x2154): 'PatientTelephoneNumbers',
    (0x0010, 0x1060): 'PatientMotherBirthName',
    (0x0008, 0x0081): 'InstitutionAddress',
    (0x0008, 0x1040): 'InstitutionalDepartmentName',
    (0x0008, 0x1050): 'PerformingPhysicianName',
    (0x0008, 0x1060): 'NameOfPhysiciansReadingStudy',
    (0x0008, 0x1070): 'OperatorsName',
    (0x0008, 0x1010): 'StationName',
    (0x0008, 0x0021): 'SeriesDate',
    (0x0008, 0x0031): 'SeriesTime',
    (0x0008, 0x0022): 'AcquisitionDate',
    (0x0008, 0x002A): 'AcquisitionDateTime',
    (0x0010, 0x2110): 'Allergies',
    (0x0010, 0x21B0): 'AdditionalPatientHistory',
    (0x0032, 0x1032): 'RequestingPhysician',
}


class DICOMHandler(FormatHandler):
    """Format handler for DICOM WSI files."""

    format_name = "dicom"

    def can_handle(self, filepath: Path) -> bool:
        if filepath.suffix.lower() not in ('.dcm', '.dicom'):
            return False
        if not HAS_PYDICOM:
            return False
        return _has_dicom_magic(filepath)

    def scan(self, filepath: Path) -> ScanResult:
        """Scan DICOM file for PHI — read-only."""
        t0 = time.monotonic()
        file_size = os.path.getsize(filepath)
        findings: List[PHIFinding] = []

        if not HAS_PYDICOM:
            elapsed = (time.monotonic() - t0) * 1000
            return ScanResult(
                filepath=filepath, format="dicom", findings=[],
                is_clean=True, scan_time_ms=elapsed,
                file_size=file_size,
                error="pydicom not installed (pip install pathsafe[dicom])",
            )

        try:
            ds = pydicom.dcmread(str(filepath), stop_before_pixels=True,
                                 force=True)

            # Check tags to blank
            for tag_tuple, (name, vr) in TAGS_TO_BLANK.items():
                tag = Tag(*tag_tuple)
                if tag in ds:
                    value = str(ds[tag].value).strip()
                    if value and not _is_dicom_anonymized(value, vr):
                        findings.append(PHIFinding(
                            offset=0, length=len(value),
                            tag_id=tag_tuple[0] << 16 | tag_tuple[1],
                            tag_name=f'DICOM:{name}',
                            value_preview=f'{name}={value[:50]}',
                            source='dicom_tag',
                        ))

            # Check tags to delete
            for tag_tuple, name in TAGS_TO_DELETE.items():
                tag = Tag(*tag_tuple)
                if tag in ds:
                    value = str(ds[tag].value).strip()
                    if value:
                        findings.append(PHIFinding(
                            offset=0, length=len(value),
                            tag_id=tag_tuple[0] << 16 | tag_tuple[1],
                            tag_name=f'DICOM:{name}',
                            value_preview=f'{name}={value[:50]}',
                            source='dicom_tag',
                        ))

            # Check for private tags
            private_count = sum(
                1 for elem in ds if elem.tag.is_private)
            if private_count > 0:
                findings.append(PHIFinding(
                    offset=0, length=0, tag_id=None,
                    tag_name='DICOM:PrivateTags',
                    value_preview=f'{private_count} private tag(s)',
                    source='dicom_tag',
                ))

        except Exception as e:
            elapsed = (time.monotonic() - t0) * 1000
            return ScanResult(
                filepath=filepath, format="dicom", findings=findings,
                is_clean=len(findings) == 0, scan_time_ms=elapsed,
                file_size=file_size, error=str(e),
            )

        elapsed = (time.monotonic() - t0) * 1000
        return ScanResult(
            filepath=filepath, format="dicom", findings=findings,
            is_clean=len(findings) == 0, scan_time_ms=elapsed,
            file_size=file_size,
        )

    def anonymize(self, filepath: Path) -> List[PHIFinding]:
        """Anonymize PHI in a DICOM file in-place."""
        if not HAS_PYDICOM:
            return []

        cleared: List[PHIFinding] = []
        ds = pydicom.dcmread(str(filepath), force=True)

        # Blank Type 2 tags
        for tag_tuple, (name, vr) in TAGS_TO_BLANK.items():
            tag = Tag(*tag_tuple)
            if tag not in ds:
                continue
            value = str(ds[tag].value).strip()
            if not value or _is_dicom_anonymized(value, vr):
                continue

            if vr == 'DA':
                ds[tag].value = '19000101'
            elif vr == 'TM':
                ds[tag].value = '000000'
            elif vr == 'DT':
                ds[tag].value = '19000101000000'
            else:
                ds[tag].value = ''

            cleared.append(PHIFinding(
                offset=0, length=len(value),
                tag_id=tag_tuple[0] << 16 | tag_tuple[1],
                tag_name=f'DICOM:{name}',
                value_preview=f'{name}={value[:50]}',
                source='dicom_tag',
            ))

        # Delete Type 3 tags
        for tag_tuple, name in TAGS_TO_DELETE.items():
            tag = Tag(*tag_tuple)
            if tag not in ds:
                continue
            value = str(ds[tag].value).strip()
            if not value:
                continue

            del ds[tag]
            cleared.append(PHIFinding(
                offset=0, length=len(value),
                tag_id=tag_tuple[0] << 16 | tag_tuple[1],
                tag_name=f'DICOM:{name}',
                value_preview=f'{name}={value[:50]}',
                source='dicom_tag',
            ))

        # Remove private tags
        private_count = sum(1 for elem in ds if elem.tag.is_private)
        if private_count > 0:
            ds.remove_private_tags()
            cleared.append(PHIFinding(
                offset=0, length=0, tag_id=None,
                tag_name='DICOM:PrivateTags',
                value_preview=f'removed {private_count} private tag(s)',
                source='dicom_tag',
            ))

        # Save modified file
        if cleared:
            ds.save_as(str(filepath))

        return cleared

    def get_format_info(self, filepath: Path) -> Dict:
        """Get DICOM file metadata."""
        info = {
            'format': 'dicom',
            'filename': filepath.name,
            'file_size': os.path.getsize(filepath),
        }

        if not HAS_PYDICOM:
            info['error'] = 'pydicom not installed'
            return info

        try:
            ds = pydicom.dcmread(str(filepath), stop_before_pixels=True,
                                 force=True)

            info['sop_class'] = str(getattr(ds, 'SOPClassUID', 'unknown'))
            info['is_wsi'] = (
                str(getattr(ds, 'SOPClassUID', '')) == WSI_SOP_CLASS_UID)
            info['modality'] = str(getattr(ds, 'Modality', 'unknown'))
            info['manufacturer'] = str(
                getattr(ds, 'Manufacturer', 'unknown'))

            if hasattr(ds, 'Rows') and hasattr(ds, 'Columns'):
                info['image_size'] = f'{ds.Columns}x{ds.Rows}'
            if hasattr(ds, 'NumberOfFrames'):
                info['frames'] = int(ds.NumberOfFrames)
            if hasattr(ds, 'ImageType'):
                info['image_type'] = str(ds.ImageType)

            info['tag_count'] = len(ds)
            info['private_tag_count'] = sum(
                1 for elem in ds if elem.tag.is_private)

        except Exception as e:
            info['error'] = str(e)

        return info


def _has_dicom_magic(filepath: Path) -> bool:
    """Check for DICOM Part 10 magic bytes at offset 128."""
    try:
        with open(filepath, 'rb') as f:
            f.seek(128)
            return f.read(4) == b'DICM'
    except (OSError, IOError):
        return False


def _is_dicom_anonymized(value: str, vr: str) -> bool:
    """Check if a DICOM tag value has already been anonymized."""
    if not value:
        return True
    if vr == 'DA' and value == '19000101':
        return True
    if vr == 'TM' and value == '000000':
        return True
    if vr == 'DT' and value == '19000101000000':
        return True
    if all(c == 'X' for c in value):
        return True
    return False
