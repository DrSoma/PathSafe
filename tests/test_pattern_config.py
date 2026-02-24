"""Tests for configurable PHI patterns (PatternConfig)."""

import json
import re

from pathsafe.scanner import (
    PatternConfig,
    scan_bytes_for_phi,
    scan_string_for_phi,
    scan_bytes_for_dates,
)


class TestPatternConfigDefault:
    """PatternConfig.default() returns valid config."""

    def test_default_has_byte_patterns(self):
        config = PatternConfig.default()
        assert len(config.byte_patterns) > 0
        # Each entry is (compiled_pattern, label)
        for pat, label in config.byte_patterns:
            assert isinstance(pat, re.Pattern)
            assert isinstance(label, str)

    def test_default_has_string_patterns(self):
        config = PatternConfig.default()
        assert len(config.string_patterns) > 0

    def test_default_has_date_patterns(self):
        config = PatternConfig.default()
        assert len(config.date_byte_patterns) > 0

    def test_default_detects_accession(self):
        config = PatternConfig.default()
        findings = scan_bytes_for_phi(b'file AS-24-12345 data', patterns=config)
        assert len(findings) > 0
        assert any('Accession' in label for _, _, _, label in findings)


class TestPatternConfigFromJSON:
    """PatternConfig.from_json() loads and merges custom patterns."""

    def test_load_custom_byte_pattern(self, tmp_path):
        config_file = tmp_path / "patterns.json"
        config_file.write_text(json.dumps({
            "byte_patterns": [["CUSTOM-\\d+", "Custom_Pattern"]],
        }))

        config = PatternConfig.from_json(config_file)
        # Should have default patterns plus our custom one
        default_count = len(PatternConfig.default().byte_patterns)
        assert len(config.byte_patterns) == default_count + 1

        # Custom pattern should detect custom data
        findings = scan_bytes_for_phi(b'ID: CUSTOM-99887', patterns=config)
        assert any(label == 'Custom_Pattern' for _, _, _, label in findings)

    def test_load_custom_string_pattern(self, tmp_path):
        config_file = tmp_path / "patterns.json"
        config_file.write_text(json.dumps({
            "string_patterns": [["INST-\\d{6}", "Institutional_ID"]],
        }))

        config = PatternConfig.from_json(config_file)
        findings = scan_string_for_phi("case INST-123456 note", patterns=config)
        assert any(label == 'Institutional_ID' for _, _, _, label in findings)

    def test_load_custom_date_pattern(self, tmp_path):
        config_file = tmp_path / "patterns.json"
        config_file.write_text(json.dumps({
            "date_byte_patterns": [["\\d{2}\\.\\d{2}\\.\\d{4}", "Date_Dot"]],
        }))

        config = PatternConfig.from_json(config_file)
        findings = scan_bytes_for_dates(b'date 15.06.2024 end', patterns=config)
        assert any(label == 'Date_Dot' for _, _, _, label in findings)

    def test_empty_json_returns_defaults(self, tmp_path):
        config_file = tmp_path / "patterns.json"
        config_file.write_text("{}")

        config = PatternConfig.from_json(config_file)
        default = PatternConfig.default()
        assert len(config.byte_patterns) == len(default.byte_patterns)
        assert len(config.string_patterns) == len(default.string_patterns)
        assert len(config.date_byte_patterns) == len(default.date_byte_patterns)

    def test_custom_pattern_detects_custom_phi(self, tmp_path):
        """End-to-end test: custom pattern detects institution-specific PHI."""
        config_file = tmp_path / "patterns.json"
        config_file.write_text(json.dumps({
            "byte_patterns": [["LAB-\\d{4}-\\d{4}", "Lab_Accession"]],
        }))

        config = PatternConfig.from_json(config_file)
        # Standard pattern still works
        data = b'AS-24-12345 and LAB-2024-5678'
        findings = scan_bytes_for_phi(data, patterns=config)
        labels = {label for _, _, _, label in findings}
        assert 'Accession_AS' in labels
        assert 'Lab_Accession' in labels
