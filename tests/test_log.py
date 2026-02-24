"""Tests for pathsafe/log.py -- CLI color, HTML formatting, timestamps, escaping."""

import re

import pytest

from pathsafe import log


@pytest.fixture(autouse=True)
def _reset_log_state():
    """Restore log module state after each test."""
    log.set_color_enabled(False)
    log.set_html_theme('dark')
    yield
    log.set_color_enabled(False)
    log.set_html_theme('dark')


# ---------------------------------------------------------------------------
# CLI color-enabled tests
# ---------------------------------------------------------------------------

class TestCLIColorEnabled:
    """All CLI functions return ANSI escape codes when color is enabled."""

    @pytest.fixture(autouse=True)
    def _enable_color(self):
        log.set_color_enabled(True)
        yield

    def test_cli_header(self):
        result = log.cli_header('Test')
        assert '\033[' in result
        assert 'Test' in result

    def test_cli_success(self):
        result = log.cli_success('OK')
        assert '\033[' in result
        assert 'OK' in result

    def test_cli_warning(self):
        result = log.cli_warning('warn')
        assert '\033[' in result

    def test_cli_error(self):
        result = log.cli_error('err')
        assert '\033[' in result

    def test_cli_info(self):
        result = log.cli_info('info')
        assert '\033[' in result

    def test_cli_dim(self):
        result = log.cli_dim('dim')
        assert '\033[' in result

    def test_cli_bold(self):
        result = log.cli_bold('bold')
        assert '\033[' in result

    def test_cli_finding(self):
        result = log.cli_finding('finding')
        assert '\033[' in result

    def test_cli_separator(self):
        result = log.cli_separator()
        assert '\033[' in result
        assert '─' in result


# ---------------------------------------------------------------------------
# CLI color-disabled tests
# ---------------------------------------------------------------------------

class TestCLIColorDisabled:
    """All CLI functions return plain text when color is disabled."""

    def test_cli_header_plain(self):
        result = log.cli_header('Test')
        assert '\033[' not in result
        assert result == 'Test'

    def test_cli_success_plain(self):
        assert log.cli_success('OK') == 'OK'

    def test_cli_warning_plain(self):
        assert log.cli_warning('warn') == 'warn'

    def test_cli_error_plain(self):
        assert log.cli_error('err') == 'err'

    def test_cli_info_plain(self):
        assert log.cli_info('info') == 'info'

    def test_cli_dim_plain(self):
        assert log.cli_dim('dim') == 'dim'

    def test_cli_bold_plain(self):
        assert log.cli_bold('bold') == 'bold'

    def test_cli_finding_plain(self):
        assert log.cli_finding('finding') == 'finding'

    def test_cli_separator_plain(self):
        result = log.cli_separator()
        assert '\033[' not in result
        assert '─' in result


# ---------------------------------------------------------------------------
# Log timestamp format
# ---------------------------------------------------------------------------

class TestLogTimestamps:
    """log_info/warn/error match [YYYY-MM-DD HH:MM:SS] [LEVEL] format."""

    _TS_PATTERN = re.compile(
        r'^\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\] \[(INFO|WARN|ERROR)\]\s+.+$'
    )

    def test_log_info_format(self):
        result = log.log_info('test message')
        assert self._TS_PATTERN.match(result), f"Unexpected format: {result!r}"
        assert 'INFO' in result
        assert 'test message' in result

    def test_log_warn_format(self):
        result = log.log_warn('warning here')
        assert self._TS_PATTERN.match(result)
        assert 'WARN' in result

    def test_log_error_format(self):
        result = log.log_error('error here')
        assert self._TS_PATTERN.match(result)
        assert 'ERROR' in result


# ---------------------------------------------------------------------------
# HTML functions
# ---------------------------------------------------------------------------

class TestHTMLFunctions:
    """HTML functions return proper <span> tags and structure."""

    def test_html_header_has_span(self):
        result = log.html_header('Header')
        assert '<span' in result
        assert 'Header' in result

    def test_html_success_has_span(self):
        result = log.html_success('OK')
        assert '<span' in result
        assert 'OK' in result

    def test_html_warning_has_span(self):
        result = log.html_warning('warn')
        assert '<span' in result
        assert 'font-weight:bold' in result

    def test_html_finding_has_span(self):
        result = log.html_finding('detail')
        assert '<span' in result
        assert 'detail' in result
        assert '&nbsp;' in result  # Indentation

    def test_html_error_has_span(self):
        result = log.html_error('fail')
        assert '<span' in result
        assert 'font-weight:bold' in result

    def test_html_info_has_span(self):
        result = log.html_info('info')
        assert '<span' in result
        assert 'info' in result

    def test_html_dim_has_span(self):
        result = log.html_dim('faded')
        assert '<span' in result

    def test_html_separator_has_hr(self):
        result = log.html_separator()
        assert '<hr' in result

    def test_html_summary_line_format(self):
        result = log.html_summary_line('Files', 42, color_key='green')
        assert '<span' in result
        assert 'Files' in result
        assert '42' in result


# ---------------------------------------------------------------------------
# HTML theme switching
# ---------------------------------------------------------------------------

class TestHTMLTheme:
    """Dark vs light theme use different color hex values."""

    def test_dark_theme_colors(self):
        log.set_html_theme('dark')
        result = log.html_success('test')
        # Dark theme green: #a6e3a1
        assert '#a6e3a1' in result

    def test_light_theme_colors(self):
        log.set_html_theme('light')
        result = log.html_success('test')
        # Light theme green: #1e7a2e
        assert '#1e7a2e' in result

    def test_switch_back_to_dark(self):
        log.set_html_theme('light')
        log.set_html_theme('dark')
        result = log.html_success('test')
        assert '#a6e3a1' in result

    def test_dark_vs_light_different(self):
        log.set_html_theme('dark')
        dark = log.html_error('err')
        log.set_html_theme('light')
        light = log.html_error('err')
        # Different hex values
        assert dark != light


# ---------------------------------------------------------------------------
# HTML escaping
# ---------------------------------------------------------------------------

class TestHTMLEscaping:
    """<, >, & properly escaped in HTML output."""

    def test_ampersand_escaped(self):
        result = log.html_info('a & b')
        assert '&amp;' in result
        # Should not have unescaped '&' followed by space
        assert ' & ' not in result.split('</span>')[-2]  # Check inside span

    def test_lt_escaped(self):
        result = log.html_info('<script>')
        assert '&lt;' in result
        assert '<script>' not in result

    def test_gt_escaped(self):
        result = log.html_info('x > y')
        assert '&gt;' in result

    def test_combined_escaping(self):
        result = log.html_info('<b>A & B</b>')
        assert '&lt;b&gt;' in result
        assert '&amp;' in result


# ---------------------------------------------------------------------------
# Boundary inputs
# ---------------------------------------------------------------------------

class TestBoundaryInputs:
    """Edge case inputs for all functions."""

    def test_empty_string_cli(self):
        """Empty strings don't crash CLI functions."""
        assert log.cli_header('') == ''
        assert log.cli_success('') == ''
        assert log.cli_warning('') == ''
        assert log.cli_error('') == ''
        assert log.cli_info('') == ''
        assert log.cli_dim('') == ''
        assert log.cli_bold('') == ''
        assert log.cli_finding('') == ''

    def test_empty_string_html(self):
        """Empty strings don't crash HTML functions."""
        assert '<span' in log.html_header('')
        assert '<span' in log.html_success('')
        assert '<span' in log.html_warning('')
        assert '<span' in log.html_error('')
        assert '<span' in log.html_info('')
        assert '<span' in log.html_dim('')

    def test_empty_string_log(self):
        """Empty strings produce valid log lines."""
        result = log.log_info('')
        assert '[INFO]' in result
        result = log.log_warn('')
        assert '[WARN]' in result
        result = log.log_error('')
        assert '[ERROR]' in result

    def test_large_string_cli(self):
        """10KB string handled by CLI functions."""
        big = 'x' * 10_000
        result = log.cli_header(big)
        assert big in result

    def test_large_string_html(self):
        """10KB string handled by HTML functions."""
        big = 'y' * 10_000
        result = log.html_info(big)
        assert big in result

    def test_large_string_log(self):
        """10KB string handled by log functions."""
        big = 'z' * 10_000
        result = log.log_info(big)
        assert big in result

    def test_unicode_cli(self):
        """Unicode strings in CLI functions."""
        log.set_color_enabled(True)
        result = log.cli_header('患者テスト 🔬')
        assert '患者テスト' in result
        assert '\033[' in result

    def test_unicode_html(self):
        """Unicode strings in HTML functions."""
        result = log.html_info('患者 Ñoño')
        assert '患者' in result
        assert 'Ñoño' in result

    def test_unicode_log(self):
        """Unicode strings in log functions."""
        result = log.log_info('患者テスト')
        assert '患者テスト' in result

    def test_summary_line_zero_value(self):
        """Summary line with zero value."""
        result = log.html_summary_line('Errors', 0)
        assert '0' in result

    def test_summary_line_string_value(self):
        """Summary line with string value."""
        result = log.html_summary_line('Status', 'OK')
        assert 'OK' in result
