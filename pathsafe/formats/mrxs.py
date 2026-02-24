"""3DHISTECH MRXS (MIRAX) format handler.

Handles PHI detection and anonymization for MRXS files, including:
- Slidedat.ini metadata: SLIDE_ID, SLIDE_NAME, SLIDE_BARCODE,
  SLIDE_CREATIONDATETIME, and other PHI fields across ALL sections
- Non-hierarchical associated images (label, macro, thumbnail)
  stored in Data*.dat files -- blanked to remove photographed PHI
- Regex safety scan of Slidedat.ini and the .mrxs index file

MRXS structure:
  slide.mrxs              <- index file (may contain some metadata)
  slide/                  <- companion data directory
    Slidedat.ini          <- main metadata (INI format)
    Index.dat             <- tile index (binary)
    Data00000.dat, ...    <- tile data files (JPEG/PNG/BMP images)

Non-hierarchical (associated) images in MRXS:
  Slidedat.ini references non-hierarchical layers via NONHIER_*_VAL_* keys.
  These include label images (SlideBarcode), thumbnails (SlideThumbnail),
  and macro/preview images (SlidePreview). Each references a [DATAFILE]
  section specifying which Data*.dat file and offset stores the image.
"""

import configparser
import os
import struct
import re
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from pathsafe.formats.base import FormatHandler
from pathsafe.models import PHIFinding, ScanResult
from pathsafe.scanner import scan_bytes_for_phi, scan_string_for_phi

# PHI fields in [GENERAL] section of Slidedat.ini
GENERAL_PHI_FIELDS = {
    'SLIDE_ID', 'SLIDE_NAME', 'SLIDE_BARCODE',
    'SLIDE_CREATIONDATETIME', 'SLIDE_QUALITY',
    'PROJECT_NAME', 'SLIDE_LABEL',
}

# Additional PHI fields that may appear in other sections
# These contain file paths, user data, or identifiers
EXTRA_PHI_FIELDS = {
    'SLIDE_DESCRIPTION', 'SLIDE_CREATOR', 'SLIDE_COMMENT',
    'PATIENT_ID', 'PATIENT_NAME', 'CASE_ID', 'CASE_NUMBER',
    'ACCESSION_NUMBER', 'PHYSICIAN_NAME', 'OPERATOR',
}

# Non-hierarchical layer names that correspond to associated images
# These are the values found in NONHIER_*_VAL_* keys
LABEL_LAYER_NAMES = {
    'ScanDataLayer_SlideBarcode',
    'ScanDataLayer_SlideLabel',
    'ScanDataLayer_SlideBarcodeImage',
}
MACRO_LAYER_NAMES = {
    'ScanDataLayer_SlidePreview',
    'ScanDataLayer_SlideMacro',
    'ScanDataLayer_SlideOverview',
}
THUMBNAIL_LAYER_NAMES = {
    'ScanDataLayer_SlideThumbnail',
}
# All associated image layer names
ASSOCIATED_IMAGE_LAYERS = LABEL_LAYER_NAMES | MACRO_LAYER_NAMES | THUMBNAIL_LAYER_NAMES

# Date/time-like field names (values replaced with sentinel)
DATE_FIELDS = {'SLIDE_CREATIONDATETIME'}


class MRXSHandler(FormatHandler):
    """Format handler for 3DHISTECH MRXS (MIRAX) files."""

    format_name = "mrxs"

    def can_handle(self, filepath: Path) -> bool:
        return filepath.suffix.lower() == '.mrxs'

    def scan(self, filepath: Path) -> ScanResult:
        """Scan MRXS file for PHI -- read-only."""
        t0 = time.monotonic()
        file_size = os.path.getsize(filepath)
        findings: List[PHIFinding] = []

        try:
            data_dir = _get_data_dir(filepath)
            if data_dir is None:
                elapsed = (time.monotonic() - t0) * 1000
                return ScanResult(
                    filepath=filepath, format="mrxs", findings=[],
                    is_clean=False, scan_time_ms=elapsed,
                    file_size=file_size,
                    error="No companion data directory found",
                )

            slidedat = data_dir / 'Slidedat.ini'
            if slidedat.exists():
                findings += self._scan_slidedat(slidedat)
                findings += self._scan_slidedat_all_sections(slidedat)
                findings += self._scan_associated_images(slidedat, data_dir)
                findings += self._scan_slidedat_regex(slidedat)

            # Also scan the .mrxs file itself for PHI patterns
            findings += self._scan_mrxs_file(filepath)
            findings += self.scan_filename(filepath)

        except Exception as e:
            elapsed = (time.monotonic() - t0) * 1000
            return ScanResult(
                filepath=filepath, format="mrxs", findings=findings,
                is_clean=False, scan_time_ms=elapsed,
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
            cleared += self._anonymize_slidedat_all_sections(slidedat)
            cleared += self._blank_associated_images(slidedat, data_dir)

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

                # Report associated images
                images = _find_associated_images(config)
                if images:
                    info['associated_images'] = [
                        img_type for img_type, _, _, _ in images]

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

        # Build case-insensitive lookup: uppercase key -> actual INI key
        general_keys = {k.upper(): k for k in config.options('GENERAL')}

        for field in GENERAL_PHI_FIELDS:
            actual_key = general_keys.get(field)
            if actual_key is None:
                continue
            value = config.get('GENERAL', actual_key).strip()
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

    def _scan_slidedat_all_sections(self, slidedat_path: Path) -> List[PHIFinding]:
        """Scan ALL sections of Slidedat.ini for additional PHI fields."""
        findings = []
        config = _read_slidedat(slidedat_path)

        for section in config.sections():
            if section == 'GENERAL':
                continue  # Already handled by _scan_slidedat
            for key in config.options(section):
                key_upper = key.upper()
                if key_upper not in EXTRA_PHI_FIELDS:
                    continue
                value = config.get(section, key).strip()
                if not value or _is_anonymized(key_upper, value):
                    continue
                findings.append(PHIFinding(
                    offset=0, length=len(value), tag_id=None,
                    tag_name=f'Slidedat:{section}:{key}',
                    value_preview=f'{key}={value[:50]}',
                    source='ini_metadata',
                ))

        return findings

    def _scan_associated_images(self, slidedat_path: Path,
                                data_dir: Path) -> List[PHIFinding]:
        """Detect label, macro, and thumbnail images that may contain PHI."""
        findings = []
        config = _read_slidedat(slidedat_path)
        images = _find_associated_images(config)

        for img_type, dat_file_key, section_name, layer_name in images:
            # Resolve the data file path
            dat_path = _resolve_dat_file(config, dat_file_key, data_dir)
            if dat_path is None or not dat_path.exists():
                continue

            # Get the image data size from the section
            data_size = _get_image_data_size(config, section_name)
            if data_size <= 0:
                # Try to estimate from file
                data_size = dat_path.stat().st_size

            # Check if already blanked
            if _is_image_blanked(dat_path, config, section_name):
                continue

            findings.append(PHIFinding(
                offset=0, length=data_size, tag_id=None,
                tag_name=img_type,
                value_preview=f'{img_type} ({data_size / 1024:.0f}KB) in {dat_path.name}',
                source='image_content',
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
        """Anonymize PHI fields in Slidedat.ini [GENERAL] section."""
        cleared = []
        config = _read_slidedat(slidedat_path)

        if not config.has_section('GENERAL'):
            return cleared

        # Build case-insensitive lookup: uppercase key -> actual INI key
        general_keys = {k.upper(): k for k in config.options('GENERAL')}

        modified = False
        for field in GENERAL_PHI_FIELDS:
            actual_key = general_keys.get(field)
            if actual_key is None:
                continue
            value = config.get('GENERAL', actual_key).strip()
            if not value or _is_anonymized(field, value):
                continue

            # Replace with anonymized value
            if field in DATE_FIELDS:
                anon_value = '19000101000000'
            else:
                anon_value = 'X' * len(value)

            config.set('GENERAL', actual_key, anon_value)
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

    def _anonymize_slidedat_all_sections(self,
                                          slidedat_path: Path) -> List[PHIFinding]:
        """Anonymize extra PHI fields in all Slidedat.ini sections."""
        cleared = []
        config = _read_slidedat(slidedat_path)
        modified = False

        for section in config.sections():
            if section == 'GENERAL':
                continue
            for key in config.options(section):
                key_upper = key.upper()
                if key_upper not in EXTRA_PHI_FIELDS:
                    continue
                value = config.get(section, key).strip()
                if not value or _is_anonymized(key_upper, value):
                    continue

                if 'DATE' in key_upper or 'TIME' in key_upper:
                    anon_value = '19000101000000'
                else:
                    anon_value = 'X' * len(value)

                config.set(section, key, anon_value)
                modified = True
                cleared.append(PHIFinding(
                    offset=0, length=len(value), tag_id=None,
                    tag_name=f'Slidedat:{section}:{key}',
                    value_preview=f'{key}={value[:50]}',
                    source='ini_metadata',
                ))

        if modified:
            _write_slidedat(slidedat_path, config)

        return cleared

    def _blank_associated_images(self, slidedat_path: Path,
                                  data_dir: Path) -> List[PHIFinding]:
        """Blank label, macro, and thumbnail images in Data*.dat files."""
        cleared = []
        config = _read_slidedat(slidedat_path)
        images = _find_associated_images(config)

        for img_type, dat_file_key, section_name, layer_name in images:
            dat_path = _resolve_dat_file(config, dat_file_key, data_dir)
            if dat_path is None or not dat_path.exists():
                continue

            if _is_image_blanked(dat_path, config, section_name):
                continue

            # Get offset and size of image data within the dat file
            offset, size = _get_image_offset_size(config, section_name, dat_path)
            if size <= 0:
                continue

            # Overwrite image data with zeros
            with open(dat_path, 'r+b') as f:
                f.seek(offset)
                f.write(b'\x00' * size)

            cleared.append(PHIFinding(
                offset=offset, length=size, tag_id=None,
                tag_name=img_type,
                value_preview=f'blanked {img_type} ({size / 1024:.0f}KB) in {dat_path.name}',
                source='image_content',
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


def _find_associated_images(
    config: configparser.ConfigParser,
) -> List[Tuple[str, str, str, str]]:
    """Find non-hierarchical associated images (label, macro, thumbnail).

    MRXS stores associated images as non-hierarchical layers referenced
    in Slidedat.ini. The NONHIER_*_COUNT and NONHIER_*_VAL_* keys in
    the [HIERARCHICAL] section identify these layers.

    Returns list of (image_type, dat_file_key, section_name, layer_name).
    """
    images = []

    if not config.has_section('HIERARCHICAL'):
        return images

    # Find non-hierarchical layer count
    nonhier_count = 0
    if config.has_option('HIERARCHICAL', 'NONHIER_COUNT'):
        try:
            nonhier_count = int(config.get('HIERARCHICAL', 'NONHIER_COUNT'))
        except ValueError:
            pass

    for layer_idx in range(nonhier_count):
        # Get the number of values in this non-hierarchical layer
        count_key = f'NONHIER_{layer_idx}_COUNT'
        if not config.has_option('HIERARCHICAL', count_key):
            continue
        try:
            val_count = int(config.get('HIERARCHICAL', count_key))
        except ValueError:
            continue

        for val_idx in range(val_count):
            val_key = f'NONHIER_{layer_idx}_VAL_{val_idx}'
            if not config.has_option('HIERARCHICAL', val_key):
                continue

            layer_name = config.get('HIERARCHICAL', val_key).strip()

            # Classify the layer
            img_type = None
            if layer_name in LABEL_LAYER_NAMES:
                img_type = 'LabelImage'
            elif layer_name in MACRO_LAYER_NAMES:
                img_type = 'MacroImage'
            elif layer_name in THUMBNAIL_LAYER_NAMES:
                img_type = 'ThumbnailImage'

            if img_type is None:
                continue

            # The section name for this layer's data file reference
            section_key = f'NONHIER_{layer_idx}_VAL_{val_idx}_SECTION'
            if config.has_option('HIERARCHICAL', section_key):
                section_name = config.get('HIERARCHICAL', section_key)
            else:
                # Fallback: construct section name from layer name
                section_name = f'NONHIER_{layer_idx}_LEVEL_{val_idx}'

            # Look for the IMAGEFILE key in the section to find dat file
            dat_file_key = None
            if config.has_section(section_name):
                if config.has_option(section_name, 'FILE'):
                    dat_file_key = config.get(section_name, 'FILE')
                elif config.has_option(section_name, 'IMAGEFILE'):
                    dat_file_key = config.get(section_name, 'IMAGEFILE')

            images.append((img_type, dat_file_key, section_name, layer_name))

    return images


def _resolve_dat_file(config: configparser.ConfigParser,
                       dat_file_key: Optional[str],
                       data_dir: Path) -> Optional[Path]:
    """Resolve a dat file reference to an actual file path.

    MRXS may reference data files by name (e.g., 'Data0000.dat')
    or by a key into a [DATAFILE] section.
    """
    if dat_file_key is None:
        return None

    # Direct filename
    dat_path = data_dir / dat_file_key
    if dat_path.exists():
        return dat_path

    # Try as a section reference
    if config.has_section('DATAFILE'):
        if config.has_option('DATAFILE', dat_file_key):
            filename = config.get('DATAFILE', dat_file_key)
            dat_path = data_dir / filename
            if dat_path.exists():
                return dat_path

    # Try common dat file patterns
    for dat_file in sorted(data_dir.glob('Data*.dat')):
        return dat_file  # Return first as fallback

    return None


def _get_image_data_size(config: configparser.ConfigParser,
                          section_name: str) -> int:
    """Get the image data size from a section in Slidedat.ini."""
    if not config.has_section(section_name):
        return 0

    for key in ('FILE_SIZE', 'FILESIZE', 'SIZE', 'BYTECOUNT'):
        if config.has_option(section_name, key):
            try:
                return int(config.get(section_name, key))
            except ValueError:
                pass
    return 0


def _get_image_offset_size(config: configparser.ConfigParser,
                            section_name: str,
                            dat_path: Path) -> Tuple[int, int]:
    """Get the offset and size of image data within a dat file.

    Returns (offset, size). Offset defaults to 0 if not specified.
    Size defaults to the entire file if not specified.
    """
    offset = 0
    size = 0

    if config.has_section(section_name):
        for key in ('FILE_OFFSET', 'FILEOFFSET', 'OFFSET'):
            if config.has_option(section_name, key):
                try:
                    offset = int(config.get(section_name, key))
                except ValueError:
                    pass
                break

        for key in ('FILE_SIZE', 'FILESIZE', 'SIZE', 'BYTECOUNT'):
            if config.has_option(section_name, key):
                try:
                    size = int(config.get(section_name, key))
                except ValueError:
                    pass
                break

    if size <= 0:
        # Fall back to file size minus offset
        try:
            size = dat_path.stat().st_size - offset
        except OSError:
            size = 0

    return offset, size


def _is_image_blanked(dat_path: Path,
                       config: configparser.ConfigParser,
                       section_name: str) -> bool:
    """Check if an associated image has already been blanked."""
    offset, size = _get_image_offset_size(config, section_name, dat_path)
    if size <= 0:
        return True

    # Check first 8 bytes for all zeros
    try:
        with open(dat_path, 'rb') as f:
            f.seek(offset)
            head = f.read(min(size, 8))
            return head == b'\x00' * len(head)
    except OSError:
        return False
