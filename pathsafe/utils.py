"""Shared utility functions for PathSafe.

Security-focused helpers used across the anonymizer, format handlers,
and converter modules.
"""

from __future__ import annotations

import re


# Substrings in exception messages that commonly precede embedded PHI
# (e.g., pydicom decoding patient names, struct unpacking tag values).
_PHI_MARKERS = re.compile(
    r"\b(?:patient|name|accession|mrn|dob|ssn|birth|person|address|phone|physician|institution|identifier)\b",
    re.IGNORECASE,
)

# Maximum length for the safe portion of an error message
_MAX_SAFE_MSG_LEN = 100


def _safe_msg(raw: str) -> str:
    """Truncate an exception message and strip content after PHI markers.

    Exception text from pydicom, struct, or XML parsers can embed raw
    tag values that contain patient names, accession numbers, or dates.
    This function removes everything after the first PHI-related keyword
    and caps the total length.
    """
    # Strip content from the first PHI marker onward
    m = _PHI_MARKERS.search(raw)
    if m:
        raw = raw[: m.start()].rstrip(" :=-")

    if len(raw) > _MAX_SAFE_MSG_LEN:
        raw = raw[:_MAX_SAFE_MSG_LEN] + "..."

    return raw


def _sanitize_error(e: Exception) -> str:
    """Return a sanitized error string safe for logs and result objects.

    Combines the exception class name with a truncated, PHI-stripped
    message.  Never expose the full ``str(e)`` to callers -- pydicom
    and struct exceptions routinely embed raw tag values that can
    contain patient identifiers.
    """
    return f"{type(e).__name__}: {_safe_msg(str(e))}"
