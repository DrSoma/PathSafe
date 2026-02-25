# PathSafe

<p align="center">
  <img src="pathsafe/assets/icon.png" alt="PathSafe icon" width="180">
</p>

**Remove patient information from pathology slide files... safely, automatically, and verifiably.**

When pathology scanners create digital slide files, they often embed hidden patient data inside the file: accession numbers, scan dates, operator names, and even photographs of the slide label. This information is invisible when viewing the slide image, but anyone with the right tools can extract it. PathSafe finds and removes all of this hidden data so your slides are safe to share for research or education.

PathSafe works with all major scanner brands, can process thousands of files at once, and double-checks its own work to make sure nothing was missed.

---

## What PathSafe Does

| | |
|-|-|
| **Finds hidden patient data** | Accession numbers, dates, and names can be buried inside files in places you can't see when viewing the slide |
| **Works with all major scanners** | Hamamatsu (NDPI), Aperio (SVS), 3DHISTECH (MRXS), Roche/Ventana (BIF), Leica (SCN), DICOM, and other TIFF-based files |
| **Erases label photos** | Many scanners take a photo of the physical slide label (which may show patient names) and hide it inside the file. PathSafe erases these photos |
| **Keeps your originals safe** | PathSafe creates cleaned copies in a separate folder, so your original files are never touched |
| **Double-checks everything** | After cleaning, PathSafe re-scans every file to confirm all patient data was actually removed |
| **Creates compliance reports** | Generates PDF reports and certificates documenting exactly what was found, what was removed, and proof that each file is clean |
| **Easy to use** | A visual interface guides you through four simple steps with no typing commands required |
| **Handles large batches** | Process hundreds or thousands of slides at once, with parallel processing to speed things up |

---

## Installation

### Option 1: Installer (recommended)

Download the installer for your platform. It creates a desktop shortcut and adds PathSafe to your Start Menu (Windows) or Applications folder (macOS).

| Platform | Installer |
|----------|-----------|
| **Windows** | [PathSafe-Setup.exe](https://github.com/DrSoma/PathSafe/releases/latest/download/PathSafe-Setup.exe) |
| **macOS** | [pathsafe-gui-macos.dmg](https://github.com/DrSoma/PathSafe/releases/latest/download/pathsafe-gui-macos.dmg) |
| **Linux** | [pathsafe-gui-linux.AppImage](https://github.com/DrSoma/PathSafe/releases/latest/download/pathsafe-gui-linux.AppImage) |

**Windows note**: Windows may show a "Windows protected your PC" warning the first time. Click "More info" then "Run anyway".

**macOS note**: After downloading, drag into your applications folder and input the following into the terminal:

**sudo xattr -rd com.apple.quarantine "/Applications/PathSafe.app"**

**open "/Applications/PathSafe.app"**

**Linux note**: You may need to right-click > properties, and choose "Open/execute as program" the first time, or run `chmod +x` on the downloaded file.

### Option 2: Standalone executable (no installation needed)

A single portable file you can run from anywhere, including USB drives.

| Platform | Standalone |
|----------|------------|
| **Windows** | [pathsafe-gui-windows.exe](https://github.com/DrSoma/PathSafe/releases/latest/download/pathsafe-gui-windows.exe) |
| **macOS** | [pathsafe-gui-macos.dmg](https://github.com/DrSoma/PathSafe/releases/latest/download/pathsafe-gui-macos.dmg) |
| **Linux** | [pathsafe-gui-linux.AppImage](https://github.com/DrSoma/PathSafe/releases/latest/download/pathsafe-gui-linux.AppImage) |

### Alternative: Install with Python

For users who have Python installed (version 3.9 or newer):

```
pip install pathsafe[gui]
```

Then launch with `pathsafe gui` or use `pathsafe` for the command line.

---

## How to Use PathSafe (GUI)

**Most users should use the graphical interface.** For step-by-step instructions with screenshots, see the **[full instructions guide](docs/INSTRUCTIONS.md)**.

Launch PathSafe and follow four steps:

### Step 1: Select your files

Browse for files or a folder, or simply drag and drop them onto the window. You can select multiple files at once by holding Ctrl or Shift while clicking.

### Step 2: Scan

Click **Scan for PHI**. PathSafe checks your files and shows you what patient data it found. **Nothing is changed at this point.** This is just a preview. A PDF report is saved automatically.

### Step 3: Choose where to save

Pick the output folder where your cleaned copies will go. A default location is already filled in for you.

### Step 4: Anonymize

Click **Anonymize**. PathSafe copies your files to the output folder, removes all patient data from the copies, and automatically double-checks that everything was removed. **Your original files are never modified.**

A summary popup tells you exactly what happened after each step.

### Other things you can do in the GUI

| Feature | How |
|---------|-----|
| **Switch between dark and light theme** | Use the View menu (your choice is remembered) |
| **Drag and drop files** | Drop files or folders directly onto the window |
| **Select multiple files at once** | Hold Ctrl or Shift when browsing |
| **Use keyboard shortcuts** | Ctrl+O (open files), Ctrl+Shift+O (open folder), Ctrl+S (scan), Ctrl+R (anonymize), Ctrl+E (verify), Ctrl+I (file info), Ctrl+T (convert), Ctrl+L (save log), Esc (stop) |
| **Speed up large batches** | Increase the Workers slider (try 2-4) |
| **Preview without changing anything** | Check the "Dry run" box |
| **Add your institution name** | Fill in the Institution field (it appears on PDF reports and is remembered) |
| **Save your results** | Use Save Log or Export JSON in the Actions menu |
| **Convert file formats** | Use the Convert tab to change between NDPI, SVS, TIFF, PNG, and JPEG |
| **Right-click a slide file** | On Linux, right-click any slide file and choose "Open with PathSafe" |

---

## How to Use PathSafe (Command Line)

Install the command-line tool from PyPI:

```bash
pip install pathsafe
```

For users comfortable with a terminal. Three commands is all you need:

```bash
# 1. Scan your files (nothing is changed)
pathsafe scan /path/to/slides/ --verbose

# 2. Anonymize (copies to a new folder, originals safe)
pathsafe anonymize /path/to/slides/ --output /path/to/clean/

# 3. Verify the results
pathsafe verify /path/to/clean/
```

### Generate compliance documentation

```bash
pathsafe anonymize /path/to/slides/ --output /path/to/clean/ \
    --certificate certificate.json --institution "My Hospital"
```

### Generate a scan report

```bash
pathsafe scan /path/to/slides/ --report scan_report.pdf --institution "My Hospital"
```

### Export scan results as JSON (for integration with other tools)

```bash
pathsafe scan /path/to/slides/ --json-out results.json
```

### Anonymize files in place (modifies originals, so make sure you have backups!)

```bash
pathsafe anonymize /path/to/slides/ --in-place
```

### Convert between file formats

```bash
pathsafe convert slide.ndpi -o slide.tiff                          # Convert to pyramidal TIFF
pathsafe convert slide.ndpi -o slide.tiff --anonymize              # Convert and anonymize
pathsafe convert slide.ndpi -o slide.png -t png                    # Convert to PNG
pathsafe convert slide.ndpi -o slide.jpg -t jpeg --quality 85      # Convert to JPEG
pathsafe convert slide.ndpi -o label.png --extract label           # Extract label image
pathsafe convert /slides/ -o /converted/ -t tiff -w 4              # Batch convert with 4 workers
```

<details>
<summary>Full list of command line options (click to expand)</summary>

### All commands

```
pathsafe scan PATH       Check files for patient data (read-only)
pathsafe anonymize PATH  Remove patient data from files
pathsafe verify PATH     Confirm anonymization was successful
pathsafe convert PATH    Convert WSI files between formats
pathsafe info FILE       Show metadata for a single file
pathsafe gui             Launch the graphical interface
```

### Scan options

| Option | What it does |
|--------|-------------|
| `--verbose` / `-v` | Show detailed output with finding locations |
| `--format FORMAT` | Only scan files of a specific format (ndpi, svs, mrxs, bif, scn, dicom, tiff) |
| `--workers N` / `-w N` | Scan N files in parallel (faster for large batches) |
| `--report FILE` | Generate a PDF scan report |
| `--json-out FILE` | Export scan results as machine-readable JSON |
| `--institution NAME` | Institution name for PDF report headers |
| `--log FILE` | Save all output to a log file |

### Anonymize options

| Option | What it does |
|--------|-------------|
| `--output DIR` / `-o` | Save cleaned copies to this directory (originals untouched) |
| `--in-place` | Modify files directly instead of copying (requires explicit opt-in) |
| `--dry-run` | Show what would be done without making any changes |
| `--verbose` / `-v` | Show detailed output |
| `--workers N` / `-w N` | Process N files in parallel (faster for large batches) |
| `--certificate FILE` / `-c` | Generate a compliance certificate (JSON + PDF) |
| `--institution NAME` / `-i` | Institution name for PDF certificate headers |
| `--format FORMAT` | Only process files of a specific format |
| `--no-verify` | Skip the automatic re-scan after anonymization |
| `--no-verify-integrity` | Skip image integrity checking (enabled by default) |
| `--no-reset-timestamps` | Keep original file timestamps (reset by default) |
| `--log FILE` | Save all output to a log file |

### Verify options

| Option | What it does |
|--------|-------------|
| `--verbose` / `-v` | Show detailed output |
| `--format FORMAT` | Only verify files of a specific format |

### Convert options

| Option | What it does |
|--------|-------------|
| `--output FILE/DIR` / `-o` | Output file or directory (required) |
| `--target-format` / `-t` | Target format: `tiff` (default), `png`, or `jpeg` |
| `--tile-size N` | Tile size for pyramidal TIFF in pixels (default: 256) |
| `--quality N` | JPEG quality 1-100 (default: 90) |
| `--anonymize` / `-a` | Also anonymize the converted output |
| `--extract TYPE` | Extract a `label`, `macro`, or `thumbnail` image (single file only) |
| `--reset-timestamps` | Reset file timestamps on output files |
| `--workers N` / `-w N` | Number of parallel workers for batch conversion |
| `--format FORMAT` | Only convert files of a specific format (batch mode) |
| `--verbose` / `-v` | Show detailed output |

</details>

---

## Compliance Certificate

When you anonymize files (through the GUI or with `--certificate` on the command line), PathSafe generates a report documenting everything it did. This report serves as proof that your files were properly de-identified.

**What's in the certificate:**

- Which version of PathSafe was used
- When the batch was processed
- For each file: what patient data was found, what was removed, and whether the file passed verification
- A unique fingerprint (hash) of each cleaned file, so you can later prove the file hasn't been modified
- A glossary explaining each type of finding

**Why this matters:** This documentation can be used for regulatory reviews, research ethics submissions, or institutional audit trails. Keep the certificate with your anonymized files.

---

## What Patient Data Does PathSafe Remove?

PathSafe removes these types of hidden information from your slide files:

- **Accession numbers and case IDs**: The primary patient/case identifiers embedded in file metadata
- **Patient names, IDs, and demographics**: Found in DICOM files and some scanner formats
- **Scan dates and times**: Can be cross-referenced with hospital records to identify patients
- **Operator and physician names**: Who scanned or ordered the slide
- **Label and macro images**: Embedded photographs of the physical slide label, which may show patient names, barcodes, or handwritten notes
- **Scanner and institution information**: Serial numbers, software versions, and location data that could identify where a slide came from
- **Hidden metadata**: Technical data (EXIF, GPS coordinates, color profiles) that standard viewers don't show but can still be extracted
- **Filenames**: PathSafe detects patient data in filenames and warns you (filenames must be renamed manually)

PathSafe scans every layer of the file, not just the surface. It also does a final sweep of the raw file data to catch anything that might have been missed.

For a detailed technical breakdown of exactly which fields are cleaned in each format, see the [compliance documentation](docs/COMPLIANCE.md).

---

## Supported Scanner Formats

| Scanner brand | File type | Fully supported |
|---------------|-----------|:---------------:|
| **Hamamatsu** | .ndpi | Yes |
| **Aperio** | .svs | Yes |
| **3DHISTECH / MIRAX** | .mrxs | Yes |
| **Roche / Ventana** | .bif | Yes |
| **Leica** | .scn | Yes |
| **DICOM WSI** | .dcm, .dicom | Yes |
| **Other TIFF-based** (Philips, QPTIFF, Trestle, OME-TIFF, etc.) | .tif, .tiff | Yes (generic handler) |

---

## How PathSafe Compares

PathSafe implements **Level IV** anonymization as defined by [Bisson et al. (2023)](https://doi.org/10.1177/20552076231171475), which covers filename detection, label/macro image destruction, and complete metadata removal.

| Capability | PathSafe | anonymize-slide | EMPAIA wsi-anon |
|------------|:--------:|:---------------:|:---------------:|
| Detects patient data in filenames | Yes | No | No |
| Erases label/macro photos | Yes | Yes | Yes |
| Removes all metadata | Yes | No | Partial |
| Scans every layer of the file | Yes | No | Unknown |
| Scans hidden sub-directories (EXIF, GPS) | Yes | No | No |
| Re-checks files after cleaning | Yes | No | No |
| Verifies image integrity | Yes | No | No |
| Generates compliance reports (PDF + JSON) | Yes | No | No |
| Number of formats supported | 7 | 3 | Multiple |
| Graphical interface | Yes | No | No |

---

## Security

- **No internet connection**: PathSafe works entirely offline. No data ever leaves your computer.
- **No code execution from files**: PathSafe reads and overwrites bytes but never runs anything found inside slide files.
- **Open source**: The entire codebase is available for review.

---

## Dependencies

If you use the downloadable installers (`.exe`, `.dmg`, `.AppImage`), you do not need to install Python dependencies manually.

For PyPI installs, PathSafe is lightweight. The base install (CLI) only requires `click` (command-line framework) and `fpdf2` (PDF generation). All file reading uses Python's built-in standard library.

- CLI only: `pip install pathsafe`
- GUI: `pip install pathsafe[gui]`

Optional packages add extra features:

| Package | What it adds | Install with |
|---------|-------------|--------------|
| PySide6 | Graphical interface | `pip install pathsafe[gui]` |
| pydicom | DICOM WSI support | `pip install pathsafe[dicom]` |
| openslide-python | Enhanced format detection | `pip install pathsafe[openslide]` |
| tifffile + numpy | Format conversion | `pip install pathsafe[convert]` |

---

## Further Reading

- **[Instructions Guide](docs/INSTRUCTIONS.md)**: Step-by-step walkthrough of every feature
- **[User Guide](docs/USER_GUIDE.md)**: Detailed usage for CLI and GUI
- **[Compliance Documentation](docs/COMPLIANCE.md)**: Full technical breakdown of every field cleaned in every format
- **[Developer Guide](docs/DEVELOPER.md)**: Architecture, testing, and how to add new formats

---

## License

Apache 2.0



