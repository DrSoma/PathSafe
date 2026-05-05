"""Stain classification from WSI label images via OCR.

Extracts the label associated image from whole-slide image files using
OpenSlide, runs PaddleOCR to read the text, and classifies the stain
type (H&E vs IHC) using regex-based line classification ported from
LungAI-scripts/extract_svs_labels.py.

**PHI safety model** -- allowlist-only output:

    The raw OCR text is never stored or returned.  After OCR, only the
    stain-related fields (stain_type, stain_name, stain_code) are
    extracted via deterministic regex matching and validated against a
    known stain vocabulary.  Every output field is additionally checked
    against PHI_STRING_PATTERNS from ``scanner.py`` before export.

Dependencies (guarded):
    - openslide-python  (label image extraction)
    - paddleocr         (text recognition)
    - numpy             (image array conversion)
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any


logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Guarded optional imports -- singleton pattern matching converter.py
# ---------------------------------------------------------------------------

_openslide: Any = None
_paddleocr: Any = None
_numpy: Any = None
_ocr_instance: Any = None
_ocr_lock = threading.Lock()


def _require_openslide() -> Any:
    """Lazy-load openslide-python, raising a clear message if missing."""
    global _openslide
    if _openslide is not None:
        return _openslide
    try:
        import openslide

        _openslide = openslide
        return openslide
    except ImportError:
        raise ImportError(
            "openslide-python is required for stain classification. "
            "Install it with: pip install pathsafe[classify]"
        ) from None


def _require_paddleocr() -> Any:
    """Lazy-load paddleocr, raising a clear message if missing."""
    global _paddleocr
    if _paddleocr is not None:
        return _paddleocr
    try:
        import paddleocr

        _paddleocr = paddleocr
        return paddleocr
    except ImportError:
        raise ImportError(
            "paddleocr is required for stain classification. "
            "Install it with: pip install paddleocr paddlepaddle"
        ) from None


def _require_numpy() -> Any:
    """Lazy-load numpy, raising a clear message if missing."""
    global _numpy
    if _numpy is not None:
        return _numpy
    try:
        import numpy

        _numpy = numpy
        return numpy
    except ImportError:
        raise ImportError(
            "numpy is required for stain classification. Install it with: pip install numpy"
        ) from None


def _get_ocr() -> Any:
    """Return a PaddleOCR singleton instance (thread-safe).

    Follows the same lazy-load-once pattern used elsewhere in the
    codebase (see ``converter._require_openslide``).  PaddleOCR model
    loading is expensive (~2-4 s), so we do it once and reuse.
    """
    global _ocr_instance
    if _ocr_instance is not None:
        return _ocr_instance
    with _ocr_lock:
        # Double-check after acquiring lock
        if _ocr_instance is not None:
            return _ocr_instance
        paddleocr = _require_paddleocr()
        _ocr_instance = paddleocr.PaddleOCR(
            use_angle_cls=True,
            lang="en",
            show_log=False,
        )
        return _ocr_instance


# ---------------------------------------------------------------------------
# Stain vocabulary -- allowlist validation
# ---------------------------------------------------------------------------

_VOCABULARY_PATH = Path(__file__).parent / "data" / "stain_vocabulary.json"

# Loaded lazily; normalized to uppercase for matching.
_stain_vocabulary: set | None = None
_vocab_lock = threading.Lock()


def _load_vocabulary() -> set:
    """Load stain vocabulary from JSON, falling back to a hardcoded set.

    The vocabulary file is expected at ``pathsafe/data/stain_vocabulary.json``
    with a top-level ``"stains"`` array of strings.  All names are normalized
    to uppercase for case-insensitive matching.
    """
    global _stain_vocabulary
    if _stain_vocabulary is not None:
        return _stain_vocabulary
    with _vocab_lock:
        if _stain_vocabulary is not None:
            return _stain_vocabulary
        if _VOCABULARY_PATH.is_file():
            try:
                with open(str(_VOCABULARY_PATH), encoding="utf-8") as f:
                    data = json.load(f)
                names = data.get("stains", [])
                _stain_vocabulary = {n.upper() for n in names if isinstance(n, str)}
                logger.debug(
                    "Loaded %d stain names from %s", len(_stain_vocabulary), _VOCABULARY_PATH
                )
                return _stain_vocabulary
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning(
                    "Failed to load stain vocabulary from %s: %s. "
                    "Falling back to hardcoded defaults.",
                    _VOCABULARY_PATH,
                    exc,
                )
        # Hardcoded fallback -- the ~50 most common stains
        _stain_vocabulary = {
            # Histochemical
            "H&E",
            "H+E",
            "H STAIN",
            "PAS",
            "PAS-D",
            "MASSON",
            "MASSON TRICHROME",
            "GIEMSA",
            "GMS",
            "GRAM",
            "AFB",
            "ZIEHL-NEELSEN",
            "IRON",
            "PERLS",
            "CONGO RED",
            "RETICULIN",
            "ELASTIC",
            "EVG",
            "ALCIAN BLUE",
            "MUCICARMINE",
            "TRICHROME",
            "FONTANA-MASSON",
            "VON KOSSA",
            "WARTHIN-STARRY",
            "FITE",
            # IHC -- epithelial / lung panel
            "CK7",
            "CK7-U",
            "CK20",
            "CK20-U",
            "CK5",
            "CK5-6",
            "CK5/6",
            "TTF-1",
            "TTF1",
            "TTF+NAP-A",
            "TTF-1+NAP-A",
            "NAPSIN-A",
            "NAP-A",
            "P40",
            "P40CK5-6",
            "P40CK5+6",
            "P40CK5+6-U",
            "P63",
            "CDX2",
            "CDX-2",
            # IHC -- targeted / predictive
            "ALK",
            "ALK LUNG",
            "ROS1",
            "ROS-1",
            "PD-L1",
            "PD-L1 22C3",
            "PD-L1 SP263",
            "PDL1",
            "KI67",
            "KI-67",
            "MIB-1",
            "HER2",
            "HER-2",
            "ER",
            "PR",
            # IHC -- hematolymphoid
            "CD3",
            "CD4",
            "CD5",
            "CD8",
            "CD10",
            "CD15",
            "CD20",
            "CD23",
            "CD30",
            "CD31",
            "CD34",
            "CD45",
            "CD56",
            "CD68",
            "CD117",
            "CD138",
            # IHC -- melanocytic / mesenchymal
            "S100",
            "S-100",
            "SOX10",
            "MELAN-A",
            "HMB-45",
            "DESMIN",
            "SMA",
            "VIMENTIN",
            # IHC -- neuroendocrine
            "SYNAPTOPHYSIN",
            "SYN",
            "CHROMOGRANIN",
            "CHR-A",
            "INSM1",
            # IHC -- other common
            "PAX8",
            "PAX-8",
            "WT1",
            "CALRETININ",
            "D2-40",
            "DOG1",
            "P53",
            "P16",
            "CYCLIN D1",
            "BCL2",
            "BCL-2",
            "PANCK",
            "PAN-CK",
            "AE1/AE3",
            "CAM5.2",
            "EMA",
            "CMV",
            "HSV",
            "EBER",
            "EBV",
            "MLH1",
            "MSH2",
            "MSH6",
            "PMS2",
        }
        return _stain_vocabulary


def _validate_stain_name(raw_name: str) -> str:
    """Validate a stain name against the vocabulary allowlist.

    Returns the original name if it matches (case-insensitive), or an
    empty string if the name is not recognized.  This prevents any
    unexpected OCR text (including potential PHI fragments) from leaking
    into the output.
    """
    if not raw_name:
        return ""
    vocab = _load_vocabulary()
    # Exact match (case-insensitive)
    if raw_name.upper() in vocab:
        return raw_name
    # Try normalizing common OCR artifacts: extra spaces, trailing -U
    normalized = re.sub(r"\s+", " ", raw_name).strip().upper()
    if normalized in vocab:
        return raw_name
    # Strip trailing "-U" (universal antibody suffix) and retry
    base = re.sub(r"-U$", "", normalized)
    if base in vocab:
        return raw_name
    # Check if the name starts with a known stain (handles "CK20-U lot 123")
    for known in sorted(vocab, key=len, reverse=True):
        if normalized.startswith(known):
            return raw_name[: len(known)]
    logger.debug("Stain name '%s' not in vocabulary; discarded", raw_name)
    return ""


# ---------------------------------------------------------------------------
# PHI safety net -- import patterns from scanner.py
# ---------------------------------------------------------------------------


def _check_phi_safety(value: str) -> bool:
    """Return True if the value triggers any PHI string pattern.

    Used as a final safety check on every output field before export.
    """
    if not value:
        return False
    from pathsafe.scanner import PHI_STRING_PATTERNS

    return any(pattern.search(value) for pattern, _label in PHI_STRING_PATTERNS)


def _sanitize_field(value: str) -> str:
    """Return the value unchanged if clean, or empty string if it contains PHI."""
    if _check_phi_safety(value):
        logger.warning(
            "PHI pattern detected in classifier output field; value suppressed for safety"
        )
        return ""
    return value


# ---------------------------------------------------------------------------
# Classification regex patterns -- ported from LungAI-scripts
# ---------------------------------------------------------------------------

# H&E: starts with accession -- AS-YY-NNNNNN (allow OCR noise)
_HE_FIRST_RE = re.compile(
    r"^[A0On][S$5:]\s*[-=\s]\s*\d{2}\s*[-=\s]\s*\d{3,}",
    re.IGNORECASE,
)
# FS/FE-prefixed (frozen section accessions)
_FS_FIRST_RE = re.compile(r"^F[iIeE]?[SE$]\s*[-=\s]\s*\d{2}", re.IGNORECASE)
# IHC (standard): starts with stain code number
_IHC_NUM_FIRST_RE = re.compile(r"^\d+[\s:]+\S+|^\d{3}[A-Z]", re.IGNORECASE)
# IHC (send-out / SV-prefixed)
_SV_FIRST_RE = re.compile(r"^[Ss][Vv]\s*[-=\s]", re.IGNORECASE)
# IHC (stain name first, no code number)
_STAIN_NAME_FIRST_RE = re.compile(r"^(P40|CK|TTF|NAP|CDX|ROS|ALK|PD|LTT)", re.IGNORECASE)
# Standalone 3-digit stain code on its own line
_STANDALONE_CODE_RE = re.compile(r"^\d{3}$")

# Stain code extraction: leading digits from an IHC first line
_STAIN_CODE_EXTRACT_RE = re.compile(r"^(\d{2,3})[\s:]+(.+)")
# Block identifier
_BLOCK_RE = re.compile(r"^[A-Z]\d+(-\d+)?$", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass
class StainClassification:
    """Allowlist-only classification result for a single slide.

    Only stain-related fields are populated.  Raw OCR text, patient
    names, accession numbers, and all other PHI-bearing fields are
    never stored.

    Attributes:
        stain_type: Classification category -- one of ``"he"``,
            ``"ihc"``, ``"ihc_sv"``, or ``"unknown"``.
        stain_name: Human-readable stain name validated against the
            vocabulary allowlist.  Examples: ``"H&E"``, ``"CK20-U"``,
            ``"TTF-1+NAP-A"``.  Empty string if unrecognized.
        stain_code: Numeric stain code from IHC labels (e.g. ``"122"``,
            ``"310"``).  Empty string for H&E or if not present.
        confidence: Average PaddleOCR confidence score across all
            detected text lines (0.0 -- 1.0).
        label_format: Description of the classification method used
            (e.g. ``"he_accession_first"``, ``"ihc_code_name"``).
        error: Error message if classification failed, otherwise None.
    """

    stain_type: str = "unknown"
    stain_name: str = ""
    stain_code: str = ""
    confidence: float = 0.0
    label_format: str = ""
    error: str | None = None


# ---------------------------------------------------------------------------
# Label classification -- regex-based first-line matching
# ---------------------------------------------------------------------------


def _any_line_has_he(lines: list[tuple[str, float]]) -> bool:
    """Fallback check: return True if any line mentions H&E stain."""
    for text, _ in lines:
        t = text.upper()
        if "H STAIN" in t or "H+E" in t or "H&E" in t:
            return True
    return False


def classify_label(lines: list[tuple[str, float]]) -> tuple[str, str]:
    """Classify a label's stain type from sorted OCR lines.

    Applies regex patterns against the first OCR line to determine
    label format.  Patterns are evaluated in priority order:

        1. H&E accession format (AS-YY-NNNNNN)
        2. Frozen section prefix (FS-YY-...)
        3. IHC numeric code + stain name (122 CK20-U)
        4. IHC send-out (SV-YY-NNNNN)
        5. IHC stain name first (P40CK5-6)
        6. Standalone code number (301)
        7. Fallback: any line mentioning H&E

    Args:
        lines: List of ``(text, confidence)`` tuples, sorted top-to-bottom.

    Returns:
        Tuple of ``(stain_type, label_format)`` where stain_type is one
        of ``"he"``, ``"ihc"``, ``"ihc_sv"``, ``"unknown"``.
    """
    if not lines:
        return "unknown", "no_lines"
    first = lines[0][0].strip()
    if _HE_FIRST_RE.match(first):
        return "he", "he_accession_first"
    if _FS_FIRST_RE.match(first):
        return "he", "he_frozen_section"
    if _IHC_NUM_FIRST_RE.match(first):
        return "ihc", "ihc_code_name"
    if _SV_FIRST_RE.match(first):
        return "ihc_sv", "ihc_send_out"
    if _STAIN_NAME_FIRST_RE.match(first):
        return "ihc", "ihc_name_first"
    # Standalone code number with stain name on next line
    if _STANDALONE_CODE_RE.match(first) and len(lines) >= 2:
        return "ihc", "ihc_code_then_name"
    # Fallback: if any line mentions H&E
    if _any_line_has_he(lines):
        return "he", "he_fallback"
    return "unknown", "unrecognized"


# ---------------------------------------------------------------------------
# Label parsers -- extract ONLY stain fields (allowlist approach)
# ---------------------------------------------------------------------------


def parse_he_label(lines: list[tuple[str, float]]) -> tuple[str, str]:
    """Extract stain name and code from an H&E label.

    H&E labels have a predictable layout::

        line 0: accession  (PHI -- ignored)
        line 1: block      (ignored)
        line 2: stain      (H Stain H+E)
        line 3+: name/date (PHI -- ignored)

    Returns:
        Tuple of ``(stain_name, stain_code)``.  For H&E, stain_code
        is always empty.
    """
    stain_name = "H&E"  # Default for H&E type
    if len(lines) >= 3:
        stain_text = lines[2][0].strip().rstrip(".")
        upper = stain_text.upper()
        # Confirm it actually mentions a stain
        if "H" in upper and ("STAIN" in upper or "+E" in upper or "&E" in upper):
            stain_name = "H&E"
        else:
            validated = _validate_stain_name(stain_text)
            if validated:
                stain_name = validated
    return stain_name, ""


def parse_ihc_label(lines: list[tuple[str, float]]) -> tuple[str, str]:
    """Extract stain name and code from a standard IHC label.

    Handles several sub-layouts:

        A) ``122 CK20-U / AS-21-37595-C4 / ...``
        B) ``P40CK5-6 / 301 / AS-18-... / ...``  (stain name first)
        C) ``301 / P40CK5+6-U / AS-21-... / ...`` (code alone first)
        D) ``310: TTF+NAP-A / AS-21-... / ...``   (colon after code)

    Returns:
        Tuple of ``(stain_name, stain_code)``.
    """
    if not lines:
        return "", ""

    first = lines[0][0].strip()
    stain_name = ""
    stain_code = ""

    if _STANDALONE_CODE_RE.match(first):
        # Code alone on first line, stain name on next
        stain_code = first
        if len(lines) >= 2:
            candidate = lines[1][0].strip()
            stain_name = _validate_stain_name(candidate)
    elif _STAIN_NAME_FIRST_RE.match(first) and not _IHC_NUM_FIRST_RE.match(first):
        # Stain name first, code on next line
        stain_name = _validate_stain_name(first)
        if len(lines) >= 2 and re.match(r"^\d{2,3}$", lines[1][0].strip()):
            stain_code = lines[1][0].strip()
    else:
        # Standard: code + name on same line (e.g. "122 CK20-U")
        m = _STAIN_CODE_EXTRACT_RE.match(first)
        if m:
            stain_code = m.group(1)
            stain_name = _validate_stain_name(m.group(2).strip())
        else:
            # Could be "310:TTF+NAP-A" with colon but no space after digits
            colon_m = re.match(r"^(\d{2,3}):?\s*(.+)", first)
            if colon_m:
                stain_code = colon_m.group(1)
                stain_name = _validate_stain_name(colon_m.group(2).strip())
            else:
                stain_name = _validate_stain_name(first)

    return stain_name, stain_code


def parse_ihc_sv_label(lines: list[tuple[str, float]]) -> tuple[str, str]:
    """Extract stain name and code from a send-out IHC label (SV-prefixed).

    Layout::

        SV - YY - NNNNN / STAIN_NAME / BLOCK / TRS_LEVEL / AS_ACCESSION

    Returns:
        Tuple of ``(stain_name, stain_code)``.  Send-out labels rarely
        have numeric stain codes.
    """
    stain_name = ""
    stain_code = ""

    for text_raw, _conf in lines:
        text = text_raw.strip().rstrip("*.").strip()
        if not text:
            continue
        upper = text.upper()

        # Skip SV number, TRS lines, lot numbers, block IDs, accessions
        if upper.startswith(("SV", "TRS", "LOT")):
            continue
        if re.match(r"^\d{4,6}$", text):
            continue
        if _BLOCK_RE.match(text):
            continue
        if re.match(r"^A[S$]\s*[-\s]?\s*\d{2}", text, re.IGNORECASE):
            continue

        # First remaining non-numeric text is the stain name
        if not stain_name and not text[0].isdigit():
            stain_name = _validate_stain_name(text)
            if stain_name:
                break

    return stain_name, stain_code


# ---------------------------------------------------------------------------
# Label image extraction
# ---------------------------------------------------------------------------


def _extract_label_array(filepath: Path) -> Any:
    """Extract the label associated image from a WSI as a numpy RGB array.

    The image is held in memory only -- never written to disk.

    Args:
        filepath: Path to the WSI file (SVS, NDPI, etc.).

    Returns:
        numpy ndarray of shape ``(H, W, 3)`` with dtype uint8, or None
        if the slide has no label image.

    Raises:
        ImportError: If openslide or numpy are not installed.
        Exception: If OpenSlide cannot open the file.
    """
    openslide = _require_openslide()
    np = _require_numpy()

    slide = openslide.OpenSlide(str(filepath))
    try:
        if "label" not in slide.associated_images:
            return None
        img = slide.associated_images["label"]
        arr = np.array(img.convert("RGB"))
        return arr
    finally:
        slide.close()


# ---------------------------------------------------------------------------
# OCR execution
# ---------------------------------------------------------------------------


def _run_ocr(image_array: Any) -> list[tuple[str, float]]:
    """Run PaddleOCR on an image array and return sorted text lines.

    Args:
        image_array: numpy ndarray of shape ``(H, W, 3)``.

    Returns:
        List of ``(text, confidence)`` tuples, sorted top-to-bottom by
        the y-coordinate of each detection's bounding box.
    """
    ocr = _get_ocr()
    result = ocr.ocr(image_array, cls=True)

    if not result or not result[0]:
        return []

    # Sort detections top-to-bottom by the y-coordinate of the top-left corner
    detections = sorted(result[0], key=lambda x: x[0][0][1])
    lines: list[tuple[str, float]] = [(text, conf) for _bbox, (text, conf) in detections]
    return lines


# ---------------------------------------------------------------------------
# File hashing
# ---------------------------------------------------------------------------


def _compute_file_hash(filepath: Path) -> str:
    """Compute SHA-256 hash of a file for use as a PHI-free identifier.

    Args:
        filepath: Path to the file.

    Returns:
        Hex-encoded SHA-256 digest string.
    """
    h = hashlib.sha256()
    with open(str(filepath), "rb") as f:
        while True:
            chunk = f.read(65536)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _is_hex_hash(value: str) -> bool:
    """Return True if the value looks like a hex-encoded SHA-256 hash."""
    return bool(re.fullmatch(r"[0-9a-f]{64}", value))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def classify_slide(filepath: Path) -> StainClassification:
    """Classify a single slide's stain type from its label image.

    Extracts the label image from the WSI, runs PaddleOCR, and applies
    regex-based classification to determine the stain type.  Only
    allowlisted stain fields are returned; all other OCR text (patient
    names, accession numbers, dates) is discarded immediately after
    parsing.

    Args:
        filepath: Path to the WSI file (SVS, NDPI, SCN, etc.).

    Returns:
        A ``StainClassification`` with sanitized stain fields.

    Raises:
        ImportError: If openslide-python, paddleocr, or numpy are not
            installed.  Dependency errors propagate so callers can show
            actionable install instructions.
    """
    filepath = Path(filepath)
    result = StainClassification()

    if not filepath.exists():
        result.error = f"File not found: {filepath.name}"
        return result

    # Step 1: Extract label image (in memory only)
    try:
        image_array = _extract_label_array(filepath)
    except ImportError:
        raise  # Let dependency errors propagate clearly
    except Exception as exc:
        result.error = f"Failed to read label image: {type(exc).__name__}"
        return result

    if image_array is None:
        result.error = "no_label_image"
        return result

    # Step 2: Run OCR
    try:
        lines = _run_ocr(image_array)
    except ImportError:
        raise
    except Exception as exc:
        result.error = f"OCR failed: {type(exc).__name__}"
        return result

    if not lines:
        result.error = "ocr_no_text"
        return result

    # Step 3: Compute average confidence
    result.confidence = sum(c for _, c in lines) / len(lines)

    # Step 4: Classify label type
    stain_type, label_format = classify_label(lines)
    result.stain_type = stain_type
    result.label_format = label_format

    # Step 5: Parse stain fields (allowlist extraction only)
    if stain_type == "he":
        stain_name, stain_code = parse_he_label(lines)
    elif stain_type == "ihc":
        stain_name, stain_code = parse_ihc_label(lines)
    elif stain_type == "ihc_sv":
        stain_name, stain_code = parse_ihc_sv_label(lines)
    else:
        stain_name, stain_code = "", ""

    # Step 6: PHI safety net -- check all output fields against scanner patterns
    result.stain_name = _sanitize_field(stain_name)
    result.stain_code = _sanitize_field(stain_code)

    return result


def classify_batch(
    slides_dir: Path,
    format_filter: str | None = None,
    progress_callback: Any | None = None,
    use_filenames: bool = False,
) -> dict[str, StainClassification]:
    """Classify all slides in a directory.

    Iterates over WSI files, classifies each one, and returns a dict
    keyed by file SHA-256 hash (default) or filename.

    Args:
        slides_dir: Directory containing WSI files.
        format_filter: Optional extension filter (e.g. ``"svs"``).
            If None, all supported WSI extensions are included.
        progress_callback: Optional callable with signature
            ``(index: int, total: int, filepath: Path,
            result: StainClassification) -> None``.
        use_filenames: If True, use filenames as dict keys instead of
            SHA-256 hashes.  Only appropriate when files have already
            been deidentified.

    Returns:
        Dict mapping identifier (hash or filename) to
        ``StainClassification``.
    """
    import os

    from pathsafe.deidentifier import FORMAT_EXT_MAP, WSI_EXTENSIONS

    slides_dir = Path(slides_dir)
    if not slides_dir.is_dir():
        raise ValueError(f"Not a directory: {slides_dir}")

    # Determine allowed extensions
    if format_filter:
        extensions = FORMAT_EXT_MAP.get(format_filter, WSI_EXTENSIONS)
    else:
        extensions = WSI_EXTENSIONS

    # Collect files (sorted for deterministic order)
    files: list[Path] = []
    for root, _, filenames in os.walk(slides_dir):
        for fname in sorted(filenames):
            fpath = Path(root) / fname
            if fpath.is_symlink():
                logger.warning("Skipping symlinked file: %s", fpath.name)
                continue
            if fpath.suffix.lower() in extensions:
                files.append(fpath)
    files.sort()

    total = len(files)
    results: dict[str, StainClassification] = {}

    for i, filepath in enumerate(files):
        classification = classify_slide(filepath)

        # Determine key
        if use_filenames:
            key = filepath.name
        else:
            try:
                key = _compute_file_hash(filepath)
            except OSError as exc:
                logger.warning("Cannot hash %s: %s", filepath.name, exc)
                classification.error = f"hash_failed: {type(exc).__name__}"
                key = f"unhashed_{i}"

        results[key] = classification

        if progress_callback:
            progress_callback(i + 1, total, filepath, classification)

    return results


def export_classifications(
    results: dict[str, StainClassification],
    output_path: Path,
    format: str = "json",
) -> None:
    """Write sanitized classification results to JSON or CSV.

    All fields undergo a final PHI safety check before writing.  Any
    field that triggers a PHI pattern is replaced with an empty string
    in the output.

    Args:
        results: Dict from ``classify_batch`` mapping identifiers to
            ``StainClassification`` objects.
        output_path: Destination file path.
        format: Output format -- ``"json"`` or ``"csv"``.

    Raises:
        ValueError: If format is not ``"json"`` or ``"csv"``.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Build sanitized records
    records: dict[str, dict] = {}
    for key, classification in results.items():
        # Sanitize the key itself (could be a filename with PHI)
        safe_key = _sanitize_field(key) if not _is_hex_hash(key) else key
        if not safe_key:
            safe_key = f"redacted_{hashlib.sha256(key.encode()).hexdigest()[:12]}"

        record = {
            "stain_type": classification.stain_type,
            "stain_name": _sanitize_field(classification.stain_name),
            "stain_code": _sanitize_field(classification.stain_code),
            "confidence": round(classification.confidence, 4),
            "label_format": classification.label_format,
        }
        # Include error only if present (never contains PHI -- it is
        # built from controlled string literals in classify_slide)
        if classification.error:
            record["error"] = classification.error

        records[safe_key] = record

    if format == "json":
        with open(str(output_path), "w", encoding="utf-8") as f:
            json.dump(records, f, indent=2, ensure_ascii=False)
        logger.info("Wrote %d classifications to %s", len(records), output_path)

    elif format == "csv":
        import csv

        fieldnames = [
            "identifier",
            "stain_type",
            "stain_name",
            "stain_code",
            "confidence",
            "label_format",
            "error",
        ]
        with open(str(output_path), "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for identifier, record in records.items():
                row = {"identifier": identifier, **record}
                # Ensure all fieldnames are present
                for fn in fieldnames:
                    row.setdefault(fn, "")
                writer.writerow(row)
        logger.info("Wrote %d classifications to %s", len(records), output_path)

    else:
        raise ValueError(f"Unsupported export format: {format!r}. Use 'json' or 'csv'.")
