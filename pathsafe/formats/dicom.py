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

Anonymization follows DICOM PS3.15 Basic Application Level Confidentiality
Profile for de-identification (Table E.1-1).
"""

import hashlib
import os
import time
from pathlib import Path
from typing import Dict, List, Optional

from pathsafe.formats.base import FormatHandler
from pathsafe.models import PHIFinding, ScanResult

try:
    import pydicom
    from pydicom.tag import Tag
    from pydicom.uid import generate_uid
    HAS_PYDICOM = True
except ImportError:
    HAS_PYDICOM = False

# VL Whole Slide Microscopy Image Storage SOP Class UID
WSI_SOP_CLASS_UID = "1.2.840.10008.5.1.4.1.1.77.1.6"

# PathSafe UID root (derived from a hash, used for UID remapping)
PATHSAFE_UID_ROOT = "1.2.826.0.1.3680043.10.1118."

# Tags to BLANK (Type 2: replace with empty/dummy value, keep tag present)
# Based on DICOM PS3.15 Table E.1-1 with Type 1/2 attributes
TAGS_TO_BLANK = {
    # Patient module
    (0x0010, 0x0010): ('PatientName', 'PN'),
    (0x0010, 0x0020): ('PatientID', 'LO'),
    (0x0010, 0x0030): ('PatientBirthDate', 'DA'),
    (0x0010, 0x0032): ('PatientBirthTime', 'TM'),
    (0x0010, 0x0040): ('PatientSex', 'CS'),
    (0x0010, 0x1010): ('PatientAge', 'AS'),
    (0x0010, 0x1020): ('PatientSize', 'DS'),
    (0x0010, 0x1030): ('PatientWeight', 'DS'),
    # Study module
    (0x0008, 0x0050): ('AccessionNumber', 'SH'),
    (0x0020, 0x0010): ('StudyID', 'SH'),
    (0x0008, 0x0020): ('StudyDate', 'DA'),
    (0x0008, 0x0030): ('StudyTime', 'TM'),
    (0x0008, 0x1030): ('StudyDescription', 'LO'),
    (0x0008, 0x0080): ('InstitutionName', 'LO'),
    (0x0008, 0x0090): ('ReferringPhysicianName', 'PN'),
    # Series module
    (0x0008, 0x0021): ('SeriesDate', 'DA'),
    (0x0008, 0x0031): ('SeriesTime', 'TM'),
    (0x0008, 0x103E): ('SeriesDescription', 'LO'),
    (0x0008, 0x1070): ('OperatorsName', 'PN'),
    (0x0020, 0x0011): ('SeriesNumber', 'IS'),
    # Content date/time
    (0x0008, 0x0023): ('ContentDate', 'DA'),
    (0x0008, 0x0033): ('ContentTime', 'TM'),
    # Acquisition
    (0x0008, 0x0022): ('AcquisitionDate', 'DA'),
    (0x0008, 0x0032): ('AcquisitionTime', 'TM'),
    (0x0008, 0x002A): ('AcquisitionDateTime', 'DT'),
}

# Tags to DELETE entirely (Type 3: optional, remove)
# Based on DICOM PS3.15 Table E.1-1 with Type 3 attributes
TAGS_TO_DELETE = {
    # Patient identifiers
    (0x0010, 0x1000): 'OtherPatientIDs',
    (0x0010, 0x1001): 'OtherPatientNames',
    (0x0010, 0x1002): 'OtherPatientIDsSequence',
    (0x0010, 0x1040): 'PatientAddress',
    (0x0010, 0x2154): 'PatientTelephoneNumbers',
    (0x0010, 0x1060): 'PatientMotherBirthName',
    (0x0010, 0x2110): 'Allergies',
    (0x0010, 0x21B0): 'AdditionalPatientHistory',
    (0x0010, 0x4000): 'PatientComments',
    (0x0010, 0x2160): 'EthnicGroup',
    (0x0010, 0x0050): 'PatientInsurancePlanCodeSequence',
    (0x0010, 0x21F0): 'PatientReligiousPreference',
    # Institutional
    (0x0008, 0x0081): 'InstitutionAddress',
    (0x0008, 0x0082): 'InstitutionCodeSequence',
    (0x0008, 0x1040): 'InstitutionalDepartmentName',
    (0x0008, 0x1010): 'StationName',
    # Physician/operator
    (0x0008, 0x1048): 'PhysiciansOfRecord',
    (0x0008, 0x1049): 'PhysiciansOfRecordIdentificationSequence',
    (0x0008, 0x1050): 'PerformingPhysicianName',
    (0x0008, 0x1052): 'PerformingPhysicianIdentificationSequence',
    (0x0008, 0x1060): 'NameOfPhysiciansReadingStudy',
    (0x0008, 0x1062): 'PhysiciansReadingStudyIdentificationSequence',
    (0x0032, 0x1032): 'RequestingPhysician',
    (0x0032, 0x1033): 'RequestingService',
    (0x0008, 0x0092): 'ReferringPhysicianAddress',
    (0x0008, 0x0094): 'ReferringPhysicianTelephoneNumbers',
    (0x0008, 0x0096): 'ReferringPhysicianIdentificationSequence',
    # Study/order
    (0x0008, 0x1032): 'ProcedureCodeSequence',
    (0x0032, 0x1060): 'RequestedProcedureDescription',
    (0x0040, 0x0275): 'RequestAttributesSequence',
    (0x0040, 0x1001): 'RequestedProcedureID',
    (0x0040, 0xA730): 'ContentSequence',
    # Comments/descriptions
    (0x0020, 0x4000): 'ImageComments',
    (0x0008, 0x4000): 'IdentifyingComments',
    # Misc identifiers
    # Note: (0x0012,0x0062) PatientIdentityRemoved is SET by us, not deleted
    (0x0038, 0x0010): 'AdmissionID',
    (0x0038, 0x0500): 'PatientState',
    (0x0040, 0x2016): 'PlacerOrderNumberImagingServiceRequest',
    (0x0040, 0x2017): 'FillerOrderNumberImagingServiceRequest',
}

# Tags whose UIDs should be remapped (not simply deleted)
UID_TAGS = {
    (0x0008, 0x0018): 'SOPInstanceUID',
    (0x0020, 0x000D): 'StudyInstanceUID',
    (0x0020, 0x000E): 'SeriesInstanceUID',
    (0x0008, 0x0016): 'SOPClassUID',  # Keep original (functional, not PHI)
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
                is_clean=False, scan_time_ms=elapsed,
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
                    raw_val = ds[tag].value
                    if raw_val is None:
                        continue
                    value = str(raw_val).strip()
                    if value and value != 'None' and not _is_dicom_anonymized(value, vr):
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
                    raw_val = ds[tag].value
                    if raw_val is None:
                        continue
                    value = str(raw_val).strip()
                    if value and value != 'None':
                        # Skip sequence tags that are just containers
                        if ds[tag].VR == 'SQ':
                            continue
                        findings.append(PHIFinding(
                            offset=0, length=len(value),
                            tag_id=tag_tuple[0] << 16 | tag_tuple[1],
                            tag_name=f'DICOM:{name}',
                            value_preview=f'{name}={value[:50]}',
                            source='dicom_tag',
                        ))

            # Scan sequences (VR=SQ) for nested PHI
            findings += _scan_sequences(ds)

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

            # Check if PatientIdentityRemoved is not set
            pir = getattr(ds, 'PatientIdentityRemoved', None)
            if pir != 'YES' and findings:
                # Not marking this as a separate finding, just noting
                # it for the anonymize step
                pass

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
            raw_val = ds[tag].value
            if raw_val is None:
                continue
            value = str(raw_val).strip()
            if not value or value == 'None' or _is_dicom_anonymized(value, vr):
                continue

            if vr in ('DA',):
                ds[tag].value = '19000101'
            elif vr in ('TM',):
                ds[tag].value = '000000'
            elif vr in ('DT',):
                ds[tag].value = '19000101000000'
            elif vr in ('IS', 'DS', 'AS'):
                ds[tag].value = ''
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
            raw_val = ds[tag].value
            if raw_val is None:
                continue
            value = str(raw_val).strip()
            if not value or value == 'None':
                continue

            del ds[tag]
            cleared.append(PHIFinding(
                offset=0, length=len(value),
                tag_id=tag_tuple[0] << 16 | tag_tuple[1],
                tag_name=f'DICOM:{name}',
                value_preview=f'{name}={value[:50]}',
                source='dicom_tag',
            ))

        # Remap UIDs (generate deterministic replacements)
        cleared += _remap_uids(ds, filepath)

        # Clean PHI from sequences
        cleared += _anonymize_sequences(ds)

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

        # Set PatientIdentityRemoved flag (DICOM PS3.15 requirement)
        if cleared:
            ds.add_new(Tag(0x0012, 0x0062), 'CS', 'YES')
            ds.add_new(Tag(0x0012, 0x0063), 'LO',
                       'PathSafe Basic Application Level Confidentiality Profile')
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
    # PN (PersonName) with only caret separators = empty name
    if vr == 'PN' and all(c == '^' for c in value):
        return True
    return False


def _remap_uid(original_uid: str, filepath: Path) -> str:
    """Generate a deterministic replacement UID from the original.

    Uses SHA-256 hash of original UID + filepath to produce a consistent
    but non-reversible replacement. Same input always produces same output.
    The result is a valid DICOM UID (digits and dots only, max 64 chars,
    no component with leading zeros).
    """
    hash_input = f"{original_uid}:{filepath}".encode()
    digest = hashlib.sha256(hash_input).digest()
    # Convert to a large integer, then to decimal string
    numeric = str(int.from_bytes(digest[:16], 'big'))
    new_uid = PATHSAFE_UID_ROOT + numeric
    if len(new_uid) > 64:
        new_uid = new_uid[:64]
    return new_uid


def _remap_uids(ds, filepath: Path) -> List[PHIFinding]:
    """Remap DICOM UIDs to anonymized values."""
    cleared = []

    for tag_tuple, name in UID_TAGS.items():
        if name == 'SOPClassUID':
            continue  # Keep SOP Class UID (functional, not PHI)
        tag = Tag(*tag_tuple)
        if tag not in ds:
            continue
        original = str(ds[tag].value).strip()
        if not original:
            continue
        # Check if already remapped (starts with our root)
        if original.startswith(PATHSAFE_UID_ROOT):
            continue

        new_uid = _remap_uid(original, filepath)
        ds[tag].value = new_uid
        cleared.append(PHIFinding(
            offset=0, length=len(original),
            tag_id=tag_tuple[0] << 16 | tag_tuple[1],
            tag_name=f'DICOM:{name}',
            value_preview=f'{name} remapped',
            source='dicom_tag',
        ))

    return cleared


# Tags within sequences that may contain PHI (identifiers, not vocabulary codes)
_SQ_PHI_TAGS = {
    Tag(0x0010, 0x0010),  # PatientName (in nested)
    Tag(0x0010, 0x0020),  # PatientID (in nested)
    Tag(0x0008, 0x0080),  # InstitutionName (in nested)
    Tag(0x0008, 0x0090),  # ReferringPhysicianName (in nested)
    Tag(0x0008, 0x1050),  # PerformingPhysicianName (in nested)
    Tag(0x0008, 0x1070),  # OperatorsName (in nested)
    Tag(0x0040, 0xA123),  # PersonName (in nested)
    Tag(0x0008, 0x0081),  # InstitutionAddress (in nested)
}

# VRs that typically contain text/name PHI within sequences
_PHI_VRS_IN_SQ = {'PN', 'LO', 'SH', 'DA', 'TM', 'DT'}


def _scan_sequences(ds, depth: int = 0) -> List[PHIFinding]:
    """Recursively scan DICOM sequences for PHI."""
    if depth > 5:
        return []
    findings = []
    for elem in ds:
        if elem.VR == 'SQ' and elem.value:
            for item in elem.value:
                # Check known PHI tags in sequence items
                for phi_tag in _SQ_PHI_TAGS:
                    if phi_tag in item:
                        val = str(item[phi_tag].value).strip()
                        vr = item[phi_tag].VR
                        if val and not _is_dicom_anonymized(val, vr):
                            findings.append(PHIFinding(
                                offset=0, length=len(val),
                                tag_id=None,
                                tag_name=f'DICOM:SQ:{item[phi_tag].keyword}',
                                value_preview=f'{item[phi_tag].keyword}={val[:40]}',
                                source='dicom_tag',
                            ))
                # Recurse into nested sequences
                findings += _scan_sequences(item, depth + 1)
    return findings


def _anonymize_sequences(ds, depth: int = 0) -> List[PHIFinding]:
    """Recursively anonymize PHI in DICOM sequences."""
    if depth > 5:
        return []
    cleared = []
    for elem in ds:
        if elem.VR == 'SQ' and elem.value:
            for item in elem.value:
                for phi_tag in _SQ_PHI_TAGS:
                    if phi_tag in item:
                        val = str(item[phi_tag].value).strip()
                        vr = item[phi_tag].VR
                        if val and not _is_dicom_anonymized(val, vr):
                            if vr == 'DA':
                                item[phi_tag].value = '19000101'
                            elif vr == 'TM':
                                item[phi_tag].value = '000000'
                            elif vr == 'DT':
                                item[phi_tag].value = '19000101000000'
                            else:
                                item[phi_tag].value = ''
                            cleared.append(PHIFinding(
                                offset=0, length=len(val),
                                tag_id=None,
                                tag_name=f'DICOM:SQ:{item[phi_tag].keyword}',
                                value_preview=f'{item[phi_tag].keyword}={val[:40]}',
                                source='dicom_tag',
                            ))
                # Remove private tags in sequence items
                private_in_sq = [e for e in item if e.tag.is_private]
                for priv in private_in_sq:
                    del item[priv.tag]
                # Recurse
                cleared += _anonymize_sequences(item, depth + 1)
    return cleared
