# PathSafe

Hospital-grade WSI anonymizer for pathology slide files.

PathSafe detects and removes Protected Health Information (PHI) from whole-slide image (WSI) files. It was built from production experience anonymizing 3,101+ NDPI files across 9 LungAI batches, after discovering that existing tools (wsianon) miss critical PHI fields and fail on certain scanner outputs.

## Why PathSafe?

| Problem with existing tools | PathSafe solution |
|---|---|
| wsianon fails on NDPI files without macro images (CaloPix) | Handles all NDPI variants |
| wsianon misses NDPI tag 65468 (NDPI_BARCODE) with accession numbers | Targets tag 65468 as primary PHI source |
| No label/macro image handling in metadata-only tools | Blanks label and macro images that may contain photographed patient info |
| No copy mode — only in-place modification | Copy-then-anonymize by default |
| No verification | Re-scans after anonymization to confirm |
| No compliance reporting | JSON compliance certificates |
| CLI only | CLI + Qt GUI with dark theme, drag-and-drop |

## Installation

```bash
pip install -e /path/to/pathsafe

# With GUI support (PySide6):
pip install -e "/path/to/pathsafe[gui]"

# With DICOM support:
pip install -e "/path/to/pathsafe[dicom]"

# Everything:
pip install -e "/path/to/pathsafe[all]"
```

## Quick Start

### Scan for PHI (read-only)

```bash
# Scan a directory
pathsafe scan /path/to/slides/

# Scan a single file with details
pathsafe scan /path/to/slide.ndpi --verbose
```

### Anonymize (copy mode — originals preserved)

```bash
pathsafe anonymize /path/to/slides/ --output /path/to/clean/
```

### Anonymize (in-place)

```bash
pathsafe anonymize /path/to/slides/ --in-place
```

### Verify anonymization

```bash
pathsafe verify /path/to/clean/
```

### File info

```bash
pathsafe info /path/to/slide.ndpi
```

## What Gets Anonymized

### NDPI (Hamamatsu)

| Tag | Name | Action |
|-----|------|--------|
| 65468 | NDPI_BARCODE | Overwrite with X's |
| 65427 | NDPI_REFERENCE | Overwrite with X's |
| 306 | DateTime | Zero out |
| 36867/36868 | DateTimeOriginal/Digitized | Zero out |
| — | Macro image (SOURCELENS=-1) | Blank image data |
| — | Barcode image (SOURCELENS=-2) | Blank image data |
| — | Regex safety scan (first 100KB) | Overwrite matches |

### SVS (Aperio)

| Tag | Name | Action |
|-----|------|--------|
| 270 | ImageDescription | Parse key=value pairs, redact ScanScope ID, Filename, Date, Time, User |
| 306 | DateTime | Zero out |
| 36867/36868 | DateTimeOriginal/Digitized | Zero out |
| — | Label image | Blank image data |
| — | Macro image | Blank image data |
| — | Regex safety scan (first 100KB) | Overwrite matches |

### MRXS (3DHISTECH/MIRAX)

| Field | Location | Action |
|-------|----------|--------|
| SLIDE_ID | Slidedat.ini [GENERAL] | Overwrite with X's |
| SLIDE_NAME | Slidedat.ini [GENERAL] | Overwrite with X's |
| SLIDE_BARCODE | Slidedat.ini [GENERAL] | Overwrite with X's |
| SLIDE_CREATIONDATETIME | Slidedat.ini [GENERAL] | Replace with sentinel |
| — | Regex scan of .mrxs and Slidedat.ini | Overwrite matches |

### DICOM WSI

| Tag | Name | Action |
|-----|------|--------|
| (0010,0010) | PatientName | Blank |
| (0010,0020) | PatientID | Blank |
| (0010,0030) | PatientBirthDate | Replace with 19000101 |
| (0008,0050) | AccessionNumber | Blank |
| (0008,0020) | StudyDate | Replace with 19000101 |
| + 20 more | Institution, Physician, etc. | Blank or delete |
| — | All private tags | Remove entirely |

### Generic TIFF

All ASCII string tags in the first IFD are scanned for accession number patterns and redacted if found. Date tags are zeroed.

## CLI Options

```
pathsafe scan PATH [--verbose] [--format ndpi|svs|mrxs|dicom|tiff] [--json-out FILE]
pathsafe anonymize PATH [--output DIR] [--in-place] [--dry-run] [--no-verify]
                        [--format ndpi|svs|mrxs|dicom|tiff] [--certificate FILE]
                        [--verbose] [--workers N] [--log FILE]
pathsafe verify PATH [--verbose] [--format ndpi|svs|mrxs|dicom|tiff]
pathsafe info FILE
pathsafe gui
```

## Compliance Certificate

After batch anonymization, generate a JSON certificate:

```bash
pathsafe anonymize /slides/ --output /clean/ --certificate /clean/certificate.json
```

The certificate includes file hashes, findings cleared, verification status, and timestamps for audit trails.

## GUI

Launch the graphical interface for non-technical users:

```bash
pathsafe gui
```

Features:
- Dark theme with modern Catppuccin-inspired styling
- Drag-and-drop file/folder support
- Workflow step indicator (Select Files > Scan > Anonymize > Verify)
- Menu bar with keyboard shortcuts (Ctrl+S scan, Ctrl+R anonymize)
- Tooltips on all controls
- Status bar with live progress
- Copy/in-place mode selection with verification

Falls back to Tkinter GUI if PySide6 is not installed.

## Parallel Processing

Speed up large batches with multiple workers:

```bash
pathsafe anonymize /slides/ --output /clean/ --workers 4
```

## Supported Formats

- **NDPI** (Hamamatsu) — full support including label/macro blanking
- **SVS** (Aperio) — full support including label/macro blanking
- **MRXS** (3DHISTECH/MIRAX) — Slidedat.ini metadata anonymization
- **DICOM WSI** — full DICOM tag anonymization (requires `pydicom`)
- **Generic TIFF** — fallback scanning for any TIFF-based format

## Optional OpenSlide Integration

When `openslide-python` is installed, PathSafe can use OpenSlide for enhanced format detection and slide property reading:

```python
from pathsafe.openslide_utils import get_slide_info, detect_vendor
info = get_slide_info(Path("slide.ndpi"))
```

## Building a Standalone Executable

```bash
pip install pyinstaller
pyinstaller pathsafe.spec
```

This produces `dist/pathsafe` (CLI) and `dist/pathsafe-gui` (GUI).

## Dependencies

- **Core**: Python 3.9+, `click` (CLI framework). All file parsing uses Python stdlib only (`struct`, `re`, `pathlib`)
- **GUI**: `PySide6` (optional, `pip install pathsafe[gui]`)
- **DICOM**: `pydicom` (optional, `pip install pathsafe[dicom]`)
- **OpenSlide**: `openslide-python` (optional, `pip install pathsafe[openslide]`)

## License

MIT
