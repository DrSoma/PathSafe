# PathSafe User Guide

Step-by-step instructions for hospital staff to anonymize pathology slide files.

## Overview

PathSafe removes patient-identifying information from whole-slide image (WSI) files before they are shared for research. It works with NDPI files (Hamamatsu scanners), SVS files (Aperio scanners), and other TIFF-based formats.

PathSafe can be used via the command line or the graphical interface (GUI).

## Installation

Ask your IT department to install PathSafe, or run:

```bash
pip install -e /path/to/pathsafe
```

Verify installation:

```bash
pathsafe --version
```

## Step 1: Check Your Files First (Scan)

Before anonymizing, scan your files to see what PHI is present.

```bash
pathsafe scan /path/to/your/slides/ --verbose
```

This is read-only — it does not modify any files. You'll see output like:

```
Scanning 500 file(s)...
  [1/500] slide001.ndpi — 1 finding(s)
    NDPI_BARCODE at offset 1234: AS-24-123456
  [2/500] slide002.ndpi — 1 finding(s)
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
PathSafe v1.0.0 — copy anonymization
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

## Step 3: Verify

After anonymization, verify that all PHI has been removed:

```bash
pathsafe verify /path/to/clean/slides/ --verbose
```

Expected output:

```
Verifying 500 file(s)...
  [1/500] slide001.ndpi — CLEAN
  [2/500] slide002.ndpi — CLEAN
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

If you prefer a graphical interface, launch:

```bash
pathsafe gui
```

The GUI provides:
- **File/Folder browser** — select input files and output directory
- **Mode selection** — copy (safe) or in-place
- **Scan** button — read-only PHI detection
- **Anonymize** button — one-click anonymize with progress bar
- **Verify** button — confirm all PHI has been removed
- **Log panel** — real-time output of what's happening
- **Workers** setting — speed up large batches with parallel processing

## Common Options

| Option | Description |
|--------|-------------|
| `--verbose` / `-v` | Show detailed output |
| `--format ndpi` | Only process NDPI files |
| `--format svs` | Only process SVS files |
| `--dry-run` | Preview without changes |
| `--workers N` | Use N parallel workers for faster batch processing |
| `--log FILE` | Save output to a log file |
| `--certificate FILE` | Generate compliance certificate |

## Troubleshooting

### "No WSI files found"

Make sure the directory contains `.ndpi`, `.svs`, `.tif`, or `.tiff` files. Use `--format` to filter if needed.

### "Error: Must specify --output for copy mode, or --in-place"

PathSafe requires explicit confirmation for in-place modification. Either:
- Add `--output /destination/` for copy mode, or
- Add `--in-place` to confirm modification of originals

### "Some files still contain PHI!"

If verification finds remaining PHI, run anonymize again on the flagged files. This can happen with unusual file structures. Report persistent issues to your IT team.

## Getting Help

```bash
pathsafe --help
pathsafe scan --help
pathsafe anonymize --help
```
