# PathSafe Compliance Documentation

## Purpose

PathSafe removes Protected Health Information (PHI) from whole-slide image (WSI) files so they can be used in research or shared externally. It provides a documented, verifiable de-identification process with full audit trails.

## PHI Categories Addressed

### Direct Identifiers

#### NDPI (Hamamatsu)

| Data Element | Where Found | Anonymization Method |
|---|---|---|
| Accession numbers | TIFF tag 65468 (NDPI_BARCODE) | Overwritten with 'X' characters + null terminator |
| Reference strings | TIFF tag 65427 (NDPI_REFERENCE) | Overwritten with 'X' characters + null terminator |
| Scan dates | TIFF tag 306 (DateTime) | Zeroed with null bytes |
| EXIF dates | TIFF tags 36867, 36868 | Zeroed with null bytes |
| Macro image | IFD with NDPI_SOURCELENS = -1.0 | Image data blanked (minimal JPEG + zeros) |
| Barcode/label image | IFD with NDPI_SOURCELENS = -2.0 | Image data blanked (minimal JPEG + zeros) |
| Embedded accession patterns | Raw binary header (first 100KB) | Overwritten with 'X' characters |

#### SVS (Aperio)

| Data Element | Where Found | Anonymization Method |
|---|---|---|
| Scanner ID | Tag 270 ImageDescription (ScanScope ID) | Overwritten with 'X' characters |
| Filename | Tag 270 ImageDescription (Filename) | Overwritten with 'X' characters |
| Scan date | Tag 270 ImageDescription (Date) | Replaced with sentinel '01/01/00' |
| Scan time | Tag 270 ImageDescription (Time) | Replaced with sentinel '00:00:00' |
| Operator name | Tag 270 ImageDescription (User) | Overwritten with 'X' characters |
| Scan dates | TIFF tag 306 (DateTime) | Zeroed with null bytes |
| Label image | IFD with "label" in ImageDescription | Image data blanked (minimal JPEG + zeros) |
| Macro image | IFD with "macro" in ImageDescription | Image data blanked (minimal JPEG + zeros) |
| Embedded accession patterns | Raw binary header (first 100KB) | Overwritten with 'X' characters |

#### MRXS (3DHISTECH/MIRAX)

| Data Element | Where Found | Anonymization Method |
|---|---|---|
| Slide ID | Slidedat.ini [GENERAL] SLIDE_ID | Overwritten with 'X' characters |
| Slide name | Slidedat.ini [GENERAL] SLIDE_NAME | Overwritten with 'X' characters |
| Slide barcode | Slidedat.ini [GENERAL] SLIDE_BARCODE | Overwritten with 'X' characters |
| Creation date/time | Slidedat.ini [GENERAL] SLIDE_CREATIONDATETIME | Replaced with sentinel '1970-01-01T00:00:00' |
| Slide quality | Slidedat.ini [GENERAL] SLIDE_QUALITY | Overwritten with 'X' characters |
| Project name | Slidedat.ini [GENERAL] PROJECT_NAME | Overwritten with 'X' characters |
| Slide label | Slidedat.ini [GENERAL] SLIDE_LABEL | Overwritten with 'X' characters |
| Embedded accession patterns | .mrxs file and Slidedat.ini | Overwritten with 'X' characters |

#### DICOM WSI

| Data Element | DICOM Tag | Anonymization Method |
|---|---|---|
| Patient name | (0010,0010) | Blanked (empty string) |
| Patient ID | (0010,0020) | Blanked (empty string) |
| Patient birth date | (0010,0030) | Replaced with '19000101' |
| Patient sex | (0010,0040) | Blanked |
| Patient age | (0010,1010) | Blanked |
| Accession number | (0008,0050) | Blanked |
| Study date | (0008,0020) | Replaced with '19000101' |
| Series date | (0008,0021) | Replaced with '19000101' |
| Acquisition date | (0008,0022) | Replaced with '19000101' |
| Content date | (0008,0023) | Replaced with '19000101' |
| Study time | (0008,0030) | Blanked |
| Referring physician | (0008,0090) | Blanked |
| Institution name | (0008,0080) | Blanked |
| Other patient IDs | (0010,1000) | Deleted |
| Patient address | (0010,1040) | Deleted |
| Institution address | (0008,0081) | Deleted |
| Operator's name | (0008,1070) | Deleted |
| Physician(s) of record | (0008,1048) | Deleted |
| Performing physician | (0008,1050) | Deleted |
| Patient's mother's name | (0010,1060) | Deleted |
| Patient comments | (0010,4000) | Deleted |
| Study comments | (0032,4000) | Deleted |
| Additional patient history | (0010,21B0) | Deleted |
| Requesting physician | (0032,1032) | Deleted |
| Study description | (0008,1030) | Deleted |
| Series description | (0008,103E) | Deleted |
| Protocol name | (0018,1030) | Deleted |
| All private tags | Vendor-specific | Removed entirely |

#### Generic TIFF

| Data Element | Where Found | Anonymization Method |
|---|---|---|
| All ASCII string tags | First IFD | Scanned for accession number patterns, matches overwritten |
| Dates | TIFF tag 306 (DateTime) | Zeroed with null bytes |

### Pattern-Based Detection

PathSafe uses the following regex patterns to detect accession numbers in raw binary data:

- `AS-\d\d-\d{3,}`: Standard accession format
- `AC-\d\d-\d{3,}`: Alternative accession format
- `CH\d{5,}`: CH-prefix accession format
- `00000AS\d+`: Zero-padded accession format

## Label and Macro Image Handling

Whole-slide image files often contain embedded photographs of the physical slide label (label image) and an overview photograph of the entire slide (macro image). These images can contain patient-identifying information printed or handwritten on the slide label.

PathSafe blanks label and macro images by overwriting their pixel data with a minimal valid 1x1 white JPEG (630 bytes, compatible with libjpeg/OpenSlide) followed by zero bytes. This preserves the TIFF file structure while destroying all visual content.

| Format | Label Detection Method | Macro Detection Method |
|---|---|---|
| NDPI | NDPI_SOURCELENS tag = -2.0 | NDPI_SOURCELENS tag = -1.0 |
| SVS | "label" in ImageDescription | "macro" in ImageDescription |

## Anonymization Process

### Copy Mode (Default)

1. Source file is copied to the output directory
2. PHI is identified and removed from the copy
3. Label and macro images are blanked (NDPI, SVS)
4. The copy is re-scanned to verify all PHI was removed
5. A compliance certificate is generated

Original files are never modified in copy mode.

### In-Place Mode

1. PHI is identified in the original file
2. PHI fields are overwritten directly in the original file
3. Label and macro images are blanked (NDPI, SVS)
4. The file is re-scanned to verify all PHI was removed
5. A compliance certificate is generated

In-place mode requires explicit `--in-place` flag to prevent accidental modification.

## Verification

After anonymization, PathSafe re-scans every processed file using the same detection engine. A file is considered "verified clean" only if the re-scan finds zero PHI findings.

Verification can also be run independently at any time:

```bash
pathsafe verify /path/to/anonymized/files/
```

## Compliance Certificate

Each batch anonymization produces a JSON certificate containing:

- **PathSafe version**: Software version used
- **Certificate ID**: Unique UUID for this anonymization run
- **Timestamp**: ISO 8601 UTC timestamp
- **Mode**: "copy" or "inplace"
- **Summary**: Total files, anonymized count, error count, verification status
- **Per-file records**: Filename, format, SHA-256 hash after anonymization, findings cleared, verification status

### Certificate Storage

Certificates should be stored alongside the anonymized files and retained according to your institution's data governance policy.

## Audit Trail

For each anonymized file, the certificate records:

1. Source file path
2. Output file path
3. File format detected
4. Number of PHI findings cleared
5. Whether post-anonymization verification passed
6. SHA-256 hash of the anonymized file
7. Processing time

## Limitations

- **Image content**: PathSafe anonymizes metadata, embedded text fields, and label/macro images. It does not analyze or modify the diagnostic slide image content itself.
- **MRXS images**: MRXS label/macro images are stored as separate files in the data directory. PathSafe currently anonymizes Slidedat.ini metadata but does not blank MRXS label images.
- **Pattern coverage**: PHI detection relies on known accession number patterns. Custom patterns for your institution should be added to the scanner configuration.
- **DICOM completeness**: DICOM anonymization covers standard tags and private tags. Application-specific sequences may need additional handling depending on the imaging vendor.
- **File integrity**: PathSafe modifies files at the byte level, preserving TIFF structure. However, always maintain backups of original files before in-place anonymization.

## Anonymization Depth (Bisson et al. 2023)

PathSafe implements **Level IV** anonymization as defined by Bisson et al. in ["Anonymization of whole slide images in histopathology for research and education"](https://doi.org/10.1177/20552076231171475) (Digital Health, 2023). This covers:

- **Level I**: Filename PHI detection (accession number patterns in filenames)
- **Level II**: Associated image dereferencing
- **Level III**: Label and macro image blanking (pixel data destroyed)
- **Level IV**: Complete metadata removal (scanner serial numbers, acquisition dates, operator names, barcodes, device identifiers, and all format-specific PHI fields)

Level V (spatial coherence removal to prevent tissue-based re-identification) is not currently implemented by any available tool and remains an open research problem.

## Regulatory Context

PathSafe is a de-identification tool that removes patient identifiers from slide files and provides documentation of what was done. The compliance certificate and verification reports can serve as supporting evidence when responding to regulatory or privacy reviews, submitting data for research, or maintaining institutional records.

Compliance with any specific regulation or standard depends on your institution's policies, the scope of identifiers in your data, and the broader processes surrounding data handling. PathSafe addresses the identifiers embedded in WSI file metadata and images, but should be used as part of your institution's overall data governance workflow.

## Software Security

PathSafe is designed with security in mind:

- **No network access**: PathSafe never connects to the internet. All processing happens locally on the user's machine. No data leaves the system.
- **No external dependencies for file parsing**: All TIFF/WSI file reading and writing uses Python's built-in `struct` module. There are no third-party C libraries that could introduce buffer overflow or memory corruption vulnerabilities.
- **No code execution from files**: PathSafe never executes, evaluates, or deserializes any data found in slide files. It reads bytes at known offsets and overwrites them with sanitized values.
- **Memory-safe implementation**: Python's memory safety model prevents buffer overflow attacks from maliciously crafted input files.
- **Minimal dependency surface**: The only runtime dependency is `click` (CLI framework). Optional dependencies (PySide6, pydicom, openslide-python) are well-established, widely audited libraries.
- **Open source**: The entire codebase is available for review. There is no hidden functionality or telemetry.
