"""Tests for the Excel lookup table reader (pathsafe.lookup)."""

import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import pytest

from pathsafe.lookup import (
    _col_letter_to_index,
    _normalize_header,
    load_lookup_table,
    read_excel_sheet,
)


# ---------------------------------------------------------------------------
# Helpers: build a minimal .xlsx file from Python data
# ---------------------------------------------------------------------------


def _build_xlsx(path: Path, sheet_name: str, rows: list[list[str]]) -> Path:
    """Create a minimal valid .xlsx file with one sheet.

    *rows* is a list of lists: the first sub-list is the header row.
    All values are stored via the shared-strings table (type "s").
    """
    # Collect unique strings and assign indices
    all_strings: list[str] = []
    seen: dict[str, int] = {}
    for row in rows:
        for val in row:
            if val not in seen:
                seen[val] = len(all_strings)
                all_strings.append(val)

    # shared strings XML
    ss_root = ET.Element(
        "sst",
        xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main",
        count=str(sum(len(r) for r in rows)),
        uniqueCount=str(len(all_strings)),
    )
    for s in all_strings:
        si = ET.SubElement(ss_root, "si")
        t = ET.SubElement(si, "t")
        t.text = s
    ss_xml = ET.tostring(ss_root, encoding="unicode", xml_declaration=True)

    # worksheet XML
    ws_root = ET.Element(
        "worksheet",
        xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    )
    sd = ET.SubElement(ws_root, "sheetData")
    for row_idx, row in enumerate(rows, start=1):
        r_elem = ET.SubElement(sd, "row", r=str(row_idx))
        for col_idx, val in enumerate(row):
            col_letter = chr(ord("A") + col_idx)
            ref = f"{col_letter}{row_idx}"
            c = ET.SubElement(r_elem, "c", r=ref, t="s")
            v = ET.SubElement(c, "v")
            v.text = str(seen[val])
    ws_xml = ET.tostring(ws_root, encoding="unicode", xml_declaration=True)

    # workbook XML (references sheet by name)
    wb_root = ET.Element(
        "workbook",
        xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    )
    sheets_elem = ET.SubElement(wb_root, "sheets")
    ET.SubElement(
        sheets_elem,
        "sheet",
        name=sheet_name,
        sheetId="1",
        **{"{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id": "rId1"},
    )
    wb_xml = ET.tostring(wb_root, encoding="unicode", xml_declaration=True)

    # workbook rels
    rels_root = ET.Element(
        "Relationships",
        xmlns="http://schemas.openxmlformats.org/package/2006/relationships",
    )
    ET.SubElement(
        rels_root,
        "Relationship",
        Id="rId1",
        Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet",
        Target="worksheets/sheet1.xml",
    )
    rels_xml = ET.tostring(rels_root, encoding="unicode", xml_declaration=True)

    # Write as ZIP
    xlsx_path = path / "test.xlsx"
    with zipfile.ZipFile(xlsx_path, "w") as zf:
        zf.writestr("xl/sharedStrings.xml", ss_xml)
        zf.writestr("xl/worksheets/sheet1.xml", ws_xml)
        zf.writestr("xl/workbook.xml", wb_xml)
        zf.writestr("xl/_rels/workbook.xml.rels", rels_xml)

    return xlsx_path


# ---------------------------------------------------------------------------
# Tests: read_excel_sheet
# ---------------------------------------------------------------------------


class TestReadExcelSheet:
    """read_excel_sheet: basic reading, column lookup, edge cases."""

    def test_basic_read(self, tmp_path):
        xlsx = _build_xlsx(
            tmp_path,
            "Sheet1",
            [
                ["id", "name", "group"],
                ["001", "Alice", "GroupA"],
                ["002", "Bob", "GroupB"],
                ["003", "Carol", "GroupA"],
            ],
        )
        result = read_excel_sheet(xlsx, "Sheet1", "id", ["name", "group"])
        assert len(result) == 3
        assert result["001"] == {"name": "Alice", "group": "GroupA"}
        assert result["002"] == {"name": "Bob", "group": "GroupB"}
        assert result["003"] == {"name": "Carol", "group": "GroupA"}

    def test_case_insensitive_columns(self, tmp_path):
        """Column matching should be case-insensitive."""
        xlsx = _build_xlsx(
            tmp_path,
            "Sheet1",
            [
                ["Patient_ID", "Slide_Name", "Group_ID"],
                ["P001", "slide_a", "GRP1"],
            ],
        )
        result = read_excel_sheet(xlsx, "Sheet1", "patient_id", ["slide_name", "group_id"])
        assert result["P001"] == {"slide_name": "slide_a", "group_id": "GRP1"}

    def test_whitespace_tolerant_columns(self, tmp_path):
        """Extra whitespace in column headers should be collapsed."""
        xlsx = _build_xlsx(
            tmp_path,
            "Sheet1",
            [
                ["  Patient  ID  ", " Slide Name ", "Group"],
                ["P001", "s1", "G1"],
            ],
        )
        result = read_excel_sheet(xlsx, "Sheet1", "patient id", ["slide name", "Group"])
        assert "P001" in result

    def test_missing_column_raises(self, tmp_path):
        xlsx = _build_xlsx(
            tmp_path,
            "Sheet1",
            [
                ["id", "name"],
                ["001", "Alice"],
            ],
        )
        with pytest.raises(ValueError, match="not found"):
            read_excel_sheet(xlsx, "Sheet1", "id", ["nonexistent_column"])

    def test_missing_key_column_raises(self, tmp_path):
        xlsx = _build_xlsx(
            tmp_path,
            "Sheet1",
            [
                ["id", "name"],
                ["001", "Alice"],
            ],
        )
        with pytest.raises(ValueError, match="not found"):
            read_excel_sheet(xlsx, "Sheet1", "missing_key", ["name"])

    def test_missing_sheet_raises(self, tmp_path):
        xlsx = _build_xlsx(
            tmp_path,
            "Sheet1",
            [
                ["id", "name"],
                ["001", "Alice"],
            ],
        )
        with pytest.raises(ValueError, match="not found"):
            read_excel_sheet(xlsx, "NoSuchSheet", "id", ["name"])

    def test_file_not_found_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            read_excel_sheet(tmp_path / "no_such_file.xlsx", "Sheet1", "id", ["name"])

    def test_empty_key_rows_skipped(self, tmp_path):
        """Rows with an empty key cell should be silently skipped."""
        xlsx = _build_xlsx(
            tmp_path,
            "Sheet1",
            [
                ["id", "name"],
                ["001", "Alice"],
                ["", "Blank"],
                ["003", "Carol"],
            ],
        )
        result = read_excel_sheet(xlsx, "Sheet1", "id", ["name"])
        assert len(result) == 2
        assert "001" in result
        assert "003" in result


# ---------------------------------------------------------------------------
# Tests: load_lookup_table
# ---------------------------------------------------------------------------


class TestLoadLookupTable:
    """load_lookup_table: grouping_map and rename_map extraction."""

    def test_grouping_and_rename(self, tmp_path):
        xlsx = _build_xlsx(
            tmp_path,
            "Data",
            [
                ["deidentified_identifier", "patient_id", "output_name"],
                ["UUID-001", "PAT-A", "slide_renamed_1"],
                ["UUID-002", "PAT-B", "slide_renamed_2"],
                ["UUID-003", "PAT-A", "slide_renamed_3"],
            ],
        )
        grouping, rename = load_lookup_table(
            xlsx,
            "Data",
            source_column="deidentified_identifier",
            group_column="patient_id",
            rename_column="output_name",
        )
        assert grouping == {
            "UUID-001": "PAT-A",
            "UUID-002": "PAT-B",
            "UUID-003": "PAT-A",
        }
        assert rename == {
            "UUID-001": "slide_renamed_1",
            "UUID-002": "slide_renamed_2",
            "UUID-003": "slide_renamed_3",
        }

    def test_grouping_only_no_rename(self, tmp_path):
        """When rename_column is None, rename_map should be empty."""
        xlsx = _build_xlsx(
            tmp_path,
            "Sheet1",
            [
                ["slide_id", "patient"],
                ["S001", "P1"],
                ["S002", "P2"],
            ],
        )
        grouping, rename = load_lookup_table(
            xlsx,
            "Sheet1",
            source_column="slide_id",
            group_column="patient",
            rename_column=None,
        )
        assert grouping == {"S001": "P1", "S002": "P2"}
        assert rename == {}

    def test_missing_group_column_raises(self, tmp_path):
        xlsx = _build_xlsx(
            tmp_path,
            "Sheet1",
            [
                ["id", "name"],
                ["001", "Alice"],
            ],
        )
        with pytest.raises(ValueError, match="not found"):
            load_lookup_table(
                xlsx,
                "Sheet1",
                source_column="id",
                group_column="nonexistent",
            )

    def test_case_insensitive_lookup(self, tmp_path):
        """Column names in load_lookup_table should be case-insensitive."""
        xlsx = _build_xlsx(
            tmp_path,
            "Sheet1",
            [
                ["Deidentified_Identifier", "Patient_ID"],
                ["U1", "P1"],
            ],
        )
        grouping, _ = load_lookup_table(
            xlsx,
            "Sheet1",
            source_column="deidentified_identifier",
            group_column="patient_id",
        )
        assert grouping == {"U1": "P1"}


# ---------------------------------------------------------------------------
# Tests: helper functions
# ---------------------------------------------------------------------------


class TestHelpers:
    def test_normalize_header(self):
        assert _normalize_header("  Patient  ID  ") == "patient id"
        assert _normalize_header("Name") == "name"
        assert _normalize_header("  a   B  c ") == "a b c"

    def test_col_letter_to_index(self):
        assert _col_letter_to_index("A") == 0
        assert _col_letter_to_index("B") == 1
        assert _col_letter_to_index("Z") == 25
        assert _col_letter_to_index("AA") == 26
        assert _col_letter_to_index("AB") == 27
