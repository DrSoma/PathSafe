# PathSafe

Hospital-grade WSI anonymizer for pathology slide files.

PathSafe detects and removes Protected Health Information (PHI) from whole-slide image (WSI) files before they are shared for research. It supports all major WSI formats and provides both a command-line interface and a graphical user interface.

Built from production experience anonymizing 3,101+ slides across 9 clinical batches.

## Key Features

- **Multi-format support**: NDPI, SVS, MRXS, DICOM WSI, and generic TIFF
- **Label and macro image blanking**: Removes photographed slide labels that may contain patient information
- **Safe by default**: Copy mode preserves originals; in-place requires explicit confirmation
- **Built-in verification**: Re-scans every file after anonymization to confirm all PHI was removed
- **Compliance certificates**: JSON audit trail with file hashes, timestamps, and per-file details
- **Graphical interface**: Qt GUI with dark/light theme and drag-and-drop for non-technical users
- **Parallel processing**: Speed up large batches with multiple workers

## Supported Formats

| Format | Scanner | What Gets Cleaned |
|--------|---------|-------------------|
| **NDPI** | Hamamatsu | Accession numbers, dates, macro/barcode images, embedded text |
| **SVS** | Aperio | Scanner metadata, operator names, dates, label/macro images |
| **MRXS** | 3DHISTECH/MIRAX | Slide IDs, barcodes, names, dates in Slidedat.ini |
| **DICOM WSI** | Various | 30+ patient/study/institution tags, all private tags |
| **Generic TIFF** | Any | Accession number patterns and dates in metadata tags |

## Installation

Requires Python 3.9+.

```bash
# Core (command line only):
pip install -e /path/to/pathsafe

# With graphical interface:
pip install -e "/path/to/pathsafe[gui]"

# With DICOM support:
pip install -e "/path/to/pathsafe[dicom]"

# Everything:
pip install -e "/path/to/pathsafe[all]"
```

## Quick Start

### 1. Scan your files (read-only, nothing is modified)

```bash
pathsafe scan /path/to/slides/ --verbose
```

### 2. Anonymize (originals are preserved)

```bash
pathsafe anonymize /path/to/slides/ --output /path/to/clean/
```

### 3. Verify the results

```bash
pathsafe verify /path/to/clean/
```

### Or use the graphical interface

```bash
pathsafe gui
```

## Graphical Interface

The GUI walks you through each step visually, so no command-line experience is needed.

- Dark and light themes, switchable from the View menu
- Drag and drop files or folders directly onto the window
- Step-by-step workflow indicator: **Select Files > Scan > Anonymize > Verify**
- Keyboard shortcuts for common actions
- Real-time progress and log output

Falls back to a simpler Tkinter interface if PySide6 is not installed.

## What Gets Anonymized

### NDPI (Hamamatsu)

| What | Where | Action |
|------|-------|--------|
| Accession numbers | Tag 65468 (NDPI_BARCODE) | Overwritten |
| Reference strings | Tag 65427 (NDPI_REFERENCE) | Overwritten |
| Scan dates | Tag 306, 36867, 36868 | Cleared |
| Macro image | Embedded overview photo | Blanked |
| Barcode image | Embedded barcode photo | Blanked |
| Any remaining patterns | First 100KB binary scan | Overwritten |

### SVS (Aperio)

| What | Where | Action |
|------|-------|--------|
| Scanner ID, filename, operator | Tag 270 (ImageDescription) | Redacted |
| Scan dates | Tag 306, 36867, 36868 | Cleared |
| Label image | Embedded label photo | Blanked |
| Macro image | Embedded overview photo | Blanked |
| Any remaining patterns | First 100KB binary scan | Overwritten |

### MRXS (3DHISTECH/MIRAX)

| What | Where | Action |
|------|-------|--------|
| Slide ID, name, barcode | Slidedat.ini [GENERAL] | Overwritten |
| Creation date/time | Slidedat.ini [GENERAL] | Replaced with placeholder |
| Any remaining patterns | .mrxs file and Slidedat.ini | Overwritten |

### DICOM WSI

| What | Examples | Action |
|------|----------|--------|
| Patient identifiers | Name, ID, birth date, sex, age | Blanked or replaced |
| Study identifiers | Accession number, study date, description | Blanked or replaced |
| Institution/physician info | Institution name, referring/performing physician | Blanked or deleted |
| Private tags | Vendor-specific data | Removed entirely |

### Generic TIFF

All text metadata tags are scanned for accession number patterns and redacted. Date tags are cleared.

## CLI Reference

```
pathsafe scan PATH [--verbose] [--format ndpi|svs|mrxs|dicom|tiff] [--json-out FILE]
pathsafe anonymize PATH [--output DIR] [--in-place] [--dry-run] [--no-verify]
                        [--format ndpi|svs|mrxs|dicom|tiff] [--certificate FILE]
                        [--verbose] [--workers N] [--log FILE]
pathsafe verify PATH [--verbose] [--format ndpi|svs|mrxs|dicom|tiff]
pathsafe info FILE
pathsafe gui
```

### Common options

| Option | What it does |
|--------|-------------|
| `--output DIR` | Save anonymized copies to this directory (originals untouched) |
| `--in-place` | Modify files directly instead of copying |
| `--dry-run` | Show what would be done without making changes |
| `--verbose` | Show detailed output |
| `--workers N` | Process N files in parallel |
| `--certificate FILE` | Generate a JSON compliance certificate |
| `--format FORMAT` | Only process files of this format |
| `--log FILE` | Save output to a log file |

## Compliance Certificate

Generate an audit trail for your anonymization batch:

```bash
pathsafe anonymize /slides/ --output /clean/ --certificate /clean/certificate.json
```

The certificate records the PathSafe version, a unique run ID, timestamps, per-file SHA-256 hashes, findings cleared, and verification status.

## Dependencies

- **Core**: Python 3.9+, `click`. All file parsing uses Python standard library only.
- **GUI** (optional): `PySide6` via `pip install pathsafe[gui]`
- **DICOM** (optional): `pydicom` via `pip install pathsafe[dicom]`
- **OpenSlide** (optional): `openslide-python` via `pip install pathsafe[openslide]`

## Building a Standalone Executable

```bash
pip install pyinstaller
pyinstaller pathsafe.spec
```

Produces `dist/pathsafe` (CLI) and `dist/pathsafe-gui` (GUI).

## License

MIT
