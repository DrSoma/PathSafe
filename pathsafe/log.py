"""Logging utilities -- ANSI terminal colors, HTML rich text, timestamps.

Provides consistent color-coded output for CLI (ANSI) and GUI (HTML),
with structured timestamped log file support.
"""

import sys
from datetime import datetime

# ---------------------------------------------------------------------------
# ANSI color codes
# ---------------------------------------------------------------------------

_RESET = '\033[0m'
_BOLD = '\033[1m'
_DIM = '\033[2m'

_RED = '\033[31m'
_GREEN = '\033[32m'
_YELLOW = '\033[33m'
_BLUE = '\033[34m'
_CYAN = '\033[36m'
_WHITE = '\033[37m'

_BOLD_RED = '\033[1;31m'
_BOLD_GREEN = '\033[1;32m'
_BOLD_YELLOW = '\033[1;33m'
_BOLD_CYAN = '\033[1;36m'
_BOLD_WHITE = '\033[1;37m'


def _is_tty():
    """Check if stdout is a terminal (not piped)."""
    try:
        return sys.stdout.isatty()
    except AttributeError:
        return False


# Module-level flag -- set once at import time
_USE_COLOR = _is_tty()


def set_color_enabled(enabled: bool):
    """Override automatic color detection."""
    global _USE_COLOR
    _USE_COLOR = enabled


def _c(code: str, text: str) -> str:
    """Apply ANSI code if color is enabled."""
    if _USE_COLOR:
        return f'{code}{text}{_RESET}'
    return text


# ---------------------------------------------------------------------------
# CLI formatting helpers
# ---------------------------------------------------------------------------

def cli_header(text: str) -> str:
    """Bold cyan header line."""
    return _c(_BOLD_CYAN, text)


def cli_success(text: str) -> str:
    """Green text for clean / success."""
    return _c(_GREEN, text)


def cli_warning(text: str) -> str:
    """Yellow text for PHI findings."""
    return _c(_YELLOW, text)


def cli_error(text: str) -> str:
    """Red text for errors."""
    return _c(_BOLD_RED, text)


def cli_info(text: str) -> str:
    """Cyan text for informational messages."""
    return _c(_CYAN, text)


def cli_dim(text: str) -> str:
    """Dim text for secondary information."""
    return _c(_DIM, text)


def cli_bold(text: str) -> str:
    """Bold white text for emphasis."""
    return _c(_BOLD_WHITE, text)


def cli_finding(text: str) -> str:
    """Yellow text for individual PHI finding details."""
    return _c(_YELLOW, text)


def cli_separator() -> str:
    """A visual separator line."""
    return _c(_DIM, '─' * 60)


# ---------------------------------------------------------------------------
# Log file formatting (always plain text with timestamps and levels)
# ---------------------------------------------------------------------------

def _timestamp() -> str:
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def log_info(msg: str) -> str:
    """Format a log file INFO line."""
    return f'[{_timestamp()}] [INFO]  {msg}'


def log_warn(msg: str) -> str:
    """Format a log file WARN line."""
    return f'[{_timestamp()}] [WARN]  {msg}'


def log_error(msg: str) -> str:
    """Format a log file ERROR line."""
    return f'[{_timestamp()}] [ERROR] {msg}'


# ---------------------------------------------------------------------------
# HTML formatting helpers (for Qt GUI QTextEdit)
# ---------------------------------------------------------------------------

# Color palette -- works on both dark and light themes
_HTML_COLORS = {
    'green': '#a6e3a1',
    'yellow': '#f9e2af',
    'orange': '#fab387',
    'red': '#f38ba8',
    'cyan': '#89b4fa',
    'dim': '#6c7086',
    'text': '#cdd6f4',
    'white': '#cdd6f4',
}

# Lighter palette for light theme (auto-selected by gui)
_HTML_COLORS_LIGHT = {
    'green': '#1e7a2e',
    'yellow': '#8a6d00',
    'orange': '#b45300',
    'red': '#c03030',
    'cyan': '#1a65c0',
    'dim': '#888888',
    'text': '#333333',
    'white': '#1e1e2e',
}

_html_palette = _HTML_COLORS  # default to dark


def set_html_theme(theme: str):
    """Switch HTML color palette ('dark' or 'light')."""
    global _html_palette
    _html_palette = _HTML_COLORS if theme == 'dark' else _HTML_COLORS_LIGHT


def _html_span(color_key: str, text: str, bold: bool = False) -> str:
    """Wrap text in a colored HTML span."""
    color = _html_palette.get(color_key, _html_palette['text'])
    weight = 'font-weight:bold;' if bold else ''
    # Escape HTML entities in the text
    safe = text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
    return f'<span style="color:{color};{weight}">{safe}</span>'


def _html_ts() -> str:
    """Timestamp as a dim HTML span."""
    ts = datetime.now().strftime('%H:%M:%S')
    return _html_span('dim', ts)


def html_header(text: str) -> str:
    """Bold cyan header with timestamp."""
    return f'{_html_ts()} {_html_span("cyan", text, bold=True)}'


def html_success(text: str) -> str:
    """Green line with timestamp."""
    return f'{_html_ts()} {_html_span("green", text)}'


def html_warning(text: str) -> str:
    """Orange/yellow line with timestamp -- PHI found."""
    return f'{_html_ts()} {_html_span("orange", text, bold=True)}'


def html_finding(text: str) -> str:
    """Yellow indented finding detail."""
    return f'{"&nbsp;" * 10}{_html_span("yellow", text)}'


def html_error(text: str) -> str:
    """Red bold line with timestamp."""
    return f'{_html_ts()} {_html_span("red", text, bold=True)}'


def html_info(text: str) -> str:
    """Normal text with timestamp."""
    return f'{_html_ts()} {_html_span("text", text)}'


def html_dim(text: str) -> str:
    """Dim text with timestamp."""
    return f'{_html_ts()} {_html_span("dim", text)}'


def html_separator() -> str:
    """A thin horizontal rule."""
    color = _html_palette.get('dim', '#6c7086')
    return f'<hr style="border:none;border-top:1px solid {color};margin:4px 0;">'


def html_summary_line(label: str, value, color_key: str = 'text') -> str:
    """A label: value line for summaries."""
    lbl = _html_span('dim', f'  {label}')
    val = _html_span(color_key, str(value), bold=True)
    return f'{lbl} {val}'
