"""PathSafe — Hospital-grade WSI anonymizer for pathology slide files."""

__version__ = "1.0.0"

from pathsafe.models import (
    AnonymizationResult,
    BatchResult,
    PHIFinding,
    ScanResult,
)
from pathsafe.anonymizer import anonymize_file, anonymize_batch
from pathsafe.scanner import scan_file
from pathsafe.verify import verify_file, verify_batch
from pathsafe.report import generate_certificate

__all__ = [
    "__version__",
    "PHIFinding",
    "ScanResult",
    "AnonymizationResult",
    "BatchResult",
    "anonymize_file",
    "anonymize_batch",
    "scan_file",
    "verify_file",
    "verify_batch",
    "generate_certificate",
]
