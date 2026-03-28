# PathSafe Pipeline Extension -- Architecture Proposal

## 1. Problem Statement

PathSafe currently handles **anonymization** of whole-slide images: scan for PHI,
strip it, rename files, verify, generate certificates. But a real institutional
workflow has steps both before and after anonymization:

1. **Before**: Classify each slide (what stain? what case?) to decide *which*
   slides to process and *how* to organize them.
2. **During**: Anonymize, rename, and group into per-patient folders.
3. **After**: Transfer the cleaned output to a remote server (PACS, research
   storage, collaborator workstation).

These three phases form a **pipeline** that needs to be runnable as a single
command while keeping each phase independently useful.

---

## 2. Design Principles

| Principle | Rationale |
|---|---|
| **Each phase is a standalone command** | Users must be able to run `classify`, `anonymize`, or `transfer` independently. The pipeline composes them; it does not replace them. |
| **Pipeline state flows via a manifest file** | Phases communicate through a well-defined JSON manifest on disk, not in-memory coupling. This makes the pipeline restartable after failure. |
| **Optional dependencies stay optional** | OCR requires Tesseract + Pillow. Transfer requires paramiko. These must not be imported at startup or affect existing commands. |
| **GUI gets a "Pipeline" tab, not a redesign** | The existing 4-step GUI workflow stays untouched. A new tab provides pipeline-specific controls. |
| **Fail-safe by default** | If classification fails for one file, the pipeline continues. Errors accumulate in the manifest. No partial transfers. |

---

## 3. Module Layout

```
pathsafe/
    cli.py                  # Extended: +classify, +transfer, +pipeline commands
    anonymizer.py           # Unchanged
    serializer.py           # Extended: +per-patient grouping, +lookup table support
    models.py               # Extended: +ClassificationResult, +TransferResult, +PipelineManifest
    scanner.py              # Unchanged
    formats/                # Unchanged
        base.py
        ndpi.py, svs.py, ...

    # --- NEW MODULES ---
    classifier/
        __init__.py         # Public API: classify_file(), classify_batch()
        ocr.py              # Label image extraction + Tesseract OCR
        stain.py            # Stain classification (H&E vs IHC) from OCR text + color heuristics
        rules.py            # Configurable rule engine for mapping OCR text -> stain/case metadata

    transfer/
        __init__.py         # Public API: transfer_batch()
        rsync.py            # Local rsync subprocess wrapper
        scp.py              # Paramiko-based SCP/SFTP transfer
        progress.py         # Shared progress tracking for both backends

    pipeline/
        __init__.py         # Public API: run_pipeline()
        manifest.py         # PipelineManifest read/write/merge logic
        runner.py           # Orchestrates classify -> anonymize -> transfer
        resume.py           # Detects completed phases, resumes from failure point

    gui/
        pipeline_tab.py     # NEW: Pipeline configuration and monitoring tab
```

### Why This Structure

The `classifier/`, `transfer/`, and `pipeline/` packages are **leaf packages**
with no upward imports into the existing codebase. The existing code never
imports from them. The only integration points are:

- `cli.py` imports from `classifier`, `transfer`, `pipeline` (lazy, behind
  try/except for optional deps).
- `serializer.py` gains new functions (no existing signatures change).
- `models.py` gains new dataclasses (additive only).

This means the change is **safe to merge incrementally** -- classifier can land
first, then transfer, then pipeline orchestration.

---

## 4. Data Flow: The Pipeline Manifest

The central design decision is how pipeline phases share state. Three options
were evaluated:

| Approach | Pros | Cons |
|---|---|---|
| **In-memory dict passed between functions** | Simple, fast | Not restartable. Lost on crash. Tight coupling. |
| **Database (SQLite)** | Queryable, transactional | Heavy for a CLI tool. Overkill for file lists. |
| **JSON manifest file on disk** | Restartable, inspectable, portable, human-readable | Slightly more I/O. Must handle concurrent writes. |

**Decision: JSON manifest on disk.** It aligns with PathSafe's existing
file-centric approach (the serializer already writes a CSV manifest). The
pipeline manifest is a superset.

### Manifest Schema

```json
{
  "version": "1.0",
  "pipeline_id": "2026-03-27T14-30-00_batch001",
  "created": "2026-03-27T14:30:00Z",
  "updated": "2026-03-27T14:45:22Z",
  "config": {
    "input_path": "/slides/incoming/",
    "output_path": "/slides/anonymized/",
    "remote": "user@server:/data/research/",
    "classify": true,
    "anonymize": true,
    "transfer": true
  },
  "phases": {
    "classify": { "status": "completed", "started": "...", "finished": "..." },
    "anonymize": { "status": "completed", "started": "...", "finished": "..." },
    "transfer": { "status": "running", "started": "...", "finished": null }
  },
  "files": [
    {
      "source": "/slides/incoming/SP-24-12345 A1 HE.ndpi",
      "source_basename": "SP-24-12345 A1 HE.ndpi",
      "format": "ndpi",
      "classification": {
        "stain": "H&E",
        "case_id": "SP-24-12345",
        "block": "A1",
        "ocr_text": "SP-24-12345 A1 H&E",
        "ocr_confidence": 0.87,
        "label_image_extracted": true,
        "error": null
      },
      "anonymization": {
        "output_path": "/slides/anonymized/STUDY001/ANON_0001/ANON_0001_HE.ndpi",
        "serial_id": "ANON_0001",
        "patient_folder": "ANON_0001",
        "findings_cleared": 3,
        "sha256": "a1b2c3...",
        "error": null
      },
      "transfer": {
        "remote_path": "user@server:/data/research/STUDY001/ANON_0001/ANON_0001_HE.ndpi",
        "bytes_transferred": 2147483648,
        "transfer_time_s": 45.2,
        "verified": true,
        "error": null
      }
    }
  ]
}
```

### Flow Between Phases

```
                     +-----------------+
                     |  collect_files  |
                     +--------+--------+
                              |
                   files: List[Path]
                              |
                 +------------v-----------+
                 |   classify (optional)  |
                 |  OCR label images      |
                 |  -> stain, case_id     |
                 +------------+-----------+
                              |
              manifest.files[*].classification
                              |
                 +------------v-----------+
                 |   filter + group       |
                 |  apply include/exclude |
                 |  group by case_id      |
                 +------------+-----------+
                              |
              filtered files + folder plan
                              |
                 +------------v-----------+
                 |   anonymize            |
                 |  existing anonymizer   |
                 |  + serializer rename   |
                 |  + per-patient folders |
                 +------------+-----------+
                              |
              manifest.files[*].anonymization
                              |
                 +------------v-----------+
                 |   transfer (optional)  |
                 |  rsync or SCP          |
                 |  verify checksums      |
                 +------------+-----------+
                              |
              manifest.files[*].transfer
                              |
                 +------------v-----------+
                 |   manifest finalized   |
                 |  written to output_dir |
                 +-------------------------+
```

---

## 5. Detailed Design per Component

### 5.1 Classifier (`pathsafe classify`)

**Purpose**: Extract the label image from a WSI, run OCR, parse the text to
determine stain type and case identifier.

**Integration point**: New module, new CLI command. Does NOT modify
`FormatHandler` base class -- label extraction is done via OpenSlide's
`associated_images` API, which is format-agnostic.

**Why not a FormatHandler method?** The format handlers are responsible for
PHI scanning and anonymization of binary file structures. Classification is
a higher-level operation (image analysis, text parsing) that operates on the
label image, not the file structure. Mixing these concerns would bloat the
handler interface and force every handler to implement OCR logic. Keeping
classification separate also allows it to work without format-specific
knowledge -- OpenSlide abstracts the label extraction.

#### Module: `classifier/ocr.py`

```python
def extract_label_image(filepath: Path) -> Optional[PIL.Image.Image]:
    """Extract the label associated image from a WSI file.

    Uses OpenSlide if available, falls back to PathSafe's built-in
    TIFF label extractor (convert --extract label) for TIFF-based formats.

    Returns None if no label image exists.
    """

def ocr_label(image: PIL.Image.Image, lang: str = "eng") -> OcrResult:
    """Run Tesseract OCR on a label image.

    Returns OcrResult with text, per-word confidences, and bounding boxes.
    Pre-processes the image (grayscale, threshold, deskew) for better accuracy.
    """
```

#### Module: `classifier/stain.py`

```python
def classify_stain(ocr_text: str, rules: StainRules | None = None) -> StainClassification:
    """Classify stain type from OCR text.

    Default rules:
    - "H&E", "HE", "H+E", "hematoxylin" -> H&E
    - Known IHC markers (CD3, CD20, Ki67, CK7, etc.) -> IHC:{marker}
    - "PAS", "trichrome", "reticulin", etc. -> Special:{name}
    - No match -> "unknown"

    Custom rules can be loaded from a JSON/YAML config file.
    """

def parse_case_id(ocr_text: str, patterns: list[re.Pattern] | None = None) -> CaseIdResult:
    """Extract case identifier (accession number, block ID) from OCR text.

    Uses the same accession patterns from pathsafe.scanner but applied to
    OCR text instead of binary data. Additional patterns for block labels
    (A1, B2, etc.) and part numbers.
    """
```

#### Module: `classifier/rules.py`

```python
@dataclass
class StainRules:
    """Configurable rule set for stain classification.

    Loaded from a JSON file with format:
    {
      "stain_patterns": {
        "H&E": ["H&E", "HE", "H+E", "hematoxylin"],
        "IHC:CD3": ["CD3", "CD-3"],
        "IHC:Ki67": ["Ki67", "Ki-67", "MIB-1"],
        ...
      },
      "case_id_patterns": ["AS-\\d{2}-\\d+", "SP-\\d{2}-\\d+", ...],
      "block_patterns": ["[A-Z]\\d+", "\\d+[A-Z]"]
    }
    """
```

#### CLI Command

```
pathsafe classify /slides/incoming/ \
    --output classify-results.json \
    --format ndpi \
    --rules custom-rules.json \
    --lang eng+fra \
    --workers 4 \
    --verbose
```

Output formats: JSON (default, machine-readable), CSV (spreadsheet-friendly),
or stdout table (human-readable). The JSON output doubles as a `--filter-file`
input for the anonymize command -- the existing `load_filter_file()` already
accepts `{filename: anything}` dicts.

#### Dependency Group

```toml
[project.optional-dependencies]
classify = [
    "Pillow>=10.0",
    "pytesseract>=0.3.10",
]
```

Tesseract itself is a system dependency (apt install tesseract-ocr). The
`classify` command checks for it at startup and prints a clear error message
if missing.


### 5.2 Extended Serializer (Per-Patient Folder Grouping)

**Purpose**: Group anonymized files into per-patient subdirectories within the
output directory, using classification metadata (case_id) or a lookup table.

**Integration point**: Extends `serializer.py` with new functions. No existing
function signatures change.

#### New Concept: GroupingConfig

```python
@dataclass
class GroupingConfig:
    """Configuration for per-patient folder grouping."""
    mode: GroupingMode  # NONE | CASE_ID | LOOKUP | STUDY
    lookup_path: Optional[Path] = None  # Excel/CSV lookup table
    study_prefix: str = ""              # e.g., "STUDY001"
    subfolder_template: str = "{serial_id}"  # folder name pattern
```

**How grouping interacts with renaming**: Grouping runs AFTER rename-plan
computation. The rename plan produces flat `(source, output)` pairs. Grouping
restructures the output paths by inserting a patient subfolder:

```
Before grouping:  output_dir/ANON_0001_HE.ndpi
After grouping:   output_dir/ANON_0001/ANON_0001_HE.ndpi
                             ^^^^^^^^^
                          patient folder
```

When classification data is available, files from the same case_id are grouped
together:

```
Before:  ANON_0001_HE.ndpi, ANON_0001_CD3.ndpi  (both from SP-24-12345)
After:   ANON_0001/ANON_0001_HE.ndpi
         ANON_0001/ANON_0001_CD3.ndpi
```

#### Lookup Table Support (Excel/CSV)

For study-specific workflows, a lookup table maps original case IDs to
anonymized patient IDs. This is common in research where a study coordinator
maintains a key file.

```csv
case_id,patient_id,study_arm
SP-24-12345,PAT001,treatment
SP-24-12346,PAT002,control
```

```python
def load_grouping_lookup(path: Path) -> Dict[str, str]:
    """Load a case_id -> patient_id mapping from CSV or Excel.

    CSV: requires 'case_id' and 'patient_id' columns.
    Excel (.xlsx): reads the first sheet, same column requirements.
    Excel support requires openpyxl (optional dependency).
    """
```

#### New CLI Options on `anonymize`

```
--group none|case_id|lookup|study   Folder grouping mode (default: none)
--group-lookup LOOKUP_FILE          CSV/Excel mapping case_id -> patient_id
--study-prefix PREFIX               Top-level study folder name
--group-template TEMPLATE           Patient subfolder name pattern
                                    Tokens: {serial_id}, {patient_id}, {case_id}, {stain}
```

These options are only meaningful when `--output` is specified (copy mode) and
are ignored silently in in-place mode.


### 5.3 Transfer (`pathsafe transfer`)

**Purpose**: Transfer anonymized output to a remote server with progress
tracking, checksum verification, and resume support.

**Integration point**: New module, new CLI command. Completely independent of
the anonymization pipeline.

#### Design Decision: rsync vs SCP

| Feature | rsync (subprocess) | SCP/SFTP (paramiko) |
|---|---|---|
| Resume partial transfers | Yes (--partial) | Manual (seek to offset) |
| Bandwidth limiting | Yes (--bwlimit) | Manual throttling |
| Delta transfer | Yes (only changed bytes) | No (full file) |
| Progress reporting | Parseable --progress2 output | Callback-based |
| SSH key auth | Via system SSH config | Via paramiko key loading |
| Windows support | Requires WSL/cygwin | Native Python |
| Dependency | System rsync binary | pip install paramiko |

**Decision: rsync as primary, paramiko as fallback.** rsync is the standard
tool for this job in pathology IT. Paramiko provides cross-platform support
for environments where rsync is unavailable.

#### Module: `transfer/rsync.py`

```python
def transfer_rsync(
    source_dir: Path,
    remote: str,                    # user@host:/path/ or /local/path/
    bwlimit: Optional[int] = None,  # KB/s
    partial: bool = True,
    checksum: bool = True,
    dry_run: bool = False,
    progress_callback: Optional[Callable[[TransferProgress], None]] = None,
    ssh_key: Optional[Path] = None,
    exclude: Optional[List[str]] = None,
) -> TransferResult:
    """Transfer files using rsync subprocess.

    Parses rsync --info=progress2 output for real-time progress.
    Verifies checksums post-transfer via rsync --checksum.
    """
```

#### Module: `transfer/scp.py`

```python
def transfer_scp(
    source_dir: Path,
    remote: str,
    progress_callback: Optional[Callable[[TransferProgress], None]] = None,
    ssh_key: Optional[Path] = None,
) -> TransferResult:
    """Transfer files using paramiko SFTP.

    Falls back to this when rsync is not available.
    Creates remote directory structure, transfers files with progress,
    verifies checksums by computing SHA-256 on both ends.
    """
```

#### CLI Command

```
pathsafe transfer /slides/anonymized/ \
    --remote user@server:/data/research/ \
    --bwlimit 50000 \
    --checksum \
    --dry-run \
    --ssh-key ~/.ssh/id_research \
    --exclude "*.pathsafe_pending" \
    --verbose
```

#### Dependency Group

```toml
[project.optional-dependencies]
transfer = [
    "paramiko>=3.0",
]
```

rsync is a system dependency (already present on most Linux/macOS systems).
The transfer command checks for rsync first and falls back to paramiko.


### 5.4 Pipeline (`pathsafe pipeline`)

**Purpose**: Chain classify, anonymize, and transfer into a single command
with a shared manifest, progress tracking, and resume capability.

**This is a new command, not a flag.** Rationale:

| Approach | Pros | Cons |
|---|---|---|
| Flag on anonymize (`--pipeline`) | Fewer commands | Overloads an already complex command (20+ options). Confusing: is `--transfer` an anonymize option? |
| Composition via shell pipe | Unix-philosophy | No shared state, no resume, no unified progress |
| **New `pipeline` command** | Clear intent, dedicated options, shared manifest, resumable | One more top-level command |

The pipeline command is a thin orchestrator that calls the same public APIs as
the individual commands.

#### CLI Command

```
pathsafe pipeline /slides/incoming/ \
    --output /slides/anonymized/ \
    --remote user@server:/data/research/ \
    --classify \
    --classify-rules custom-rules.json \
    --rename auto --prefix ANON \
    --group case_id \
    --study-prefix STUDY001 \
    --transfer \
    --bwlimit 50000 \
    --checksum \
    --certificate pipeline-cert.json \
    --manifest pipeline-manifest.json \
    --resume \
    --workers 4 \
    --verbose
```

Flags `--classify` and `--transfer` are opt-in. Without them, the pipeline
degrades to the existing anonymize command. This means `pathsafe pipeline
--output /out /in` is equivalent to `pathsafe anonymize --output /out /in`.

#### Resume Logic

```python
def can_resume(manifest_path: Path) -> ResumeInfo:
    """Check if a pipeline manifest exists and determine where to resume.

    Returns which phase to start from and which files are already done.
    A file is 'done' for a phase if its phase entry has no error and
    the output file still exists on disk.
    """
```

Resume is file-granular, not phase-granular. If classify completed for 900 of
1000 files before a crash, resume picks up at file 901, not at the beginning
of the classify phase.

#### Module: `pipeline/runner.py`

```python
def run_pipeline(config: PipelineConfig) -> PipelineResult:
    """Execute the full pipeline: classify -> anonymize -> transfer.

    1. Collect files (respecting format filter and include/exclude).
    2. If --classify: run classify_batch(), write results to manifest.
    3. Apply filters using classification output (e.g., only H&E slides).
    4. Compute rename plan + grouping plan.
    5. Run anonymize_batch() with precomputed pairs.
    6. If --transfer: run transfer_batch() on the output directory.
    7. Finalize manifest with all phase results.

    At each phase boundary, the manifest is written to disk so the
    pipeline is resumable.
    """
```

---

## 6. Dependency Chain and Execution Order

The dependency chain between phases is:

```
classify (optional)
    |
    | outputs: stain, case_id per file
    v
filter (uses classification to include/exclude)
    |
    | outputs: filtered file list
    v
group (uses case_id to compute folder structure)
    |
    | outputs: (source, output_with_subfolder) pairs
    v
rename (uses serializer to compute final filenames)
    |
    | outputs: precomputed (source, final_output) pairs
    v
anonymize (uses precomputed pairs)
    |
    | outputs: anonymized files at final paths
    v
transfer (optional, operates on output directory)
```

Key constraint: **grouping depends on classification output.** If classification
is disabled, grouping falls back to sequential patient folders
(`ANON_0001/`, `ANON_0002/`) or lookup-table-based folders. This means the
serializer's `compute_rename_plan()` function must accept an optional
`classification_data` parameter to inject case_id grouping information.

### Extended `compute_rename_plan` Signature

```python
def compute_rename_plan(
    config: SerializerConfig,
    source_paths: List[Path],
    output_dir: Path,
    grouping: Optional[GroupingConfig] = None,
    classification: Optional[Dict[str, ClassificationResult]] = None,
) -> List[Tuple[Path, Path]]:
```

The two new parameters are optional and default to None, so all existing call
sites continue to work unchanged.

---

## 7. New Data Models

Added to `models.py`:

```python
@dataclass
class OcrResult:
    """Raw OCR output from a label image."""
    text: str
    confidence: float              # Mean word confidence 0.0-1.0
    word_confidences: List[float]  # Per-word confidences
    lang: str                      # Tesseract language used
    preprocessing: str             # "grayscale+threshold" etc.
    error: Optional[str] = None


@dataclass
class ClassificationResult:
    """Classification result for a single WSI file."""
    filepath: Path
    stain: str                     # "H&E", "IHC:CD3", "Special:PAS", "unknown"
    case_id: Optional[str] = None  # Parsed accession number
    block_id: Optional[str] = None # Parsed block label (A1, B2, etc.)
    ocr_text: Optional[str] = None
    ocr_confidence: float = 0.0
    label_extracted: bool = False
    error: Optional[str] = None


@dataclass
class TransferProgress:
    """Progress update during file transfer."""
    bytes_transferred: int
    bytes_total: int
    files_transferred: int
    files_total: int
    current_file: str
    speed_bytes_per_sec: float
    eta_seconds: float


@dataclass
class TransferResult:
    """Result of transferring files to a remote destination."""
    files_transferred: int = 0
    files_errored: int = 0
    bytes_transferred: int = 0
    transfer_time_seconds: float = 0.0
    verified: bool = False
    errors: List[str] = field(default_factory=list)


@dataclass
class PipelineConfig:
    """Configuration for a full pipeline run."""
    input_path: Path
    output_dir: Path
    remote: Optional[str] = None

    # Phase toggles
    do_classify: bool = False
    do_anonymize: bool = True
    do_transfer: bool = False

    # Classify options
    classify_rules: Optional[Path] = None
    classify_lang: str = "eng"

    # Anonymize options (mirrors existing CLI)
    rename: str = "keep"
    prefix: str = "ANON"
    start: int = 1
    digits: int = 4
    separator: str = "_"
    mapping_file: Optional[Path] = None
    rename_template: str = "{prefix}_{index}.{ext}"
    reset_timestamps: bool = True
    verify_integrity: bool = False
    checksum: bool = False

    # Grouping options
    grouping: str = "none"
    grouping_lookup: Optional[Path] = None
    study_prefix: str = ""
    group_template: str = "{serial_id}"

    # Transfer options
    bwlimit: Optional[int] = None
    ssh_key: Optional[Path] = None

    # Filter options
    include: Optional[List[str]] = None
    exclude: Optional[List[str]] = None
    filter_file: Optional[Path] = None
    format_filter: Optional[str] = None

    # General
    workers: int = 0
    manifest_path: Optional[Path] = None
    certificate_path: Optional[Path] = None
    resume: bool = False
    dry_run: bool = False


@dataclass
class PipelineResult:
    """Aggregate result of a pipeline run."""
    classification_results: List[ClassificationResult] = field(default_factory=list)
    anonymization_result: Optional[BatchResult] = None
    transfer_result: Optional[TransferResult] = None
    manifest_path: Optional[Path] = None
    total_time_seconds: float = 0.0
    resumed_from: Optional[str] = None  # Phase name if resumed
```

---

## 8. Updated `pyproject.toml` Dependencies

```toml
[project.optional-dependencies]
gui = ["PySide6>=6.5"]
dicom = ["pydicom>=2.3"]
openslide = ["openslide-python>=1.2"]
convert = [
    "openslide-python>=1.2",
    "tifffile>=2023.1",
    "imagecodecs>=2023.1",
    "numpy>=1.24",
]
# --- NEW ---
classify = [
    "Pillow>=10.0",
    "pytesseract>=0.3.10",
    "openslide-python>=1.2",   # For label image extraction
]
transfer = [
    "paramiko>=3.0",           # Fallback when rsync unavailable
]
lookup = [
    "openpyxl>=3.1",           # Excel lookup table support
]
pipeline = [
    "pathsafe[classify,transfer]",
]
all = [
    "PySide6>=6.5",
    "pydicom>=2.3",
    "openslide-python>=1.2",
    "tifffile>=2023.1",
    "imagecodecs>=2023.1",
    "numpy>=1.24",
    "Pillow>=10.0",
    "pytesseract>=0.3.10",
    "paramiko>=3.0",
    "openpyxl>=3.1",
]
```

---

## 9. GUI Integration

The GUI gains a **Pipeline tab** alongside the existing workflow tabs. This tab
is only visible when the `classify` and/or `transfer` extras are installed.

### Pipeline Tab Layout

```
+------------------------------------------------------------------+
| Pipeline Configuration                                            |
|                                                                  |
|  Input:    [/slides/incoming/         ] [Browse]                 |
|  Output:   [/slides/anonymized/       ] [Browse]                 |
|  Remote:   [user@server:/data/        ] (optional)               |
|                                                                  |
|  Phases:                                                         |
|  [x] Classify   Rules: [default     v]  Lang: [eng+fra]         |
|  [x] Anonymize  Rename: [auto       v]  Prefix: [ANON]          |
|      Group: [case_id  v]  Study: [STUDY001]                      |
|  [x] Transfer   Bandwidth: [50000 KB/s]  [x] Verify checksums   |
|                                                                  |
|  [x] Resume if manifest exists                                   |
|                                                                  |
|  [ Start Pipeline ]  [ Stop ]                                    |
|                                                                  |
|  Phase Progress:                                                 |
|  Classify:   [====================] 100%  450/450 files          |
|  Anonymize:  [============        ]  60%  270/450 files          |
|  Transfer:   [                    ]   0%  waiting                |
|                                                                  |
|  Log Output:                                                     |
|  14:30:01  Classifying SP-24-12345 A1 HE.ndpi -> H&E (0.92)    |
|  14:30:02  Classifying SP-24-12345 A1 CD3.ndpi -> IHC:CD3      |
|  ...                                                             |
+------------------------------------------------------------------+
```

### Implementation Approach

The `PipelineTab` widget follows the same pattern as the existing GUI: a
`QThread` worker (`PipelineWorker`) calls `run_pipeline()` from
`pipeline/runner.py` and emits signals for progress and log updates. The
existing `WorkerSignals` class is reused.

Feature detection at startup:

```python
# In gui/pipeline_tab.py
def is_available() -> bool:
    """Check if pipeline dependencies are installed."""
    try:
        import PIL
        import pytesseract
        return True
    except ImportError:
        return False

# In gui/window.py, during tab setup:
try:
    from pathsafe.gui.pipeline_tab import PipelineTab, is_available
    if is_available():
        self.tabs.addTab(PipelineTab(self), "Pipeline")
except ImportError:
    pass  # classify/transfer extras not installed
```

---

## 10. CLI Command Summary

After the extension, PathSafe's command tree looks like this:

```
pathsafe
    scan          # Existing: read-only PHI scan
    anonymize     # Existing: strip PHI (+ new --group options)
    verify        # Existing: re-scan to confirm clean
    convert       # Existing: format conversion
    info          # Existing: file metadata
    gui           # Existing: launch GUI
    classify      # NEW: OCR labels, classify stain/case
    transfer      # NEW: rsync/SCP to remote
    pipeline      # NEW: chained classify->anonymize->transfer
```

---

## 11. Error Handling Strategy

| Scenario | Behavior |
|---|---|
| OCR fails for one file (no label, Tesseract crash) | Log warning, set `classification.error` in manifest, continue. File is included in anonymization with `stain: "unknown"`. |
| Anonymization fails for one file | Log error, set `anonymization.error` in manifest, continue. File is excluded from transfer. |
| Transfer fails mid-batch (network drop) | Stop transfer phase. Manifest records which files transferred. `--resume` picks up from last successful file. |
| rsync not found, paramiko not installed | Error message with install instructions. Transfer phase skipped with exit code 1. |
| Tesseract not found | Error message: "Install tesseract-ocr (apt/brew)". Classify phase skipped. |
| Manifest file corrupted | Refuse to resume. Print error, suggest `--no-resume` to start fresh. |
| Disk full during anonymization | Existing preflight check catches this. Pipeline inherits the same safeguard. |

---

## 12. Implementation Order

The work is structured to land in 4 independent, reviewable pull requests:

### PR 1: Classifier (low risk, no existing code changes)
- `classifier/` package (ocr.py, stain.py, rules.py)
- `ClassificationResult` model
- `pathsafe classify` CLI command
- `classify` dependency group in pyproject.toml
- Tests: mock Tesseract, test stain rules, test case_id parsing

### PR 2: Extended Serializer (medium risk, touches serializer.py)
- `GroupingConfig` dataclass
- `compute_rename_plan()` extended signature (backward-compatible)
- `load_grouping_lookup()` function
- New `--group*` CLI options on `anonymize`
- `lookup` dependency group in pyproject.toml
- Tests: folder structure assertions, lookup table loading, edge cases

### PR 3: Transfer (low risk, no existing code changes)
- `transfer/` package (rsync.py, scp.py, progress.py)
- `TransferResult`, `TransferProgress` models
- `pathsafe transfer` CLI command
- `transfer` dependency group in pyproject.toml
- Tests: mock rsync subprocess, mock paramiko session

### PR 4: Pipeline Orchestration + GUI Tab
- `pipeline/` package (manifest.py, runner.py, resume.py)
- `PipelineConfig`, `PipelineResult`, `PipelineManifest` models
- `pathsafe pipeline` CLI command
- `gui/pipeline_tab.py`
- `pipeline` dependency group in pyproject.toml
- Integration tests: full pipeline with mock backends

---

## 13. Key Takeaways

- **Classify is a standalone module**, not a format-handler method. It uses
  OpenSlide for label extraction and Tesseract for OCR, both format-agnostic.
  This keeps the format handler interface clean and focused on binary PHI.

- **The pipeline manifest is the integration contract.** Phases communicate
  through a JSON file on disk. This makes the pipeline restartable, inspectable,
  and debuggable. No hidden in-memory state.

- **Per-patient grouping extends the serializer, not the anonymizer.** The
  anonymizer does not know about folder structure. The serializer computes
  `(source, output_with_subfolder)` pairs and passes them as `precomputed_pairs`
  to `anonymize_batch()` -- the same mechanism already used for rename plans.

- **Pipeline is a new command, not a flag.** It deserves its own option namespace
  rather than overloading the already complex `anonymize` command.

- **All new dependencies are optional.** The core `pathsafe scan`, `anonymize`,
  `verify`, `convert`, and `info` commands work with zero new dependencies.
  Classification needs Pillow + pytesseract. Transfer needs paramiko (or system
  rsync). The `all` extra installs everything.

- **Four independent PRs** allow incremental review and deployment. Each PR is
  useful on its own -- you can ship `classify` without `pipeline`.
