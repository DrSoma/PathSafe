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
| `pip install pathsafe[all]` | All of the above |

---

# How to Use PathSafe

There are two ways to use PathSafe: the **graphical interface** (easier) or the **command line** (more flexible).

## Option A: Graphical Interface (recommended for most users)

Launch the GUI:

- **Standalone**: Double-click the `pathsafe-gui` file you downloaded
- **Python install**: Type `pathsafe gui` in a terminal

The interface walks you through four steps:

1. **Select Files**: Browse for files or folders, or drag and drop them onto the window
2. **Scan**: PathSafe checks your files and reports what patient data it found (nothing is changed yet)
3. **Anonymize**: PathSafe removes all patient data (your originals are preserved by default)
4. **Verify**: PathSafe re-scans the anonymized files to confirm everything was removed

The GUI includes a dark and light theme (switchable from the View menu), tooltips on every button, and keyboard shortcuts for common actions.

## Option B: Command Line

### Step 1: Scan your files (nothing is modified)

```
pathsafe scan /path/to/slides/ --verbose
```

This shows you what patient data is present without changing anything. Think of it as a preview.

### Step 2: Anonymize (originals are preserved)

```
pathsafe anonymize /path/to/slides/ --output /path/to/clean/
```

This creates anonymized copies in the output folder. Your original files are untouched.

If you want to modify files directly instead of copying (e.g., you already have backups):

```
pathsafe anonymize /path/to/slides/ --in-place
```

### Step 3: Verify the results

```
pathsafe verify /path/to/clean/
```

This re-scans every anonymized file and confirms that no patient data remains.

### Step 4 (optional): Generate a compliance certificate

```
pathsafe anonymize /path/to/slides/ --output /path/to/clean/ --certificate /path/to/clean/certificate.json
```

The certificate is a JSON file that records exactly what was done to each file, useful for audits and regulatory compliance.

---

# Supported Formats

## NDPI (Hamamatsu)

| What gets removed | Where it's hiding | Why it matters |
|-------------------|-------------------|----------------|
| Accession numbers | Tag 65468 (NDPI_BARCODE) | This is the primary patient identifier in Hamamatsu files |
| Reference strings | Tag 65427 (NDPI_REFERENCE) | May contain additional identifying information |
| Scan dates | DateTime tags | Dates can be used to re-identify patients when combined with other records |
| Macro image | Embedded overview photo | A photograph of the entire slide, including the label with patient info |
| Barcode image | Embedded barcode photo | A photograph of the slide barcode, which encodes the accession number |
| Remaining patterns | Binary scan of header | A safety net that catches any accession numbers embedded elsewhere in the file |

## SVS (Aperio)

| What gets removed | Where it's hiding | Why it matters |
|-------------------|-------------------|----------------|
| Scanner ID, filename, operator name | ImageDescription metadata | Contains the operator who scanned the slide and the original filename |
| Scan dates | DateTime tags | Dates can be cross-referenced with clinical records |
| Label image | Embedded label photo | A photograph of the physical slide label, which often has the patient name or ID |
| Macro image | Embedded overview photo | A wide-angle photo that may capture the label |
| Remaining patterns | Binary scan of header | A safety net for any accession numbers embedded elsewhere |

## MRXS (3DHISTECH/MIRAX)

| What gets removed | Where it's hiding | Why it matters |
|-------------------|-------------------|----------------|
| Slide ID, name, barcode | Slidedat.ini configuration file | These fields directly identify the patient or case |
| Creation date/time | Slidedat.ini configuration file | Can be cross-referenced with clinical records |
| Remaining patterns | .mrxs file and Slidedat.ini | A safety net for any other identifiers |

## DICOM WSI

| What gets removed | Examples | Why it matters |
|-------------------|----------|----------------|
| Patient identifiers | Name, ID, birth date, sex, age | Direct patient identification |
| Study identifiers | Accession number, study date, description | Can be used to look up the patient in hospital systems |
| Institution/physician info | Institution name, referring physician, operator | May indirectly identify the patient or the context of care |
| Private tags | Vendor-specific data | Unknown content that could contain identifiers |

## Generic TIFF

For any TIFF-based slide file not covered above, PathSafe scans all text metadata for accession number patterns and clears date fields.

---

# Command Line Reference

```
pathsafe scan PATH       Check files for patient data (read-only)
pathsafe anonymize PATH  Remove patient data from files
pathsafe verify PATH     Confirm anonymization was successful
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
| `--format FORMAT` | Only process files of a specific format (ndpi, svs, mrxs, dicom, tiff) |
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

---

# Acknowledgments

Developed and tested at the McGill University Health Center Research Institute, Department of Pathology.

# License

Apache 2.0
