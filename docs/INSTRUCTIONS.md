# How to Use PathSafe

A friendly, step-by-step guide to anonymizing your pathology slide files.

---

## What Does PathSafe Do?

When a pathology scanner creates a digital slide file, it quietly embeds extra information inside: the patient's accession number, the date it was scanned, the operator's name, and sometimes even a photograph of the physical slide label (which may have the patient's name written on it).

All of this is invisible when you view the slide in a viewer, but anyone who opens the file with the right tools can read it.

**PathSafe finds all of this hidden information and removes it**, so the slide can be safely shared for research or education. The actual microscope image (the tissue you diagnose from) is never touched.

---

## Before You Start

You need two things:

1. **Your slide files** -- the `.ndpi`, `.svs`, `.mrxs`, `.bif`, `.scn`, `.dcm`, or `.tiff` files from your scanner
2. **An output folder** -- an empty folder where PathSafe will save the cleaned copies

PathSafe **never modifies your originals** by default. It always creates copies first.

---

## Using the Graphical Interface (Recommended)

The graphical interface is the easiest way to use PathSafe. No typing required.

### Launching the GUI

- **If you installed PathSafe**: find it in your Start Menu (Windows), Applications (macOS), or run the AppImage (Linux)
- **If you have the standalone file**: double-click `pathsafe-gui`
- **If you installed with Python**: open a terminal and type `pathsafe gui`
- **Right-click a slide file** (Linux): right-click any `.ndpi`, `.svs`, or `.tiff` file and choose "Open with PathSafe". The file path will already be filled in when PathSafe opens.

### The Four Steps

PathSafe walks you through four steps, shown at the top of the window:

```
  Select Files  -->  Scan  -->  Select Output  -->  Anonymize
```

Each step button shows its status: blank when not started, **[Done]** when completed, or **[Default]** when using the default setting (like the output folder).

#### Step 1: Select Your Files

Click **Step 1** and choose whether to select files or a folder. You can also drag and drop files directly onto the window.

**Selecting multiple files**: When browsing for files, you can hold **Ctrl** (or **Shift**) to select multiple files at once. The input box will show how many files you've selected (e.g., "3 files selected").

**Tip**: If you have a folder full of slides, just select the whole folder. PathSafe will find all the slide files inside it automatically. Any non-slide files in the folder are silently ignored.

#### Step 2: Scan (Optional but Recommended)

Click **Step 2 -- Scan for PHI**. PathSafe will read through your files and tell you what patient information it found, without changing anything.

The log panel at the bottom will show something like:

```
  [1/10] slide001.ndpi | 3 finding(s)
  [2/10] slide002.ndpi | 2 finding(s)
  [3/10] slide003.svs  | already clean
```

A popup will appear summarizing the results. PathSafe also saves a **PDF scan report** automatically to your output folder. The report includes:
- A table of all files with their status and SHA-256 hash
- Detailed findings for each file, using human-readable names (e.g., "Barcode" instead of "NDPI_BARCODE")
- A legend explaining what each finding type means

#### Step 3: Select Output

Click **Step 3** and choose where anonymized copies will be saved. By default, PathSafe suggests a folder inside your Documents directory. The step button shows **[Default]** if you haven't changed it, or **[Done]** if you've picked a custom folder.

#### Step 4: Anonymize

Click **Step 4 -- Anonymize**. PathSafe will:

1. Copy each file to your output folder
2. Remove all patient information from the copy
3. Verify image integrity via SHA-256 checksums
4. Re-scan the copy to confirm all PHI was removed
5. Reset file timestamps

The log will show progress as each file is processed. When it's done, a popup will summarize the results and a PDF compliance certificate is saved.

### Options (What All the Buttons Mean)

#### Mode
- **Copy (safe)**: Creates anonymized copies in the output folder. Your originals are untouched. This is the default and recommended mode.
- **In-place**: Modifies the original files directly. Only use this if you have backups. PathSafe will ask you to confirm before proceeding.

#### Workers (anonymize only)
Controls how many files are processed at the same time during anonymization. Higher numbers are faster but use more memory. The default of 4 is good for most computers. Note: scanning always processes one file at a time to ensure accurate reporting.

#### Institution for report (optional)
Type your institution's name here and it will appear in the header of PDF reports and certificates. This setting is remembered between sessions.

#### Format
If you only want to process one type of file (for example, only NDPI files), select it here. "All formats" processes everything.

#### Dry Run
When checked, PathSafe scans your files and reports what it *would* do, but doesn't actually change anything. Useful for previewing before committing.

### Automatic Safety Features

PathSafe applies these automatically during every anonymization:

#### Timestamp Reset
File "last modified" and "last accessed" dates are reset to January 1, 1970. This removes temporal metadata that could help someone figure out when the slide was scanned.

#### Image Integrity Verification
PathSafe takes a SHA-256 fingerprint of all diagnostic image data before and after anonymization and compares them. If they match, the tissue images are mathematically proven identical. Label and macro images are expected to change (intentionally blanked) and are excluded from this comparison. Only available for TIFF-based formats (NDPI, SVS, BIF, SCN, generic TIFF).

#### Multi-IFD Scanning
WSI files contain multiple image layers (IFDs). PathSafe scans **every** IFD in the file for PHI tags, not just the first one. Duplicate tag offsets shared across IFDs are automatically deduplicated to avoid redundant processing.

#### EXIF and GPS Sub-IFD Scanning
TIFF files can contain hidden sub-directories (EXIF and GPS sub-IFDs) with additional metadata like dates, GPS coordinates, and device identifiers. PathSafe follows these pointers and scans/blanks all PHI found inside them.

#### Regex Safety Scan
After structured tag processing, PathSafe runs a regex-based scan of the first 1 MB of each file to catch any accession numbers, medical record numbers (MRN), Social Security numbers (SSN), date of birth (DOB), or date patterns that may have been missed by the format-specific parser. This covers 18+ pattern types across common hospital naming conventions (AS-, AC-, SP-, AP-, CY-, H-, S-, CH, MRN, DOB, and more).

#### Post-Anonymization Verification
After anonymizing each file, PathSafe re-scans it with the same detection engine to confirm all PHI was removed.

#### Filename PHI Warning
If a file's name contains patient identifiers (e.g., `AS-24-123456.ndpi`), PathSafe warns you to rename it manually. The file contents are fully anonymized, but the filename itself cannot be changed automatically without breaking file associations.

#### Fail-Closed Error Handling
If PathSafe encounters an error while scanning a file, it reports the file as **not clean** rather than assuming it's safe. In copy mode, if anonymization fails, the unanonymized copy is automatically deleted to prevent PHI from being left in the output directory.

### Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| Ctrl+O | Open a file |
| Ctrl+Shift+O | Open a folder |
| Ctrl+S | Scan for PHI |
| Ctrl+R | Anonymize |
| Ctrl+E | Verify |
| Ctrl+I | File info |
| Ctrl+T | Convert |
| Ctrl+L | Save log |
| Ctrl+J | Export scan results as JSON |
| Escape | Stop the current operation |

### Switching Themes

Go to **View** in the menu bar and choose **Dark Theme** or **Light Theme**. Your choice is remembered between sessions. The dark theme is easier on the eyes for extended use.

### Saving Your Work

- **Save Log**: Click the **Save Log** button (or Ctrl+L from the Actions menu) to save the log panel contents as an HTML file. Useful for record-keeping.
- **Export JSON**: After a scan, click **Export JSON** (or Ctrl+J) to save the scan results as a JSON file for further analysis.

---

## Using the Command Line

The command line gives you more flexibility and is better for automation and scripting.

### Quick Start

```bash
# 1. Scan your files (nothing is changed)
pathsafe scan /path/to/slides/ --verbose

# 2. Anonymize (copies to a new folder)
pathsafe anonymize /path/to/slides/ --output /path/to/clean/

# 3. Verify (double-check the results)
pathsafe verify /path/to/clean/
```

That's it. Three commands and you're done.

### Scanning

```bash
pathsafe scan /path/to/slides/ --verbose
```

This reads your files and tells you what patient information is present. Nothing is modified. The `--verbose` flag shows details about each finding, using human-readable names.

You can scan a single file too:
```bash
pathsafe scan /path/to/slides/slide001.ndpi --verbose
```

To generate a PDF scan report:
```bash
pathsafe scan /path/to/slides/ --report scan_report.pdf --institution "My Hospital"
```

### Anonymizing

**Copy mode** (recommended -- your originals are safe):
```bash
pathsafe anonymize /path/to/slides/ --output /path/to/clean/
```

**In-place mode** (modifies originals -- make sure you have backups):
```bash
pathsafe anonymize /path/to/slides/ --in-place
```

**Dry run** (preview what would happen without changing anything):
```bash
pathsafe anonymize /path/to/slides/ --output /path/to/clean/ --dry-run
```

**With compliance certificate**:
```bash
pathsafe anonymize /path/to/slides/ --output /path/to/clean/ \
    --certificate /path/to/clean/certificate.json
```

Image integrity verification and timestamp reset are enabled by default. Use `--no-verify-integrity` or `--no-reset-timestamps` to disable them.

**Faster processing with parallel workers**:
```bash
pathsafe anonymize /path/to/slides/ --output /path/to/clean/ --workers 4
```

**Only process one format**:
```bash
pathsafe anonymize /path/to/slides/ --output /path/to/clean/ --format ndpi
```

### Verifying

```bash
pathsafe verify /path/to/clean/ --verbose
```

Every file should show "CLEAN". If any file still has patient information, PathSafe will tell you which ones.

### File Info

To see what's inside a single file:
```bash
pathsafe info /path/to/slides/slide001.ndpi
```

This shows the file format, size, metadata, and whether any patient information is present.

### Format Conversion

PathSafe can convert slides between formats (requires `pip install pathsafe[convert]`):

```bash
# Convert to pyramidal TIFF
pathsafe convert slide.ndpi -o slide.tiff

# Convert and anonymize in one step
pathsafe convert slide.ndpi -o slide.tiff --anonymize

# Extract the label image
pathsafe convert slide.ndpi -o label.png --extract label

# Batch convert a whole folder
pathsafe convert /path/to/slides/ -o /path/to/converted/ -t tiff --workers 4
```

### All Command-Line Options

#### `pathsafe anonymize`

| Option | What it does |
|--------|-------------|
| `--output DIR` / `-o` | Save anonymized copies to this directory |
| `--in-place` | Modify files directly instead of copying |
| `--dry-run` | Show what would be done without making changes |
| `--no-verify` | Skip the automatic post-anonymization check |
| `--verbose` / `-v` | Show detailed output |
| `--workers N` / `-w` | Process N files in parallel |
| `--format FORMAT` | Only process one format (ndpi, svs, mrxs, bif, scn, dicom, tiff) |
| `--certificate FILE` / `-c` | Generate a JSON + PDF compliance certificate |
| `--institution NAME` / `-i` | Institution name for the PDF certificate header |
| `--no-reset-timestamps` | Keep original file timestamps (reset to epoch by default) |
| `--no-verify-integrity` | Skip SHA-256 image integrity verification (enabled by default) |
| `--log FILE` | Save all output to a log file |

#### `pathsafe scan`

| Option | What it does |
|--------|-------------|
| `--verbose` / `-v` | Show detailed findings |
| `--format FORMAT` | Only scan one format |
| `--json-out FILE` | Save results as JSON |
| `--report FILE` / `-r` | Generate a PDF scan report |
| `--institution NAME` / `-i` | Institution name for the PDF report header |
| `--workers N` / `-w` | Scan N files in parallel |

#### `pathsafe verify`

| Option | What it does |
|--------|-------------|
| `--verbose` / `-v` | Show detailed findings |
| `--format FORMAT` | Only verify one format |

#### `pathsafe convert`

| Option | What it does |
|--------|-------------|
| `--output FILE` / `-o` | Output file or directory (required) |
| `--target-format` / `-t` | Target format: tiff, png, jpeg (default: tiff) |
| `--anonymize` / `-a` | Anonymize the converted file |
| `--tile-size` | Tile size in pixels (default: 256) |
| `--quality` | JPEG quality 1-100 (default: 90) |
| `--extract` | Extract an image: label, macro, thumbnail |
| `--workers N` / `-w` | Parallel workers for batch conversion |
| `--reset-timestamps` | Reset file dates on output |

---

## Understanding the Results

### What "Findings" Are

A "finding" is one piece of patient information that PathSafe detected. For example:

- An accession number in the barcode tag = 1 finding
- A date in the DateTime tag = 1 finding
- A label image that needs blanking = 1 finding

A file with 3 findings means PathSafe found 3 separate pieces of information to remove.

In reports, findings are shown with human-readable names. For example, "Barcode" instead of "NDPI_BARCODE", or "EXIF: DateTimeOriginal" instead of "EXIF:DateTimeOriginal".

### What "Verified" Means

After anonymizing a file, PathSafe re-scans it with the exact same detection engine. If the re-scan finds zero findings, the file is "verified clean." This is your proof that the anonymization worked.

### What "Image Integrity Verified" Means

PathSafe takes a SHA-256 fingerprint of all the diagnostic image data (the tissue tiles) before and after anonymization. If the fingerprints match, the diagnostic images are mathematically proven to be identical. Label and macro images are expected to change (they were intentionally blanked), so those are skipped in the comparison.

### The SHA-256 Hash

Every file gets a SHA-256 hash -- a unique 64-character code that acts as a digital fingerprint. If even one byte of the file changes, the hash changes completely. You can use the "before" hash (from the scan report) and "after" hash (from the certificate) to confirm:
- The file was not tampered with after anonymization
- The file you received is the same one that was processed

### The Compliance Certificate

The certificate is a JSON file (with a matching PDF) that records everything PathSafe did. It includes:

- The PathSafe version used
- A unique ID for this anonymization run
- The exact date and time
- For each file: what was found, what was removed, the SHA-256 hash of the final file, and whether verification passed
- A legend explaining each finding type

Keep this file with your anonymized slides. It serves as your audit trail for regulatory reviews, research submissions, and institutional records.

---

## Troubleshooting

### "No WSI files found"

Make sure your folder contains files with one of these extensions: `.ndpi`, `.svs`, `.tif`, `.tiff`, `.mrxs`, `.bif`, `.scn`, `.dcm`, `.dicom`. If your files use a different extension, try renaming one to see if PathSafe can read it.

### "Error: Must specify --output for copy mode, or --in-place"

PathSafe won't modify your files without explicit confirmation. Either provide an output directory (copy mode) or add `--in-place` to confirm you want to modify the originals.

### "Some files still contain PHI!"

This is rare but can happen with unusual file structures. Try running anonymize again on the specific files that failed. If the problem persists, please report it.

### The GUI won't launch (Linux)

If you see an error about `xcb` or Qt platform plugins, install the required system library:

```bash
sudo apt install -y libxcb-cursor0
```

### Processing is slow

- **Large files**: A 5 GB slide file takes a while to copy and process. This is normal.
- **HDD vs SSD**: Processing is much faster on solid-state drives. If your files are on a spinning hard drive, be patient.
- **Parallel workers**: Try increasing the workers count to process multiple files simultaneously. Start with 4 and go up from there if your computer can handle it.
- **Image integrity verification**: This reads all image data twice, which adds I/O time. Use `--no-verify-integrity` to skip it if speed is critical.

### Getting Help

```bash
pathsafe --help
pathsafe scan --help
pathsafe anonymize --help
pathsafe convert --help
```

Or open an issue at the project's GitHub repository.

---

## Quick Reference Card

| I want to... | Do this |
|---------------|---------|
| See what patient data is in my files | `pathsafe scan /slides/ -v` |
| Get a PDF scan report | `pathsafe scan /slides/ -r report.pdf` |
| Anonymize and keep originals safe | `pathsafe anonymize /slides/ -o /clean/` |
| Anonymize with compliance certificate | `pathsafe anonymize /slides/ -o /clean/ -c cert.json` |
| Double-check the results | `pathsafe verify /clean/ -v` |
| Look at one file's metadata | `pathsafe info slide.ndpi` |
| Convert to TIFF | `pathsafe convert slide.ndpi -o slide.tiff` |
| Use the graphical interface | `pathsafe gui` |
