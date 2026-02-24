# PathSafe User Guide

Step-by-step instructions for hospital staff to anonymize pathology slide files.

## Overview

PathSafe removes patient-identifying information from whole-slide image (WSI) files before they are shared for research. It works with:

- **NDPI** files (Hamamatsu scanners)
- **SVS** files (Aperio scanners)
- **MRXS** files (3DHISTECH/MIRAX scanners)
- **DICOM WSI** files
- Other TIFF-based formats

PathSafe can be used via the command line or the graphical interface (GUI).

## Installation

Ask your IT department to install PathSafe, or run:

```bash
# Core (CLI only):
pip install -e /path/to/pathsafe

# With GUI support (recommended for non-technical users):
pip install -e "/path/to/pathsafe[gui]"

# With DICOM support:
pip install -e "/path/to/pathsafe[dicom]"

# Everything:
pip install -e "/path/to/pathsafe[all]"
```

Verify installation:

```bash
pathsafe --version
```

You should see `pathsafe, version 1.0.0`.

## Step 1: Check Your Files First (Scan)

Before anonymizing, scan your files to see what PHI is present.

```bash
pathsafe scan /path/to/your/slides/ --verbose
```

This is read-only and does not modify any files. You'll see output like:

```
Scanning 500 file(s)...
  [1/500] slide001.ndpi - 1 finding(s)
    NDPI_BARCODE at offset 1234: AS-24-123456
  [2/500] slide002.ndpi - 1 finding(s)
    NDPI_BARCODE at offset 1234: AS-24-123457
  ...
Summary: 500 files scanned, 0 clean, 500 with PHI (500 total findings)
```

## Step 2: Anonymize (Copy Mode Recommended)

Copy mode creates anonymized copies in a new directory. Your originals are untouched.

```bash
pathsafe anonymize /path/to/your/slides/ --output /path/to/clean/slides/ --certificate /path/to/clean/certificate.json --verbose
```

You'll see progress:

```
PathSafe v1.0.0 - copy anonymization
Processing 500 file(s)...

  [1/500] 2.5/s ETA 3m | slide001.ndpi | cleared 1 finding(s) [verified]
  [2/500] 2.6/s ETA 3m | slide002.ndpi | cleared 1 finding(s) [verified]
  ...

Done in 195.3s
  Total:         500
  Anonymized:    498
  Already clean: 2
  Errors:        0

Compliance certificate: /path/to/clean/certificate.json
```

### In-Place Anonymization

If you don't need to keep originals (e.g., you have backups):

```bash
pathsafe anonymize /path/to/your/slides/ --in-place --verbose
```

### Dry Run

Preview what would be anonymized without making changes:

```bash
pathsafe anonymize /path/to/your/slides/ --output /path/to/clean/ --dry-run
```

### Parallel Processing

Speed up large batches with multiple workers:

```bash
pathsafe anonymize /path/to/your/slides/ --output /path/to/clean/ --workers 4
```

## Step 3: Verify

After anonymization, verify that all PHI has been removed:

```bash
pathsafe verify /path/to/clean/slides/ --verbose
```

Expected output:

```
Verifying 500 file(s)...
  [1/500] slide001.ndpi - CLEAN
  [2/500] slide002.ndpi - CLEAN
  ...
Verification: 500 clean, 0 with remaining PHI
All files verified clean.
```

## Step 4: Review the Compliance Certificate

Open the JSON certificate file to review the anonymization report. It contains:

- PathSafe version used
- Timestamp
- Per-file details (findings cleared, SHA-256 hash, verification status)
- Summary statistics

Keep this certificate with the anonymized files for audit purposes.

## Using the GUI

Launch the graphical interface:

```bash
pathsafe gui
```

### Qt GUI (Recommended)

If PySide6 is installed (`pip install pathsafe[gui]`), PathSafe launches a modern Qt GUI with:

- **Dark / Light theme**: Catppuccin-inspired color schemes, remembered between sessions
- **Drag-and-drop**: Drop files or folders directly onto the window
- **Multi-file selection**: Select multiple files at once when browsing (hold Ctrl or Shift)
- **Workflow step indicator**: Visual progress through Select Files > Scan > Select Output > Anonymize, with [Default] and [Done] status labels
- **Application icon**: Custom PathSafe icon in the title bar and taskbar
- **Right-click integration**: On Linux, right-click any slide file and choose "Open with PathSafe"
- **Menu bar with keyboard shortcuts**:
 - `Ctrl+O`: Open file(s)
 - `Ctrl+Shift+O`: Open folder
 - `Ctrl+S`: Scan
 - `Ctrl+R`: Anonymize
 - `Ctrl+E`: Verify
 - `Esc`: Stop current operation
- **Tooltips**: Hover over any control for guidance
- **Status bar**: Live file count and elapsed time
- **Log panel**: Real-time output with human-readable finding names
- **PDF reports**: Scan reports and compliance certificates generated automatically with SHA-256 hashes and a findings legend
- **Copy/in-place mode**: Select via radio buttons
- **Workers**: Adjust parallel processing for anonymization
- **Institution name**: Optional field for PDF report headers, remembered between sessions
- **Persistent settings**: Institution, worker count, and theme are saved between sessions

## Common Options

| Option | Description |
|--------|-------------|
| `--verbose` / `-v` | Show detailed output |
| `--format ndpi` | Only process NDPI files |
| `--format svs` | Only process SVS files |
| `--format mrxs` | Only process MRXS files |
| `--format dicom` | Only process DICOM files |
| `--format tiff` | Only process generic TIFF files |
| `--dry-run` | Preview without changes |
| `--workers N` | Use N parallel workers for faster batch processing |
| `--log FILE` | Save output to a log file |
| `--certificate FILE` | Generate compliance certificate |
| `--no-verify-integrity` | Skip SHA-256 image integrity verification (enabled by default) |
| `--no-reset-timestamps` | Keep original file timestamps (reset to epoch by default) |

## What Gets Anonymized

PathSafe removes these categories of PHI:

- **Accession numbers**: Found in TIFF metadata tags, binary data, and filenames (AS-, AC-, SP-, AP-, CY-, H-, S-, CH and more formats)
- **Medical record numbers (MRN)**: Detected via pattern matching in metadata and filenames
- **Patient names and IDs**: Found in DICOM tags and DICOM sequences (recursive)
- **Dates**: Scan dates, EXIF dates, study dates, ISO 8601 dates, slash-delimited dates
- **Operator/physician names**: Found in SVS, DICOM, and extra metadata tags (Artist, HostComputer)
- **Institution information**: Found in DICOM tags and device serial numbers
- **Label/macro images**: Photographed slide labels that may show patient information (NDPI, SVS, BIF, SCN)
- **Slide identifiers**: MRXS slide names, barcodes, IDs
- **Extra metadata**: XMP, EXIF UserComment, IPTC, Copyright, ImageUniqueID, ICC Color Profile
- **EXIF sub-IFD**: Dates, UserComment, ImageUniqueID hidden in EXIF sub-directories
- **GPS sub-IFD**: Location coordinates and timestamps hidden in GPS sub-directories
- **Social Security numbers**: Detected via pattern matching as a HIPAA safe harbor measure
- **Date of birth**: DOB patterns detected in filenames and metadata

All tags are scanned across **every IFD** (image layer) in the file, not just the first one.

**Note on filenames:** PathSafe detects PHI in filenames but cannot automatically rename files (this would break file associations). If a filename contains patient data, PathSafe displays a warning so you can rename the file manually.

For a detailed breakdown by format, see the main [README](../README.md).

## File Info

To inspect a single file's metadata:

```bash
pathsafe info /path/to/slide.ndpi
```

## Troubleshooting

### "No WSI files found"

Make sure the directory contains `.ndpi`, `.svs`, `.tif`, `.tiff`, `.mrxs`, `.dcm`, or `.dicom` files. Use `--format` to filter if needed.

### "Error: Must specify --output for copy mode, or --in-place"

PathSafe requires explicit confirmation for in-place modification. Either:
- Add `--output /destination/` for copy mode, or
- Add `--in-place` to confirm modification of originals

### "Some files still contain PHI!"

If verification finds remaining PHI, run anonymize again on the flagged files. This can happen with unusual file structures. Report persistent issues to your IT team.

### GUI won't launch

If you see `qt.qpa.plugin: Could not load the Qt platform plugin 'xcb'`, install the required system library:

```bash
sudo apt install -y libxcb-cursor0
```

If PySide6 is not installed at all, PathSafe will fall back to the Tkinter GUI automatically.

## Getting Help

```bash
pathsafe --help
pathsafe scan --help
pathsafe anonymize --help
```
