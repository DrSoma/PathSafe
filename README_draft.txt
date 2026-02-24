# PathSafe

**Remove patient information from pathology slide files safely, automatically, and verifiably.**

Whole-slide image (WSI) files from pathology scanners often contain hidden patient data: accession numbers, dates, operator names, and even photographed slide labels embedded in the file metadata. This data must be removed before slides can be shared for research or education.

PathSafe scans your slide files, finds all patient information, removes it, and then double-checks that nothing was missed. It works with all major scanner brands and can process thousands of files at once.

Built from real-world experience anonymizing 3,101+ clinical slides.

---

## At a Glance

| What PathSafe does | Why it matters |
|--------------------|----------------|
| Finds hidden patient data in slide files | Accession numbers, dates, and names can be buried in metadata that's invisible when viewing the slide but still present in the file |
| Removes patient data from all major formats | Works with Hamamatsu (NDPI), Aperio (SVS), 3DHISTECH (MRXS), DICOM, and other TIFF-based files |
| Blanks label and macro images | Scanners often photograph the physical slide label, which may show patient names or IDs. PathSafe erases these embedded photos |
| Preserves your originals | By default, PathSafe creates anonymized copies so your original files are never touched |
| Verifies its own work | After anonymizing, PathSafe re-scans every file to confirm all patient data was actually removed |
| Generates compliance certificates | Produces a detailed JSON report listing every file processed, what was found, and what was removed, ready for audits |
| Includes a graphical interface | Non-technical users can drag and drop files into a visual interface without needing the command line |
| Processes files in parallel | Large batches of hundreds or thousands of slides can be processed faster using multiple workers |

---

## Getting PathSafe

There are two ways to get PathSafe: **download a standalone app** (no installation needed) or **install with Python** (more flexible).

### Option A: Download the standalone app (easiest)

No Python required. Just download and run.

1. Go to the [Releases page](https://github.com/DrSoma/PathSafe/releases)
2. Download the file for your operating system:

| Your computer | Download the CLI (command line) | Download the GUI (graphical interface) |
|---------------|--------------------------------|----------------------------------------|
| **Windows** | `pathsafe-windows.exe` | `pathsafe-gui-windows.exe` |
| **macOS** | `pathsafe-macos` | `pathsafe-gui-macos` |
| **Linux** | `pathsafe-linux` | `pathsafe-gui-linux` |

3. Run it:
   - **Windows**: Double-click `pathsafe-gui-windows.exe` to launch the graphical interface
   - **macOS**: Open Terminal, navigate to your Downloads folder, and run `chmod +x pathsafe-gui-macos && ./pathsafe-gui-macos`
   - **Linux**: Open a terminal, navigate to your Downloads folder, and run `chmod +x pathsafe-gui-linux && ./pathsafe-gui-linux`

No installation, no Python, no dependencies needed.

### Option B: Install with Python (for developers and advanced users)

This option gives you more control and makes it easy to update. Requires **Python 3.9 or newer**.

If you're not sure whether Python is installed, open a terminal (or Command Prompt on Windows) and type:

```
python --version
```

If you see `Python 3.9` or higher, you're good to go. If not, download Python from [python.org](https://www.python.org/downloads/) and install it first.

#### Windows

1. Open **Command Prompt** (search for "cmd" in the Start menu).

2. Navigate to wherever you downloaded or cloned PathSafe:
   ```
   cd C:\Users\YourName\Downloads\PathSafe
   ```

3. Install PathSafe:
   ```
   pip install -e .
   ```

4. To also install the graphical interface:
   ```
   pip install -e ".[gui]"
   ```

5. Verify it worked:
   ```
   pathsafe --version
   ```

#### macOS

1. Open **Terminal** (search for "Terminal" in Spotlight, or find it in Applications > Utilities).

2. Navigate to wherever you downloaded or cloned PathSafe:
   ```
   cd ~/Downloads/PathSafe
   ```

3. Install PathSafe:
   ```
   pip install -e .
   ```

4. To also install the graphical interface:
   ```
   pip install -e ".[gui]"
   ```

5. Verify it worked:
   ```
   pathsafe --version
   ```

#### Linux

1. Open a **terminal**.

2. Navigate to wherever you downloaded or cloned PathSafe:
   ```
   cd ~/Downloads/PathSafe
   ```

3. Install PathSafe:
   ```
   pip install -e .
   ```

4. To also install the graphical interface:
   ```
   pip install -e ".[gui]"
   ```

   If the GUI fails to launch later, you may need to install a system library:
   ```
   sudo apt install -y libxcb-cursor0
   ```

5. Verify it worked:
   ```
   pathsafe --version
   ```

#### Optional extras

| Install command | What it adds |
|----------------|-------------|
| `pip install -e ".[gui]"` | Graphical interface (recommended for non-technical users) |
| `pip install -e ".[dicom]"` | Support for DICOM WSI files |
| `pip install -e ".[openslide]"` | Enhanced format detection via OpenSlide |
| `pip install -e ".[all]"` | All of the above |

---

## How to Use PathSafe

There are two ways to use PathSafe: the **graphical interface** (easier) or the **command line** (more flexible).

### Option A: Graphical Interface (recommended for most users)

Launch the GUI:

- **Standalone**: Double-click the `pathsafe-gui` file you downloaded
- **Python install**: Type `pathsafe gui` in a terminal

The interface walks you through four steps:

1. **Select Files**: Browse for files or folders, or drag and drop them onto the window
2. **Scan**: PathSafe checks your files and reports what patient data it found (nothing is changed yet)
3. **Anonymize**: PathSafe removes all patient data (your originals are preserved by default)
4. **Verify**: PathSafe re-scans the anonymized files to confirm everything was removed

The GUI includes a dark theme that's comfortable for extended use, tooltips on every button, and keyboard shortcuts for common actions.

### Option B: Command Line

#### Step 1: Scan your files (nothing is modified)

```
pathsafe scan /path/to/slides/ --verbose
```

This shows you what patient data is present without changing anything. Think of it as a preview.

#### Step 2: Anonymize (originals are preserved)

```
pathsafe anonymize /path/to/slides/ --output /path/to/clean/
```

This creates anonymized copies in the output folder. Your original files are untouched.

If you want to modify files directly instead of copying (e.g., you already have backups):

```
pathsafe anonymize /path/to/slides/ --in-place
```

#### Step 3: Verify the results

```
pathsafe verify /path/to/clean/
```

This re-scans every anonymized file and confirms that no patient data remains.

#### Step 4 (optional): Generate a compliance certificate

```
pathsafe anonymize /path/to/slides/ --output /path/to/clean/ --certificate /path/to/clean/certificate.json
```

The certificate is a JSON file that records exactly what was done to each file, useful for audits and regulatory compliance.

---

## Supported Formats

### NDPI (Hamamatsu)

| What gets removed | Where it's hiding | Why it matters |
|-------------------|-------------------|----------------|
| Accession numbers | Tag 65468 (NDPI_BARCODE) | This is the primary patient identifier in Hamamatsu files |
| Reference strings | Tag 65427 (NDPI_REFERENCE) | May contain additional identifying information |
| Scan dates | DateTime tags | Dates can be used to re-identify patients when combined with other records |
| Macro image | Embedded overview photo | A photograph of the entire slide, including the label with patient info |
| Barcode image | Embedded barcode photo | A photograph of the slide barcode, which encodes the accession number |
| Remaining patterns | Binary scan of header | A safety net that catches any accession numbers embedded elsewhere in the file |

### SVS (Aperio)

| What gets removed | Where it's hiding | Why it matters |
|-------------------|-------------------|----------------|
| Scanner ID, filename, operator name | ImageDescription metadata | Contains the operator who scanned the slide and the original filename |
| Scan dates | DateTime tags | Dates can be cross-referenced with clinical records |
| Label image | Embedded label photo | A photograph of the physical slide label, which often has the patient name or ID |
| Macro image | Embedded overview photo | A wide-angle photo that may capture the label |
| Remaining patterns | Binary scan of header | A safety net for any accession numbers embedded elsewhere |

### MRXS (3DHISTECH/MIRAX)

| What gets removed | Where it's hiding | Why it matters |
|-------------------|-------------------|----------------|
| Slide ID, name, barcode | Slidedat.ini configuration file | These fields directly identify the patient or case |
| Creation date/time | Slidedat.ini configuration file | Can be cross-referenced with clinical records |
| Remaining patterns | .mrxs file and Slidedat.ini | A safety net for any other identifiers |

### DICOM WSI

| What gets removed | Examples | Why it matters |
|-------------------|----------|----------------|
| Patient identifiers | Name, ID, birth date, sex, age | Direct patient identification |
| Study identifiers | Accession number, study date, description | Can be used to look up the patient in hospital systems |
| Institution/physician info | Institution name, referring physician, operator | May indirectly identify the patient or the context of care |
| Private tags | Vendor-specific data | Unknown content that could contain identifiers |

### Generic TIFF

For any TIFF-based slide file not covered above, PathSafe scans all text metadata for accession number patterns and clears date fields.

---

## Command Line Reference

```
pathsafe scan PATH       Check files for patient data (read-only)
pathsafe anonymize PATH  Remove patient data from files
pathsafe verify PATH     Confirm anonymization was successful
pathsafe info FILE       Show metadata for a single file
pathsafe gui             Launch the graphical interface
```

### Common options

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

## Compliance Certificate

When you use the `--certificate` option, PathSafe generates a JSON file that serves as an audit trail. It records:

- The PathSafe version used
- A unique identifier for this anonymization run
- The date and time
- For each file: the original path, what was found and removed, a cryptographic hash of the anonymized file, and whether verification passed

This is useful for demonstrating compliance with HIPAA, GDPR, IRB requirements, or institutional data governance policies.

---

## Dependencies

PathSafe is designed to be lightweight. The only required dependency beyond Python itself is `click` (for the command-line interface). All file parsing uses Python's built-in standard library.

Optional dependencies add extra capabilities:

| Package | What it adds | How to install |
|---------|-------------|----------------|
| PySide6 | Graphical interface | `pip install pathsafe[gui]` |
| pydicom | DICOM WSI support | `pip install pathsafe[dicom]` |
| openslide-python | Enhanced format detection | `pip install pathsafe[openslide]` |

---

## License

MIT
