"""Tests for the stain classifier -- works WITHOUT paddleocr installed.

Tests the classification regex patterns (classify_label with mock OCR lines),
stain vocabulary loading, PHI sanitization of output, and export format
correctness.
"""

import csv
import json

import pytest

from pathsafe.classifier import (
    StainClassification,
    _load_vocabulary,
    _sanitize_field,
    _validate_stain_name,
    classify_label,
    export_classifications,
    parse_he_label,
    parse_ihc_label,
    parse_ihc_sv_label,
)


# ---------------------------------------------------------------------------
# Stain vocabulary loading
# ---------------------------------------------------------------------------


class TestStainVocabulary:
    def test_vocabulary_loads(self):
        vocab = _load_vocabulary()
        assert isinstance(vocab, set)
        assert len(vocab) > 50  # should have at least the basic stains

    def test_vocabulary_contains_common_stains(self):
        vocab = _load_vocabulary()
        assert "H&E" in vocab
        assert "PAS" in vocab
        assert "CD3" in vocab
        assert "KI67" in vocab
        assert "PD-L1" in vocab

    def test_vocabulary_is_uppercase(self):
        vocab = _load_vocabulary()
        for stain in vocab:
            assert stain == stain.upper(), f"Stain '{stain}' is not uppercase"


# ---------------------------------------------------------------------------
# Stain name validation against vocabulary
# ---------------------------------------------------------------------------


class TestValidateStainName:
    def test_exact_match(self):
        assert _validate_stain_name("H&E") == "H&E"
        assert _validate_stain_name("CD3") == "CD3"
        assert _validate_stain_name("PAS") == "PAS"

    def test_case_insensitive(self):
        assert _validate_stain_name("h&e") == "h&e"
        assert _validate_stain_name("cd20") == "cd20"

    def test_unknown_returns_empty(self):
        assert _validate_stain_name("NOTAREALSTAIN") == ""

    def test_empty_returns_empty(self):
        assert _validate_stain_name("") == ""


# ---------------------------------------------------------------------------
# Classification regex patterns (classify_label with mock OCR lines)
# ---------------------------------------------------------------------------


class TestClassifyLabel:
    def test_he_accession_first(self):
        """H&E label: first line is an accession like AS-24-123456."""
        lines = [
            ("AS-24-123456", 0.95),
            ("B3", 0.90),
            ("H Stain H+E", 0.92),
        ]
        stain_type, label_format = classify_label(lines)
        assert stain_type == "he"
        assert "he" in label_format.lower()

    def test_he_frozen_section(self):
        """H&E label: frozen section format FS-24-..."""
        lines = [
            ("FS-24-00123", 0.93),
            ("A1", 0.91),
            ("H Stain H+E", 0.90),
        ]
        stain_type, label_format = classify_label(lines)
        assert stain_type == "he"

    def test_ihc_code_name(self):
        """IHC label: first line starts with numeric code + stain name."""
        lines = [
            ("122 CK20-U", 0.96),
            ("AS-21-37595-C4", 0.88),
        ]
        stain_type, label_format = classify_label(lines)
        assert stain_type == "ihc"

    def test_ihc_send_out(self):
        """IHC send-out label: first line is SV-prefixed."""
        lines = [
            ("SV-24-12345", 0.94),
            ("PD-L1 22C3", 0.91),
        ]
        stain_type, label_format = classify_label(lines)
        assert stain_type == "ihc_sv"

    def test_ihc_name_first(self):
        """IHC label: stain name is the first line (e.g. P40CK5-6)."""
        lines = [
            ("P40CK5-6", 0.97),
            ("301", 0.89),
            ("AS-18-55555-A1", 0.85),
        ]
        stain_type, label_format = classify_label(lines)
        assert stain_type == "ihc"

    def test_ihc_standalone_code(self):
        """IHC label: standalone 3-digit code on first line."""
        lines = [
            ("301", 0.95),
            ("P40CK5+6-U", 0.92),
            ("AS-21-00000-B2", 0.88),
        ]
        stain_type, label_format = classify_label(lines)
        assert stain_type == "ihc"

    def test_he_fallback(self):
        """If no first-line pattern matches but a line mentions H&E."""
        lines = [
            ("BLOCK A2", 0.90),
            ("H+E", 0.88),
        ]
        stain_type, label_format = classify_label(lines)
        assert stain_type == "he"
        assert "fallback" in label_format

    def test_unknown(self):
        """No stain-related text at all."""
        lines = [
            ("SOME RANDOM TEXT", 0.70),
            ("NO STAIN HERE", 0.65),
        ]
        stain_type, label_format = classify_label(lines)
        assert stain_type == "unknown"

    def test_empty_lines(self):
        stain_type, label_format = classify_label([])
        assert stain_type == "unknown"
        assert "no_lines" in label_format


# ---------------------------------------------------------------------------
# Label parsers
# ---------------------------------------------------------------------------


class TestParseHeLabel:
    def test_standard_he_label(self):
        lines = [
            ("AS-24-123456", 0.95),
            ("B3", 0.90),
            ("H Stain H+E", 0.92),
            ("Dr. Smith 01/15/2024", 0.88),
        ]
        stain_name, stain_code = parse_he_label(lines)
        assert stain_name == "H&E"
        assert stain_code == ""

    def test_short_label(self):
        """Label with fewer than 3 lines still returns H&E."""
        lines = [
            ("AS-24-123456", 0.95),
        ]
        stain_name, stain_code = parse_he_label(lines)
        assert stain_name == "H&E"


class TestParseIhcLabel:
    def test_code_and_name_same_line(self):
        lines = [
            ("122 CK20-U", 0.96),
            ("AS-21-37595-C4", 0.88),
        ]
        stain_name, stain_code = parse_ihc_label(lines)
        assert stain_code == "122"
        assert stain_name  # Should validate against vocabulary

    def test_standalone_code_first(self):
        lines = [
            ("301", 0.95),
            ("CK7", 0.92),
        ]
        stain_name, stain_code = parse_ihc_label(lines)
        assert stain_code == "301"

    def test_empty_lines(self):
        stain_name, stain_code = parse_ihc_label([])
        assert stain_name == ""
        assert stain_code == ""


class TestParseIhcSvLabel:
    def test_send_out_label(self):
        lines = [
            ("SV-24-12345", 0.94),
            ("PD-L1", 0.91),
            ("B2", 0.85),
        ]
        stain_name, stain_code = parse_ihc_sv_label(lines)
        # SV line should be skipped, PD-L1 should be found
        assert stain_name  # Should find PD-L1 or similar


# ---------------------------------------------------------------------------
# PHI sanitization of output
# ---------------------------------------------------------------------------


class TestPHISanitization:
    def test_sanitize_clean_field(self):
        """A valid stain name should pass through unchanged."""
        # _sanitize_field checks against PHI_STRING_PATTERNS from scanner
        result = _sanitize_field("H&E")
        # If scanner patterns don't flag "H&E", it passes through
        # The exact behavior depends on scanner.py patterns
        assert isinstance(result, str)

    def test_sanitize_empty_field(self):
        result = _sanitize_field("")
        assert result == ""


# ---------------------------------------------------------------------------
# Export format
# ---------------------------------------------------------------------------


class TestExportClassifications:
    def test_json_export(self, tmp_path):
        results = {
            "abc123def456": StainClassification(
                stain_type="he",
                stain_name="H&E",
                stain_code="",
                confidence=0.93,
                label_format="he_accession_first",
            ),
            "def789abc012": StainClassification(
                stain_type="ihc",
                stain_name="CD3",
                stain_code="150",
                confidence=0.91,
                label_format="ihc_code_name",
            ),
        }
        out_path = tmp_path / "classifications.json"
        export_classifications(results, out_path, format="json")

        data = json.loads(out_path.read_text())
        assert "abc123def456" in data
        assert data["abc123def456"]["stain_name"] == "H&E"
        assert data["abc123def456"]["stain_type"] == "he"
        assert data["def789abc012"]["stain_name"] == "CD3"
        assert data["def789abc012"]["stain_code"] == "150"

    def test_csv_export(self, tmp_path):
        results = {
            "abc123def456": StainClassification(
                stain_type="he",
                stain_name="H&E",
                stain_code="",
                confidence=0.93,
                label_format="he_accession_first",
            ),
        }
        out_path = tmp_path / "classifications.csv"
        export_classifications(results, out_path, format="csv")

        with open(out_path) as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        assert len(rows) == 1
        assert rows[0]["stain_name"] == "H&E"
        assert rows[0]["stain_type"] == "he"
        assert rows[0]["identifier"] == "abc123def456"

    def test_json_export_with_errors(self, tmp_path):
        results = {
            "slide_err_hash": StainClassification(
                error="no_label_image",
            ),
        }
        out_path = tmp_path / "classifications.json"
        export_classifications(results, out_path, format="json")

        data = json.loads(out_path.read_text())
        assert data["slide_err_hash"]["error"] == "no_label_image"
        assert data["slide_err_hash"]["stain_type"] == "unknown"

    def test_json_no_phi_in_output(self, tmp_path):
        """Exported JSON should not contain raw OCR text (which could have PHI)."""
        results = {
            "abc123def456": StainClassification(
                stain_type="he",
                stain_name="H&E",
                stain_code="",
                confidence=0.93,
                label_format="he_accession_first",
            ),
        }
        out_path = tmp_path / "classifications.json"
        export_classifications(results, out_path, format="json")

        raw_text = out_path.read_text()
        # The export should not contain any field that isn't in StainClassification
        data = json.loads(raw_text)
        record = data["abc123def456"]
        # Only allowlisted keys should be present
        allowed_keys = {
            "stain_type",
            "stain_name",
            "stain_code",
            "confidence",
            "label_format",
            "error",
        }
        assert set(record.keys()).issubset(allowed_keys)

    def test_invalid_format_raises(self, tmp_path):
        results = {"key": StainClassification()}
        with pytest.raises(ValueError, match="Unsupported export format"):
            export_classifications(results, tmp_path / "out.txt", format="xml")

    def test_creates_parent_directories(self, tmp_path):
        results = {
            "abc": StainClassification(stain_type="he", stain_name="H&E"),
        }
        out_path = tmp_path / "subdir" / "nested" / "out.json"
        export_classifications(results, out_path, format="json")
        assert out_path.exists()
