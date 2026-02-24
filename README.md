# PathSafe

**Remove patient information from pathology slide files safely, automatically, and verifiably.**

Whole-slide image (WSI) files from pathology scanners often contain hidden patient data: accession numbers, dates, operator names, and even photographed slide labels embedded in the file metadata. This data must be removed before slides can be shared for research or education.

PathSafe scans your slide files, finds all patient information, removes it, and then double-checks that nothing was missed. It works with all major scanner brands and can process thousands of files at once.

Built from real-world experience anonymizing 3,101+ clinical slides.

---

# At a Glance

| What PathSafe does | Why it matters |
|--------------------|----------------|
| **Finds hidden patient data** | Accession numbers, dates, and names can be buried in file metadata that's invisible when viewing the slide, but still accessible to anyone who opens the file with the right tools |
| **Supports all major formats** | Works with Hamamatsu (NDPI), Aperio (SVS), 3DHISTECH (MRXS), DICOM, and other TIFF-based files, so you don't need different tools for different scanners |
| **Blanks label and macro images** | Many scanners photograph the physical slide label, which may show patient names or IDs. PathSafe erases these embedded photos so the information can't be recovered |
| **Preserves your originals** | By default, PathSafe creates anonymized copies in a separate folder so your original files are never touched |
| **Verifies its own work** | After anonymizing, PathSafe re-scans every file to confirm all patient data was actually removed, giving you confidence that nothing was missed |
| **Generates compliance certificates** | Produces a detailed JSON report that records every file processed, what patient data was found, what was removed, and a cryptographic hash of the final file. This report can serve as documentation for regulatory reviews, research submissions, and institutional data governance |
| **Includes a graphical interface** | Non-technical users can drag and drop files into a visual interface and follow a guided four-step workflow without needing to type any commands |
| **Processes files in parallel** | Large batches of hundreds or thousands of slides can be processed much faster by using multiple workers simultaneously |

---

# PathSafe Installation

## Option A: Install PathSafe (recommended)

Download the installer for your operating system. It installs PathSafe like any other application on your computer, with shortcuts and an uninstaller.

| Your computer | Download |
|---------------|----------|
| **Windows** | [PathSafe-Setup.exe](https://github.com/DrSoma/PathSafe/releases/latest/download/PathSafe-Setup.exe) |
| **macOS** | [PathSafe.dmg](https://github.com/DrSoma/PathSafe/releases/latest/download/PathSafe-1.0.0.dmg) |
| **Linux** | [PathSafe.AppImage](https://github.com/DrSoma/PathSafe/releases/latest/download/PathSafe-1.0.0-x86_64.AppImage) |

**Windows**: Double-click `PathSafe-Setup.exe` and follow the installation wizard. It will install PathSafe to your Program Files folder, create a Start Menu shortcut, and optionally add a Desktop shortcut. Windows may show a "Windows protected your PC" warning the first time. Click "More info" then "Run anyway".

**macOS**: Double-click `PathSafe.dmg` to open it, then drag the PathSafe icon to the Applications folder. You can then launch PathSafe from Launchpad or the Applications folder.

**Linux**: Download the AppImage, then open a terminal and run:
```
chmod +x ~/Downloads/PathSafe-1.0.0-x86_64.AppImage
~/Downloads/PathSafe-1.0.0-x86_64.AppImage
```
You can move the AppImage anywhere you like. No installation needed.

## Option B: Run without installing (standalone)

If you prefer not to install anything, you can download a standalone executable and run it directly. No installer, no Python, no dependencies.

| Your computer | Graphical interface | Command line |
|---------------|---------------------|--------------|
| **Windows** | [pathsafe-gui-windows.exe](https://github.com/DrSoma/PathSafe/releases/latest/download/pathsafe-gui-windows.exe) | [pathsafe-windows.exe](https://github.com/DrSoma/PathSafe/releases/latest/download/pathsafe-windows.exe) |
| **macOS** | [pathsafe-gui-macos](https://github.com/DrSoma/PathSafe/releases/latest/download/pathsafe-gui-macos) | [pathsafe-macos](https://github.com/DrSoma/PathSafe/releases/latest/download/pathsafe-macos) |
| **Linux** | [pathsafe-gui-linux](https://github.com/DrSoma/PathSafe/releases/latest/download/pathsafe-gui-linux) | [pathsafe-linux](https://github.com/DrSoma/PathSafe/releases/latest/download/pathsafe-linux) |

Just download and double-click (Windows) or `chmod +x` and run (macOS/Linux).

## Option C: Install with Python

This option is for users who already have Python and want to integrate PathSafe into their existing environment. Requires **Python 3.9 or newer**.

```
pip install pathsafe[gui]
```

This installs PathSafe and its graphical interface. You can then run `pathsafe gui` to launch the GUI or `pathsafe` for the command line.

If you only need the command line (no graphical interface):
```
pip install pathsafe
```

### Optional extras

| Install command | What it adds |
|----------------|-------------|
| `pip install pathsafe[gui]` | Graphical interface (recommended) |
| `pip install pathsafe[dicom]` | Support for DICOM WSI files |
| `pip install pathsafe[openslide]` | Enhanced format detection via OpenSlide |
| `pip install pathsafe[convert]` | Format conversion (OpenSlide + tifffile) |
| `pip install pathsafe[all]` | All of the above |

---

# How to Use PathSafe

There are two ways to use PathSafe: the **graphical interface** (easier, recommended for most users) or the **command line** (more flexible, better for scripting).

For detailed, step-by-step instructions with screenshots of every option, see the **[full instructions guide](docs/INSTRUCTIONS.md)**.

## Option A: Graphical Interface (recommended)

Launch the GUI:

- **Standalone**: Double-click the `pathsafe-gui` file you downloaded
- **Python install**: Type `pathsafe gui` in a terminal

The interface walks you through four steps:

1. **Select Files**: Browse for files or folders, or drag and drop them onto the window
2. **Scan**: Click **Scan for PHI** -- PathSafe checks your files and reports what patient data it found (nothing is changed yet)
3. **Select Output**: Choose the output folder where anonymized copies will be saved
4. **Anonymize**: Click **Anonymize** -- PathSafe copies your files to the output folder, removes all patient data, and automatically verifies everything was removed (your originals are never touched)

A summary popup appears after each step telling you exactly what happened.

### GUI Features

| Feature | How to use it |
|---------|---------------|
| **Dark / Light theme** | View menu, or it remembers your last choice |
| **Drag and drop** | Drop files or folders directly onto the window |
| **Keyboard shortcuts** | Ctrl+S (scan), Ctrl+R (anonymize), Ctrl+E (verify), Ctrl+I (info), Ctrl+T (convert) |
| **Parallel processing** | Adjust the Workers slider (2-4 recommended) |
| **Dry run** | Check "Dry run" to preview without modifying anything |
| **Image integrity verification** | Automatically verifies diagnostic images were not altered using SHA-256 checksums before and after anonymization |
| **Timestamp reset** | Automatically resets file timestamps to epoch, removing temporal metadata that could aid re-identification |
| **Technical measures audit** | The compliance certificate includes a detailed list of all technical measures applied (metadata cleared, labels blanked, integrity verified, timestamps reset) |
| **Save log / Export JSON** | Save your results for record-keeping (Actions menu or buttons) |

## Option B: Command Line

Three commands is all you need:

```bash
# 1. Scan your files (nothing is changed)
pathsafe scan /path/to/slides/ --verbose

# 2. Anonymize (copies to a new folder, originals safe)
pathsafe anonymize /path/to/slides/ --output /path/to/clean/

# 3. Verify the results
pathsafe verify /path/to/clean/
```

### With full compliance documentation:

```bash
pathsafe anonymize /path/to/slides/ --output /path/to/clean/ \
    --certificate certificate.json
```

This generates a compliance certificate documenting all technical measures applied. Image integrity verification and timestamp reset are enabled by default.

### In-place mode (modifies originals -- make sure you have backups):

```bash
pathsafe anonymize /path/to/slides/ --in-place
```

### Format conversion (requires `pip install pathsafe[convert]`):

```bash
pathsafe convert slide.ndpi -o slide.tiff              # Convert to TIFF
pathsafe convert slide.ndpi -o slide.tiff --anonymize   # Convert + anonymize
pathsafe convert slide.ndpi -o label.png --extract label # Extract label image
```

---

# Supported Formats

## NDPI (Hamamatsu)

| What gets removed | Where it's hiding | Why it matters |
|-------------------|-------------------|----------------|
| Accession numbers | Tag 65468 (NDPI_BARCODE) - all IFDs | This is the primary patient identifier in Hamamatsu files |
| Reference strings | Tag 65427 (NDPI_REFERENCE) - all IFDs | May contain additional identifying information; present in every IFD |
| Scanner serial number | Tag 65442 (NDPI_SERIAL_NUMBER) - all IFDs | Device fingerprint that could link slides to a specific institution |
| Scanner properties | Tag 65449 (NDPI_SCANNER_PROPS) - all IFDs: dates, serial numbers | Created/Updated timestamps, macro/NDP serial numbers |
| Extra metadata | Tags 270, 305, 315, 316, 700, 33723, 37510, 42016 - all IFDs | Institutional info, operator names, XMP, EXIF, IPTC |
| Scan dates | DateTime tags (306, 36867, 36868) - all IFDs | Dates can be used to re-identify patients when combined with other records |
| Macro/label image | Embedded overview photo | A photograph of the entire slide, including the label with patient info |
| Companion files | .ndpa annotation files | XML annotation files that may reference patient identifiers |
| Filename patterns | Accession numbers in filenames | Filenames like `AS-24-123456.ndpi` contain case numbers |
| Remaining patterns | Binary scan of header (1MB) | A safety net that catches accession numbers, MRNs, SSNs, and dates embedded elsewhere |

## SVS (Aperio)

| What gets removed | Where it's hiding | Why it matters |
|-------------------|-------------------|----------------|
| Scanner ID, filename, operator name | ImageDescription metadata — scanned across **all** IFDs | Contains the operator who scanned the slide and the original filename |
| Scan dates | DateTime tags — scanned across **all** IFDs | Dates can be cross-referenced with clinical records |
| Extra metadata | Software, Artist, HostComputer, XMP, Copyright | Institutional info and device fingerprints |
| Label image | Embedded label photo | A photograph of the physical slide label, which often has the patient name or ID |
| Macro image | Embedded overview photo | A wide-angle photo that may capture the label |
| Filename patterns | Accession numbers in filenames | Filenames containing case identifiers |
| Remaining patterns | Binary scan of header (1MB) | A safety net that catches accession numbers, MRNs, SSNs, and dates embedded elsewhere |

## MRXS (3DHISTECH/MIRAX)

| What gets removed | Where it's hiding | Why it matters |
|-------------------|-------------------|----------------|
| Slide ID, name, barcode | Slidedat.ini [GENERAL] section | These fields directly identify the patient or case |
| Creation date/time | Slidedat.ini [GENERAL] section | Can be cross-referenced with clinical records |
| Additional metadata | All Slidedat.ini sections (patient ID, case number, operator, etc.) | PHI can appear in non-GENERAL sections too |
| Label image | Non-hierarchical layer in Data*.dat files | Photograph of slide barcode label containing patient info |
| Macro/preview image | Non-hierarchical layer in Data*.dat files | Overview photo that may show the label |
| Thumbnail image | Non-hierarchical layer in Data*.dat files | May contain readable text from the label |
| Filename patterns | Accession numbers in filenames | Filenames containing case identifiers |
| Remaining patterns | .mrxs file and Slidedat.ini | A safety net for accession numbers, MRNs, SSNs, and dates |

## BIF (Roche/Ventana)

| What gets removed | Where it's hiding | Why it matters |
|-------------------|-------------------|----------------|
| Barcodes | XMP tag: iScan BarCode1/BarCode2 attributes | Barcode values encode patient/case identifiers |
| Scan dates | XMP tag: iScan ScanDate/ScanTime + DateTime tags | Cross-referenceable with clinical records |
| Device/operator info | XMP tag: DeviceSerialNumber, OperatorID, UniqueID | Institutional fingerprints |
| Base filename | XMP tag: BaseFileName | May contain patient identifiers |
| Label/macro image | IFDs labeled "Label Image" or "Macro" | Photographed slide labels with patient info |
| Remaining patterns | Binary scan of header (1MB) | Safety net for stray identifiers (accession numbers, MRNs, SSNs, dates) |

## SCN (Leica)

| What gets removed | Where it's hiding | Why it matters |
|-------------------|-------------------|----------------|
| Barcode | ImageDescription XML: barcode element | Slide barcode containing case identifiers |
| Creation date | ImageDescription XML: creationDate element | Cross-referenceable timestamp |
| Device info | ImageDescription XML: device/model/version | Institutional fingerprints |
| Label/macro image | Separate TIFF IFDs | Photographed slide labels |
| Remaining patterns | Binary scan of header (1MB) | Safety net for stray identifiers (accession numbers, MRNs, SSNs, dates) |

## DICOM WSI

| What gets removed | Examples | Why it matters |
|-------------------|----------|----------------|
| Patient identifiers | Name, ID, birth date, sex, age | Direct patient identification |
| Study identifiers | Accession number, study date, description | Can be used to look up the patient in hospital systems |
| Specimen identifiers | Container ID, Specimen ID, Specimen UID | Pathology-specific identifiers linking to the case |
| Institution/physician info | Institution name, referring physician, operator | May indirectly identify the patient or the context of care |
| Device info | Serial number, software versions | Institutional fingerprints |
| Sequence-nested PHI | PHI tags inside DICOM sequences (recursive, reported in scan) | Patient data can be nested multiple levels deep |
| Private tags | Vendor-specific data | Unknown content that could contain identifiers |
| UIDs | Remapped to anonymized deterministic values | Original UIDs can be cross-referenced |

## Generic TIFF

For any TIFF-based slide file not covered above (including Philips TIFF, QPTIFF, Trestle, OME-TIFF), PathSafe scans all text metadata for accession number patterns, clears date fields, checks extra metadata tags (XMP, EXIF, IPTC, etc.), and reports filename PHI.

---

# Anonymization Depth

Bisson et al. (2023) defined five levels of whole-slide image anonymization in their peer-reviewed study ["Anonymization of whole slide images in histopathology for research and education"](https://doi.org/10.1177/20552076231171475):

| Level | Description | What it covers |
|-------|-------------|----------------|
| **I** | Filename de-identification | Remove patient identifiers from file and folder names |
| **II** | Dereference associated images | Unlink label and macro image pointers so they are not directly accessible |
| **III** | Delete associated images | Destroy the label and macro image pixel data entirely |
| **IV** | Remove all metadata | Remove all sensitive metadata including scanner serial numbers, acquisition dates, operator names, barcodes, and device identifiers |
| **V** | Spatial coherence removal | Alter the diagnostic image itself to prevent re-identification through tissue pattern matching (unsolved research problem) |

PathSafe implements **Level IV** anonymization. The table below shows how PathSafe compares to other open-source tools:

| Capability | PathSafe | [anonymize-slide](https://github.com/bgilbert/anonymize-slide) | [EMPAIA wsi-anon](https://gitlab.com/empaia/integration/wsi-anon) |
|------------|----------|-----------------|-----------------|
| Level I (filename detection) | Yes | No | No |
| Level II (dereference images) | Yes | No | Yes |
| Level III (blank label/macro) | Yes | Yes | Yes |
| Level IV (all metadata) | Yes | No | Partial |
| Format-specific deep parsing | Yes (structured tag fields) | No | String replacement only |
| Multi-IFD scanning | All IFDs with deduplication | Stops at first match | Unknown |
| Extra metadata tags (XMP, IPTC, EXIF, etc.) | Yes (9 tag types) | No | No |
| Regex safety scan (binary header) | Yes (first 1MB, 17+ pattern types) | No | No |
| Post-anonymization verification | Yes (re-scan + report) | No | No |
| Image integrity verification | Yes (SHA-256 per IFD) | No | No |
| Compliance certificate | Yes (JSON audit trail) | No | No |
| Formats supported | 7 (NDPI, SVS, MRXS, BIF, SCN, DICOM, generic TIFF) | 3 (SVS, NDPI, MRXS) | Multiple |
| GUI | Yes (PySide6) | No | No |

Level V (spatial coherence removal) is not implemented by any current tool. It remains an open research problem because the tissue features that enable re-identification are the same features that make slides diagnostically useful.

---

# Command Line Reference

```
pathsafe scan PATH       Check files for patient data (read-only)
pathsafe anonymize PATH  Remove patient data from files
pathsafe verify PATH     Confirm anonymization was successful
pathsafe convert PATH    Convert WSI files between formats
pathsafe info FILE       Show metadata for a single file
pathsafe gui             Launch the graphical interface
```

## Common options

| Option | What it does |
|--------|-------------|
| `--output DIR` | Save anonymized copies to this directory (originals untouched) |
| `--in-place` | Modify files directly instead of copying |
| `--dry-run` | Show what would be done without making any changes |
| `--verbose` | Show detailed output |
| `--workers N` | Process N files in parallel (faster for large batches) |
| `--certificate FILE` | Generate a JSON compliance certificate |
| `--format FORMAT` | Only process files of a specific format (ndpi, svs, mrxs, bif, scn, dicom, tiff) |
| `--no-verify-integrity` | Skip SHA-256 image integrity verification (enabled by default) |
| `--no-reset-timestamps` | Keep original file timestamps (reset to epoch by default) |
| `--log FILE` | Save all output to a log file |

---

# Compliance Certificate

When you use the `--certificate` option, PathSafe generates a JSON file that serves as an audit trail for your anonymization batch.

## What's in the certificate

- **PathSafe version**: The exact software version used, so results can be reproduced
- **Certificate ID**: A unique identifier (UUID) for this specific anonymization run
- **Timestamp**: The exact date and time the batch was processed (ISO 8601 UTC)
- **Mode**: Whether files were copied ("copy") or modified in place ("inplace")
- **Summary**: Total files processed, how many were anonymized, how many were already clean, how many had errors, and whether verification passed
- **Per-file details**: For every file in the batch, the certificate records the original filename, detected format, SHA-256 cryptographic hash of the anonymized file, number of PHI findings cleared, and whether post-anonymization verification passed

## Why this matters

The certificate provides a documented record of every de-identification step performed on each file. This documentation can be useful when:

- **Responding to regulatory or privacy reviews**: Demonstrating that a systematic, verified process was used to remove patient identifiers from shared files
- **Submitting data for research**: Providing reviewers with evidence of how de-identification was performed and verified
- **Maintaining institutional records**: Keeping a traceable audit trail of what was done to each file and when
- **Confirming file integrity**: The SHA-256 hash allows anyone to verify that a file has not been modified since anonymization

## Example

```bash
pathsafe anonymize /slides/ --output /clean/ --certificate /clean/certificate.json
```

---

# Security

PathSafe is designed with security in mind:

- **No network access**: PathSafe never connects to the internet. All processing happens locally on your machine.
- **No external dependencies for file parsing**: All TIFF/WSI file reading uses Python's built-in `struct` module. There are no third-party C libraries that could introduce vulnerabilities.
- **No code execution from files**: PathSafe never executes or evaluates any data found in slide files. It reads bytes and overwrites them.
- **Memory-safe**: Python's memory safety prevents buffer overflow attacks from maliciously crafted files.
- **Open source**: The entire codebase is available for review. No hidden functionality.

---

# Dependencies

PathSafe is designed to be lightweight. The only required dependency beyond Python itself is `click` (for the command-line interface). All file parsing uses Python's built-in standard library.

Optional dependencies add extra capabilities:

| Package | What it adds | How to install |
|---------|-------------|----------------|
| PySide6 | Graphical interface | `pip install pathsafe[gui]` |
| pydicom | DICOM WSI support | `pip install pathsafe[dicom]` |
| openslide-python | Enhanced format detection | `pip install pathsafe[openslide]` |
| tifffile + numpy | Format conversion (pyramidal TIFF output) | `pip install pathsafe[convert]` |

---

# Acknowledgments

Developed and tested at the McGill University Health Center Research Institute, Department of Pathology.

# License

Apache 2.0
