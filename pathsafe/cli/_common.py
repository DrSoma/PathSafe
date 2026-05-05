"""Shared helpers for CLI subcommands."""

from __future__ import annotations


def _apply_custom_patterns(patterns_path: str) -> None:
    """Load a custom patterns JSON and replace module-level pattern lists."""
    from pathsafe import scanner
    from pathsafe.scanner import PatternConfig

    config = PatternConfig.from_json(patterns_path)
    scanner.PHI_BYTE_PATTERNS = config.byte_patterns
    scanner.PHI_STRING_PATTERNS = config.string_patterns
    scanner.DATE_BYTE_PATTERNS = config.date_byte_patterns
