"""3DHISTECH MRXS (MIRAX) format handler.

Handles PHI detection and anonymization for MRXS files, including:
- Slidedat.ini metadata: SLIDE_ID, SLIDE_NAME, SLIDE_BARCODE,
  SLIDE_CREATIONDATETIME, and other PHI fields in the [GENERAL] section
- Regex safety scan of Slidedat.ini for accession patterns

MRXS structure:
  slide.mrxs              <- index file (may contain some metadata)
  slide/                  <- companion data directory
    Slidedat.ini          <- main metadata (INI format)
    Index.dat             <- tile index
    Data00000.dat, ...    <- tile data files
"""

import configparser
import os
import re
import time
from pathlib import Path
from typing import Dict, List, Optional

from pathsafe.formats.base import FormatHandler
from pathsafe.models import PHIFinding, ScanResult
from pathsafe.scanner import scan_bytes_for_phi, scan_string_for_phi

# PHI fields in [GENERAL] section of Slidedat.ini
GENERAL_PHI_FIELDS = {
    'SLIDE_ID', 'SLIDE_NAME', 'SLIDE_BARCODE',
    'SLIDE_CREATIONDATETIME', 'SLIDE_QUALITY',
    'PROJECT_NAME', 'SLIDE_LABEL',
}

# Date/time-like field names (values replaced with sentinel)
DATE_FIELDS = {'SLIDE_CREATIONDATETIME'}


class MRXSHandler(FormatHandler):
    """Format handler for 3DHISTECH MRXS (MIRAX) files."""

    format_name = "mrxs"

    def can_handle(self, filepath: Path) -> bool:
        return filepath.suffix.lower() == '.mrxs'

    def scan(self, filepath: Path) -> ScanResult:
        """Scan MRXS file for PHI — read-only."""
        t0 = time.monotonic()
        file_size = os.path.getsize(filepath)
        findings: List[PHIFinding] = []

        try:
            data_dir = _get_data_dir(filepath)
            if data_dir is None:
                elapsed = (time.monotonic() - t0) * 1000
                return ScanResult(
                    filepath=filepath, format="mrxs", findings=[],
                    is_clean=True, scan_time_ms=elapsed,
                    file_size=file_size,
                    error="No companion data directory found",
                )

            slidedat = data_dir / 'Slidedat.ini'
            if slidedat.exists():
                findings += self._scan_slidedat(slidedat)
                findings += self._scan_slidedat_regex(slidedat)

            # Also scan the .mrxs file itself for PHI patterns
            findings += self._scan_mrxs_file(filepath)

        except Exception as e:
            elapsed = (time.monotonic() - t0) * 1000
            return ScanResult(
                filepath=filepath, format="mrxs", findings=findings,
                is_clean=len(findings) == 0, scan_time_ms=elapsed,
                file_size=file_size, error=str(e),
            )

        elapsed = (time.monotonic() - t0) * 1000
        return ScanResult(
            filepath=filepath, format="mrxs", findings=findings,
            is_clean=len(findings) == 0, scan_time_ms=elapsed,
            file_size=file_size,
        )

    def anonymize(self, filepath: Path) -> List[PHIFinding]:
        """Anonymize PHI in MRXS files in-place."""
        cleared: List[PHIFinding] = []

        data_dir = _get_data_dir(filepath)
        if data_dir is None:
            return cleared

        slidedat = data_dir / 'Slidedat.ini'
        if slidedat.exists():
            cleared += self._anonymize_slidedat(slidedat)

        # Anonymize regex patterns in the .mrxs file
        cleared += self._anonymize_mrxs_file(filepath)

        return cleared

    def get_format_info(self, filepath: Path) -> Dict:
        """Get MRXS file metadata."""
        info = {
            'format': 'mrxs',
            'filename': filepath.name,
            'file_size': os.path.getsize(filepath),
        }

        data_dir = _get_data_dir(filepath)
        if data_dir is None:
            info['error'] = 'No companion data directory found'
            return info

        info['data_directory'] = str(data_dir)

        slidedat = data_dir / 'Slidedat.ini'
        if slidedat.exists():
            try:
                config = _read_slidedat(slidedat)
                if config.has_section('GENERAL'):
                    for key in ('SLIDE_VERSION', 'SLIDE_TYPE',
                                'IMAGENUMBER_X', 'IMAGENUMBER_Y',
                                'OBJECTIVE_MAGNIFICATION'):
                        if config.has_option('GENERAL', key):
                            info[key.lower()] = config.get('GENERAL', key)

                # Count data files
                dat_files = list(data_dir.glob('Data*.dat'))
                info['data_file_count'] = len(dat_files)
                info['total_data_size'] = sum(
                    f.stat().st_size for f in dat_files)

            except Exception as e:
                info['error'] = str(e)

        return info

    # --- Internal methods ---

    def _scan_slidedat(self, slidedat_path: Path) -> List[PHIFinding]:
        """Scan Slidedat.ini [GENERAL] section for PHI fields."""
        findings = []
        config = _read_slidedat(slidedat_path)

        if not config.has_section('GENERAL'):
            return findings

        for field in GENERAL_PHI_FIELDS:
            if not config.has_option('GENERAL', field):
                continue
            value = config.get('GENERAL', field).strip()
            if not value or _is_anonymized(field, value):
                continue

            findings.append(PHIFinding(
                offset=0,
                length=len(value),
                tag_id=None,
                tag_name=f'Slidedat:{field}',
                value_preview=f'{field}={value[:50]}',
                source='ini_metadata',
            ))

        return findings

    def _scan_slidedat_regex(self, slidedat_path: Path) -> List[PHIFinding]:
        """Regex scan of entire Slidedat.ini for accession patterns."""
        data = slidedat_path.read_bytes()
        raw_findings = scan_bytes_for_phi(data)
        findings = []
        for offset, length, matched, label in raw_findings:
            value = matched.decode('ascii', errors='replace')
            findings.append(PHIFinding(
                offset=offset, length=length, tag_id=None,
                tag_name=f'regex:{label}',
                value_preview=value[:50],
                source='regex_scan',
            ))
        return findings

    def _scan_mrxs_file(self, filepath: Path) -> List[PHIFinding]:
        """Regex scan of the .mrxs file for accession patterns."""
        data = filepath.read_bytes()
        raw_findings = scan_bytes_for_phi(data)
        findings = []
        for offset, length, matched, label in raw_findings:
            value = matched.decode('ascii', errors='replace')
            findings.append(PHIFinding(
                offset=offset, length=length, tag_id=None,
                tag_name=f'regex:{label}',
                value_preview=value[:50],
                source='regex_scan',
            ))
        return findings

    def _anonymize_slidedat(self, slidedat_path: Path) -> List[PHIFinding]:
        """Anonymize PHI fields in Slidedat.ini."""
        cleared = []
        config = _read_slidedat(slidedat_path)

        if not config.has_section('GENERAL'):
            return cleared

        modified = False
        for field in GENERAL_PHI_FIELDS:
            if not config.has_option('GENERAL', field):
                continue
            value = config.get('GENERAL', field).strip()
            if not value or _is_anonymized(field, value):
                continue

            # Replace with anonymized value
            if field in DATE_FIELDS:
                anon_value = '19000101000000'
            else:
                anon_value = 'X' * len(value)

            config.set('GENERAL', field, anon_value)
            modified = True
            cleared.append(PHIFinding(
                offset=0, length=len(value), tag_id=None,
                tag_name=f'Slidedat:{field}',
                value_preview=f'{field}={value[:50]}',
                source='ini_metadata',
            ))

        if modified:
            _write_slidedat(slidedat_path, config)

        # Also do regex anonymization on the raw file
        data = slidedat_path.read_bytes()
        raw_findings = scan_bytes_for_phi(data)
        if raw_findings:
            with open(slidedat_path, 'r+b') as f:
                for offset, length, matched, label in raw_findings:
                    value = matched.decode('ascii', errors='replace')
                    f.seek(offset)
                    f.write(b'X' * length)
                    cleared.append(PHIFinding(
                        offset=offset, length=length, tag_id=None,
                        tag_name=f'regex:{label}',
                        value_preview=value[:50],
                        source='regex_scan',
                    ))

        return cleared

    def _anonymize_mrxs_file(self, filepath: Path) -> List[PHIFinding]:
        """Anonymize regex patterns in the .mrxs file itself."""
        data = filepath.read_bytes()
        raw_findings = scan_bytes_for_phi(data)
        if not raw_findings:
            return []

        cleared = []
        with open(filepath, 'r+b') as f:
            for offset, length, matched, label in raw_findings:
                value = matched.decode('ascii', errors='replace')
                f.seek(offset)
                f.write(b'X' * length)
                cleared.append(PHIFinding(
                    offset=offset, length=length, tag_id=None,
                    tag_name=f'regex:{label}',
                    value_preview=value[:50],
                    source='regex_scan',
                ))
        return cleared


def _get_data_dir(filepath: Path) -> Optional[Path]:
    """Find the companion data directory for an MRXS file.

    Convention: slide.mrxs -> slide/ (same name without extension)
    """
    data_dir = filepath.parent / filepath.stem
    if data_dir.is_dir():
        return data_dir
    return None


def _read_slidedat(slidedat_path: Path) -> configparser.ConfigParser:
    """Read Slidedat.ini with configparser."""
    config = configparser.ConfigParser()
    config.optionxform = str  # Preserve case
    config.read(str(slidedat_path), encoding='utf-8-sig')
    return config


def _write_slidedat(slidedat_path: Path, config: configparser.ConfigParser):
    """Write modified Slidedat.ini back to disk."""
    with open(slidedat_path, 'w', encoding='utf-8') as f:
        config.write(f)


def _is_anonymized(field: str, value: str) -> bool:
    """Check if a field value has already been anonymized."""
    if not value:
        return True
    if all(c == 'X' for c in value):
        return True
    if field in DATE_FIELDS and value == '19000101000000':
        return True
    return False
