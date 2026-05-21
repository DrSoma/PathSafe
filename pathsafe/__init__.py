"""PathSafe -- WSI de-identifier for pathology slide files."""

from __future__ import annotations

from typing import Any


__version__ = "2.0.2"

from pathsafe.deidentifier import deidentify_batch, deidentify_file
from pathsafe.models import (
    BatchResult,
    ConversionBatchResult,
    ConversionResult,
    DeidentificationResult,
    PHIFinding,
    PreflightResult,
    ScanResult,
)
from pathsafe.scanner import scan_file
from pathsafe.verify import verify_batch, verify_file


# Lazy imports for optional report module (avoids hard fpdf2 dependency)
def generate_certificate(*args: Any, **kwargs: Any) -> Any:
    from pathsafe.report import generate_certificate as _generate_certificate

    return _generate_certificate(*args, **kwargs)


def generate_pdf_certificate(*args: Any, **kwargs: Any) -> Any:
    from pathsafe.report import generate_pdf_certificate as _generate_pdf_certificate

    return _generate_pdf_certificate(*args, **kwargs)


def generate_scan_report(*args: Any, **kwargs: Any) -> Any:
    from pathsafe.report import generate_scan_report as _generate_scan_report

    return _generate_scan_report(*args, **kwargs)


# Lazy imports for optional conversion module
def convert_file(*args: Any, **kwargs: Any) -> Any:
    from pathsafe.converter import convert_file as _convert_file

    return _convert_file(*args, **kwargs)


def convert_batch(*args: Any, **kwargs: Any) -> Any:
    from pathsafe.converter import convert_batch as _convert_batch

    return _convert_batch(*args, **kwargs)


# Lazy imports for optional classifier module
def classify_slide(*args: Any, **kwargs: Any) -> Any:
    from pathsafe.classifier import classify_slide as _classify_slide

    return _classify_slide(*args, **kwargs)


def classify_batch(*args: Any, **kwargs: Any) -> Any:
    from pathsafe.classifier import classify_batch as _classify_batch

    return _classify_batch(*args, **kwargs)


# Lazy imports for optional transfer module
def transfer_batch(*args: Any, **kwargs: Any) -> Any:
    from pathsafe.transfer import transfer_batch as _transfer_batch

    return _transfer_batch(*args, **kwargs)


# Lazy imports for optional pipeline module
def run_pipeline(*args: Any, **kwargs: Any) -> Any:
    from pathsafe.pipeline_runner import run_pipeline as _run_pipeline

    return _run_pipeline(*args, **kwargs)


__all__ = [
    "__version__",
    "PHIFinding",
    "ScanResult",
    "DeidentificationResult",
    "BatchResult",
    "PreflightResult",
    "ConversionResult",
    "ConversionBatchResult",
    "deidentify_file",
    "deidentify_batch",
    "scan_file",
    "verify_file",
    "verify_batch",
    "generate_certificate",
    "generate_pdf_certificate",
    "generate_scan_report",
    "convert_file",
    "convert_batch",
    "classify_slide",
    "classify_batch",
    "transfer_batch",
    "run_pipeline",
]
