"""Tests for the DICOM format handler.

Requires pydicom -- tests are skipped if pydicom is not installed.
"""

import pytest
from pathlib import Path

pydicom = pytest.importorskip('pydicom', reason='pydicom not installed')
from pydicom.dataset import Dataset, FileDataset
from pydicom.uid import ExplicitVRLittleEndian, generate_uid
from pydicom.sequence import Sequence
from pydicom.tag import Tag

from pathsafe.formats.dicom import (
    DICOMHandler, _has_dicom_magic, _is_dicom_anonymized,
    _remap_uid, TAGS_TO_BLANK, TAGS_TO_DELETE, PATHSAFE_UID_ROOT,
)


def _make_dicom_file(filepath, **kwargs):
    """Create a minimal DICOM WSI file with PHI for testing."""
    file_meta = pydicom.Dataset()
    file_meta.MediaStorageSOPClassUID = '1.2.840.10008.5.1.4.1.1.77.1.6'
    file_meta.MediaStorageSOPInstanceUID = generate_uid()
    file_meta.TransferSyntaxUID = ExplicitVRLittleEndian

    ds = FileDataset(str(filepath), {}, file_meta=file_meta, preamble=b'\x00' * 128)

    # Patient module
    ds.PatientName = kwargs.get('PatientName', 'Doe^John')
    ds.PatientID = kwargs.get('PatientID', 'PID12345')
    ds.PatientBirthDate = kwargs.get('PatientBirthDate', '19800115')
    ds.PatientSex = kwargs.get('PatientSex', 'M')

    # Study module
    ds.AccessionNumber = kwargs.get('AccessionNumber', 'ACC-2024-001')
    ds.StudyID = kwargs.get('StudyID', 'STD001')
    ds.StudyDate = kwargs.get('StudyDate', '20240615')
    ds.StudyTime = kwargs.get('StudyTime', '103000')
    ds.InstitutionName = kwargs.get('InstitutionName', 'Test Hospital')
    ds.ReferringPhysicianName = kwargs.get('ReferringPhysicianName', 'Smith^Dr')

    # Series module
    ds.OperatorsName = kwargs.get('OperatorsName', 'TechOp')
    ds.SeriesDate = kwargs.get('SeriesDate', '20240615')
    ds.SeriesTime = kwargs.get('SeriesTime', '103100')

    # UIDs
    ds.SOPClassUID = '1.2.840.10008.5.1.4.1.1.77.1.6'
    ds.SOPInstanceUID = generate_uid()
    ds.StudyInstanceUID = generate_uid()
    ds.SeriesInstanceUID = generate_uid()

    # Image
    ds.Modality = 'SM'
    ds.Rows = 256
    ds.Columns = 256

    ds.save_as(str(filepath))
    return filepath


@pytest.fixture
def handler():
    return DICOMHandler()


@pytest.fixture
def tmp_dicom(tmp_path):
    """Create a synthetic DICOM WSI file with PHI."""
    return _make_dicom_file(tmp_path / 'test.dcm')


@pytest.fixture
def tmp_dicom_clean(tmp_path):
    """Create a DICOM file that has been anonymized."""
    filepath = _make_dicom_file(tmp_path / 'clean.dcm')
    handler = DICOMHandler()
    handler.anonymize(filepath)
    return filepath


class TestDICOMCanHandle:
    def test_dcm_extension(self, handler, tmp_dicom):
        assert handler.can_handle(tmp_dicom)

    def test_dicom_extension(self, handler, tmp_path):
        filepath = _make_dicom_file(tmp_path / 'test.dicom')
        assert handler.can_handle(filepath)

    def test_non_dicom(self, handler, tmp_path):
        assert not handler.can_handle(tmp_path / 'slide.ndpi')
        assert not handler.can_handle(tmp_path / 'slide.svs')

    def test_no_magic_bytes(self, handler, tmp_path):
        f = tmp_path / 'fake.dcm'
        f.write_bytes(b'NOT A DICOM FILE')
        assert not handler.can_handle(f)


class TestDICOMScan:
    def test_detect_patient_phi(self, handler, tmp_dicom):
        result = handler.scan(tmp_dicom)
        assert not result.is_clean
        assert result.format == 'dicom'
        tag_names = {f.tag_name for f in result.findings}
        assert any('PatientName' in t for t in tag_names)
        assert any('PatientID' in t for t in tag_names)

    def test_detect_accession(self, handler, tmp_dicom):
        result = handler.scan(tmp_dicom)
        tag_names = {f.tag_name for f in result.findings}
        assert any('AccessionNumber' in t for t in tag_names)

    def test_detect_institution(self, handler, tmp_dicom):
        result = handler.scan(tmp_dicom)
        tag_names = {f.tag_name for f in result.findings}
        assert any('InstitutionName' in t for t in tag_names)

    def test_clean_file(self, handler, tmp_dicom_clean):
        result = handler.scan(tmp_dicom_clean)
        # After anonymization, PatientIdentityRemoved=YES
        # and all PHI tags blanked/deleted
        assert result.is_clean

    def test_scan_error_fail_closed(self, handler, tmp_dicom, monkeypatch):
        """Scan error returns is_clean=False."""
        import pathsafe.formats.dicom as dicom_mod
        original_dcmread = dicom_mod.pydicom.dcmread
        def _raise(*args, **kwargs):
            raise Exception("Forced test error")
        monkeypatch.setattr(dicom_mod.pydicom, 'dcmread', _raise)
        result = handler.scan(tmp_dicom)
        assert not result.is_clean
        assert result.error is not None


class TestDICOMAnonymize:
    def test_anonymize_blanks_type2(self, handler, tmp_dicom):
        cleared = handler.anonymize(tmp_dicom)
        assert len(cleared) > 0

        ds = pydicom.dcmread(str(tmp_dicom), stop_before_pixels=True, force=True)
        assert str(ds.PatientName) == ''
        assert str(ds.PatientID) == ''

    def test_anonymize_deletes_type3(self, handler, tmp_path):
        filepath = _make_dicom_file(tmp_path / 'del.dcm')
        ds = pydicom.dcmread(str(filepath), force=True)
        ds.add_new(Tag(0x0010, 0x1040), 'LO', '123 Main St')  # PatientAddress
        ds.save_as(str(filepath))

        handler.anonymize(filepath)
        ds = pydicom.dcmread(str(filepath), stop_before_pixels=True, force=True)
        assert Tag(0x0010, 0x1040) not in ds

    def test_anonymize_dates(self, handler, tmp_dicom):
        handler.anonymize(tmp_dicom)
        ds = pydicom.dcmread(str(tmp_dicom), stop_before_pixels=True, force=True)
        assert ds.StudyDate == '19000101'
        assert ds.StudyTime == '000000'
        assert ds.PatientBirthDate == '19000101'

    def test_anonymize_remaps_uids(self, handler, tmp_dicom):
        ds_before = pydicom.dcmread(str(tmp_dicom), stop_before_pixels=True, force=True)
        original_study_uid = str(ds_before.StudyInstanceUID)

        handler.anonymize(tmp_dicom)
        ds_after = pydicom.dcmread(str(tmp_dicom), stop_before_pixels=True, force=True)

        assert str(ds_after.StudyInstanceUID) != original_study_uid
        assert str(ds_after.StudyInstanceUID).startswith(PATHSAFE_UID_ROOT)

    def test_anonymize_keeps_sop_class_uid(self, handler, tmp_dicom):
        ds_before = pydicom.dcmread(str(tmp_dicom), stop_before_pixels=True, force=True)
        original_sop_class = str(ds_before.SOPClassUID)

        handler.anonymize(tmp_dicom)
        ds_after = pydicom.dcmread(str(tmp_dicom), stop_before_pixels=True, force=True)
        assert str(ds_after.SOPClassUID) == original_sop_class

    def test_anonymize_removes_private_tags(self, handler, tmp_path):
        filepath = _make_dicom_file(tmp_path / 'priv.dcm')
        ds = pydicom.dcmread(str(filepath), force=True)
        ds.add_new(Tag(0x0009, 0x0010), 'LO', 'PrivateCreator')
        ds.add_new(Tag(0x0009, 0x1001), 'LO', 'PrivateData')
        ds.save_as(str(filepath))

        handler.anonymize(filepath)
        ds = pydicom.dcmread(str(filepath), stop_before_pixels=True, force=True)
        private_count = sum(1 for elem in ds if elem.tag.is_private)
        assert private_count == 0

    def test_anonymize_sets_identity_removed(self, handler, tmp_dicom):
        handler.anonymize(tmp_dicom)
        ds = pydicom.dcmread(str(tmp_dicom), stop_before_pixels=True, force=True)
        assert ds[Tag(0x0012, 0x0062)].value == 'YES'

    def test_idempotent(self, handler, tmp_dicom):
        cleared1 = handler.anonymize(tmp_dicom)
        cleared2 = handler.anonymize(tmp_dicom)
        assert len(cleared1) > 0
        assert len(cleared2) == 0


class TestDICOMSequences:
    def test_scan_detects_phi_in_sequences(self, handler, tmp_path):
        filepath = _make_dicom_file(tmp_path / 'seq.dcm')
        ds = pydicom.dcmread(str(filepath), force=True)

        # Add a sequence with PHI
        item = Dataset()
        item.PatientName = 'SeqPatient'
        item.AccessionNumber = 'SEQ-ACC-001'
        ds.ReferencedStudySequence = Sequence([item])
        ds.save_as(str(filepath))

        result = handler.scan(filepath)
        tag_names = {f.tag_name for f in result.findings}
        assert any('SQ:' in t for t in tag_names)

    def test_anonymize_cleans_sequences(self, handler, tmp_path):
        filepath = _make_dicom_file(tmp_path / 'seq_anon.dcm')
        ds = pydicom.dcmread(str(filepath), force=True)

        item = Dataset()
        item.PatientName = 'SeqPatient'
        ds.ReferencedStudySequence = Sequence([item])
        ds.save_as(str(filepath))

        handler.anonymize(filepath)
        ds = pydicom.dcmread(str(filepath), stop_before_pixels=True, force=True)
        # ReferencedStudySequence is in TAGS_TO_DELETE, so it should be removed
        assert Tag(0x0008, 0x1110) not in ds


class TestDICOMInfo:
    def test_get_info(self, handler, tmp_dicom):
        info = handler.get_format_info(tmp_dicom)
        assert info['format'] == 'dicom'
        assert info['file_size'] > 0
        assert info['modality'] == 'SM'


class TestDICOMHelpers:
    def test_has_dicom_magic(self, tmp_dicom):
        assert _has_dicom_magic(tmp_dicom)

    def test_no_dicom_magic(self, tmp_path):
        f = tmp_path / 'bad.dcm'
        f.write_bytes(b'NOT DICOM' * 20)
        assert not _has_dicom_magic(f)

    def test_is_anonymized_date(self):
        assert _is_dicom_anonymized('19000101', 'DA')

    def test_is_anonymized_time(self):
        assert _is_dicom_anonymized('000000', 'TM')

    def test_is_anonymized_datetime(self):
        assert _is_dicom_anonymized('19000101000000', 'DT')

    def test_is_anonymized_empty(self):
        assert _is_dicom_anonymized('', 'LO')

    def test_is_not_anonymized(self):
        assert not _is_dicom_anonymized('Doe^John', 'PN')

    def test_remap_uid_deterministic(self, tmp_dicom):
        uid1 = _remap_uid('1.2.3.4', tmp_dicom)
        uid2 = _remap_uid('1.2.3.4', tmp_dicom)
        assert uid1 == uid2
        assert uid1.startswith(PATHSAFE_UID_ROOT)

    def test_remap_uid_different_inputs(self, tmp_dicom):
        uid1 = _remap_uid('1.2.3.4', tmp_dicom)
        uid2 = _remap_uid('5.6.7.8', tmp_dicom)
        assert uid1 != uid2

    def test_remap_uid_max_length(self, tmp_dicom):
        uid = _remap_uid('1.2.3.4.5.6.7.8.9.10.11.12.13.14.15', tmp_dicom)
        assert len(uid) <= 64
