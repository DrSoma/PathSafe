"""PHI detection engine — regex patterns and tag scanning.

Provides configurable pattern sets for detecting Protected Health Information
in WSI file headers and metadata.
"""

import re
from typing import List, Tuple

# PHI regex patterns for binary scanning: (compiled_pattern, label)
# These are applied to raw file bytes.
#
# Covers common hospital accession formats:
#   AS-YY-NNNNN  (MUHC surgical pathology)
#   AC-YY-NNNNN  (MUHC cytology)
#   SP-YY-NNNNN  (generic surgical pathology)
#   H-YY-NNNNN   (histology)
#   S-YY-NNNNN   (surgical)
#   CH12345       (CHUM-style)
#   00000AS12345  (padded barcodes)
PHI_BYTE_PATTERNS: List[Tuple[re.Pattern, str]] = [
    (re.compile(rb'AS-\d\d-\d{3,}'), 'Accession_AS'),
    (re.compile(rb'AC-\d\d-\d{3,}'), 'Accession_AC'),
    (re.compile(rb'SP-\d\d-\d{3,}'), 'Accession_SP'),
    (re.compile(rb'(?<![A-Z])H-\d\d-\d{3,}'), 'Accession_H'),
    (re.compile(rb'(?<![A-Z])S-\d\d-\d{3,}'), 'Accession_S'),
    (re.compile(rb'CH\d{5,}'), 'Accession_CH'),
    (re.compile(rb'00000AS\d+'), 'Accession_Padded'),
    # SSN pattern (unlikely in WSI but HIPAA safe harbor identifier)
    (re.compile(rb'(?<!\d)\d{3}-\d{2}-\d{4}(?!\d)'), 'SSN_Pattern'),
]

# Date patterns (byte-level) — these match TIFF DateTime format and variants.
# Excluded: dates containing 1900:01:01 or 0000:00:00 (already anonymized).
DATE_BYTE_PATTERNS: List[Tuple[re.Pattern, str]] = [
    (re.compile(rb'(?:19|20)\d{2}:\d{2}:\d{2} \d{2}:\d{2}:\d{2}'), 'DateTime_TIFF'),
]

# PHI patterns for string-level scanning of tag values
PHI_STRING_PATTERNS: List[Tuple[re.Pattern, str]] = [
    (re.compile(r'AS-\d\d-\d{3,}'), 'Accession_AS'),
    (re.compile(r'AC-\d\d-\d{3,}'), 'Accession_AC'),
    (re.compile(r'SP-\d\d-\d{3,}'), 'Accession_SP'),
    (re.compile(r'(?<![A-Z])H-\d\d-\d{3,}'), 'Accession_H'),
    (re.compile(r'(?<![A-Z])S-\d\d-\d{3,}'), 'Accession_S'),
    (re.compile(r'CH\d{5,}'), 'Accession_CH'),
    (re.compile(r'00000AS\d+'), 'Accession_Padded'),
    (re.compile(r'(?<!\d)\d{3}-\d{2}-\d{4}(?!\d)'), 'SSN_Pattern'),
]

# Anonymized date sentinel — dates that have already been zeroed
ANONYMIZED_DATE_SENTINEL = b'1900:01:01 00:00:00'

# Default header scan size for regex safety scan (256KB)
DEFAULT_SCAN_SIZE = 256_000


def scan_bytes_for_phi(data: bytes,
                       skip_offsets: set = None) -> List[Tuple[int, int, bytes, str]]:
    """Scan raw bytes for PHI patterns.

    Args:
        data: Raw bytes to scan.
        skip_offsets: Set of offsets to skip (already handled by tag processing).

    Returns:
        List of (offset, length, matched_bytes, pattern_label) tuples.
    """
    if skip_offsets is None:
        skip_offsets = set()

    findings = []

    for pattern, label in PHI_BYTE_PATTERNS:
        for m in pattern.finditer(data):
            if m.start() in skip_offsets:
                continue
            # Extend match to null terminator if present
            try:
                end = data.index(b'\x00', m.start())
            except ValueError:
                end = m.end()
            matched = data[m.start():end]
            # Skip if already anonymized (all X's)
            if matched == b'X' * len(matched):
                continue
            findings.append((m.start(), len(matched), matched, label))

    return findings


def scan_string_for_phi(value: str) -> List[Tuple[int, int, str, str]]:
    """Scan a string value for PHI patterns.

    Returns:
        List of (char_offset, length, matched_text, pattern_label) tuples.
    """
    findings = []
    for pattern, label in PHI_STRING_PATTERNS:
        for m in pattern.finditer(value):
            findings.append((m.start(), len(m.group()), m.group(), label))
    return findings


def scan_bytes_for_dates(data: bytes) -> List[Tuple[int, int, bytes, str]]:
    """Scan raw bytes for date patterns that may constitute PHI.

    Skips already-anonymized dates (1900:01:01).

    Returns:
        List of (offset, length, matched_bytes, pattern_label) tuples.
    """
    findings = []
    for pattern, label in DATE_BYTE_PATTERNS:
        for m in pattern.finditer(data):
            matched = m.group()
            if b'1900:01:01' in matched or b'0000:00:00' in matched:
                continue
            findings.append((m.start(), len(matched), matched, label))
    return findings


def is_date_anonymized(value: str) -> bool:
    """Check if a date string has already been anonymized."""
    return '1900:01:01' in value or '0000:00:00' in value or value.strip('\x00 ') == ''


def scan_file(filepath, handler=None):
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
    from pathlib import Path

    filepath = Path(filepath)
    if handler is None:
        handler = get_handler(filepath)
    return handler.scan(filepath)
