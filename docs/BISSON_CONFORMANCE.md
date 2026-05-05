# PathSafe Conformance to Bisson et al. (2023) Level IV

## Reference

Bisson T., Franz M., Dogan O.I., Romberg D., Jansen C., Hufnagl P., Zerbe N. (2023).
"Anonymization of Whole Slide Images in Histopathology for Research and Education."
*Digital Health* 9, DOI: [10.1177/20552076231171475](https://doi.org/10.1177/20552076231171475).

This document is a per-criterion mapping from the paper to PathSafe's code and tests. Each row cites a verbatim phrase from the paper, the PathSafe source location that implements it, and the test that exercises it. The conformance test file (`tests/test_bisson_conformance.py`) is the machine-checkable counterpart of this matrix; running `pytest tests/test_bisson_conformance.py -v` regenerates it from current code.

PathSafe targets **Level IV** of the paper's five-level hierarchy. Level V ("dissolve spatial coherence") is explicitly out of scope -- the paper itself states no usable solution exists yet.

## Scope vs. paper Table 1

| Format | Bisson Table 1 | PathSafe support | Conformance scope |
|---|:-:|:-:|---|
| Aperio / Leica SVS (`.svs`) | yes | yes | tested |
| Hamamatsu NDPI (`.ndpi`) | yes | yes | tested (label and macro share one image; both removed via macro path per paper) |
| 3DHistech MIRAX (`.mrxs`) | yes | yes | tested |
| Roche / Ventana BIF (`.bif`) | yes | yes | tested (label and macro share one image; same constraint as NDPI) |
| Philips iSyntax (`.isyntax`) | yes | **no** | **not claimed** -- PathSafe has no `pathsafe/formats/isyntax.py` |
| Leica SCN (`.scn`) | not in paper | yes | extension beyond paper |
| Generic TIFF / OME-TIFF / QPTIFF | not in paper | yes | extension beyond paper |
| DICOM WSI | discussed but not enumerated | yes | extension beyond paper (PS3.15 Annex E) |

The Bisson Level IV claim covers SVS, NDPI, MRXS, and BIF. iSyntax is acknowledged as a gap.

## Level I: filename

| Bisson criterion | PathSafe code | Test |
|---|---|---|
| "removing sensitive information from the file name" | `pathsafe/formats/base.py` (filename PHI scan) + `pathsafe/serializer.py` (`--rename auto`/`mapping`/`template`) | `TestLevelI_Filename::test_filename_phi_detected` |

PathSafe additionally *detects* filename PHI at scan time so users see the warning before they run deidentify; the paper requires only the rename step.

## Level II: associated images unlinked

Paper, Methods → Implementation:

> "the IFD pointer of the predecessor has to be overwritten with the IFD pointer of the ensuing directory or, in case it is the last directory, terminated with a null-pointer."

| Bisson criterion | PathSafe code | Test |
|---|---|---|
| Unlink label/macro IFD from chain | `pathsafe/tiff/blanking.py::unlink_ifd` | `TestLevelII_AssociatedImageUnlinked::test_svs_unlink_preserves_valid_tiff`, `::test_ndpi_unlink_preserves_valid_tiff` |
| Post-unlink file remains a valid TIFF chain | `pathsafe/tiff/parser.py::iter_ifds` (re-parses) | same |

## Level III: image data destroyed

Paper:

> "the image data is overwritten with a blank image so that it cannot be reconstructed later."

| Bisson criterion | PathSafe code | Test |
|---|---|---|
| Overwrite label/macro strip/tile bytes | `pathsafe/tiff/blanking.py::blank_ifd_image_data` | `TestLevelIII_ImageDataDestroyed::test_image_data_overwritten_after_deidentify[tmp_svs/ndpi/bif/scn]` |
| Verify-after-blank | `pathsafe/tiff/blanking.py::is_ifd_image_blanked` | same |

## Level IV: all sensitive metadata deleted

Paper:

> "Level IV requires that all sensitive metadata be deleted in addition to the label image."

The paper's Appendix A lists, per format, the metadata fields that must be removed. Each row below maps the Appendix A field set to PathSafe's PHI list and to a test that asserts every field is recognized.

### Aperio / Leica SVS

Paper Appendix A: `ScanScope ID`, `Date`, `Time`, `User`, `Filename`.

| Bisson field | PathSafe source | Test |
|---|---|---|
| ScanScope ID | `pathsafe/formats/svs.py::SVS_PHI_FIELDS` | `TestLevelIV_AppendixA_SVS::test_appendix_a_fields_scrubbed` |
| Filename | same | same |
| Date | same | same |
| Time | same | same |
| User | same | same |

PathSafe additionally scrubs `DSR ID`, `Time Zone`, `ImageID`, `Left`, `Top`, `LineCameraSkew`, `LineAreaXOffset`, `LineAreaYOffset` (extension beyond paper).

### Hamamatsu NDPI

Paper Appendix A: `Macro.S/N`, `NDP.S/N`, `Created`, `Updated`. Stored in NDPI tag `65449` (`NDPI_SCANNER_PROPS`) as a key=value property string.

| Bisson field | PathSafe source | Test |
|---|---|---|
| Macro.S/N | `pathsafe/formats/ndpi.py::SCANNER_PROPS_PHI_KEYS` | `TestLevelIV_AppendixA_NDPI::test_appendix_a_keys_recognized` |
| NDP.S/N | same | same |
| Created | same | same |
| Updated | same | same |

PathSafe additionally scrubs `Firmware.Version` plus any property key whose name contains `User`, `Name`, or `Operator` (substring match).

### 3DHistech MIRAX

Paper Appendix A: `SLIDE_NAME`, `PROJECT_NAME`, `SLIDE_ID`, `SLIDE_CREATIONDATETIME`, `SCANNER_HARDWARE_ID`, `SLIDE_UTC_CREATIONDATETIME`, `ProfileName`. Stored in `Slidedat.ini` under `[GENERAL]`.

| Bisson field | PathSafe source | Test |
|---|---|---|
| SLIDE_NAME | `pathsafe/formats/mrxs.py::GENERAL_PHI_FIELDS` | `TestLevelIV_AppendixA_MRXS::test_appendix_a_keys_recognized` + `::test_phi_fields_in_synthetic_file_scrubbed` |
| PROJECT_NAME | same | same |
| SLIDE_ID | same | same |
| SLIDE_CREATIONDATETIME | same | same |
| SCANNER_HARDWARE_ID | same | same |
| SLIDE_UTC_CREATIONDATETIME | same | same |
| ProfileName | same (case-insensitive) | same |

PathSafe additionally scrubs `SLIDE_BARCODE`, `SLIDE_QUALITY`, `SLIDE_LABEL`, `SLIDE_DESCRIPTION`, `SLIDE_CREATOR`, `SLIDE_COMMENT`, `PATIENT_ID`, `PATIENT_NAME`, `CASE_ID`, `CASE_NUMBER`, `ACCESSION_NUMBER`, `PHYSICIAN_NAME`, `OPERATOR`.

### Roche / Ventana BIF

Paper Appendix A: `JP2FileName`, `UnitNumber`, `UserName`, `Barcode1D`, `Barcode2D`, `BaseName`, `BuildDate`. Stored as XMP attributes in TIFF tag `700`.

These attribute names correspond to an older Ventana XML schema. Modern iScan files use `BarCode1`/`BarCode2`, `ScanDate`, `OperatorID`, `BaseFileName`, etc. PathSafe handles both schemas:

| Bisson field (older schema) | PathSafe source | Test |
|---|---|---|
| JP2FileName | `pathsafe/formats/bif.py::XMP_PHI_ATTRIBUTES` | `TestLevelIV_AppendixA_BIF::test_appendix_a_keys_recognized` |
| UnitNumber | same | same |
| UserName | same | same |
| Barcode1D | same | same |
| Barcode2D | same | same |
| BaseName | same | same |
| BuildDate | same | same |

Modern-schema attributes (`BarCode1`, `BarCode2`, `ScanDate`, `ScanTime`, `BaseFileName`, `UniqueID`, `DeviceSerialNumber`, `OperatorID`, `PatientName`, `CaseID`, `SampleID`, `LabelText`, `Comment`, `Description`, plus `BarCodeType1`/`BarCodeType2`) are exercised by `TestLevelIV_AppendixA_BIF::test_modern_xmp_attributes_scrubbed`.

## Level IV operational invariants

These rules govern *how* deletion is performed; they apply to every format.

| Bisson invariant | Verbatim wording | PathSafe code | Test |
|---|---|---|---|
| Two-step destruction | "First, the image data is overwritten with a blank image so that it cannot be reconstructed later. Then, the image is unlinked..." | `blank_ifd_image_data()` then `unlink_ifd()` in `pathsafe/tiff/blanking.py` | `TestLevelIVInvariants::test_two_step_destruction_implemented` |
| Fixed-length string replacement | "the sensitive data can not just be removed but has to be replaced by an arbitrary, content-free string of the same length as the original string" | In-place patching in `pathsafe/formats/{ndpi,svs,mrxs,bif,scn}.py` -- file size never changes | `TestLevelIVInvariants::test_fixed_length_replacement_svs` |
| File remains valid post-deidentify | "the resulting WSI files are still usable by the designated proprietary or common open-source software" | TIFF parser re-walks the file | `TestLevelIVInvariants::test_file_remains_valid_tiff_after_deidentify` |
| Compression-pattern preservation | "Compressed image data, for instance, need to preserve the binary structure of the underlying compression algorithm stated in the WSI header (e.g. LZW, Deflate, or JPEG)" | PathSafe writes a valid empty JPEG (`FF D8 ... FF D9`) at the start of blanked image data | `TestLevelIVInvariants::test_jpeg_blank_pattern_preserves_compression_signature` |

## Level V: out of scope

Paper:

> "this thesis results in our final anonymization level V, in which we require the elimination of the spatial coherence of tissue sections... Currently, there are no usable solutions for Level V anonymization."

PathSafe does not address Level V. The README does not claim Level V conformance.

## PathSafe behaviours beyond Bisson Level IV

These are protections PathSafe provides that the paper does NOT require. They are not part of the Bisson conformance claim; they are extensions for stricter institutional environments.

| Behaviour | PathSafe code | Test |
|---|---|---|
| EXIF sub-IFD scrubbing | `pathsafe/tiff/sub_ifd.py::scan_exif_sub_ifd_tags`, `blank_exif_sub_ifd_tags` | `TestPathSafeBeyondBisson::test_exif_sub_ifd_handling_present` |
| GPS sub-IFD scrubbing | `pathsafe/tiff/sub_ifd.py::scan_gps_sub_ifd`, `blank_gps_sub_ifd` | `TestPathSafeBeyondBisson::test_gps_sub_ifd_handling_present` |
| Raw-byte regex sweep | `pathsafe/scanner.py::scan_bytes_for_phi` | `TestPathSafeBeyondBisson::test_raw_byte_regex_sweep_present` |
| DICOM PS3.15 de-identification | `pathsafe/formats/dicom.py` | `TestPathSafeBeyondBisson::test_dicom_handler_registered` |

## Verification methodology

The paper's own verification is informal:

> "the resulting WSI files are still usable by the designated proprietary or common open-source software."

PathSafe's verification is deliberately stricter. Each criterion above is exercised by an automated pytest test against synthetic files containing the PHI payload. Per-format tests build the file, run `deidentify_file()`, and assert the criterion holds. Run `pytest tests/test_bisson_conformance.py -v` for a current report.

A standalone third-party verifier (`tools/independent_scanner.py`) is also provided. It does not import PathSafe code; it parses TIFF binary structure from scratch and runs PHI detection against the output. See `tools/independent_scanner.py` for details.

## Known gaps

| Gap | Status |
|---|---|
| Philips iSyntax format | Not supported. The paper covers iSyntax; PathSafe does not yet. Listed in README and tested via `TestPaperFormatCoverage::test_isyntax_not_supported`. |
| Real-WSI conformance corpus | The conformance suite uses synthetic minimal-TIFF fixtures. Running it against the OpenSlide WSI repository (the corpus the paper used) is on the roadmap. |
| Re-validation in OpenSlide / vendor SDKs | The paper requires post-deidentify files open in OpenSlide / BioFormats / vendor SDKs. PathSafe's release builds open them in OpenSlide via `openslide-python` integration tests, but a per-criterion vendor-SDK round-trip is not yet automated. |

## Updating this document

`tests/test_bisson_conformance.py` is the source of truth. If you change PathSafe's behaviour:

1. Update or add a test in `test_bisson_conformance.py` that names the criterion.
2. Confirm `pytest tests/test_bisson_conformance.py -v` passes.
3. Update the matching row in this document (the row's "Test" column should always cite a real test name).

If a Bisson criterion stops being met, the corresponding test will fail. That failure IS the conformance regression.
