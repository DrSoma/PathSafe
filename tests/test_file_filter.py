"""Tests for file filtering (include/exclude/filter-file)."""

import json
from pathlib import Path

import pytest

from pathsafe.serializer import apply_filters, load_filter_file


class TestApplyFilters:
    """Tests for apply_filters()."""

    def _make_paths(self, names):
        return [Path(f"/slides/{n}") for n in names]

    def test_no_filters_returns_all(self):
        files = self._make_paths(["a.ndpi", "b.svs", "c.ndpi"])
        result = apply_filters(files)
        assert result == files

    def test_include_single_pattern(self):
        files = self._make_paths(["case1_HE.ndpi", "case1_CK7.ndpi", "case2_HE.svs"])
        result = apply_filters(files, include=["*HE*"])
        assert [f.name for f in result] == ["case1_HE.ndpi", "case2_HE.svs"]

    def test_include_multiple_patterns(self):
        files = self._make_paths(["slide_HE.ndpi", "slide_CK7.ndpi", "slide_PDL1.svs"])
        result = apply_filters(files, include=["*HE*", "*PDL1*"])
        assert [f.name for f in result] == ["slide_HE.ndpi", "slide_PDL1.svs"]

    def test_exclude_single_pattern(self):
        files = self._make_paths(["case1_HE.ndpi", "case1_CK7.ndpi", "case2_HE.svs"])
        result = apply_filters(files, exclude=["*CK7*"])
        assert [f.name for f in result] == ["case1_HE.ndpi", "case2_HE.svs"]

    def test_exclude_multiple_patterns(self):
        files = self._make_paths(["a_HE.ndpi", "b_CK7.ndpi", "c_PDL1.ndpi", "d_HE.svs"])
        result = apply_filters(files, exclude=["*CK7*", "*PDL1*"])
        assert [f.name for f in result] == ["a_HE.ndpi", "d_HE.svs"]

    def test_include_and_exclude_combined(self):
        """Include first, then exclude from the result."""
        files = self._make_paths(
            [
                "case1_HE.ndpi",
                "case1_CK7.ndpi",
                "case2_HE.svs",
                "case2_HE_frozen.svs",
            ]
        )
        result = apply_filters(files, include=["*HE*"], exclude=["*frozen*"])
        assert [f.name for f in result] == ["case1_HE.ndpi", "case2_HE.svs"]

    def test_include_by_extension(self):
        files = self._make_paths(["a.ndpi", "b.svs", "c.ndpi", "d.mrxs"])
        result = apply_filters(files, include=["*.ndpi"])
        assert [f.name for f in result] == ["a.ndpi", "c.ndpi"]

    def test_all_filtered_returns_empty(self):
        files = self._make_paths(["a_CK7.ndpi", "b_PDL1.ndpi"])
        result = apply_filters(files, include=["*HE*"])
        assert result == []

    def test_preserves_order(self):
        files = self._make_paths(["z.ndpi", "a.ndpi", "m.ndpi"])
        result = apply_filters(files, include=["*.ndpi"])
        assert [f.name for f in result] == ["z.ndpi", "a.ndpi", "m.ndpi"]


class TestLoadFilterFile:
    """Tests for load_filter_file() with different formats."""

    def test_plain_text(self, tmp_path):
        f = tmp_path / "filter.txt"
        f.write_text("slide1.ndpi\nslide2.svs\n# comment\n\nslide3.ndpi\n")
        result = load_filter_file(f)
        assert result == {"slide1.ndpi", "slide2.svs", "slide3.ndpi"}

    def test_plain_text_strips_paths(self, tmp_path):
        f = tmp_path / "filter.txt"
        f.write_text("/data/slides/slide1.ndpi\nslide2.svs\n")
        result = load_filter_file(f)
        assert result == {"slide1.ndpi", "slide2.svs"}

    def test_csv_with_file_column(self, tmp_path):
        f = tmp_path / "filter.csv"
        f.write_text("filename,stain,confidence\nslide1.ndpi,H&E,0.95\nslide2.svs,H&E,0.88\n")
        result = load_filter_file(f)
        assert result == {"slide1.ndpi", "slide2.svs"}

    def test_csv_falls_back_to_first_column(self, tmp_path):
        f = tmp_path / "filter.csv"
        f.write_text("slide_name,stain\nslide1.ndpi,HE\nslide2.svs,HE\n")
        result = load_filter_file(f)
        assert result == {"slide1.ndpi", "slide2.svs"}

    def test_json_list(self, tmp_path):
        f = tmp_path / "filter.json"
        f.write_text(json.dumps(["slide1.ndpi", "slide2.svs", "slide3.ndpi"]))
        result = load_filter_file(f)
        assert result == {"slide1.ndpi", "slide2.svs", "slide3.ndpi"}

    def test_json_dict_keys(self, tmp_path):
        """JSON dict format — matches the OCR stain classification output."""
        f = tmp_path / "filter.json"
        f.write_text(
            json.dumps(
                {
                    "slide1.ndpi": "H&E",
                    "slide2.svs": "H&E",
                    "slide3.ndpi": "IHC",  # included in set — filtering by value is caller's job
                }
            )
        )
        result = load_filter_file(f)
        assert result == {"slide1.ndpi", "slide2.svs", "slide3.ndpi"}

    def test_json_dict_strips_paths(self, tmp_path):
        f = tmp_path / "filter.json"
        f.write_text(json.dumps({"/data/slides/slide1.ndpi": "H&E"}))
        result = load_filter_file(f)
        assert result == {"slide1.ndpi"}

    def test_invalid_json_type(self, tmp_path):
        f = tmp_path / "filter.json"
        f.write_text('"just a string"')
        with pytest.raises(ValueError, match="list or dict"):
            load_filter_file(f)


class TestFilterFileIntegration:
    """Test apply_filters with filter_file."""

    def test_filter_file_whitelist(self, tmp_path):
        f = tmp_path / "he_slides.txt"
        f.write_text("case1_HE.ndpi\ncase3_HE.ndpi\n")
        files = [
            Path("/slides/case1_HE.ndpi"),
            Path("/slides/case2_CK7.ndpi"),
            Path("/slides/case3_HE.ndpi"),
        ]
        result = apply_filters(files, filter_file=f)
        assert [p.name for p in result] == ["case1_HE.ndpi", "case3_HE.ndpi"]

    def test_filter_file_plus_exclude(self, tmp_path):
        """Filter file selects H&E, then exclude drops frozen sections."""
        f = tmp_path / "he_slides.txt"
        f.write_text("case1_HE.ndpi\ncase2_HE_frozen.ndpi\ncase3_HE.ndpi\n")
        files = [
            Path("/slides/case1_HE.ndpi"),
            Path("/slides/case2_HE_frozen.ndpi"),
            Path("/slides/case3_HE.ndpi"),
            Path("/slides/case4_CK7.ndpi"),
        ]
        result = apply_filters(files, exclude=["*frozen*"], filter_file=f)
        assert [p.name for p in result] == ["case1_HE.ndpi", "case3_HE.ndpi"]
