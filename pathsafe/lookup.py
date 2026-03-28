"""Excel (.xlsx) lookup table reader for PathSafe.

Reads XLSX files using only the standard library (zipfile + ElementTree),
with no dependency on openpyxl or pandas.  The low-level helpers are
ported from the LungAI-scripts project and generalized so they work with
any spreadsheet that has identifiable column headers.

Typical usage::

    grouping_map, rename_map = load_lookup_table(
        Path("study.xlsx"),
        sheet_name="Sheet1",
        source_column="anonymized_identifier",
        group_column="patient_id",
        rename_column="output_name",
    )

"""

from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
import zipfile
from collections.abc import Iterable
from pathlib import Path


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# XML namespaces used inside XLSX (Office Open XML)
# ---------------------------------------------------------------------------

_NS = {
    "main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
}


# ---------------------------------------------------------------------------
# Low-level XLSX helpers (zipfile + ElementTree, no openpyxl)
# ---------------------------------------------------------------------------


def _get_shared_strings(zf: zipfile.ZipFile) -> list[str]:
    """Read the shared-strings table from an open XLSX zip."""
    try:
        xml_bytes = zf.read("xl/sharedStrings.xml")
    except KeyError:
        return []
    root = ET.fromstring(xml_bytes)
    strings: list[str] = []
    for si in root.findall("main:si", _NS):
        text_parts: list[str] = []
        for t in si.findall(".//main:t", _NS):
            text_parts.append(t.text or "")
        strings.append("".join(text_parts))
    return strings


def _get_sheet_path(zf: zipfile.ZipFile, sheet_name: str) -> str | None:
    """Resolve a sheet name to its internal zip path (e.g. ``xl/worksheets/sheet1.xml``)."""
    wb = ET.fromstring(zf.read("xl/workbook.xml"))
    sheets = wb.find("main:sheets", _NS)
    if sheets is None:
        return None
    sheet_id: str | None = None
    for s in sheets.findall("main:sheet", _NS):
        if s.attrib.get("name") == sheet_name:
            sheet_id = s.attrib.get("{{{}}}id".format(_NS["r"]))
            break
    if sheet_id is None:
        return None
    rels = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
    for rel in rels.findall(
        "{http://schemas.openxmlformats.org/package/2006/relationships}Relationship"
    ):
        if rel.attrib.get("Id") == sheet_id:
            return "xl/" + rel.attrib["Target"].lstrip("/")
    return None


def _col_letter_to_index(col: str) -> int:
    """Convert an Excel column letter (A, B, ..., AA, AB, ...) to a 0-based index."""
    idx = 0
    for c in col:
        idx = idx * 26 + (ord(c.upper()) - ord("A") + 1)
    return idx - 1


def _iter_sheet_rows(
    zf: zipfile.ZipFile,
    sheet_path: str,
    shared_strings: list[str],
) -> Iterable[list[str]]:
    """Yield rows from a worksheet as lists of string values.

    Cell references are resolved via the shared-strings table when the
    cell type is ``s`` (shared string).  Inline strings (``inlineStr``)
    and raw values are returned as-is.
    """
    ns_uri = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    with zf.open(sheet_path) as f:
        context = ET.iterparse(f, events=("start", "end"))
        for event, elem in context:
            if event == "end" and elem.tag.endswith("row"):
                values: dict[int, str] = {}
                for c in elem.findall(f".//{{{ns_uri}}}c"):
                    ref = c.attrib.get("r")
                    if not ref:
                        continue
                    col = "".join(ch for ch in ref if ch.isalpha())
                    col_idx = _col_letter_to_index(col)
                    cell_type = c.attrib.get("t")
                    v = c.find(f"{{{ns_uri}}}v")
                    if cell_type == "s":
                        if v is not None:
                            try:
                                values[col_idx] = shared_strings[int(v.text)]
                            except Exception:
                                values[col_idx] = v.text or ""
                        else:
                            values[col_idx] = ""
                    elif cell_type == "inlineStr":
                        t = c.find(f".//{{{ns_uri}}}t")
                        values[col_idx] = t.text if t is not None else ""
                    else:
                        values[col_idx] = v.text if v is not None else ""

                if values:
                    max_idx = max(values.keys())
                    row = [values.get(i, "") for i in range(max_idx + 1)]
                    yield row
                elem.clear()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def _normalize_header(name: str) -> str:
    """Normalize a column header for case-insensitive, whitespace-tolerant matching."""
    return re.sub(r"\s+", " ", name.strip()).lower()


def _find_column_index(
    header_norm: list[str],
    column_name: str,
    context: str = "",
) -> int:
    """Find the index of *column_name* in a normalized header row.

    Raises :class:`ValueError` if the column is not found.
    """
    target = _normalize_header(column_name)
    for i, h in enumerate(header_norm):
        if h == target:
            return i
    available = ", ".join(repr(h) for h in header_norm)
    raise ValueError(f"{context}Column '{column_name}' not found. Available columns: [{available}]")


def read_excel_sheet(
    excel_path: Path,
    sheet_name: str,
    key_column: str,
    value_columns: list[str],
) -> dict[str, dict[str, str]]:
    """Read an Excel sheet and return ``{key: {col: value}}`` for every row.

    Column matching is case-insensitive and whitespace-tolerant (leading /
    trailing spaces and extra internal whitespace are collapsed).

    Args:
        excel_path: Path to the ``.xlsx`` file.
        sheet_name: Worksheet name (exact, case-sensitive).
        key_column: Header of the column whose values become dict keys.
        value_columns: Headers of the columns to include as values.

    Returns:
        A dict mapping each unique key to a dict of
        ``{value_column: cell_value}``.  Rows with an empty key are
        skipped silently.

    Raises:
        FileNotFoundError: If *excel_path* does not exist.
        ValueError: If the sheet or any requested column is not found.
    """
    excel_path = Path(excel_path)
    if not excel_path.exists():
        raise FileNotFoundError(f"Excel file not found: {excel_path}")

    with zipfile.ZipFile(excel_path) as zf:
        sheet_path = _get_sheet_path(zf, sheet_name)
        if sheet_path is None:
            raise ValueError(f"Sheet '{sheet_name}' not found in {excel_path.name}")

        shared = _get_shared_strings(zf)
        rows = _iter_sheet_rows(zf, sheet_path, shared)

        # First row is the header
        try:
            header = next(rows)
        except StopIteration:
            raise ValueError(f"Sheet '{sheet_name}' is empty (no header row)") from None

        header_norm = [_normalize_header(h) for h in header]

        ctx = f"In sheet '{sheet_name}': "
        key_idx = _find_column_index(header_norm, key_column, context=ctx)
        value_indices: dict[str, int] = {}
        for vc in value_columns:
            value_indices[vc] = _find_column_index(header_norm, vc, context=ctx)

        result: dict[str, dict[str, str]] = {}
        for row in rows:
            key_val = (row[key_idx] if key_idx < len(row) else "").strip()
            if not key_val:
                continue
            entry: dict[str, str] = {}
            for col_name, col_idx in value_indices.items():
                entry[col_name] = (row[col_idx] if col_idx < len(row) else "").strip()
            result[key_val] = entry

    logger.info(
        "Read %d rows from %s [%s] (key=%s)",
        len(result),
        excel_path.name,
        sheet_name,
        key_column,
    )
    return result


def load_lookup_table(
    excel_path: Path,
    sheet_name: str,
    source_column: str,
    group_column: str,
    rename_column: str | None = None,
) -> tuple[dict[str, str], dict[str, str]]:
    """Load a lookup table and return ``(grouping_map, rename_map)``.

    This is a convenience wrapper around :func:`read_excel_sheet` that
    returns two flat dicts ready to plug into
    :class:`~pathsafe.serializer.SerializerConfig`.

    Args:
        excel_path: Path to the ``.xlsx`` file.
        sheet_name: Worksheet name.
        source_column: Column containing the identifier to match against
            filenames (used as the dict key).
        group_column: Column containing the patient / group ID for
            subfolder organization.
        rename_column: Optional column containing the desired output
            filename.  If ``None``, the rename map is returned empty.

    Returns:
        A 2-tuple of:
        - **grouping_map** -- ``{source_id: group_id}``
        - **rename_map** -- ``{source_id: output_name}`` (empty dict when
          *rename_column* is ``None``).

    Raises:
        FileNotFoundError: If *excel_path* does not exist.
        ValueError: If the sheet or any requested column is not found.
    """
    value_cols = [group_column]
    if rename_column is not None:
        value_cols.append(rename_column)

    data = read_excel_sheet(
        excel_path,
        sheet_name=sheet_name,
        key_column=source_column,
        value_columns=value_cols,
    )

    grouping_map: dict[str, str] = {}
    rename_map: dict[str, str] = {}

    for source_id, values in data.items():
        group_val = values.get(group_column, "").strip()
        if group_val:
            grouping_map[source_id] = group_val

        if rename_column is not None:
            rename_val = values.get(rename_column, "").strip()
            if rename_val:
                rename_map[source_id] = rename_val

    logger.info(
        "Lookup table: %d grouping entries, %d rename entries",
        len(grouping_map),
        len(rename_map),
    )
    return grouping_map, rename_map
