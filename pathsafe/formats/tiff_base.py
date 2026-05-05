"""Intermediate base class for TIFF-based WSI format handlers.

Extracts duplicated methods that are nearly identical across SVS, BIF,
SCN, GenericTIFF, and NDPI handlers:
- DateTime tag scanning/deidentification
- EXIF/GPS sub-IFD scanning/deidentification
- Extra metadata tag scanning/deidentification (includes EXIF/GPS)
- Label/macro image detection and blanking
- Regex safety scanning/deidentification

Subclasses customize behavior via class attributes and method overrides.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, BinaryIO

from pathsafe.formats.base import FormatHandler
from pathsafe.models import PHIFinding
from pathsafe.scanner import (
    DEFAULT_SCAN_SIZE,
    is_date_deidentified,
    scan_bytes_for_phi,
)
from pathsafe.tiff import (
    EXIF_SUB_IFD_PHI_TAGS,
    EXTRA_METADATA_TAGS,
    GPS_TAG_NAMES,
    blank_extra_metadata_tag,
    blank_ifd_image_data,
    get_ifd_image_data_size,
    get_ifd_image_size,
    is_ifd_image_blanked,
    iter_ifds,
    read_exif_sub_ifd,
    read_gps_sub_ifd,
    read_header,
    read_tag_string,
    scan_exif_sub_ifd_tags,
    scan_extra_metadata_tags,
    scan_gps_sub_ifd,
    scan_sub_ifds,
    unlink_ifd,
)


class TiffFormatHandler(FormatHandler):
    """Intermediate base for TIFF-based WSI format handlers.

    Provides default implementations for common TIFF scanning and
    deidentification operations. Subclasses override class attributes
    and specific methods for format-specific behavior.
    """

    # Standard TIFF date tags -- subclasses may override
    date_tags: dict[int, str] = {
        306: "DateTime",
        36867: "DateTimeOriginal",
        36868: "DateTimeDigitized",
    }

    # Tags to exclude from extra metadata scanning because the handler
    # processes them itself. E.g., SVS excludes {270}, BIF excludes {270, 700}.
    extra_metadata_exclude_tags: set[int] = set()

    # ----------------------------------------------------------------
    # DateTime tag scanning / deidentification
    # ----------------------------------------------------------------

    def _scan_datetime_tags(self, filepath: Path) -> list[PHIFinding]:
        """Scan DateTime tags across all IFDs with seen_offsets dedup."""
        findings: list[PHIFinding] = []
        seen: set = set()
        with open(filepath, "rb") as f:
            header = read_header(f)
            if header is None:
                return findings
            for _, entries in iter_ifds(f, header):
                for entry in entries:
                    if entry.tag_id in self.date_tags and entry.value_offset not in seen:
                        seen.add(entry.value_offset)
                        value = read_tag_string(f, entry)
                        if value and not is_date_deidentified(value):
                            findings.append(
                                PHIFinding(
                                    offset=entry.value_offset,
                                    length=entry.total_size,
                                    tag_id=entry.tag_id,
                                    tag_name=self.date_tags[entry.tag_id],
                                    value_preview=value[:30],
                                    source="tiff_tag",
                                )
                            )
        return findings

    def _deidentify_datetime_tags(self, filepath: Path) -> list[PHIFinding]:
        """Deidentify DateTime tags by writing null bytes across all IFDs."""
        cleared: list[PHIFinding] = []
        seen: set = set()
        with open(filepath, "r+b") as f:
            header = read_header(f)
            if header is None:
                return cleared
            for _, entries in iter_ifds(f, header):
                for entry in entries:
                    if entry.tag_id in self.date_tags and entry.value_offset not in seen:
                        seen.add(entry.value_offset)
                        value = read_tag_string(f, entry)
                        if value and not is_date_deidentified(value):
                            f.seek(entry.value_offset)
                            f.write(b"\x00" * entry.total_size)
                            cleared.append(
                                PHIFinding(
                                    offset=entry.value_offset,
                                    length=entry.total_size,
                                    tag_id=entry.tag_id,
                                    tag_name=self.date_tags[entry.tag_id],
                                    value_preview=value[:30],
                                    source="tiff_tag",
                                )
                            )
        return cleared

    # ----------------------------------------------------------------
    # EXIF / GPS sub-IFD scanning / deidentification
    # ----------------------------------------------------------------

    @staticmethod
    def _scan_exif_gps_entries(f: BinaryIO, header, entries: list, seen: set) -> list[PHIFinding]:
        """Scan EXIF and GPS sub-IFDs for a single IFD's entries.

        Works on an already-open file handle. Used by both the file-level
        convenience methods and format handlers (like NDPI) that manage
        their own file handle and IFD iteration.

        Args:
            f: Open file handle (read mode).
            header: Parsed TIFFHeader.
            entries: IFD entries to inspect for EXIF/GPS pointer tags.
            seen: Shared set of value_offsets for dedup (modified in place).

        Returns:
            List of PHIFinding for EXIF/GPS tags with non-empty PHI content.
        """
        findings: list[PHIFinding] = []

        # EXIF sub-IFD scanning
        exif_result = read_exif_sub_ifd(f, header, entries)
        if exif_result is not None:
            _, sub_entries = exif_result
            for sub_entry, value in scan_exif_sub_ifd_tags(f, header, sub_entries):
                if sub_entry.value_offset not in seen:
                    seen.add(sub_entry.value_offset)
                    findings.append(
                        PHIFinding(
                            offset=sub_entry.value_offset,
                            length=sub_entry.total_size,
                            tag_id=sub_entry.tag_id,
                            tag_name=f"EXIF:{EXIF_SUB_IFD_PHI_TAGS[sub_entry.tag_id]}",
                            value_preview=value[:50],
                            source="tiff_tag",
                        )
                    )

        # GPS sub-IFD scanning
        gps_result = read_gps_sub_ifd(f, header, entries)
        if gps_result is not None:
            _, sub_entries = gps_result
            for sub_entry, preview in scan_gps_sub_ifd(f, header, sub_entries):
                if sub_entry.value_offset not in seen:
                    seen.add(sub_entry.value_offset)
                    findings.append(
                        PHIFinding(
                            offset=sub_entry.value_offset,
                            length=sub_entry.total_size,
                            tag_id=sub_entry.tag_id,
                            tag_name=f"GPS:{GPS_TAG_NAMES.get(sub_entry.tag_id, f'Tag_{sub_entry.tag_id}')}",
                            value_preview=preview[:50],
                            source="tiff_tag",
                        )
                    )

        return findings

    @staticmethod
    def _deidentify_exif_gps_entries(
        f: BinaryIO, header, entries: list, seen: set
    ) -> list[PHIFinding]:
        """Blank EXIF and GPS sub-IFD PHI tags for a single IFD's entries.

        Works on an already-open file handle in r+b mode.

        Args:
            f: Open file handle (r+b mode).
            header: Parsed TIFFHeader.
            entries: IFD entries to inspect for EXIF/GPS pointer tags.
            seen: Shared set of value_offsets for dedup (modified in place).

        Returns:
            List of PHIFinding for blanked EXIF/GPS tags.
        """
        cleared: list[PHIFinding] = []

        # Blank EXIF sub-IFD PHI tags
        exif_result = read_exif_sub_ifd(f, header, entries)
        if exif_result is not None:
            _, sub_entries = exif_result
            for sub_entry, value in scan_exif_sub_ifd_tags(f, header, sub_entries):
                if sub_entry.value_offset not in seen:
                    seen.add(sub_entry.value_offset)
                    f.seek(sub_entry.value_offset)
                    f.write(b"\x00" * sub_entry.total_size)
                    cleared.append(
                        PHIFinding(
                            offset=sub_entry.value_offset,
                            length=sub_entry.total_size,
                            tag_id=sub_entry.tag_id,
                            tag_name=f"EXIF:{EXIF_SUB_IFD_PHI_TAGS[sub_entry.tag_id]}",
                            value_preview=value[:50],
                            source="tiff_tag",
                        )
                    )

        # Blank GPS sub-IFD entirely
        gps_result = read_gps_sub_ifd(f, header, entries)
        if gps_result is not None:
            _, sub_entries = gps_result
            for sub_entry, preview in scan_gps_sub_ifd(f, header, sub_entries):
                if sub_entry.value_offset not in seen:
                    seen.add(sub_entry.value_offset)
                    f.seek(sub_entry.value_offset)
                    f.write(b"\x00" * sub_entry.total_size)
                    cleared.append(
                        PHIFinding(
                            offset=sub_entry.value_offset,
                            length=sub_entry.total_size,
                            tag_id=sub_entry.tag_id,
                            tag_name=f"GPS:{GPS_TAG_NAMES.get(sub_entry.tag_id, f'Tag_{sub_entry.tag_id}')}",
                            value_preview=preview[:50],
                            source="tiff_tag",
                        )
                    )

        return cleared

    def _scan_exif_gps(self, filepath: Path, seen: set | None = None) -> list[PHIFinding]:
        """Scan EXIF and GPS sub-IFDs across all IFDs.

        Args:
            seen: Optional shared set of already-seen value_offsets for dedup.
                  If None, a local set is used.
        """
        if seen is None:
            seen = set()
        findings: list[PHIFinding] = []
        with open(filepath, "rb") as f:
            header = read_header(f)
            if header is None:
                return findings
            for _, entries in iter_ifds(f, header):
                findings.extend(self._scan_exif_gps_entries(f, header, entries, seen))
        return findings

    def _deidentify_exif_gps(self, filepath: Path, seen: set | None = None) -> list[PHIFinding]:
        """Deidentify EXIF and GPS sub-IFDs across all IFDs.

        Args:
            seen: Optional shared set of already-seen value_offsets for dedup.
                  If None, a local set is used.
        """
        if seen is None:
            seen = set()
        cleared: list[PHIFinding] = []
        with open(filepath, "r+b") as f:
            header = read_header(f)
            if header is None:
                return cleared
            for _, entries in iter_ifds(f, header):
                cleared.extend(self._deidentify_exif_gps_entries(f, header, entries, seen))
        return cleared

    # ----------------------------------------------------------------
    # Extra metadata scanning / deidentification (includes EXIF/GPS)
    # ----------------------------------------------------------------

    def _scan_extra_metadata(self, filepath: Path) -> list[PHIFinding]:
        """Scan extra metadata tags (XMP, ICC, IPTC, etc.) plus EXIF/GPS and SubIFDs.

        Uses ``self.extra_metadata_exclude_tags`` for the exclude set.
        """
        findings: list[PHIFinding] = []
        seen: set = set()
        with open(filepath, "rb") as f:
            header = read_header(f)
            if header is None:
                return findings
            for _, entries in iter_ifds(f, header):
                for entry, value in scan_extra_metadata_tags(
                    f, header, entries, exclude_tags=self.extra_metadata_exclude_tags or None
                ):
                    if entry.value_offset not in seen:
                        seen.add(entry.value_offset)
                        findings.append(
                            PHIFinding(
                                offset=entry.value_offset,
                                length=entry.total_size,
                                tag_id=entry.tag_id,
                                tag_name=EXTRA_METADATA_TAGS[entry.tag_id],
                                value_preview=value[:50],
                                source="tiff_tag",
                            )
                        )

                # EXIF sub-IFD scanning
                exif_result = read_exif_sub_ifd(f, header, entries)
                if exif_result is not None:
                    _, sub_entries = exif_result
                    for sub_entry, value in scan_exif_sub_ifd_tags(f, header, sub_entries):
                        if sub_entry.value_offset not in seen:
                            seen.add(sub_entry.value_offset)
                            findings.append(
                                PHIFinding(
                                    offset=sub_entry.value_offset,
                                    length=sub_entry.total_size,
                                    tag_id=sub_entry.tag_id,
                                    tag_name=f"EXIF:{EXIF_SUB_IFD_PHI_TAGS[sub_entry.tag_id]}",
                                    value_preview=value[:50],
                                    source="tiff_tag",
                                )
                            )

                # GPS sub-IFD scanning
                gps_result = read_gps_sub_ifd(f, header, entries)
                if gps_result is not None:
                    _, sub_entries = gps_result
                    for sub_entry, preview in scan_gps_sub_ifd(f, header, sub_entries):
                        if sub_entry.value_offset not in seen:
                            seen.add(sub_entry.value_offset)
                            findings.append(
                                PHIFinding(
                                    offset=sub_entry.value_offset,
                                    length=sub_entry.total_size,
                                    tag_id=sub_entry.tag_id,
                                    tag_name=f"GPS:{GPS_TAG_NAMES.get(sub_entry.tag_id, f'Tag_{sub_entry.tag_id}')}",
                                    value_preview=preview[:50],
                                    source="tiff_tag",
                                )
                            )

                # SubIFD (tag 330) traversal
                for sub_entry, value in scan_sub_ifds(f, header, entries):
                    if sub_entry.value_offset not in seen:
                        seen.add(sub_entry.value_offset)
                        tag_label = EXTRA_METADATA_TAGS.get(
                            sub_entry.tag_id,
                            EXIF_SUB_IFD_PHI_TAGS.get(sub_entry.tag_id, f"Tag_{sub_entry.tag_id}"),
                        )
                        findings.append(
                            PHIFinding(
                                offset=sub_entry.value_offset,
                                length=sub_entry.total_size,
                                tag_id=sub_entry.tag_id,
                                tag_name=f"SubIFD:{tag_label}",
                                value_preview=value[:50],
                                source="tiff_tag",
                            )
                        )
        return findings

    def _deidentify_extra_metadata(self, filepath: Path) -> list[PHIFinding]:
        """Deidentify extra metadata tags plus EXIF/GPS sub-IFDs and SubIFDs.

        Uses ``self.extra_metadata_exclude_tags`` for the exclude set.
        """
        cleared: list[PHIFinding] = []
        seen: set = set()
        with open(filepath, "r+b") as f:
            header = read_header(f)
            if header is None:
                return cleared
            for _, entries in iter_ifds(f, header):
                for entry, value in scan_extra_metadata_tags(
                    f, header, entries, exclude_tags=self.extra_metadata_exclude_tags or None
                ):
                    if entry.value_offset not in seen:
                        seen.add(entry.value_offset)
                        blank_extra_metadata_tag(f, entry)
                        cleared.append(
                            PHIFinding(
                                offset=entry.value_offset,
                                length=entry.total_size,
                                tag_id=entry.tag_id,
                                tag_name=EXTRA_METADATA_TAGS[entry.tag_id],
                                value_preview=value[:50],
                                source="tiff_tag",
                            )
                        )

                # Blank EXIF sub-IFD PHI tags
                exif_result = read_exif_sub_ifd(f, header, entries)
                if exif_result is not None:
                    _, sub_entries = exif_result
                    for sub_entry, value in scan_exif_sub_ifd_tags(f, header, sub_entries):
                        if sub_entry.value_offset not in seen:
                            seen.add(sub_entry.value_offset)
                            f.seek(sub_entry.value_offset)
                            f.write(b"\x00" * sub_entry.total_size)
                            cleared.append(
                                PHIFinding(
                                    offset=sub_entry.value_offset,
                                    length=sub_entry.total_size,
                                    tag_id=sub_entry.tag_id,
                                    tag_name=f"EXIF:{EXIF_SUB_IFD_PHI_TAGS[sub_entry.tag_id]}",
                                    value_preview=value[:50],
                                    source="tiff_tag",
                                )
                            )

                # Blank GPS sub-IFD entirely
                gps_result = read_gps_sub_ifd(f, header, entries)
                if gps_result is not None:
                    _, sub_entries = gps_result
                    for sub_entry, preview in scan_gps_sub_ifd(f, header, sub_entries):
                        if sub_entry.value_offset not in seen:
                            seen.add(sub_entry.value_offset)
                            f.seek(sub_entry.value_offset)
                            f.write(b"\x00" * sub_entry.total_size)
                            cleared.append(
                                PHIFinding(
                                    offset=sub_entry.value_offset,
                                    length=sub_entry.total_size,
                                    tag_id=sub_entry.tag_id,
                                    tag_name=f"GPS:{GPS_TAG_NAMES.get(sub_entry.tag_id, f'Tag_{sub_entry.tag_id}')}",
                                    value_preview=preview[:50],
                                    source="tiff_tag",
                                )
                            )

                # Blank PHI in SubIFDs (tag 330)
                # First scan to capture findings for reporting, then blank
                for sub_entry, value in scan_sub_ifds(f, header, entries):
                    if sub_entry.value_offset not in seen:
                        seen.add(sub_entry.value_offset)
                        tag_label = EXTRA_METADATA_TAGS.get(
                            sub_entry.tag_id,
                            EXIF_SUB_IFD_PHI_TAGS.get(sub_entry.tag_id, f"Tag_{sub_entry.tag_id}"),
                        )
                        f.seek(sub_entry.value_offset)
                        f.write(b"\x00" * sub_entry.total_size)
                        cleared.append(
                            PHIFinding(
                                offset=sub_entry.value_offset,
                                length=sub_entry.total_size,
                                tag_id=sub_entry.tag_id,
                                tag_name=f"SubIFD:{tag_label}",
                                value_preview=value[:50],
                                source="tiff_tag",
                            )
                        )
        return cleared

    # ----------------------------------------------------------------
    # Label / macro image detection and blanking
    # ----------------------------------------------------------------

    def _detect_label_macro_type(self, f: BinaryIO, entries: list[Any]) -> str | None:
        """Determine image type from tag 270 ImageDescription.

        Returns 'LabelImage', 'MacroImage', or None.
        Subclasses can override to add format-specific types
        (e.g., BIF adds 'ThumbnailImage').
        """
        for entry in entries:
            if entry.tag_id == 270:
                desc = read_tag_string(f, entry).lower()
                if "label" in desc:
                    return "LabelImage"
                elif "macro" in desc:
                    return "MacroImage"
                return None
        return None

    def _scan_label_macro(self, filepath: Path) -> list[PHIFinding]:
        """Detect label and macro images across all IFDs."""
        findings: list[PHIFinding] = []
        with open(filepath, "rb") as f:
            header = read_header(f)
            if header is None:
                return findings

            for ifd_offset, entries in iter_ifds(f, header):
                img_type = self._detect_label_macro_type(f, entries)
                if img_type:
                    if is_ifd_image_blanked(f, header, entries):
                        continue
                    w, h = get_ifd_image_size(header, entries, f)
                    data_size = get_ifd_image_data_size(header, entries, f)
                    if data_size > 0:
                        findings.append(
                            PHIFinding(
                                offset=ifd_offset,
                                length=data_size,
                                tag_id=None,
                                tag_name=img_type,
                                value_preview=(f"{img_type} {w}x{h} ({data_size / 1024:.0f}KB)"),
                                source="image_content",
                            )
                        )
        return findings

    def _blank_label_macro(self, filepath: Path) -> list[PHIFinding]:
        """Blank and unlink label/macro image IFDs."""
        cleared: list[PHIFinding] = []
        with open(filepath, "r+b") as f:
            header = read_header(f)
            if header is None:
                return cleared

            for ifd_offset, entries in iter_ifds(f, header):
                img_type = self._detect_label_macro_type(f, entries)
                if img_type:
                    if is_ifd_image_blanked(f, header, entries):
                        # Already blanked but may still be linked -- unlink it
                        unlink_ifd(f, header, ifd_offset)
                        continue
                    w, h = get_ifd_image_size(header, entries, f)
                    blanked = blank_ifd_image_data(f, header, entries)
                    if blanked > 0:
                        unlink_ifd(f, header, ifd_offset)
                        cleared.append(
                            PHIFinding(
                                offset=ifd_offset,
                                length=blanked,
                                tag_id=None,
                                tag_name=img_type,
                                value_preview=(
                                    f"blanked {img_type} {w}x{h} ({blanked / 1024:.0f}KB)"
                                ),
                                source="image_content",
                            )
                        )
        return cleared

    # ----------------------------------------------------------------
    # Regex safety scanning / deidentification
    # ----------------------------------------------------------------

    def _scan_regex(self, filepath: Path, skip_offsets: set[int] | None = None) -> list[PHIFinding]:
        """Regex safety scan of header bytes."""
        with open(filepath, "rb") as f:
            data = f.read(DEFAULT_SCAN_SIZE)
        raw_findings = scan_bytes_for_phi(data, skip_offsets=skip_offsets)
        findings: list[PHIFinding] = []
        for offset, length, matched, label in raw_findings:
            value = matched.decode("ascii", errors="replace")
            findings.append(
                PHIFinding(
                    offset=offset,
                    length=length,
                    tag_id=None,
                    tag_name=f"regex:{label}",
                    value_preview=value[:50],
                    source="regex_scan",
                )
            )
        return findings

    def _deidentify_regex(self, filepath: Path, skip_offsets: set[int]) -> list[PHIFinding]:
        """Regex safety scan + deidentify stragglers."""
        with open(filepath, "rb") as f:
            data = f.read(DEFAULT_SCAN_SIZE)
        raw_findings = scan_bytes_for_phi(data, skip_offsets=skip_offsets)
        if not raw_findings:
            return []
        cleared: list[PHIFinding] = []
        with open(filepath, "r+b") as f:
            for offset, length, matched, label in raw_findings:
                value = matched.decode("ascii", errors="replace")
                f.seek(offset)
                f.write(b"X" * length)
                cleared.append(
                    PHIFinding(
                        offset=offset,
                        length=length,
                        tag_id=None,
                        tag_name=f"regex:{label}",
                        value_preview=value[:50],
                        source="regex_scan",
                    )
                )
        return cleared
