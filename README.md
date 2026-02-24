# PathSafe

Hospital-grade WSI anonymizer for pathology slide files.

PathSafe detects and removes Protected Health Information (PHI) from whole-slide image (WSI) files. It was built from production experience anonymizing 3,101+ NDPI files across 9 LungAI batches, after discovering that existing tools (wsianon) miss critical PHI fields and fail on certain scanner outputs.

## Why PathSafe?

| Problem with existing tools | PathSafe solution |
|---|---|
| wsianon fails on NDPI files without macro images (CaloPix) | Handles all NDPI variants |
| wsianon misses NDPI tag 65468 (NDPI_BARCODE) with accession numbers | Targets tag 65468 as primary PHI source |
| No copy mode — only in-place modification | Copy-then-anonymize by default |
| No verification | Re-scans after anonymization to confirm |
| No compliance reporting | JSON compliance certificates |
| CLI only | CLI + Tkinter GUI |

## Installation

```bash
pip install -e /path/to/pathsafe
```

Or install directly:

```bash
cd pathsafe
pip install -e .
```

## Quick Start

### Scan for PHI (read-only)

```bash
# Scan a directory
pathsafe scan /path/to/slides/

# Scan a single file with details
pathsafe scan /path/to/slide.ndpi --verbose
```

### Anonymize (copy mode — originals preserved)

```bash
pathsafe anonymize /path/to/slides/ --output /path/to/clean/
```

### Anonymize (in-place)

```bash
pathsafe anonymize /path/to/slides/ --in-place
```

### Verify anonymization

```bash
pathsafe verify /path/to/clean/
```

### File info

```bash
pathsafe info /path/to/slide.ndpi
```

## What Gets Anonymized

### NDPI (Hamamatsu)

| Tag | Name | Action |
|-----|------|--------|
| 65468 | NDPI_BARCODE | Overwrite with X's |
| 65427 | NDPI_REFERENCE | Overwrite with X's |
| 306 | DateTime | Zero out |
| 36867/36868 | DateTimeOriginal/Digitized | Zero out |
| — | Regex safety scan (first 100KB) | Overwrite matches |

### SVS (Aperio)

| Tag | Name | Action |
|-----|------|--------|
| 270 | ImageDescription | Parse key=value pairs, redact ScanScope ID, Filename, Date, Time, User |
| 306 | DateTime | Zero out |
| 36867/36868 | DateTimeOriginal/Digitized | Zero out |
| — | Regex safety scan (first 100KB) | Overwrite matches |

### Generic TIFF

All ASCII string tags in the first IFD are scanned for accession number patterns and redacted if found. Date tags are zeroed.

## CLI Options

```
pathsafe scan PATH [--verbose] [--format ndpi|svs|tiff] [--json-out FILE]
pathsafe anonymize PATH [--output DIR] [--in-place] [--dry-run] [--no-verify]
                        [--format ndpi|svs|tiff] [--certificate FILE]
                        [--verbose] [--workers N] [--log FILE]
pathsafe verify PATH [--verbose] [--format ndpi|svs|tiff]
pathsafe info FILE
pathsafe gui
```

## Compliance Certificate

After batch anonymization, generate a JSON certificate:

```bash
pathsafe anonymize /slides/ --output /clean/ --certificate /clean/certificate.json
```

The certificate includes file hashes, findings cleared, verification status, and timestamps for audit trails.

## GUI

Launch the graphical interface for non-technical users:

```bash
pathsafe gui
```

The GUI provides file/folder browsing, scan/anonymize/verify buttons, a progress bar, and a log output panel.

## Parallel Processing

Speed up large batches with multiple workers:

```bash
pathsafe anonymize /slides/ --output /clean/ --workers 4
```

## Supported Formats

- **NDPI** (Hamamatsu) — full support
- **SVS** (Aperio) — full support
- **Generic TIFF** — fallback scanning for any TIFF-based format

## Building a Standalone Executable

```bash
pip install pyinstaller
pyinstaller pathsafe.spec
```

This produces `dist/pathsafe` (CLI) and `dist/pathsafe-gui` (GUI).

## Dependencies

- Python 3.9+
- `click` (CLI framework)
- `tkinter` (GUI, included with Python)
- All file parsing uses Python stdlib only (`struct`, `re`, `pathlib`)

## License

MIT
