# PathSafe Developer Guide

## Architecture

PathSafe is organized into layers:

```
GUI (gui.py) ─── CLI (cli.py)
        \           /
         v         v
Orchestration (anonymizer.py, verify.py, report.py)
              |
              v
Format Handlers (formats/ndpi.py, formats/svs.py, formats/generic_tiff.py)
              |
              v
Core (tiff.py, scanner.py, models.py)
```

### Core Layer

- **`tiff.py`** — Low-level TIFF/BigTIFF binary parser using Python's `struct` module. Reads headers, IFD entries, tag values. Handles both byte orders and BigTIFF.
- **`scanner.py`** — PHI detection patterns (regex for accession numbers, dates). Provides `scan_bytes_for_phi()` and `scan_string_for_phi()`.
- **`models.py`** — Dataclasses (`PHIFinding`, `ScanResult`, `AnonymizationResult`, `BatchResult`).

### Format Handlers

Each handler implements the `FormatHandler` ABC from `formats/base.py`:

```python
class FormatHandler(ABC):
    def can_handle(self, filepath: Path) -> bool: ...
    def scan(self, filepath: Path) -> ScanResult: ...
    def anonymize(self, filepath: Path) -> List[PHIFinding]: ...
    def get_format_info(self, filepath: Path) -> dict: ...
```

Handlers are registered in `formats/__init__.py` in priority order. The first handler whose `can_handle()` returns True is used.

### Orchestration Layer

- **`anonymizer.py`** — `anonymize_file()` handles copy-then-anonymize and in-place modes. `anonymize_batch()` processes directories with progress callbacks. Supports parallel processing via `ThreadPoolExecutor` (`workers` parameter).
- **`verify.py`** — Re-scans files after anonymization.
- **`report.py`** — Generates JSON compliance certificates with SHA-256 hashes.

### Interface Layer

- **`cli.py`** — Click-based CLI with `scan`, `anonymize`, `verify`, `info`, and `gui` subcommands.
- **`gui.py`** — Tkinter GUI with file browser, progress bar, scan/anonymize/verify buttons, and log output. Runs operations in background threads to keep the UI responsive.

### Current Format Handlers

- **`formats/ndpi.py`** — Hamamatsu NDPI: tag 65468 (barcode), 65427 (reference), DateTime, regex safety scan.
- **`formats/svs.py`** — Aperio SVS: tag 270 (ImageDescription) pipe-delimited key=value parsing for ScanScope ID, Filename, Date, Time, User. DateTime tags. Regex safety scan.
- **`formats/generic_tiff.py`** — Fallback: scans all ASCII string tags for PHI patterns.

## Adding a New Format Handler

1. Create a new file in `pathsafe/formats/`, e.g., `mrxs.py`.

2. Implement the `FormatHandler` ABC:

```python
from pathsafe.formats.base import FormatHandler

class MRXSHandler(FormatHandler):
    format_name = "mrxs"

    def can_handle(self, filepath):
        return filepath.suffix.lower() == '.mrxs'

    def scan(self, filepath):
        # Scan for PHI, return ScanResult
        ...

    def anonymize(self, filepath):
        # Remove PHI, return list of PHIFinding
        ...

    def get_format_info(self, filepath):
        # Return metadata dict
        ...
```

3. Register it in `formats/__init__.py`:

```python
from pathsafe.formats.mrxs import MRXSHandler

_HANDLERS = [
    NDPIHandler(),
    SVSHandler(),
    MRXSHandler(),        # Add before GenericTIFF
    GenericTIFFHandler(),
]
```

4. The CLI and GUI will automatically pick up the new format — no changes needed.

## Adding New PHI Patterns

Add patterns to `scanner.py`:

```python
# In PHI_BYTE_PATTERNS (for binary scanning):
(re.compile(rb'NEW-\d{6,}'), 'NewFormat_Accession'),

# In PHI_STRING_PATTERNS (for string tag scanning):
(re.compile(r'NEW-\d{6,}'), 'NewFormat_Accession'),
```

## TIFF Parser Details

The TIFF parser in `tiff.py` handles:

- **Byte order**: Little-endian (`II`) and big-endian (`MM`)
- **Standard TIFF**: Magic number 42, 4-byte offsets, 12-byte IFD entries
- **BigTIFF**: Magic number 43, 8-byte offsets, 20-byte IFD entries
- **All TIFF data types**: BYTE, ASCII, SHORT, LONG, RATIONAL, etc.
- **Inline values**: Values <= 4 bytes (or 8 for BigTIFF) stored in the IFD entry itself
- **IFD chains**: Following next-IFD pointers with cycle detection

Key optimization for NDPI: All pages in an NDPI file share the same tag byte offsets, so only the first IFD needs to be parsed.

## Testing

```bash
cd pathsafe
pip install -e ".[dev]"
pytest
```

### Testing with real files

```bash
# Scan test files
pathsafe scan /path/to/test/slides/ --verbose

# Dry-run anonymization
pathsafe anonymize /path/to/test/slides/ --output /tmp/test_clean/ --dry-run

# Full test
pathsafe anonymize /path/to/test/slides/ --output /tmp/test_clean/ --certificate /tmp/test_cert.json --verbose
pathsafe verify /tmp/test_clean/ --verbose
```

## Building Standalone Executables

```bash
pip install pyinstaller
cd pathsafe
pyinstaller pathsafe.spec
```

This produces:
- `dist/pathsafe` — CLI executable
- `dist/pathsafe-gui` — GUI executable (no console window)

## Project Dependencies

- **Runtime**: Python 3.9+, `click`, `tkinter` (stdlib)
- **File parsing**: Python stdlib only (`struct`, `re`, `pathlib`, `hashlib`)
- **Dev**: `pytest`, `pytest-cov`
- **Build**: PyInstaller for standalone executables

## Code Conventions

- Type hints on all public functions
- Dataclasses for structured return values
- No external dependencies for file parsing (security and portability)
- Format handlers are self-contained — each knows how to detect, scan, and anonymize its format
- GUI operations run in background threads to keep the UI responsive
- Parallel batch processing uses `ThreadPoolExecutor` (thread-safe stat updates via locks)
