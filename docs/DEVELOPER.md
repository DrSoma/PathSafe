# PathSafe Developer Guide

## Architecture

PathSafe is organized into layers:

```
GUI (gui_qt.py / gui.py) ─── CLI (cli.py)
        \                       /
         v                     v
Orchestration (anonymizer.py, verify.py, report.py)
              |
              v
Format Handlers (formats/ndpi.py, svs.py, mrxs.py, dicom.py, generic_tiff.py)
              |
              v
Core (tiff.py, scanner.py, models.py)
              |
              v
Optional (openslide_utils.py)
```

### Core Layer

- **`tiff.py`** — Low-level TIFF/BigTIFF binary parser using Python's `struct` module. Reads headers, IFD entries, tag values. Handles both byte orders and BigTIFF. Also provides label/macro image blanking utilities (`blank_ifd_image_data`, `get_ifd_image_size`, `get_ifd_image_data_size`).
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

### Current Format Handlers

- **`formats/ndpi.py`** — Hamamatsu NDPI: tag 65468 (barcode), 65427 (reference), DateTime, macro/barcode image blanking (via NDPI_SOURCELENS tag), regex safety scan.
- **`formats/svs.py`** — Aperio SVS: tag 270 (ImageDescription) pipe-delimited key=value parsing for ScanScope ID, Filename, Date, Time, User. DateTime tags. Label/macro image blanking. Regex safety scan.
- **`formats/mrxs.py`** — 3DHISTECH/MIRAX MRXS: Slidedat.ini parsing (configparser), SLIDE_ID, SLIDE_NAME, SLIDE_BARCODE, SLIDE_CREATIONDATETIME in [GENERAL] section. Regex safety scan of both .mrxs file and Slidedat.ini.
- **`formats/dicom.py`** — DICOM WSI: uses `pydicom` (optional dependency). Blanks Type 2 tags (PatientName, PatientID, etc.), deletes Type 3 tags (PatientAddress, OtherPatientIDs, etc.), removes all private tags. Only loaded if pydicom is installed.
- **`formats/generic_tiff.py`** — Fallback: scans all ASCII string tags for PHI patterns.

### Orchestration Layer

- **`anonymizer.py`** — `anonymize_file()` handles copy-then-anonymize and in-place modes. `anonymize_batch()` processes directories with progress callbacks. Supports parallel processing via `ThreadPoolExecutor` (`workers` parameter).
- **`verify.py`** — Re-scans files after anonymization.
- **`report.py`** — Generates JSON compliance certificates with SHA-256 hashes.

### Interface Layer

- **`cli.py`** — Click-based CLI with `scan`, `anonymize`, `verify`, `info`, and `gui` subcommands.
- **`gui_qt.py`** — PySide6 Qt GUI with Catppuccin dark theme, drag-and-drop, workflow step indicator, menu bar with keyboard shortcuts, tooltips, status bar. Runs operations in background threads via `QThread` workers.
- **`gui.py`** — Tkinter GUI fallback. Same core functionality with simpler styling.

### Optional Utilities

- **`openslide_utils.py`** — Optional integration with `openslide-python` for enhanced format detection and slide property reading. All functions gracefully return empty/None if OpenSlide is not installed.

## Label/Macro Image Handling

NDPI and SVS files can contain embedded label and macro images that photograph the physical slide label, potentially showing patient information.

### How It Works

The `tiff.py` module provides utilities for blanking image data:

- **`blank_ifd_image_data()`** — Overwrites all strip/tile data in an IFD with a minimal valid JPEG (`\xFF\xD8\xFF\xD9`) followed by zero bytes, preserving TIFF structure.
- **`get_ifd_image_size()`** — Reads image width/height from IFD tags.
- **`get_ifd_image_data_size()`** — Calculates total strip/tile data size.

### NDPI Label/Macro Detection

NDPI uses the proprietary `NDPI_SOURCELENS` tag (65421) to mark special pages:
- `SOURCELENS = -1.0` — Macro image (overview of the full slide)
- `SOURCELENS = -2.0` — Barcode/label image

### SVS Label/Macro Detection

SVS marks special pages by including `label` or `macro` in the `ImageDescription` tag (270).

## Adding a New Format Handler

1. Create a new file in `pathsafe/formats/`, e.g., `isyntax.py`.

2. Implement the `FormatHandler` ABC:

```python
from pathsafe.formats.base import FormatHandler
from pathsafe.models import PHIFinding, ScanResult

class ISyntaxHandler(FormatHandler):
    format_name = "isyntax"

    def can_handle(self, filepath):
        return filepath.suffix.lower() == '.isyntax'

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
from pathsafe.formats.isyntax import ISyntaxHandler

_HANDLERS = [
    NDPIHandler(),
    SVSHandler(),
    MRXSHandler(),
    ISyntaxHandler(),      # Add before GenericTIFF
    GenericTIFFHandler(),
]
```

4. Add the format to `WSI_EXTENSIONS` in `anonymizer.py` and `--format` choices in `cli.py`.

5. The GUI will automatically pick up the new format — no changes needed there.

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
- **All TIFF data types**: BYTE, ASCII, SHORT, LONG, RATIONAL, SBYTE, UNDEFINED, SSHORT, SLONG, SRATIONAL, FLOAT, DOUBLE, LONG8
- **Inline values**: Values <= 4 bytes (or 8 for BigTIFF) stored in the IFD entry itself
- **IFD chains**: Following next-IFD pointers with cycle detection
- **Strip/tile data**: Reading StripOffsets, StripByteCounts, TileOffsets, TileByteCounts for image data manipulation

Key optimization for NDPI: All pages in an NDPI file share the same tag byte offsets, so only the first IFD needs to be parsed.

## Testing

```bash
cd pathsafe
pip install -e ".[dev]"
pytest
```

Test fixtures in `tests/conftest.py` create synthetic NDPI and SVS files with embedded PHI for testing without real patient data.

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

- **Core runtime**: Python 3.9+, `click` (CLI framework)
- **File parsing**: Python stdlib only (`struct`, `re`, `pathlib`, `hashlib`)
- **GUI (optional)**: `PySide6>=6.5` — install with `pip install pathsafe[gui]`
- **DICOM (optional)**: `pydicom>=2.3` — install with `pip install pathsafe[dicom]`
- **OpenSlide (optional)**: `openslide-python>=1.2` — install with `pip install pathsafe[openslide]`
- **Dev**: `pytest>=7.0`, `pytest-cov`
- **Build**: PyInstaller for standalone executables

## Code Conventions

- Type hints on all public functions
- Dataclasses for structured return values
- No external dependencies for file parsing (security and portability)
- Format handlers are self-contained — each knows how to detect, scan, and anonymize its format
- Optional dependencies use `try: import ... except ImportError` pattern with graceful fallbacks
- GUI operations run in background threads (`QThread` for Qt, `threading.Thread` for Tkinter)
- Parallel batch processing uses `ThreadPoolExecutor` (thread-safe stat updates via locks)
