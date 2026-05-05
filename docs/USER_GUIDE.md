# PathSafe User Guide

Step-by-step instructions for hospital staff to de-identify pathology slide files.

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

You should see `pathsafe, version 1.1.0`.

## Step 1: Check Your Files First (Scan)

Before de-identifying, scan your files to see what PHI is present.

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

## Step 2: De-identify (Copy Mode Recommended)

Copy mode creates de-identified copies in a new directory. Your originals are untouched.

```bash
pathsafe deidentify /path/to/your/slides/ --output /path/to/clean/slides/ --certificate /path/to/clean/certificate.json --verbose
```

You'll see progress:

```
PathSafe v1.1.0 - copy deidentification
Processing 500 file(s)...

  [1/500] 2.5/s ETA 3m | slide001.ndpi | cleared 1 finding(s) [verified]
  [2/500] 2.6/s ETA 3m | slide002.ndpi | cleared 1 finding(s) [verified]
  ...

Done in 195.3s
  Total:         500
  Deidentified:    498
  Already clean: 2
  Errors:        0

Compliance certificate: /path/to/clean/certificate.json
```

### In-Place De-identification

If you don't need to keep originals (e.g., you have backups):

```bash
pathsafe deidentify /path/to/your/slides/ --in-place --verbose
```

### Dry Run

Preview what would be de-identified without making changes:

```bash
pathsafe deidentify /path/to/your/slides/ --output /path/to/clean/ --dry-run
```

### Parallel Processing

PathSafe automatically selects the optimal number of worker threads based on your machine's CPU count (formula: `min(cpu_count // 2, 8)`). This scales from 1 worker on a 2-core laptop to 8 on a high-end workstation.

You can override this if needed:

```bash
pathsafe deidentify /path/to/your/slides/ --output /path/to/clean/ --workers 4
```

When `--workers` is omitted (or set to 0), auto-detection is used.

### Renaming Output Files

PathSafe can rename output files during de-identification to remove PHI from filenames. Three rename modes are available:

#### Auto Mode (Sequential Numbering)

Assigns sequential numbers to output files:

```bash
pathsafe deidentify /path/to/slides/ --output /path/to/clean/ --rename auto --prefix SLIDE --start 1 --digits 4
```

This produces `SLIDE_0001.ndpi`, `SLIDE_0002.ndpi`, etc. You can customize:

- `--prefix`: Filename prefix (default: `SLIDE`)
- `--start`: Starting number (default: `1`)
- `--digits`: Zero-padded width (default: `4`)
- `--separator`: Character between prefix and number (default: `_`)

#### Mapping Mode (CSV Lookup)

Renames files based on a CSV file that maps original filenames to new names:

```bash
pathsafe deidentify /path/to/slides/ --output /path/to/clean/ --rename mapping --mapping-file /path/to/mapping.csv
```

The CSV file should have two columns (no header required):

```
original_slide_001.ndpi,RESEARCH_A001.ndpi
original_slide_002.ndpi,RESEARCH_A002.ndpi
```

#### Template Mode (Pattern-Based)

Renames files using a template pattern:

```bash
pathsafe deidentify /path/to/slides/ --output /path/to/clean/ --rename template --template "STUDY_{n:04d}"
```

The `{n}` placeholder is replaced with a sequential number. Use Python-style format specifiers like `{n:04d}` for zero-padding.

#### Manifest CSV

Add `--manifest /path/to/manifest.csv` to generate a CSV file tracking the original-to-serialized filename mapping along with SHA-256 checksums:

```bash
pathsafe deidentify /path/to/slides/ --output /path/to/clean/ --rename auto --manifest /path/to/manifest.csv
```

#### Keep Mode (Default)

Use `--rename keep` (or omit `--rename` entirely) to preserve original filenames.

## Step 3: Verify

After de-identification, verify that all PHI has been removed:

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

Open the JSON certificate file to review the de-identification report. It contains:

- PathSafe version used
- Timestamp
- Per-file details (findings cleared, SHA-256 hash, verification status)
- Summary statistics

Keep this certificate with the de-identified files for audit purposes.

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
- **Workflow step indicator**: Visual progress through Select Files > Scan > Select Output > De-identify, with [Default] and [Done] status labels
- **Application icon**: Custom PathSafe icon in the title bar and taskbar
- **Right-click integration**: On Linux, right-click any slide file and choose "Open with PathSafe"
- **Menu bar with keyboard shortcuts**:
 - `Ctrl+O`: Open file(s)
 - `Ctrl+Shift+O`: Open folder
 - `Ctrl+S`: Scan
 - `Ctrl+R`: De-identify
 - `Ctrl+E`: Verify
 - `Esc`: Stop current operation
- **Tooltips**: Hover over any control for guidance
- **Status bar**: Live file count and elapsed time
- **Log panel**: Real-time output with human-readable finding names
- **PDF reports**: Scan reports and compliance certificates generated automatically with SHA-256 hashes and a findings legend
- **Copy/in-place mode**: Select via radio buttons
- **Auto-workers**: Worker count is automatically detected based on your CPU (no manual slider). The formula is `min(cpu_count // 2, 8)`.
- **Rename output files**: Check the "Rename Output Files" checkbox to enable file renaming during de-identification. Select from Auto, Mapping, or Template mode via radio buttons. A live preview with 300ms debounce shows what the output filenames will look like before you run the operation.
- **Update checker**: Optionally check for new PathSafe releases. Disabled by default. Enable via **Settings > "Check for updates on startup"**. When a new version is found, a toast notification appears in the top-right corner (auto-dismisses after 20 seconds) with a "Download" button that opens your browser to the correct platform download. A persistent badge also appears in the status bar. You can also trigger a manual check from **Settings > "Check for updates now"**.
- **Institution name**: Optional field for PDF report headers, remembered between sessions
- **Persistent settings**: Institution and theme are saved between sessions

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
| `--workers N` | Use N parallel workers (default: 0 = auto-detect based on CPU count) |
| `--log FILE` | Save output to a log file |
| `--certificate FILE` | Generate compliance certificate |
| `--no-verify-integrity` | Skip SHA-256 image integrity verification (enabled by default) |
| `--no-reset-timestamps` | Keep original file timestamps (reset to epoch by default) |
| `--rename MODE` | Rename output files: `keep` (default), `auto`, `mapping`, or `template` |
| `--prefix TEXT` | Filename prefix for auto mode (default: `SLIDE`) |
| `--start N` | Starting number for auto mode (default: `1`) |
| `--digits N` | Zero-padded width for auto mode (default: `4`) |
| `--separator CHAR` | Separator between prefix and number (default: `_`) |
| `--mapping-file FILE` | CSV file for mapping mode (original,new per line) |
| `--template PATTERN` | Template pattern for template mode (e.g., `STUDY_{n:04d}`) |
| `--manifest FILE` | Write original-to-new filename manifest CSV with SHA-256 checksums |

## What Gets De-identified

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

## Renaming Files During De-identification

Slide filenames often contain patient identifiers (e.g., `AS22001663_1030624.svs`). PathSafe can rename files during copy-mode de-identification to remove this PHI.

### Auto-Sequential Mode

Number files sequentially with a prefix:

```bash
pathsafe deidentify /slides/ --output /anon/ --rename auto --prefix STUDY --digits 4
```

Produces: `STUDY_0001.ndpi`, `STUDY_0002.svs`, `STUDY_0003.ndpi`, ...

Options: `--prefix` (default: ANON), `--start` (default: 1), `--digits` (default: 4), `--separator` (default: _)

### Mapping Mode

Rename using a CSV lookup table:

```bash
pathsafe deidentify /slides/ --output /anon/ --rename mapping --mapping-file renames.csv
```

Where `renames.csv` contains:
```csv
source_filename,output_name
AS22001663_1030624.svs,Patient001_BlockA.svs
AS22001663_1030625.svs,Patient001_BlockB.svs
```

Files not in the mapping are skipped by default.

### Template Mode

Use a naming pattern with tokens:

```bash
pathsafe deidentify /slides/ --output /anon/ --rename template --template "{prefix}_{date}_{index}.{ext}"
```

Available tokens: `{prefix}`, `{index}`, `{ext}`, `{sha8}`, `{format}`, `{date}`

### Manifest CSV

All rename modes automatically write a `manifest.csv` to the output folder mapping original filenames to their new names, with SHA-256 checksums (if `--checksum` was used). Use `--manifest /path/to/manifest.csv` to specify a custom location.

### GUI

In the GUI, check **"Rename Output Files"** in the De-identify tab, then choose a mode (Auto-sequential, From mapping file, or Custom pattern). A live preview shows how your files will be renamed before you click De-identify.

## Update Checker

PathSafe can check GitHub for new releases. This is **disabled by default** for network privacy (no outbound requests without your consent).

To enable: **Settings > Check for updates on startup**

To check manually: **Settings > Check for updates now**

When an update is available, a notification appears briefly in the top-right corner with a **Download** button that opens your browser to the release page.

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

If verification finds remaining PHI, run de-identify again on the flagged files. This can happen with unusual file structures. Report persistent issues to your IT team.

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
pathsafe deidentify --help
```
