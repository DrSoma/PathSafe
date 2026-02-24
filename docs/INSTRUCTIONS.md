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

### The Four Steps

PathSafe walks you through four steps, shown at the top of the window:

```
  Select Files  -->  Scan  -->  Anonymize  -->  Verify
```

#### Step 1: Select Your Files

At the top of the window, you'll see two fields:

- **Input**: This is where your slide files are. Click **Browse** next to it and select a file or a folder. You can also drag and drop files directly onto the window.
- **Output**: This is where the cleaned copies will go. Click **Browse** and pick an empty folder.

**Tip**: If you have a folder full of slides, just select the whole folder. PathSafe will find all the slide files inside it automatically.

#### Step 2: Scan (Optional but Recommended)

Click the **Scan for PHI** button. PathSafe will read through your files and tell you what patient information it found, without changing anything.

The log panel at the bottom will show something like:

```
  [1/10] slide001.ndpi | 3 finding(s)
  [2/10] slide002.ndpi | 2 finding(s)
  [3/10] slide003.svs  | already clean
```

A popup will appear summarizing the results. This gives you a preview before you commit to anonymizing.

#### Step 3: Anonymize

Click the **Anonymize** button. PathSafe will:

1. Copy each file to your output folder
2. Remove all patient information from the copy
3. Re-scan the copy to make sure everything was removed (if "Verify after" is checked)

The log will show progress as each file is processed. When it's done, a popup will summarize the results and tell you where the compliance certificate was saved.

#### Step 4: Verify (Optional)

If you want an extra check, click **Verify**. This re-scans the anonymized files one more time to confirm that no patient information remains. You should see "CLEAN" next to every file.

### Options (What All the Buttons Mean)

#### Mode
- **Copy (safe)**: Creates anonymized copies in the output folder. Your originals are untouched. This is the default and recommended mode.
- **In-place**: Modifies the original files directly. Only use this if you have backups. PathSafe will ask you to confirm before proceeding.

#### Verify After
When checked (the default), PathSafe re-scans each file immediately after anonymizing it to confirm all patient data was removed. Leave this on unless you have a reason not to.

#### Workers
Controls how many files are processed at the same time. Higher numbers are faster but use more memory. The default of 4 is good for most computers.

#### Format
If you only want to process one type of file (for example, only NDPI files), select it here. "All formats" processes everything.

#### Dry Run
When checked, PathSafe scans your files and reports what it *would* do, but doesn't actually change anything. Useful for previewing before committing.

### Compliance Options

These are in the **Compliance** section below the main options:

#### Reset Timestamps
Resets the file's "last modified" and "last accessed" dates to January 1, 1970. This removes one more piece of information that could theoretically help someone figure out when the slide was scanned.

#### Attest: No Re-ID Mapping Retained
Adds a formal statement to the compliance certificate saying that you are not keeping any record that links the anonymized files back to the originals. Check this when you can truthfully make that statement.

#### Generate Assessment Checklist
Creates an additional JSON file listing all the technical and procedural steps of the anonymization. This is useful for institutional audits and regulatory reviews.

#### Verify Image Integrity
Proves that the diagnostic microscope images were not accidentally altered during anonymization. PathSafe takes a digital fingerprint (SHA-256 checksum) of all the image data before and after anonymization, then compares them. If they match, you have cryptographic proof that the tissue images are identical.

**Note**: This reads all the image data twice, so it adds extra time proportional to the file size. For a 5 GB file, expect an additional 10-50 seconds depending on your disk speed. Only available for TIFF-based formats (NDPI, SVS, BIF, SCN, generic TIFF).

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

Go to **View** in the menu bar and choose **Dark Theme** or **Light Theme**. The dark theme is easier on the eyes for extended use.

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

This reads your files and tells you what patient information is present. Nothing is modified. The `--verbose` flag shows details about each finding.

You can scan a single file too:
```bash
pathsafe scan /path/to/slides/slide001.ndpi --verbose
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

**With all compliance options**:
```bash
pathsafe anonymize /path/to/slides/ --output /path/to/clean/ \
    --certificate /path/to/clean/certificate.json \
    --checklist /path/to/clean/checklist.json \
    --reset-timestamps \
    --attest-no-mapping \
    --verify-integrity
```

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
| `--certificate FILE` / `-c` | Generate a JSON compliance certificate |
| `--checklist FILE` | Generate a JSON assessment checklist |
| `--reset-timestamps` | Reset file dates to January 1, 1970 |
| `--attest-no-mapping` | Include a no-re-identification attestation in the certificate |
| `--verify-integrity` | Verify image tile data integrity via SHA-256 checksums |
| `--log FILE` | Save all output to a log file |

#### `pathsafe scan`

| Option | What it does |
|--------|-------------|
| `--verbose` / `-v` | Show detailed findings |
| `--format FORMAT` | Only scan one format |
| `--json-out FILE` | Save results as JSON |
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

### What "Verified" Means

After anonymizing a file, PathSafe re-scans it with the exact same detection engine. If the re-scan finds zero findings, the file is "verified clean." This is your proof that the anonymization worked.

### What "Image Integrity Verified" Means

When you enable image integrity verification, PathSafe takes a SHA-256 fingerprint of all the diagnostic image data (the tissue tiles) before and after anonymization. If the fingerprints match, the diagnostic images are mathematically proven to be identical. Label and macro images are expected to change (they were intentionally blanked), so those are skipped in the comparison.

### The Compliance Certificate

The certificate is a JSON file that records everything PathSafe did. It includes:

- The PathSafe version used
- A unique ID for this anonymization run
- The exact date and time
- For each file: what was found, what was removed, the SHA-256 hash of the final file, and whether verification passed

Keep this file with your anonymized slides. It serves as your audit trail for regulatory reviews, research submissions, and institutional records.

### The Assessment Checklist

The checklist is a JSON file that lists all the technical measures PathSafe applied (metadata cleared, labels blanked, timestamps reset, integrity verified, etc.) along with procedural measures your institution needs to complete (destroy mapping files, store separately from originals, obtain REB approval, etc.).

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
- **Verify integrity**: This option reads all image data twice, which doubles the I/O time. Only enable it when you need the cryptographic proof.

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
| Anonymize and keep originals safe | `pathsafe anonymize /slides/ -o /clean/` |
| Anonymize with full compliance docs | `pathsafe anonymize /slides/ -o /clean/ -c cert.json --checklist check.json --verify-integrity --reset-timestamps` |
| Double-check the results | `pathsafe verify /clean/ -v` |
| Look at one file's metadata | `pathsafe info slide.ndpi` |
| Convert to TIFF | `pathsafe convert slide.ndpi -o slide.tiff` |
| Use the graphical interface | `pathsafe gui` |
