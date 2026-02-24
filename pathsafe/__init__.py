"""PathSafe -- Production-tested WSI anonymizer for pathology slide files."""

__version__ = "1.0.0"

from pathsafe.models import (
    AnonymizationResult,
    BatchResult,
    ConversionBatchResult,
    ConversionResult,
    PHIFinding,
    ScanResult,
)
from pathsafe.anonymizer import anonymize_file, anonymize_batch
from pathsafe.scanner import scan_file
from pathsafe.verify import verify_file, verify_batch
from pathsafe.report import generate_certificate, generate_pdf_certificate, generate_scan_report

# Lazy imports for optional conversion module
def convert_file(*args, **kwargs):
    from pathsafe.converter import convert_file as _convert_file
    return _convert_file(*args, **kwargs)

def convert_batch(*args, **kwargs):
    from pathsafe.converter import convert_batch as _convert_batch
    return _convert_batch(*args, **kwargs)

__all__ = [
    "__version__",
    "PHIFinding",
    "ScanResult",
    "AnonymizationResult",
    "BatchResult",
    "ConversionResult",
    "ConversionBatchResult",
    "anonymize_file",
    "anonymize_batch",
    "scan_file",
    "verify_file",
    "verify_batch",
    "generate_certificate",
    "generate_pdf_certificate",
    "generate_scan_report",
    "convert_file",
    "convert_batch",
]
