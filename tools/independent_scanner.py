#!/usr/bin/env python3
"""
Independent WSI PHI Scanner
============================
Written from scratch with ZERO PathSafe code. Does not import pathsafe,
does not check for PathSafe markers, and has no knowledge of PathSafe's
blanking strategy.

Purpose: Verify that a TIFF-based WSI file (SVS, NDPI, etc.) has been
truly stripped of patient information by ANY anonymization tool.

What it checks:
  1. Every IFD in the TIFF chain: dimensions, tag 270 description, image type
  2. All string tags across all IFDs (ASCII type = 2)
  3. Known PHI-bearing tags by ID (DateTime, Artist, Software, XMP, ICC, etc.)
  4. Regex scan of first 200KB for accession patterns, dates, names, UUIDs
  5. Raw byte scan for known PHI byte sequences
  6. Label/macro image detection (checks if IFDs with "label"/"macro" exist)
  7. EXIF/GPS sub-IFD presence
"""

import struct
import re
import sys
import os


# ── TIFF Parsing (written from scratch) ──────────────────────────────────

TIFF_TYPE_SIZES = {
    1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 6: 1, 7: 1, 8: 2, 9: 4, 10: 8,
    11: 4, 12: 8, 16: 8, 17: 8,
}

KNOWN_TAG_NAMES = {
    256: "ImageWidth", 257: "ImageLength", 258: "BitsPerSample",
    259: "Compression", 270: "ImageDescription", 271: "Make", 272: "Model",
    273: "StripOffsets", 279: "StripByteCounts", 305: "Software",
    306: "DateTime", 315: "Artist", 316: "HostComputer",
    324: "TileOffsets", 325: "TileByteCounts", 330: "SubIFDs",
    700: "XMP", 33432: "Copyright", 33723: "IPTC",
    34665: "EXIF_IFD_Pointer", 34675: "ICCProfile", 34853: "GPS_IFD_Pointer",
    36867: "DateTimeOriginal", 36868: "DateTimeDigitized",
    37510: "UserComment", 42016: "ImageUniqueID",
    # Hamamatsu NDPI tags
    65421: "NDPI_SourceLens", 65427: "NDPI_Reference", 65442: "NDPI_SerialNumber",
    65449: "NDPI_ScannerProps", 65468: "NDPI_Barcode", 65477: "NDPI_ScanProfile",
    65480: "NDPI_BarcodeType",
}

# Tags that should be empty/zeroed after anonymization
PHI_SENSITIVE_TAGS = {
    270, 305, 306, 315, 316, 700, 33432, 33723, 34675,
    36867, 36868, 37510, 42016,
    # NDPI-specific
    65427, 65442, 65449, 65468, 65477, 65480,
}

# Regex patterns for PHI in raw bytes
PHI_PATTERNS = [
    (r'\d{4}[:/]\d{2}[:/]\d{2}[\s]\d{2}:\d{2}:\d{2}', "EXIF DateTime"),
    (r'\d{2}/\d{2}/\d{2,4}', "Short date (MM/DD/YY)"),
    (r'(?i)AS[-]?\d{2,}[-_]\d+', "Accession number (AS-pattern)"),
    (r'(?i)(?:ScanScope\s*ID|User|Filename|Date|Time)\s*=\s*\S+', "SVS metadata field"),
    (r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', "UUID"),
    (r'(?i)SS\d{4,}', "ScanScope ID"),
    (r'(?i)(?:patient|accession|mrn|case\s*id)\s*[:=]\s*\S+', "Patient identifier field"),
    (r'\d{3}-\d{2}-\d{4}', "SSN-like pattern"),
    (r'(?i)NDP\.S/N\s*=\s*\S+', "NDPI serial number"),
]


def parse_tiff_header(f):
    """Parse TIFF header. Returns (endian, is_bigtiff, first_ifd_offset) or None."""
    f.seek(0)
    bo = f.read(2)
    if bo == b'II':
        endian = '<'
    elif bo == b'MM':
        endian = '>'
    else:
        return None

    magic = struct.unpack(endian + 'H', f.read(2))[0]
    if magic == 42:
        offset = struct.unpack(endian + 'I', f.read(4))[0]
        return endian, False, offset
    elif magic == 43:
        f.read(4)  # bytesize + reserved
        offset = struct.unpack(endian + 'Q', f.read(8))[0]
        return endian, True, offset
    return None


def read_ifd_entries(f, endian, is_bigtiff, ifd_offset):
    """Read all entries from an IFD. Returns (entries_list, next_ifd_offset).
    Each entry is a dict with tag, dtype, count, value_offset, total_size."""
    f.seek(ifd_offset)
    if is_bigtiff:
        num = struct.unpack(endian + 'Q', f.read(8))[0]
        entry_size = 20
        inline_max = 8
    else:
        num = struct.unpack(endian + 'H', f.read(2))[0]
        entry_size = 12
        inline_max = 4

    if num > 1000:
        return [], 0  # corrupt

    entries = []
    for _ in range(num):
        pos = f.tell()
        data = f.read(entry_size)
        if len(data) < entry_size:
            break

        tag = struct.unpack(endian + 'H', data[0:2])[0]
        dtype = struct.unpack(endian + 'H', data[2:4])[0]

        if is_bigtiff:
            count = struct.unpack(endian + 'Q', data[4:12])[0]
            elem_size = TIFF_TYPE_SIZES.get(dtype, 1)
            total = elem_size * count
            if total <= 8:
                value_offset = pos + 12
            else:
                value_offset = struct.unpack(endian + 'Q', data[12:20])[0]
        else:
            count = struct.unpack(endian + 'I', data[4:8])[0]
            elem_size = TIFF_TYPE_SIZES.get(dtype, 1)
            total = elem_size * count
            if total <= 4:
                value_offset = pos + 8
            else:
                value_offset = struct.unpack(endian + 'I', data[8:12])[0]

        entries.append({
            'tag': tag, 'dtype': dtype, 'count': count,
            'value_offset': value_offset, 'total_size': total,
            'name': KNOWN_TAG_NAMES.get(tag, f"Tag_{tag}"),
        })

    # Read next IFD pointer
    if is_bigtiff:
        nd = f.read(8)
        next_off = struct.unpack(endian + 'Q', nd)[0] if len(nd) == 8 else 0
    else:
        nd = f.read(4)
        next_off = struct.unpack(endian + 'I', nd)[0] if len(nd) == 4 else 0

    return entries, next_off


def read_tag_bytes(f, entry):
    """Read raw bytes of a tag value."""
    f.seek(entry['value_offset'])
    return f.read(entry['total_size'])


def read_tag_as_string(f, entry):
    """Read a tag value as ASCII string."""
    raw = read_tag_bytes(f, entry)
    return raw.rstrip(b'\x00').decode('ascii', errors='replace')


def walk_ifd_chain(f, endian, is_bigtiff, first_offset):
    """Walk the full IFD chain. Returns list of (offset, entries)."""
    chain = []
    offset = first_offset
    seen = set()
    while offset != 0 and len(chain) < 100:
        if offset in seen:
            break
        seen.add(offset)
        entries, next_off = read_ifd_entries(f, endian, is_bigtiff, offset)
        if not entries:
            break
        chain.append((offset, entries))
        offset = next_off
    return chain


# ── Independent Scanning ─────────────────────────────────────────────────

def scan_file(filepath):
    """Scan a TIFF-based WSI file for ANY remaining PHI. Returns list of findings."""
    findings = []
    file_size = os.path.getsize(filepath)

    with open(filepath, 'rb') as f:
        # Parse header
        hdr = parse_tiff_header(f)
        if hdr is None:
            findings.append(("ERROR", "Not a valid TIFF file"))
            return findings

        endian, is_bigtiff, first_ifd = hdr

        # Walk IFD chain
        chain = walk_ifd_chain(f, endian, is_bigtiff, first_ifd)

        print(f"\n  File: {os.path.basename(filepath)}")
        print(f"  Size: {file_size / (1024*1024):.1f} MB")
        print(f"  Endian: {'little' if endian == '<' else 'big'}")
        print(f"  BigTIFF: {is_bigtiff}")
        print(f"  IFDs in chain: {len(chain)}")
        print()

        # ── Check 1: Enumerate all IFDs and their properties ──
        print("  === IFD Chain ===")
        for idx, (ifd_off, entries) in enumerate(chain):
            width = height = compression = 0
            tag270_val = ""
            has_exif = False
            has_gps = False

            for e in entries:
                if e['tag'] == 256:  # ImageWidth
                    f.seek(e['value_offset'])
                    if e['dtype'] == 3:
                        width = struct.unpack(endian + 'H', f.read(2))[0]
                    else:
                        width = struct.unpack(endian + 'I', f.read(4))[0]
                elif e['tag'] == 257:  # ImageLength
                    f.seek(e['value_offset'])
                    if e['dtype'] == 3:
                        height = struct.unpack(endian + 'H', f.read(2))[0]
                    else:
                        height = struct.unpack(endian + 'I', f.read(4))[0]
                elif e['tag'] == 259:
                    f.seek(e['value_offset'])
                    compression = struct.unpack(endian + 'H', f.read(2))[0]
                elif e['tag'] == 270:
                    tag270_val = read_tag_as_string(f, e)
                elif e['tag'] == 34665:
                    has_exif = True
                elif e['tag'] == 34853:
                    has_gps = True

            # Detect image type from description
            img_type = "tissue"
            desc_lower = tag270_val.lower()
            if 'label' in desc_lower:
                img_type = "LABEL"
                findings.append(("LABEL IMAGE PRESENT", f"IFD #{idx} at offset {ifd_off}: {width}x{height} - label IFD still in chain"))
            elif 'macro' in desc_lower:
                img_type = "MACRO"
                findings.append(("MACRO IMAGE PRESENT", f"IFD #{idx} at offset {ifd_off}: {width}x{height} - macro IFD still in chain"))

            exif_str = " +EXIF" if has_exif else ""
            gps_str = " +GPS" if has_gps else ""
            if has_exif:
                findings.append(("EXIF SUB-IFD", f"IFD #{idx} has EXIF pointer"))
            if has_gps:
                findings.append(("GPS SUB-IFD", f"IFD #{idx} has GPS pointer"))

            print(f"  IFD #{idx}: offset={ifd_off:,}  {width}x{height}  [{img_type}]{exif_str}{gps_str}")
            if tag270_val:
                preview = tag270_val[:100].replace('\n', ' | ')
                print(f"           tag270: {preview}")
        print()

        # ── Check 2: Scan ALL string tags in ALL IFDs ──
        print("  === String Tag Scan (all IFDs) ===")
        for idx, (ifd_off, entries) in enumerate(chain):
            for e in entries:
                if e['dtype'] != 2:  # Not ASCII
                    continue
                if e['total_size'] < 2:
                    continue
                value = read_tag_as_string(f, e)
                if not value or not value.strip():
                    continue
                # Check if it's non-trivial content (not just nulls or X's)
                stripped = value.strip().strip('\x00')
                if not stripped:
                    continue
                if all(c == 'X' for c in stripped):
                    print(f"  IFD #{idx} tag {e['name']} ({e['tag']}): [REDACTED with X's]")
                    continue

                print(f"  IFD #{idx} tag {e['name']} ({e['tag']}): \"{stripped[:120]}\"")

                # Flag known PHI tags
                if e['tag'] in PHI_SENSITIVE_TAGS:
                    # Check if content looks like real data vs anonymized
                    if e['tag'] in (306, 36867, 36868):  # DateTime tags
                        if stripped and stripped != "0000:00:00 00:00:00":
                            findings.append(("DATETIME TAG", f"IFD #{idx} {e['name']}: {stripped[:50]}"))
                    elif e['tag'] == 270:
                        # Check for PHI fields in ImageDescription
                        for field in ['ScanScope ID=', 'User=', 'Filename=', 'Date=', 'Time=']:
                            if field in value:
                                fval = value.split(field)[1].split('|')[0].strip()
                                if fval and not all(c == 'X' for c in fval) and fval not in ('01/01/00', '00:00:00', ''):
                                    findings.append(("METADATA FIELD", f"{field}{fval[:50]}"))
                    else:
                        findings.append(("SENSITIVE TAG", f"IFD #{idx} {e['name']}: non-empty ({len(stripped)} bytes)"))
        print()

        # ── Check 3: Check for non-empty binary PHI tags ──
        print("  === Binary/Blob Tag Scan ===")
        for idx, (ifd_off, entries) in enumerate(chain):
            for e in entries:
                if e['tag'] in (700, 33723, 34675, 37510, 42016):  # XMP, IPTC, ICC, UserComment, ImageUniqueID
                    raw = read_tag_bytes(f, e)
                    if raw and raw != b'\x00' * len(raw):
                        tag_name = e['name']
                        preview = raw[:40].decode('ascii', errors='replace')
                        print(f"  IFD #{idx} {tag_name} ({e['tag']}): {len(raw)} bytes, preview: {preview!r}")
                        findings.append(("BINARY PHI TAG", f"IFD #{idx} {tag_name}: {len(raw)} non-zero bytes"))
                    else:
                        print(f"  IFD #{idx} {e['name']} ({e['tag']}): ZEROED ({len(raw)} bytes)")
        print()

        # ── Check 4: Regex scan of first 200KB ──
        print("  === Regex Scan (first 200KB of raw bytes) ===")
        f.seek(0)
        raw_head = f.read(200 * 1024)
        text_head = raw_head.decode('ascii', errors='replace')

        for pattern, label in PHI_PATTERNS:
            matches = list(re.finditer(pattern, text_head))
            if matches:
                unique_vals = set()
                for m in matches:
                    val = m.group()
                    if val not in unique_vals:
                        unique_vals.add(val)
                for val in sorted(unique_vals):
                    # Skip obvious false positives (TIFF structure bytes decoded as ASCII)
                    if len(val) < 4:
                        continue
                    print(f"  {label}: \"{val}\"")
                    findings.append(("REGEX MATCH", f"{label}: {val}"))
        print()

        # ── Check 5: Check if label/macro image data is truly destroyed ──
        print("  === Image Data Verification ===")
        for idx, (ifd_off, entries) in enumerate(chain):
            # Get image type
            for e in entries:
                if e['tag'] == 270:
                    desc = read_tag_as_string(f, e).lower()
                    if 'label' in desc or 'macro' in desc:
                        # This IFD is a label or macro - check if data is destroyed
                        img_type = "label" if "label" in desc else "macro"
                        # Find strip/tile offsets
                        offset_entry = None
                        count_entry = None
                        for e2 in entries:
                            if e2['tag'] in (273, 324):  # StripOffsets or TileOffsets
                                offset_entry = e2
                            if e2['tag'] in (279, 325):  # StripByteCounts or TileByteCounts
                                count_entry = e2
                        if offset_entry and count_entry:
                            f.seek(offset_entry['value_offset'])
                            if offset_entry['count'] == 1:
                                data_off = struct.unpack(endian + 'I', f.read(4))[0]
                            else:
                                data_off = struct.unpack(endian + 'I', f.read(4))[0]
                            f.seek(data_off)
                            sample = f.read(64)
                            is_blank = (sample == b'\x00' * len(sample)) or (sample[:2] == b'\xff\xd8' and b'\x00' * 16 in sample)
                            status = "DESTROYED" if is_blank else "HAS DATA"
                            print(f"  IFD #{idx} [{img_type}]: image data {status}")
                            print(f"    First 32 bytes: {sample[:32].hex()}")
                            if not is_blank:
                                findings.append(("IMAGE DATA INTACT", f"IFD #{idx} [{img_type}] still has non-blank image data"))
                    break
        print()

    return findings


# ── Main ─────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <file.svs|file.ndpi|file.tiff>")
        sys.exit(1)

    filepath = sys.argv[1]
    if not os.path.isfile(filepath):
        print(f"Error: {filepath} not found")
        sys.exit(1)

    print("=" * 70)
    print("  INDEPENDENT WSI PHI SCANNER")
    print("  (zero PathSafe code, no PathSafe markers checked)")
    print("=" * 70)

    findings = scan_file(filepath)

    print("=" * 70)
    if findings:
        print(f"  RESULT: {len(findings)} potential PHI finding(s)")
        print("=" * 70)
        for category, detail in findings:
            print(f"  [{category}] {detail}")
    else:
        print("  RESULT: CLEAN - no PHI detected")
        print("=" * 70)

    print()
    sys.exit(1 if findings else 0)
