"""PHI detection engine -- regex patterns and tag scanning.

Provides configurable pattern sets for detecting Protected Health Information
in WSI file headers and metadata.
"""

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

# PHI regex patterns for binary scanning: (compiled_pattern, label)
# These are applied to raw file bytes.
#
# Covers common hospital accession formats:
#   AS-YY-NNNNN  (MUHC surgical pathology)
#   AC-YY-NNNNN  (MUHC cytology)
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
PHI_BYTE_PATTERNS: List[Tuple[re.Pattern, str]] = [
    # 2-digit year formats: XX-YY-NNNNN
    (re.compile(rb'AS-\d\d-\d{3,}'), 'Accession_AS'),
    (re.compile(rb'AC-\d\d-\d{3,}'), 'Accession_AC'),
    (re.compile(rb'SP-\d\d-\d{3,}'), 'Accession_SP'),
    (re.compile(rb'AP-\d\d-\d{3,}'), 'Accession_AP'),
    (re.compile(rb'CY-\d\d-\d{3,}'), 'Accession_CY'),
    (re.compile(rb'(?<![A-Z])H-\d\d-\d{3,}'), 'Accession_H'),
    (re.compile(rb'(?<![A-Z])S-\d\d-\d{3,}'), 'Accession_S'),
    # 4-digit year formats: XX-YYYY-NNNNN
    (re.compile(rb'AS-(?:19|20)\d{2}-\d{3,}'), 'Accession_AS4'),
    (re.compile(rb'AC-(?:19|20)\d{2}-\d{3,}'), 'Accession_AC4'),
    (re.compile(rb'SP-(?:19|20)\d{2}-\d{3,}'), 'Accession_SP4'),
    (re.compile(rb'AP-(?:19|20)\d{2}-\d{3,}'), 'Accession_AP4'),
    (re.compile(rb'CY-(?:19|20)\d{2}-\d{3,}'), 'Accession_CY4'),
    # Institutional/legacy formats
    (re.compile(rb'CH\d{5,}'), 'Accession_CH'),
    (re.compile(rb'00000AS\d+'), 'Accession_Padded'),
    # Medical Record Number
    (re.compile(rb'MRN[-:# ]?\d{5,}'), 'MRN_Pattern'),
    # SSN pattern (unlikely in WSI but HIPAA safe harbor identifier)
    (re.compile(rb'(?<!\d)\d{3}-\d{2}-\d{4}(?!\d)'), 'SSN_Pattern'),
    # Date of birth in filenames/metadata
    (re.compile(rb'DOB[-_:# ]?(?:19|20)\d{2}[-/]?\d{2}[-/]?\d{2}'), 'DOB_Pattern'),
]

# Date patterns (byte-level) -- these match common date formats in metadata.
# Excluded: dates containing 1900:01:01 or 0000:00:00 (already anonymized).
DATE_BYTE_PATTERNS: List[Tuple[re.Pattern, str]] = [
    (re.compile(rb'(?:19|20)\d{2}:\d{2}:\d{2} \d{2}:\d{2}:\d{2}'), 'DateTime_TIFF'),
    (re.compile(rb'(?:19|20)\d{2}/\d{2}/\d{2}'), 'DateTime_Slash'),
    (re.compile(rb'(?:19|20)\d{2}-\d{2}-\d{2}'), 'DateTime_ISO'),
]

# PHI patterns for string-level scanning of tag values
PHI_STRING_PATTERNS: List[Tuple[re.Pattern, str]] = [
    # 2-digit year formats
    (re.compile(r'AS-\d\d-\d{3,}'), 'Accession_AS'),
    (re.compile(r'AC-\d\d-\d{3,}'), 'Accession_AC'),
    (re.compile(r'SP-\d\d-\d{3,}'), 'Accession_SP'),
    (re.compile(r'AP-\d\d-\d{3,}'), 'Accession_AP'),
    (re.compile(r'CY-\d\d-\d{3,}'), 'Accession_CY'),
    (re.compile(r'(?<![A-Z])H-\d\d-\d{3,}'), 'Accession_H'),
    (re.compile(r'(?<![A-Z])S-\d\d-\d{3,}'), 'Accession_S'),
    # 4-digit year formats
    (re.compile(r'AS-(?:19|20)\d{2}-\d{3,}'), 'Accession_AS4'),
    (re.compile(r'AC-(?:19|20)\d{2}-\d{3,}'), 'Accession_AC4'),
    (re.compile(r'SP-(?:19|20)\d{2}-\d{3,}'), 'Accession_SP4'),
    (re.compile(r'AP-(?:19|20)\d{2}-\d{3,}'), 'Accession_AP4'),
    (re.compile(r'CY-(?:19|20)\d{2}-\d{3,}'), 'Accession_CY4'),
    # Institutional/legacy formats
    (re.compile(r'CH\d{5,}'), 'Accession_CH'),
    (re.compile(r'00000AS\d+'), 'Accession_Padded'),
    # Medical Record Number
    (re.compile(r'MRN[-:# ]?\d{5,}'), 'MRN_Pattern'),
    (re.compile(r'(?<!\d)\d{3}-\d{2}-\d{4}(?!\d)'), 'SSN_Pattern'),
    # Date of birth in filenames/metadata
    (re.compile(r'DOB[-_:# ]?(?:19|20)\d{2}[-/]?\d{2}[-/]?\d{2}'), 'DOB_Pattern'),
]

# Anonymized date sentinel -- dates that have already been zeroed
ANONYMIZED_DATE_SENTINEL = b'1900:01:01 00:00:00'

# Default header scan size for regex safety scan (1MB)
DEFAULT_SCAN_SIZE = 1_000_000


@dataclass
class PatternConfig:
    """Configurable PHI pattern sets.

    Allows adding institution-specific patterns without modifying source code.
    All three fields hold lists of (compiled_pattern, label) tuples.
    """

    byte_patterns: List[Tuple[re.Pattern, str]] = field(default_factory=list)
    string_patterns: List[Tuple[re.Pattern, str]] = field(default_factory=list)
    date_byte_patterns: List[Tuple[re.Pattern, str]] = field(default_factory=list)

    @classmethod
    def default(cls) -> 'PatternConfig':
        """Return the built-in default pattern set."""
        return cls(
            byte_patterns=list(PHI_BYTE_PATTERNS),
            string_patterns=list(PHI_STRING_PATTERNS),
            date_byte_patterns=list(DATE_BYTE_PATTERNS),
        )

    @classmethod
    def from_json(cls, path) -> 'PatternConfig':
        """Load patterns from a JSON file and merge with defaults.

        JSON format::

            {
              "byte_patterns": [["PATTERN", "Label"], ...],
              "string_patterns": [["PATTERN", "Label"], ...],
              "date_byte_patterns": [["PATTERN", "Label"], ...]
            }

        All three keys are optional; omitted keys inherit built-in defaults.
        Patterns in the JSON are *appended* to defaults, not replacing them.
        """
        with open(str(path), 'r') as f:
            data = json.load(f)

        config = cls.default()

        for raw_pat, label in data.get('byte_patterns', []):
            config.byte_patterns.append((re.compile(raw_pat.encode()), label))
        for raw_pat, label in data.get('string_patterns', []):
            config.string_patterns.append((re.compile(raw_pat), label))
        for raw_pat, label in data.get('date_byte_patterns', []):
            config.date_byte_patterns.append((re.compile(raw_pat.encode()), label))

        return config


def scan_bytes_for_phi(data: bytes,
                       skip_offsets: set = None,
                       patterns: Optional[PatternConfig] = None) -> List[Tuple[int, int, bytes, str]]:
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
                end = data.index(b'\x00', m.start())
            except ValueError:
                end = m.end()
            matched = data[m.start():end]
            # Skip if already anonymized (all X's)
            if matched == b'X' * len(matched):
                continue
            findings.append((m.start(), len(matched), matched, label))

    return findings


def scan_string_for_phi(value: str,
                        patterns: Optional[PatternConfig] = None) -> List[Tuple[int, int, str, str]]:
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


def scan_bytes_for_dates(data: bytes,
                         patterns: Optional[PatternConfig] = None) -> List[Tuple[int, int, bytes, str]]:
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
            if (b'1900:01:01' in matched or b'0000:00:00' in matched
                    or b'1900/01/01' in matched or b'1900-01-01' in matched):
                continue
            findings.append((m.start(), len(matched), matched, label))
    return findings


def is_date_anonymized(value: str) -> bool:
    """Check if a date string has already been anonymized."""
    return '1900:01:01' in value or '0000:00:00' in value or value.strip('\x00 ') == ''


def scan_filename_for_phi(filepath: Path) -> List[Tuple[int, int, str, str]]:
    """Scan a filename (stem only, no extension) for PHI patterns.

    Filenames like 'AS-24-123456_slide1.ndpi' contain accession numbers.
    This is a Level I anonymization concern (Bisson et al., 2023).

    Returns:
        List of (char_offset, length, matched_text, pattern_label) tuples.
    """
    from pathlib import Path
    stem = Path(filepath).stem
    return scan_string_for_phi(stem)


def scan_file(filepath: Path, handler: Optional[object] = None):
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
