"""PHI detection engine -- regex patterns and tag scanning.

Provides configurable pattern sets for detecting Protected Health Information
in WSI file headers and metadata.
"""

from __future__ import annotations

import json
import logging
import re


logger = logging.getLogger(__name__)
from dataclasses import dataclass, field  # noqa: E402
from pathlib import Path  # noqa: E402
from typing import TYPE_CHECKING  # noqa: E402


if TYPE_CHECKING:
    from pathsafe.formats.base import FormatHandler
    from pathsafe.models import ScanResult

# PHI regex patterns for binary scanning: (compiled_pattern, label)
# These are applied to raw file bytes.
#
# Covers common hospital accession formats:
#   AS-YY-NNNNN  (surgical pathology)
#   AC-YY-NNNNN  (cytology)
#   SP-YY-NNNNN  (generic surgical pathology)
#   AP-YY-NNNNN  (anatomic pathology)
#   CY-YY-NNNNN  (cytology)
#   H-YY-NNNNN   (histology)
#   S-YY-NNNNN   (surgical)
#   XX-YYYY-NNNNN (4-digit year variants)
#   CH12345       (CHUM-style)
#   00000AS12345  (padded barcodes)
#   MRN-12345678  (medical record numbers)
#   DOB-19800115  (date of birth in filenames)
PHI_BYTE_PATTERNS: list[tuple[re.Pattern, str]] = [
    # 2-digit year formats: XX-YY-NNNNN
    (re.compile(rb"AS-\d\d-\d{3,}"), "Accession_AS"),
    (re.compile(rb"AC-\d\d-\d{3,}"), "Accession_AC"),
    (re.compile(rb"SP-\d\d-\d{3,}"), "Accession_SP"),
    (re.compile(rb"AP-\d\d-\d{3,}"), "Accession_AP"),
    (re.compile(rb"CY-\d\d-\d{3,}"), "Accession_CY"),
    (re.compile(rb"(?<![A-Z])H-\d\d-\d{3,}"), "Accession_H"),
    (re.compile(rb"(?<![A-Z])S-\d\d-\d{3,}"), "Accession_S"),
    # 4-digit year formats: XX-YYYY-NNNNN
    (re.compile(rb"AS-(?:19|20)\d{2}-\d{3,}"), "Accession_AS4"),
    (re.compile(rb"AC-(?:19|20)\d{2}-\d{3,}"), "Accession_AC4"),
    (re.compile(rb"SP-(?:19|20)\d{2}-\d{3,}"), "Accession_SP4"),
    (re.compile(rb"AP-(?:19|20)\d{2}-\d{3,}"), "Accession_AP4"),
    (re.compile(rb"CY-(?:19|20)\d{2}-\d{3,}"), "Accession_CY4"),
    # Institutional/legacy formats
    (re.compile(rb"CH\d{5,}"), "Accession_CH"),
    (re.compile(rb"00000AS\d+"), "Accession_Padded"),
    # Medical Record Number
    (re.compile(rb"MRN[-:# ]?\d{5,}"), "MRN_Pattern"),
    # SSN pattern (unlikely in WSI but HIPAA safe harbor identifier)
    (re.compile(rb"(?<!\d)\d{3}-\d{2}-\d{4}(?!\d)"), "SSN_Pattern"),
    # Date of birth in filenames/metadata
    (re.compile(rb"DOB[-_:# ]?(?:19|20)\d{2}[-/]?\d{2}[-/]?\d{2}"), "DOB_Pattern"),
]

# Date patterns (byte-level) -- these match common date formats in metadata.
# Excluded: dates containing 1900:01:01 or 0000:00:00 (already anonymized).
DATE_BYTE_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(rb"(?:19|20)\d{2}:\d{2}:\d{2} \d{2}:\d{2}:\d{2}"), "DateTime_TIFF"),
    (re.compile(rb"(?:19|20)\d{2}/\d{2}/\d{2}"), "DateTime_Slash"),
    (re.compile(rb"(?:19|20)\d{2}-\d{2}-\d{2}"), "DateTime_ISO"),
]

# PHI patterns for string-level scanning of tag values
PHI_STRING_PATTERNS: list[tuple[re.Pattern, str]] = [
    # 2-digit year formats
    (re.compile(r"AS-\d\d-\d{3,}"), "Accession_AS"),
    (re.compile(r"AC-\d\d-\d{3,}"), "Accession_AC"),
    (re.compile(r"SP-\d\d-\d{3,}"), "Accession_SP"),
    (re.compile(r"AP-\d\d-\d{3,}"), "Accession_AP"),
    (re.compile(r"CY-\d\d-\d{3,}"), "Accession_CY"),
    (re.compile(r"(?<![A-Z])H-\d\d-\d{3,}"), "Accession_H"),
    (re.compile(r"(?<![A-Z])S-\d\d-\d{3,}"), "Accession_S"),
    # 4-digit year formats
    (re.compile(r"AS-(?:19|20)\d{2}-\d{3,}"), "Accession_AS4"),
    (re.compile(r"AC-(?:19|20)\d{2}-\d{3,}"), "Accession_AC4"),
    (re.compile(r"SP-(?:19|20)\d{2}-\d{3,}"), "Accession_SP4"),
    (re.compile(r"AP-(?:19|20)\d{2}-\d{3,}"), "Accession_AP4"),
    (re.compile(r"CY-(?:19|20)\d{2}-\d{3,}"), "Accession_CY4"),
    # Institutional/legacy formats
    (re.compile(r"CH\d{5,}"), "Accession_CH"),
    (re.compile(r"00000AS\d+"), "Accession_Padded"),
    # Medical Record Number
    (re.compile(r"MRN[-:# ]?\d{5,}"), "MRN_Pattern"),
    (re.compile(r"(?<!\d)\d{3}-\d{2}-\d{4}(?!\d)"), "SSN_Pattern"),
    # Date of birth in filenames/metadata
    (re.compile(r"DOB[-_:# ]?(?:19|20)\d{2}[-/]?\d{2}[-/]?\d{2}"), "DOB_Pattern"),
]

# Anonymized date sentinel -- dates that have already been zeroed
ANONYMIZED_DATE_SENTINEL = b"1900:01:01 00:00:00"

# Default header scan size for regex safety scan (1MB)
DEFAULT_SCAN_SIZE = 1_000_000


@dataclass
class PatternConfig:
    """Configurable PHI pattern sets.

    Allows adding institution-specific patterns without modifying source code.
    All three fields hold lists of (compiled_pattern, label) tuples.
    """

    byte_patterns: list[tuple[re.Pattern, str]] = field(default_factory=list)
    string_patterns: list[tuple[re.Pattern, str]] = field(default_factory=list)
    date_byte_patterns: list[tuple[re.Pattern, str]] = field(default_factory=list)

    @classmethod
    def default(cls) -> PatternConfig:
        """Return the built-in default pattern set."""
        return cls(
            byte_patterns=list(PHI_BYTE_PATTERNS),
            string_patterns=list(PHI_STRING_PATTERNS),
            date_byte_patterns=list(DATE_BYTE_PATTERNS),
        )

    @classmethod
    def from_json(cls, path: str | Path) -> PatternConfig:
        """Load patterns from a JSON file and merge with defaults.

        JSON format::

            {
                "byte_patterns": [["PATTERN", "Label"], ...],
                "string_patterns": [["PATTERN", "Label"], ...],
                "date_byte_patterns": [["PATTERN", "Label"], ...],
            }

        All three keys are optional; omitted keys inherit built-in defaults.
        Patterns in the JSON are *appended* to defaults, not replacing them.

        **ReDoS mitigation**: each user-supplied pattern is compiled and
        tested against a short probe string before being accepted.
        Patterns that fail to compile or that exceed a reasonable source
        length are skipped with a warning.
        """
        with open(str(path)) as f:
            data = json.load(f)

        config = cls.default()

        # Maximum allowed regex source length.  Very long patterns with
        # nested quantifiers (e.g., ``(a+)+$``) can cause catastrophic
        # backtracking (ReDoS).  A 500-char cap is generous for any
        # realistic accession/MRN pattern while blocking abuse.
        _MAX_PATTERN_LEN = 500

        for raw_pat, label in data.get("byte_patterns", []):
            compiled = _safe_compile(raw_pat.encode(), label, _MAX_PATTERN_LEN)
            if compiled is not None:
                config.byte_patterns.append((compiled, label))
        for raw_pat, label in data.get("string_patterns", []):
            compiled = _safe_compile(raw_pat, label, _MAX_PATTERN_LEN)
            if compiled is not None:
                config.string_patterns.append((compiled, label))
        for raw_pat, label in data.get("date_byte_patterns", []):
            compiled = _safe_compile(raw_pat.encode(), label, _MAX_PATTERN_LEN)
            if compiled is not None:
                config.date_byte_patterns.append((compiled, label))

        return config


def _safe_compile(
    pattern: str | bytes,
    label: str,
    max_len: int,
) -> re.Pattern | None:
    """Compile a regex pattern with safety checks.

    Returns the compiled pattern, or None if:
    - The pattern source exceeds *max_len* (ReDoS risk from complex
      nested quantifiers grows with pattern length).
    - The pattern fails to compile (``re.error``).
    - The pattern takes unreasonably long on a short test string
      (basic sanity -- Python's ``re`` module does not support
      per-match timeouts, but a compile + trivial match on a short
      string catches obvious syntax errors).
    """
    if len(pattern) > max_len:
        logger.warning(
            "Skipping custom pattern '%s' (label=%s): exceeds %d-char limit",
            pattern[:60],
            label,
            max_len,
        )
        return None
    try:
        compiled = re.compile(pattern)
    except re.error as exc:
        logger.warning(
            "Skipping invalid custom pattern '%s' (label=%s): %s",
            pattern[:60],
            label,
            exc,
        )
        return None
    # Quick sanity match against a short benign string to confirm it
    # does not hang.  This does NOT fully prevent ReDoS but catches
    # patterns that explode on trivial input.
    try:
        compiled.search("AAAA-00-00000" if isinstance(pattern, str) else b"AAAA-00-00000")
    except Exception as exc:
        logger.warning(
            "Skipping custom pattern '%s' (label=%s): test match failed: %s",
            pattern[:60],
            label,
            exc,
        )
        return None
    return compiled


def scan_bytes_for_phi(
    data: bytes, skip_offsets: set[int] | None = None, patterns: PatternConfig | None = None
) -> list[tuple[int, int, bytes, str]]:
    """Scan raw bytes for PHI patterns.

    Args:
        data: Raw bytes to scan.
        skip_offsets: Set of offsets to skip (already handled by tag processing).
        patterns: Optional custom pattern config. None uses built-in defaults.

    Returns:
        List of (offset, length, matched_bytes, pattern_label) tuples.
    """
    if skip_offsets is None:
        skip_offsets = set()

    pat_list = patterns.byte_patterns if patterns is not None else PHI_BYTE_PATTERNS
    findings = []

    for pattern, label in pat_list:
        for m in pattern.finditer(data):
            if m.start() in skip_offsets:
                continue
            # Extend match to null terminator if present
            try:
                end = data.index(b"\x00", m.start())
            except ValueError:
                end = m.end()
            matched = data[m.start() : end]
            # Skip if already anonymized (all X's)
            if matched == b"X" * len(matched):
                continue
            findings.append((m.start(), len(matched), matched, label))

    return findings


def scan_string_for_phi(
    value: str, patterns: PatternConfig | None = None
) -> list[tuple[int, int, str, str]]:
    """Scan a string value for PHI patterns.

    Args:
        value: String to scan.
        patterns: Optional custom pattern config. None uses built-in defaults.

    Returns:
        List of (char_offset, length, matched_text, pattern_label) tuples.
    """
    pat_list = patterns.string_patterns if patterns is not None else PHI_STRING_PATTERNS
    findings = []
    for pattern, label in pat_list:
        for m in pattern.finditer(value):
            findings.append((m.start(), len(m.group()), m.group(), label))
    return findings


def scan_bytes_for_dates(
    data: bytes, patterns: PatternConfig | None = None
) -> list[tuple[int, int, bytes, str]]:
    """Scan raw bytes for date patterns that may constitute PHI.

    Skips already-anonymized dates (1900:01:01, 1900/01/01, 1900-01-01).

    Args:
        data: Raw bytes to scan.
        patterns: Optional custom pattern config. None uses built-in defaults.

    Returns:
        List of (offset, length, matched_bytes, pattern_label) tuples.
    """
    pat_list = patterns.date_byte_patterns if patterns is not None else DATE_BYTE_PATTERNS
    findings = []
    for pattern, label in pat_list:
        for m in pattern.finditer(data):
            matched = m.group()
            if (
                b"1900:01:01" in matched
                or b"0000:00:00" in matched
                or b"1900/01/01" in matched
                or b"1900-01-01" in matched
            ):
                continue
            findings.append((m.start(), len(matched), matched, label))
    return findings


def is_date_anonymized(value: str) -> bool:
    """Check if a date string has already been anonymized."""
    return "1900:01:01" in value or "0000:00:00" in value or value.strip("\x00 ") == ""


def scan_filename_for_phi(filepath: Path) -> list[tuple[int, int, str, str]]:
    """Scan a filename (stem only, no extension) for PHI patterns.

    Filenames like 'AS-24-123456_slide1.ndpi' contain accession numbers.
    This is a Level I anonymization concern (Bisson et al., 2023).

    Returns:
        List of (char_offset, length, matched_text, pattern_label) tuples.
    """
    from pathlib import Path

    stem = Path(filepath).stem
    return scan_string_for_phi(stem)


def scan_file(filepath: Path, handler: FormatHandler | None = None) -> ScanResult:
    """Scan a single file for PHI using the appropriate format handler.

    This is a convenience function that auto-detects format and delegates
    to the correct handler.

    Args:
        filepath: Path to the file to scan.
        handler: Optional format handler override.

    Returns:
        ScanResult from the handler.
    """
    from pathsafe.formats import get_handler

    filepath = Path(filepath)
    if handler is None:
        handler = get_handler(filepath)
    return handler.scan(filepath)
