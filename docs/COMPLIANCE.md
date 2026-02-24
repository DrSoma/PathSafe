# PathSafe Compliance Documentation

## Purpose

PathSafe ensures that whole-slide image (WSI) files are stripped of Protected Health Information (PHI) before being used in research or shared externally, in accordance with HIPAA Safe Harbor de-identification requirements.

## PHI Categories Addressed

### Direct Identifiers

#### NDPI (Hamamatsu)

| Data Element | Where Found | Anonymization Method |
|---|---|---|
| Accession numbers | TIFF tag 65468 (NDPI_BARCODE) | Overwritten with 'X' characters + null terminator |
| Reference strings | TIFF tag 65427 (NDPI_REFERENCE) | Overwritten with 'X' characters + null terminator |
| Scan dates | TIFF tag 306 (DateTime) | Zeroed with null bytes |
| EXIF dates | TIFF tags 36867, 36868 | Zeroed with null bytes |
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
| Embedded accession patterns | Raw binary header (first 100KB) | Overwritten with 'X' characters |

### Pattern-Based Detection

PathSafe uses the following regex patterns to detect accession numbers in raw binary data:

- `AS-\d\d-\d{3,}` — Standard accession format
- `AC-\d\d-\d{3,}` — Alternative accession format
- `CH\d{5,}` — CH-prefix accession format
- `00000AS\d+` — Zero-padded accession format

## Anonymization Process

### Copy Mode (Default)

1. Source file is copied to the output directory
2. PHI is identified and removed from the copy
3. The copy is re-scanned to verify all PHI was removed
4. A compliance certificate is generated

Original files are never modified in copy mode.

### In-Place Mode

1. PHI is identified in the original file
2. PHI fields are overwritten directly in the original file
3. The file is re-scanned to verify all PHI was removed
4. A compliance certificate is generated

In-place mode requires explicit `--in-place` flag to prevent accidental modification.

## Verification

After anonymization, PathSafe re-scans every processed file using the same detection engine. A file is considered "verified clean" only if the re-scan finds zero PHI findings.

Verification can also be run independently at any time:

```bash
pathsafe verify /path/to/anonymized/files/
```

## Compliance Certificate

Each batch anonymization produces a JSON certificate containing:

- **PathSafe version** — Software version used
- **Certificate ID** — Unique UUID for this anonymization run
- **Timestamp** — ISO 8601 UTC timestamp
- **Mode** — "copy" or "inplace"
- **Summary** — Total files, anonymized count, error count, verification status
- **Per-file records** — Filename, format, SHA-256 hash after anonymization, findings cleared, verification status

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

- **Image content**: PathSafe anonymizes metadata and embedded text fields. It does not analyze or modify the slide image content itself. Label and macro images (which may contain photographed patient information) are not yet handled.
- **Pattern coverage**: PHI detection relies on known accession number patterns. Custom patterns for your institution should be added to the scanner configuration.
- **File integrity**: PathSafe modifies files at the byte level, preserving TIFF structure. However, always maintain backups of original files before in-place anonymization.

## Regulatory Context

PathSafe supports compliance with:

- **HIPAA Safe Harbor** (45 CFR 164.514(b)(2)) — Removal of identifiers from health information
- **HIPAA Expert Determination** — When used as part of a broader de-identification workflow
- **GDPR Article 89** — Processing for research purposes with appropriate safeguards
- **Institutional Review Board (IRB)** requirements for de-identified data

PathSafe is a tool that assists with de-identification. Compliance ultimately depends on institutional policies and the completeness of PHI detection patterns for your specific data.
