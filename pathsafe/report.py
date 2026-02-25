"""Compliance certificate generation (JSON + PDF)."""

import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fpdf import FPDF

import pathsafe
from pathsafe.models import BatchResult


def _replacement_description(finding_source: str) -> str:
    """Return a human-readable description of what the PHI was replaced with."""
    if finding_source == 'image_content':
        return 'Blank image (IFD unlinked)'
    if finding_source == 'regex_scan':
        return 'Overwritten with padding bytes'
    # tiff_tag, and anything else
    return 'Cleared (null bytes)'


def _sha256_file(filepath: Path) -> str:
    """Compute SHA-256 hash of a file."""
    h = hashlib.sha256()
    with open(filepath, 'rb') as f:
        while True:
            chunk = f.read(65536)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def generate_certificate(
    batch_result: BatchResult,
    output_path: Optional[Path] = None,
    timestamps_reset: bool = True,
    pdf: bool = True,
    institution: str = "",
) -> dict:
    """Generate a JSON compliance certificate for a batch anonymization run.

    Includes per-file records and a summary of all technical measures applied.
    When output_path is provided and pdf=True, a companion PDF is also generated.

    Args:
        batch_result: The BatchResult from anonymize_batch().
        output_path: If provided, write the certificate JSON to this file.
        timestamps_reset: Whether timestamps were reset to epoch.
        pdf: If True (default), auto-generate a companion PDF alongside JSON.

    Returns:
        The certificate as a dict.
    """
    # Determine mode from results
    mode = "unknown"
    if batch_result.results:
        mode = batch_result.results[0].mode

    # Build per-file records
    file_records = []
    verified_count = 0
    total_findings = 0
    for result in batch_result.results:
        record = {
            'filename': result.output_path.name,
            'source_path': str(result.source_path),
            'output_path': str(result.output_path),
            'format': _detect_format_from_ext(result.output_path),
            'findings_cleared': result.findings_cleared,
            'verified_clean': result.verified,
            'anonymization_time_ms': round(result.anonymization_time_ms, 1),
        }

        # Include detailed findings with replacement info
        if result.findings:
            record['findings'] = []
            for f in result.findings:
                finding_rec = {
                    'tag_name': f.tag_name,
                    'value_preview': f.value_preview,
                    'source': f.source,
                    'replaced_with': _replacement_description(f.source),
                }
                record['findings'].append(finding_rec)

        if result.image_integrity_verified is not None:
            record['image_integrity_verified'] = result.image_integrity_verified

        if result.filename_has_phi:
            record['filename_has_phi'] = True

        if result.error:
            record['error'] = result.error
        elif result.sha256_after:
            record['sha256_after'] = result.sha256_after
        else:
            try:
                record['sha256_after'] = _sha256_file(result.output_path)
            except (OSError, FileNotFoundError):
                pass

        if result.verified:
            verified_count += 1
        total_findings += result.findings_cleared

        file_records.append(record)

    # Build technical measures summary
    integrity_verified = sum(1 for r in batch_result.results
                             if r.image_integrity_verified is True)
    integrity_failed = sum(1 for r in batch_result.results
                           if r.image_integrity_verified is False)

    measures = []
    measures.append({
        'measure': 'Metadata tags cleared',
        'status': 'applied' if total_findings > 0 else 'not_needed',
    })
    measures.append({
        'measure': 'Label/macro images blanked',
        'status': 'applied' if total_findings > 0 else 'not_needed',
    })
    measures.append({
        'measure': 'Post-anonymization verification',
        'status': 'passed' if verified_count == len(batch_result.results) and verified_count > 0 else 'skipped',
    })
    if integrity_verified > 0 or integrity_failed > 0:
        measures.append({
            'measure': 'Image data integrity (SHA-256)',
            'status': 'passed' if integrity_failed == 0 else 'failed',
        })
    if timestamps_reset:
        measures.append({
            'measure': 'Filesystem timestamps reset',
            'status': 'applied',
        })

    certificate = {
        'pathsafe_version': pathsafe.__version__,
        'certificate_id': str(uuid.uuid4()),
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'institution': institution,
        'mode': mode,
        'summary': {
            'total_files': batch_result.total_files,
            'anonymized': batch_result.files_anonymized,
            'already_clean': batch_result.files_already_clean,
            'errors': batch_result.files_errored,
            'verified': verified_count == len(batch_result.results) and verified_count > 0,
            'total_time_seconds': round(batch_result.total_time_seconds, 2),
        },
        'measures': measures,
        'files': file_records,
    }

    if output_path is not None:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, 'w') as f:
            json.dump(certificate, f, indent=2)

        if pdf:
            pdf_path = output_path.with_suffix('.pdf')
            generate_pdf_certificate(certificate, pdf_path,
                                     institution=institution)

    return certificate


# ---------------------------------------------------------------------------
# PDF certificate generation
# ---------------------------------------------------------------------------

# Status colors (R, G, B)
_STATUS_COLORS = {
    'applied': (34, 139, 34),     # forest green
    'passed':  (34, 139, 34),     # forest green
    'not_needed': (128, 128, 128), # gray
    'skipped': (200, 150, 0),     # amber
    'failed':  (192, 48, 48),     # red
}


def _trunc(text: str, max_len: int) -> str:
    """Truncate text with ellipsis if it exceeds max_len."""
    if len(text) <= max_len:
        return text
    return text[:max_len - 3] + '...'


def _sanitize_for_pdf(text: str) -> str:
    """Replace non-ASCII and non-printable characters for safe PDF rendering.

    fpdf's built-in Helvetica font only supports Latin-1. Characters outside
    that range crash with "Character ... is outside the range of characters
    supported by the font". Replace them with '?' to prevent crashes.
    """
    return ''.join(c if 0x20 <= ord(c) <= 0x7E else '?' for c in text)


# Human-readable tag name mapping for reports and GUI log
_FRIENDLY_TAG_NAMES = {
    'NDPI_BARCODE': 'Barcode',
    'NDPI_REFERENCE': 'Reference',
    'NDPI_SERIAL_NUMBER': 'Serial Number',
    'NDPI_SCANPROFILE': 'Scan Profile',
    'NDPI_BARCODE_TYPE': 'Barcode Type',
    'NDPI_FORMAT_FLAG': 'Format Flag',
    'NDPI_SOURCELENS': 'Source Lens',
    'NDPI_SCANNER_PROPS': 'Scanner Properties',
    'DateTime': 'Date/Time',
    'DateTimeOriginal': 'Date/Time Original',
    'DateTimeDigitized': 'Date/Time Digitized',
    'MacroImage': 'Macro Image',
    'LabelImage': 'Label Image',
    'ImageDescription': 'Image Description',
    'Make': 'Manufacturer',
    'Model': 'Model',
    'Software': 'Software',
    'Artist': 'Artist',
    'HostComputer': 'Computer Name',
    'ICCProfile': 'ICC Color Profile',
    'XMP': 'XMP Metadata',
    'UserComment': 'User Comment',
    'ImageUniqueID': 'Image Unique ID',
}


def friendly_tag_name(tag_name: str) -> str:
    """Convert internal tag names to human-readable labels for reports."""
    if tag_name in _FRIENDLY_TAG_NAMES:
        return _FRIENDLY_TAG_NAMES[tag_name]
    # Prefixed names: EXIF:Tag, GPS:Tag, NDPI_SCANNER_PROPS:Key, regex:label
    if ':' in tag_name:
        prefix, rest = tag_name.split(':', 1)
        if prefix == 'EXIF':
            friendly = _FRIENDLY_TAG_NAMES.get(rest, rest)
            return f'EXIF: {friendly}'
        if prefix == 'GPS':
            clean = rest.replace('GPS', '') if rest.startswith('GPS') else rest
            return f'GPS: {clean}'
        if prefix == 'NDPI_SCANNER_PROPS':
            return f'Scanner: {rest}'
        if prefix in ('regex', 'fallback'):
            return f'Pattern: {rest}'
        return f'{prefix}: {rest}'
    # NDPI_Tag_XXXXX or NDPI_UNKNOWN_XXXXX
    if tag_name.startswith('NDPI_Tag_'):
        return f'NDPI Tag {tag_name[9:]}'
    if tag_name.startswith('NDPI_UNKNOWN_'):
        return f'NDPI Tag {tag_name[13:]}'
    if tag_name.startswith('Tag_'):
        return f'Tag {tag_name[4:]}'
    return tag_name


def _pdf_label_value(pdf: FPDF, label: str, value: str):
    """Render a label: value line."""
    pdf.set_font('Helvetica', 'B', 10)
    pdf.cell(45, 6, label, new_x='RIGHT', new_y='TOP')
    pdf.set_font('Helvetica', '', 10)
    pdf.cell(0, 6, value, new_x='LMARGIN', new_y='NEXT')


def _pdf_kv_table(pdf: FPDF, rows: list):
    """Render a 2-column key-value table with alternating row shading."""
    col_w = [65, 115]
    for i, (key, value) in enumerate(rows):
        if i % 2 == 0:
            pdf.set_fill_color(240, 240, 245)
            fill = True
        else:
            fill = False
        pdf.set_font('Helvetica', 'B', 9)
        pdf.cell(col_w[0], 7, key, border=0, fill=fill,
                 new_x='RIGHT', new_y='TOP')
        pdf.set_font('Helvetica', '', 9)
        pdf.cell(col_w[1], 7, str(value), border=0, fill=fill,
                 new_x='LMARGIN', new_y='NEXT')
    pdf.ln(3)


def _pdf_measures_table(pdf: FPDF, measures: list):
    """Render the technical measures table with color-coded status."""
    col_w = [110, 70]
    # Header
    pdf.set_font('Helvetica', 'B', 9)
    pdf.set_fill_color(60, 60, 80)
    pdf.set_text_color(255, 255, 255)
    pdf.cell(col_w[0], 7, 'Measure', border=0, fill=True,
             new_x='RIGHT', new_y='TOP')
    pdf.cell(col_w[1], 7, 'Status', border=0, fill=True,
             new_x='LMARGIN', new_y='NEXT')
    pdf.set_text_color(0, 0, 0)

    for i, m in enumerate(measures):
        if i % 2 == 0:
            pdf.set_fill_color(240, 240, 245)
            fill = True
        else:
            fill = False
        pdf.set_font('Helvetica', '', 9)
        pdf.cell(col_w[0], 7, m['measure'], border=0, fill=fill,
                 new_x='RIGHT', new_y='TOP')
        status = m['status']
        r, g, b = _STATUS_COLORS.get(status, (0, 0, 0))
        pdf.set_text_color(r, g, b)
        pdf.set_font('Helvetica', 'B', 9)
        pdf.cell(col_w[1], 7, status.upper(), border=0, fill=fill,
                 new_x='LMARGIN', new_y='NEXT')
        pdf.set_text_color(0, 0, 0)
    pdf.ln(3)


def _pdf_file_results_table(pdf: FPDF, files: list):
    """Render the file results table (7 columns at small font)."""
    col_w = [8, 42, 18, 18, 18, 20, 66]  # total = 190
    headers = ['#', 'Filename', 'Format', 'Cleared', 'Verified', 'Integrity', 'SHA-256']

    # Header row
    pdf.set_font('Helvetica', 'B', 7)
    pdf.set_fill_color(60, 60, 80)
    pdf.set_text_color(255, 255, 255)
    for j, hdr in enumerate(headers):
        nx = 'RIGHT' if j < len(headers) - 1 else 'LMARGIN'
        ny = 'TOP' if j < len(headers) - 1 else 'NEXT'
        pdf.cell(col_w[j], 6, hdr, border=0, fill=True, new_x=nx, new_y=ny)
    pdf.set_text_color(0, 0, 0)

    for i, frec in enumerate(files):
        if i % 2 == 0:
            pdf.set_fill_color(245, 245, 248)
            fill = True
        else:
            fill = False

        pdf.set_font('Helvetica', '', 7)

        integrity = frec.get('image_integrity_verified')
        if integrity is True:
            integrity_str = 'YES'
        elif integrity is False:
            integrity_str = 'FAIL'
        else:
            integrity_str = '-'

        sha = frec.get('sha256_after', frec.get('error', '-'))
        row_vals = [
            str(i + 1),
            _trunc(frec.get('filename', ''), 28),
            frec.get('format', '?'),
            str(frec.get('findings_cleared', 0)),
             'YES' if frec.get('verified_clean') else 'NO',
            integrity_str,
            _trunc(sha, 40),
        ]

        for j, val in enumerate(row_vals):
            nx = 'RIGHT' if j < len(row_vals) - 1 else 'LMARGIN'
            ny = 'TOP' if j < len(row_vals) - 1 else 'NEXT'
            pdf.cell(col_w[j], 5.5, val, border=0, fill=fill,
                     new_x=nx, new_y=ny)
    pdf.ln(3)


def generate_pdf_certificate(certificate: dict, output_path: Path,
                             institution: str = "") -> Path:
    """Generate a printable PDF compliance certificate.

    Args:
        certificate: The certificate dict (as returned by generate_certificate).
        output_path: Path where the PDF file will be written.
        institution: Optional institution name to display in the header.

    Returns:
        The output_path.

    Raises:
        ValueError: If certificate dict is missing required keys.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Validate required keys
    _REQUIRED_CERT_KEYS = {'certificate_id', 'summary', 'files'}
    missing = _REQUIRED_CERT_KEYS - set(certificate.keys())
    if missing:
        raise ValueError(
            f"Certificate dict is missing required keys: {', '.join(sorted(missing))}")

    pdf = FPDF(orientation='P', unit='mm', format='A4')
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.add_page()

    # --- Header ---
    pdf.set_font('Helvetica', 'B', 16)
    pdf.cell(0, 10, 'PathSafe Anonymization Certificate', new_x='LMARGIN', new_y='NEXT')
    if institution:
        pdf.set_font('Helvetica', 'B', 12)
        pdf.set_text_color(30, 60, 120)
        pdf.cell(0, 7, institution, new_x='LMARGIN', new_y='NEXT')
        pdf.set_text_color(0, 0, 0)
    pdf.set_font('Helvetica', '', 9)
    pdf.set_text_color(120, 120, 120)
    pdf.cell(0, 5, f'PathSafe v{certificate.get("pathsafe_version", "?")}',
             new_x='LMARGIN', new_y='NEXT')
    pdf.set_text_color(0, 0, 0)
    pdf.line(10, pdf.get_y() + 1, 200, pdf.get_y() + 1)
    pdf.ln(5)

    # --- Metadata ---
    _pdf_label_value(pdf, 'Certificate ID:', certificate.get('certificate_id', '-'))
    _pdf_label_value(pdf, 'Generated:', certificate.get('generated_at', '-'))
    _pdf_label_value(pdf, 'Mode:', certificate.get('mode', '-'))
    pdf.ln(3)

    # --- Summary table ---
    pdf.set_font('Helvetica', 'B', 11)
    pdf.cell(0, 7, 'Summary', new_x='LMARGIN', new_y='NEXT')
    summary = certificate.get('summary', {})
    _pdf_kv_table(pdf, [
        ('Total files', str(summary.get('total_files', 0))),
        ('Anonymized', str(summary.get('anonymized', 0))),
        ('Already clean', str(summary.get('already_clean', 0))),
        ('Errors', str(summary.get('errors', 0))),
        ('All verified', 'Yes' if summary.get('verified') else 'No'),
        ('Total time', f'{summary.get("total_time_seconds", 0)}s'),
    ])

    # --- Technical measures ---
    pdf.set_font('Helvetica', 'B', 11)
    pdf.cell(0, 7, 'Technical Measures', new_x='LMARGIN', new_y='NEXT')
    _pdf_measures_table(pdf, certificate.get('measures', []))

    # --- File results ---
    files = certificate.get('files', [])
    if files:
        pdf.set_font('Helvetica', 'B', 11)
        pdf.cell(0, 7, 'File Results', new_x='LMARGIN', new_y='NEXT')
        _pdf_file_results_table(pdf, files)

        # Detailed findings per file (what was found, what it was replaced with)
        files_with_findings = [f for f in files if f.get('findings')]
        if files_with_findings:
            pdf.set_font('Helvetica', 'B', 11)
            pdf.cell(0, 7, 'Detailed Findings', new_x='LMARGIN', new_y='NEXT')
            pdf.ln(1)

            for frec in files_with_findings:
                pdf.set_font('Helvetica', 'B', 9)
                pdf.set_text_color(200, 130, 0)
                pdf.cell(0, 6, _trunc(frec.get('filename', ''), 80),
                         new_x='LMARGIN', new_y='NEXT')
                pdf.set_text_color(0, 0, 0)

                for finding in frec['findings']:
                    raw_tag = finding.get('tag_name', '?')
                    if raw_tag in _PDF_HIDDEN_TAGS:
                        continue

                    tag = _sanitize_for_pdf(friendly_tag_name(raw_tag))
                    preview = _sanitize_for_pdf(
                        _trunc(finding.get('value_preview', ''), 55))
                    replacement = finding.get('replaced_with', 'Cleared')

                    # Check for page break
                    if pdf.get_y() > 260:
                        pdf.add_page()

                    # Tag name (bold) + value preview
                    pdf.set_font('Helvetica', '', 8)
                    pdf.cell(5, 5, '', new_x='RIGHT', new_y='TOP')
                    pdf.set_font('Helvetica', 'B', 8)
                    pdf.cell(50, 5, tag, new_x='RIGHT', new_y='TOP')
                    pdf.set_font('Helvetica', '', 8)
                    pdf.cell(0, 5, preview, new_x='LMARGIN', new_y='NEXT')

                    # Replacement line (indented, gray)
                    pdf.set_text_color(100, 100, 100)
                    pdf.set_font('Helvetica', 'I', 7)
                    pdf.cell(55, 4, '', new_x='RIGHT', new_y='TOP')
                    pdf.cell(0, 4, f'Replaced with: {replacement}',
                             new_x='LMARGIN', new_y='NEXT')
                    pdf.set_text_color(0, 0, 0)

                pdf.ln(2)

        # Filename PHI warnings
        phi_files = [f for f in files if f.get('filename_has_phi')]
        if phi_files:
            pdf.set_font('Helvetica', 'B', 9)
            pdf.set_text_color(192, 48, 48)
            pdf.cell(0, 6, 'Filename PHI Warnings:', new_x='LMARGIN', new_y='NEXT')
            pdf.set_font('Helvetica', '', 8)
            for f in phi_files:
                pdf.cell(0, 5,
                         f'  {f["filename"]} - contains patient information, rename manually',
                         new_x='LMARGIN', new_y='NEXT')
            pdf.set_text_color(0, 0, 0)
            pdf.ln(2)

        # Error files
        error_files = [f for f in files if f.get('error')]
        if error_files:
            pdf.set_font('Helvetica', 'B', 9)
            pdf.set_text_color(192, 48, 48)
            pdf.cell(0, 6, 'Errors:', new_x='LMARGIN', new_y='NEXT')
            pdf.set_font('Helvetica', '', 8)
            for f in error_files:
                pdf.cell(0, 5,
                         f'  {f["filename"]}: {_trunc(f["error"], 80)}',
                         new_x='LMARGIN', new_y='NEXT')
            pdf.set_text_color(0, 0, 0)
            pdf.ln(2)

    # --- Legend ---
    _pdf_legend(pdf)

    # --- Footer ---
    pdf.line(10, pdf.get_y() + 1, 200, pdf.get_y() + 1)
    pdf.ln(4)
    pdf.set_font('Helvetica', 'I', 8)
    pdf.set_text_color(100, 100, 100)
    pdf.multi_cell(0, 4,
        'This certificate confirms that PathSafe processed the listed files '
        'and applied the indicated anonymization measures. Embedded metadata '
        'tags, label images, and macro images containing patient information '
        'were cleared. Filenames are NOT modified by PathSafe and may still '
        'contain patient information - check warnings above.'
    )
    pdf.set_text_color(0, 0, 0)

    pdf.output(str(output_path))
    return output_path


# ---------------------------------------------------------------------------
# PDF scan report generation
# ---------------------------------------------------------------------------

_SCAN_STATUS_COLORS = {
    'CLEAN':     (34, 139, 34),     # forest green
    'PHI FOUND': (200, 130, 0),     # orange
    'ERROR':     (192, 48, 48),     # red
}


def _pdf_scan_file_table(pdf: FPDF, results: list):
    """Render the file results table for a scan report (5 columns)."""
    col_w = [8, 42, 20, 18, 102]  # total = 190
    headers = ['#', 'Filename', 'Status', 'Findings', 'SHA-256 (before)']

    # Header row
    pdf.set_font('Helvetica', 'B', 7)
    pdf.set_fill_color(60, 60, 80)
    pdf.set_text_color(255, 255, 255)
    for j, hdr in enumerate(headers):
        nx = 'RIGHT' if j < len(headers) - 1 else 'LMARGIN'
        ny = 'TOP' if j < len(headers) - 1 else 'NEXT'
        pdf.cell(col_w[j], 6, hdr, border=0, fill=True, new_x=nx, new_y=ny)
    pdf.set_text_color(0, 0, 0)

    for i, entry in enumerate(results):
        if i % 2 == 0:
            pdf.set_fill_color(245, 245, 248)
            fill = True
        else:
            fill = False

        filepath = Path(entry.get('filepath', ''))
        error = entry.get('error')
        is_clean = entry.get('is_clean', True)
        findings = entry.get('findings', [])
        sha256 = entry.get('sha256', '')

        if error:
            status = 'ERROR'
            findings_str = _sanitize_for_pdf(_trunc(error, 30))
        elif is_clean:
            status = 'CLEAN'
            findings_str = '-'
        else:
            status = 'PHI FOUND'
            visible = [f for f in findings
                       if f.get('tag_name', '') not in _PDF_HIDDEN_TAGS]
            findings_str = f'{len(visible)} finding(s)'

        # Row number
        pdf.set_font('Helvetica', '', 7)
        pdf.cell(col_w[0], 5.5, str(i + 1), border=0, fill=fill,
                 new_x='RIGHT', new_y='TOP')
        # Filename
        pdf.cell(col_w[1], 5.5, _trunc(filepath.name, 28), border=0, fill=fill,
                 new_x='RIGHT', new_y='TOP')
        # Status (color-coded)
        r, g, b = _SCAN_STATUS_COLORS.get(status, (0, 0, 0))
        pdf.set_text_color(r, g, b)
        pdf.set_font('Helvetica', 'B', 7)
        pdf.cell(col_w[2], 5.5, status, border=0, fill=fill,
                 new_x='RIGHT', new_y='TOP')
        pdf.set_text_color(0, 0, 0)
        # Findings summary
        pdf.set_font('Helvetica', '', 7)
        pdf.cell(col_w[3], 5.5, findings_str, border=0, fill=fill,
                 new_x='RIGHT', new_y='TOP')
        # SHA-256
        pdf.cell(col_w[4], 5.5, sha256 or '-', border=0, fill=fill,
                 new_x='LMARGIN', new_y='NEXT')
    pdf.ln(3)


# Legend entries: (friendly name, description)
# Grouped by category for the PDF legend section
_LEGEND_ENTRIES = [
    # -- Identifiers --
    ('Barcode',
     'Accession number or specimen ID encoded in the slide barcode area.'),
    ('Reference',
     'Reference string embedded by the scanner (may contain patient or case identifiers).'),
    ('Serial Number',
     'Scanner hardware serial number - a device fingerprint that can identify the originating facility.'),
    # -- Images --
    ('Label Image',
     'Photograph of the paper label on the glass slide. Typically shows patient name, ID, and dates.'),
    ('Macro Image',
     'Low-resolution overview photograph of the entire glass slide, captured by the scanner camera.'),
    # -- Dates --
    ('Date/Time',
     'Date and time the slide was scanned. Can be cross-referenced with hospital scheduling records.'),
    ('Scanner: Created / Updated',
     'Scan creation or modification date stored in the scanner property map.'),
    ('EXIF: Date/Time Original',
     'Original capture timestamp from the EXIF metadata sub-directory.'),
    # -- Scanner metadata --
    ('Scanner: NDP.S/N / Macro.S/N',
     'Scanner or macro-camera serial number from the Hamamatsu property map.'),
    ('Scan Profile',
     'Scanner configuration profile name (may reveal institutional workflows).'),
    ('Barcode Type',
     'Type of barcode detected on the slide (e.g., DataMatrix, CODE-128).'),
    # -- Embedded metadata --
    ('ICC Color Profile',
     'Embedded color calibration profile. May contain device serial numbers or lab identifiers.'),
    ('XMP Metadata',
     'Extensible metadata block (XML) that may contain creator names, dates, or descriptions.'),
    # -- Location --
    ('GPS: Latitude / Longitude',
     'Geographic coordinates embedded in the image metadata. Reveals scanner location.'),
    # -- Pattern matches --
    ('Pattern: (various)',
     'Text matching a known PHI pattern (accession number, date, SSN, MRN, etc.) found by regex scan '
     'of the raw file bytes.'),
]


def _pdf_legend(pdf: FPDF, used_tags: set = None):
    """Render a findings legend/glossary section in the PDF.

    Args:
        pdf: The FPDF document to render into.
        used_tags: If provided, only show legend entries whose friendly name
                   appears as a substring in at least one used tag. If None,
                   show all entries.
    """
    pdf.add_page()
    pdf.set_font('Helvetica', 'B', 11)
    pdf.cell(0, 7, 'Findings Legend', new_x='LMARGIN', new_y='NEXT')
    pdf.ln(1)
    pdf.set_font('Helvetica', 'I', 8)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(0, 5,
             'Explanation of finding types that may appear in this report.',
             new_x='LMARGIN', new_y='NEXT')
    pdf.set_text_color(0, 0, 0)
    pdf.ln(2)

    for i, (name, description) in enumerate(_LEGEND_ENTRIES):
        if i % 2 == 0:
            pdf.set_fill_color(240, 240, 245)
            fill = True
        else:
            fill = False

        # Name column (bold)
        pdf.set_font('Helvetica', 'B', 8)
        x_start = pdf.get_x()
        y_start = pdf.get_y()
        pdf.cell(50, 5, name, border=0, fill=fill,
                 new_x='RIGHT', new_y='TOP')

        # Description column (wrapped)
        pdf.set_font('Helvetica', '', 8)
        pdf.multi_cell(130, 5, description, border=0, fill=fill,
                       new_x='LMARGIN', new_y='NEXT')

    pdf.ln(3)


# Tags to hide from PDF reports (still present in JSON data)
_PDF_HIDDEN_TAGS = {
    'NDPI_BARCODE_TYPE',   # barcode encoding format, not PHI
    'NDPI_SCANPROFILE',    # scanner configuration XML, not patient data
    'ICCProfile',          # color calibration profile, rarely identifying
}


def generate_scan_report(scan_data: dict, output_path: Path,
                         institution: str = "") -> Path:
    """Generate a PDF report of a pre-anonymization PHI scan.

    Args:
        scan_data: Dict with keys: total, clean, phi_files, phi_findings,
                   errors, results (list of per-file dicts).
        output_path: Path where the PDF file will be written.
        institution: Optional institution name to display in the header.

    Returns:
        The output_path.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    pdf = FPDF(orientation='P', unit='mm', format='A4')
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.add_page()

    # --- Header ---
    pdf.set_font('Helvetica', 'B', 16)
    pdf.cell(0, 10, 'PathSafe PHI Scan Report', new_x='LMARGIN', new_y='NEXT')
    if institution:
        pdf.set_font('Helvetica', 'B', 12)
        pdf.set_text_color(30, 60, 120)
        pdf.cell(0, 7, institution, new_x='LMARGIN', new_y='NEXT')
        pdf.set_text_color(0, 0, 0)
    pdf.set_font('Helvetica', '', 9)
    pdf.set_text_color(120, 120, 120)
    pdf.cell(0, 5, f'PathSafe v{pathsafe.__version__}  |  '
             f'{datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")}',
             new_x='LMARGIN', new_y='NEXT')
    pdf.set_text_color(0, 0, 0)
    pdf.line(10, pdf.get_y() + 1, 200, pdf.get_y() + 1)
    pdf.ln(5)

    # --- Summary table ---
    pdf.set_font('Helvetica', 'B', 11)
    pdf.cell(0, 7, 'Summary', new_x='LMARGIN', new_y='NEXT')

    total = scan_data.get('total', 0)
    clean = scan_data.get('clean', 0)
    phi_files = scan_data.get('phi_files', 0)
    phi_findings = scan_data.get('phi_findings', 0)
    errors = scan_data.get('errors', 0)

    _pdf_kv_table(pdf, [
        ('Total scanned', str(total)),
        ('Clean', str(clean)),
        ('PHI detected', f'{phi_files} file(s), {phi_findings} finding(s)'),
        ('Errors', str(errors)),
    ])

    # --- File results table ---
    results = scan_data.get('results', [])
    if results:
        pdf.set_font('Helvetica', 'B', 11)
        pdf.cell(0, 7, 'File Results', new_x='LMARGIN', new_y='NEXT')
        _pdf_scan_file_table(pdf, results)

    # --- Detailed findings ---
    phi_results = [r for r in results
                   if not r.get('is_clean') and not r.get('error')
                   and r.get('findings')]
    if phi_results:
        pdf.set_font('Helvetica', 'B', 11)
        pdf.cell(0, 7, 'Detailed Findings', new_x='LMARGIN', new_y='NEXT')
        pdf.ln(1)

        for entry in phi_results:
            filepath = Path(entry['filepath'])
            findings = entry['findings']

            pdf.set_font('Helvetica', 'B', 9)
            pdf.set_text_color(200, 130, 0)
            pdf.cell(0, 6, _trunc(filepath.name, 80),
                     new_x='LMARGIN', new_y='NEXT')
            pdf.set_text_color(0, 0, 0)

            for f in findings:
                raw_tag = f.get('tag_name', '?')
                if raw_tag in _PDF_HIDDEN_TAGS:
                    continue
                pdf.set_font('Helvetica', '', 8)
                tag = _sanitize_for_pdf(friendly_tag_name(raw_tag))
                preview = _sanitize_for_pdf(_trunc(f.get('value_preview', ''), 70))
                pdf.cell(5, 5, '', new_x='RIGHT', new_y='TOP')
                pdf.set_font('Helvetica', 'B', 8)
                pdf.cell(50, 5, tag, new_x='RIGHT', new_y='TOP')
                pdf.set_font('Helvetica', '', 8)
                pdf.cell(0, 5, preview, new_x='LMARGIN', new_y='NEXT')
            pdf.ln(2)

    # --- Legend ---
    _pdf_legend(pdf)

    # --- Footer ---
    pdf.line(10, pdf.get_y() + 1, 200, pdf.get_y() + 1)
    pdf.ln(4)
    pdf.set_font('Helvetica', 'I', 8)
    pdf.set_text_color(100, 100, 100)
    pdf.multi_cell(0, 4,
        'This is a pre-anonymization scan report. It shows patient information '
        '(PHI) detected in the listed files. Run PathSafe anonymization to '
        'remove the detected PHI and generate a compliance certificate '
        'confirming the cleanup.'
    )
    pdf.set_text_color(0, 0, 0)

    pdf.output(str(output_path))
    return output_path


def _detect_format_from_ext(filepath: Path) -> str:
    """Simple format detection from extension for certificate records."""
    ext = filepath.suffix.lower()
    return {
        '.ndpi': 'ndpi', '.svs': 'svs', '.tif': 'tiff', '.tiff': 'tiff',
        '.mrxs': 'mrxs', '.bif': 'bif', '.scn': 'scn',
        '.dcm': 'dicom', '.dicom': 'dicom',
    }.get(ext, 'unknown')
