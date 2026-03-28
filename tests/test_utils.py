"""Tests for _safe_msg() and _sanitize_error() in pathsafe.utils.

Validates that exception messages are properly truncated and stripped
of content after PHI marker keywords to prevent PHI leakage in logs.
"""

from pathsafe.utils import _safe_msg, _sanitize_error


class TestSafeMsg:
    """Test _safe_msg() truncation and PHI marker stripping."""

    def test_truncates_at_100_chars(self):
        """Messages longer than 100 characters are truncated with '...'."""
        long_msg = "A" * 200
        result = _safe_msg(long_msg)
        assert len(result) == 103  # 100 chars + "..."
        assert result.endswith("...")

    def test_short_message_unchanged(self):
        """Messages under 100 characters are returned as-is."""
        msg = "Something went wrong"
        assert _safe_msg(msg) == msg

    def test_exactly_100_chars_not_truncated(self):
        """A message of exactly 100 characters is not truncated."""
        msg = "X" * 100
        result = _safe_msg(msg)
        assert result == msg
        assert not result.endswith("...")

    def test_strips_after_patient_keyword(self):
        """Content after 'patient' keyword is stripped."""
        msg = "Invalid value for patient Doe^John"
        result = _safe_msg(msg)
        assert "Doe" not in result
        assert "John" not in result
        assert "patient" not in result

    def test_strips_after_name_keyword(self):
        """Content after 'name' keyword is stripped."""
        msg = "Error parsing name field: Smith, Jane"
        result = _safe_msg(msg)
        assert "Smith" not in result
        assert "Jane" not in result

    def test_strips_after_accession_keyword(self):
        """Content after 'accession' keyword is stripped."""
        msg = "Duplicate value in accession AS-24-123456"
        result = _safe_msg(msg)
        assert "AS-24-123456" not in result

    def test_strips_after_mrn_keyword(self):
        """Content after 'mrn' keyword is stripped."""
        msg = "Failed to parse tag with mrn 12345678"
        result = _safe_msg(msg)
        assert "12345678" not in result

    def test_strips_after_dob_keyword(self):
        """Content after 'dob' keyword is stripped."""
        msg = "Invalid date format for dob 1980-01-15"
        result = _safe_msg(msg)
        assert "1980" not in result

    def test_strips_after_ssn_keyword(self):
        """Content after 'ssn' keyword is stripped."""
        msg = "Unexpected value in ssn field: 123-45-6789"
        result = _safe_msg(msg)
        assert "123-45-6789" not in result

    def test_strips_after_physician_keyword(self):
        """Content after 'physician' keyword is stripped."""
        msg = "Metadata contains physician Dr. Roberts"
        result = _safe_msg(msg)
        assert "Roberts" not in result

    def test_word_boundary_does_not_match_named(self):
        """'named' should NOT trigger the 'name' marker (word boundary)."""
        msg = "The file named test.tif could not be opened"
        result = _safe_msg(msg)
        assert result == msg

    def test_word_boundary_does_not_match_filename(self):
        """'filename' should NOT trigger the 'name' marker."""
        msg = "Error reading filename from disk"
        result = _safe_msg(msg)
        assert result == msg

    def test_word_boundary_does_not_match_namespace(self):
        """'namespace' should NOT trigger the 'name' marker."""
        msg = "XML namespace error in tag 270"
        result = _safe_msg(msg)
        assert result == msg

    def test_strips_trailing_punctuation_before_marker(self):
        """Trailing colons/equals/hyphens before the marker are cleaned."""
        msg = "Invalid value for VR PN: patient Doe^John"
        result = _safe_msg(msg)
        # The result should end cleanly without trailing ': '
        assert not result.endswith(":")
        assert not result.endswith("=")

    def test_empty_message(self):
        """Empty string is returned as-is."""
        assert _safe_msg("") == ""

    def test_marker_at_start_of_message(self):
        """If the marker appears at the very start, result is empty."""
        msg = "patient Doe^John"
        result = _safe_msg(msg)
        assert "Doe" not in result
        assert "John" not in result

    def test_case_insensitive_matching(self):
        """PHI markers are matched case-insensitively."""
        msg = "Error in PATIENT field: secret data"
        result = _safe_msg(msg)
        assert "secret" not in result

        msg2 = "Error in Patient field: secret data"
        result2 = _safe_msg(msg2)
        assert "secret" not in result2


class TestSanitizeError:
    """Test _sanitize_error() output format and PHI stripping."""

    def test_format_includes_exception_type(self):
        """Output starts with the exception class name."""
        exc = ValueError("something broke")
        result = _sanitize_error(exc)
        assert result.startswith("ValueError: ")

    def test_format_colon_separator(self):
        """Output uses 'ExceptionType: message' format."""
        exc = TypeError("bad type")
        result = _sanitize_error(exc)
        assert result == "TypeError: bad type"

    def test_pydicom_style_exception_stripped(self):
        """Realistic pydicom exception with patient name is sanitized."""
        exc = ValueError("Invalid value for patient name: 'Doe^John'")
        result = _sanitize_error(exc)
        assert "Doe" not in result
        assert "John" not in result
        assert result.startswith("ValueError: ")

    def test_exception_with_accession_number(self):
        """Exception containing an accession number is sanitized."""
        exc = RuntimeError("Failed to process accession AS-24-999999 in tag 65468")
        result = _sanitize_error(exc)
        assert "AS-24-999999" not in result
        assert result.startswith("RuntimeError: ")

    def test_clean_exception_preserved(self):
        """Exception with no PHI markers is preserved (up to length limit)."""
        exc = OSError("Permission denied: read-only file system")
        result = _sanitize_error(exc)
        assert result == "OSError: Permission denied: read-only file system"

    def test_empty_exception_message(self):
        """Exception with empty message returns just the type name."""
        exc = ValueError("")
        result = _sanitize_error(exc)
        assert result == "ValueError: "

    def test_long_clean_message_truncated(self):
        """A long message without PHI markers is truncated at 100 chars."""
        long_msg = "X" * 200
        exc = OSError(long_msg)
        result = _sanitize_error(exc)
        # "OSError: " + 100 chars + "..."
        assert "..." in result
        assert result.startswith("OSError: ")

    def test_custom_exception_type(self):
        """Custom exception classes use their class name."""

        class MyCustomError(Exception):
            pass

        exc = MyCustomError("test message")
        result = _sanitize_error(exc)
        assert result.startswith("MyCustomError: ")
