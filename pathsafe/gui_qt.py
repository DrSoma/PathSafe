"""PathSafe Qt GUI - modern cross-platform interface for hospital staff.

One-click anonymize workflow: browse files, scan, anonymize, verify.
Uses PySide6 (Qt6) for native look and crisp text on all platforms.

Features:
- Light and dark theme (switchable from View menu)
- Drag-and-drop file/folder support
- Workflow step indicator
- Menu bar with keyboard shortcuts
- Tooltips on all controls
- Status bar with live stats
- Tabbed interface for Anonymize and Convert workflows
- Format filtering, dry-run mode, and log export
"""

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal, QObject, QSize, QSettings, QStandardPaths
from PySide6.QtGui import (
    QFont, QTextCursor, QAction, QKeySequence, QColor, QIcon,
    QPainter, QPen, QBrush, QDragEnterEvent, QDropEvent,
    QActionGroup,
)
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QGroupBox, QLabel, QLineEdit, QPushButton, QRadioButton,
    QCheckBox, QSpinBox, QSlider, QProgressBar, QTextEdit, QFileDialog,
    QMessageBox, QButtonGroup, QSizePolicy, QTabWidget, QFrame,
    QToolBar, QComboBox,
)

import pathsafe
from pathsafe.anonymizer import anonymize_batch, anonymize_file, collect_wsi_files, scan_batch, WSI_EXTENSIONS
from pathsafe.formats import detect_format, get_handler
from pathsafe.log import (
    html_dim, html_error, html_finding, html_header, html_info,
    html_separator, html_success, html_summary_line, html_warning,
    set_html_theme,
)
from pathsafe.report import generate_certificate, generate_scan_report, friendly_tag_name
from pathsafe.verify import verify_batch


# --- Dark Theme Stylesheet (Catppuccin Mocha inspired) ---

DARK_QSS = """
QMainWindow, QWidget {
    background-color: #1e1e2e;
    color: #cdd6f4;
    font-size: 14px;
}
QGroupBox {
    border: 1px solid #45475a;
    border-radius: 6px;
    margin-top: 8px;
    padding-top: 14px;
    font-weight: bold;
    color: #89b4fa;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 6px;
}
QLineEdit {
    background-color: #313244;
    color: #cdd6f4;
    border: 1px solid #45475a;
    border-radius: 4px;
    padding: 8px 10px;
    font-size: 14px;
    selection-background-color: #585b70;
}
QLineEdit:focus {
    border: 1px solid #89b4fa;
}
QPushButton {
    background-color: #313244;
    color: #cdd6f4;
    border: 1px solid #45475a;
    border-radius: 4px;
    padding: 6px 14px;
    min-height: 24px;
}
QPushButton:hover {
    background-color: #45475a;
    border-color: #585b70;
}
QPushButton:pressed {
    background-color: #585b70;
}
QPushButton:disabled {
    color: #6c7086;
    background-color: #1e1e2e;
    border-color: #313244;
}
QPushButton#btn_scan {
    background-color: #1e3a5f;
    border-color: #89b4fa;
    color: #89b4fa;
    font-weight: bold;
}
QPushButton#btn_scan:hover {
    background-color: #264b73;
}
QPushButton#btn_anonymize {
    background-color: #1e3f2e;
    border-color: #a6e3a1;
    color: #a6e3a1;
    font-weight: bold;
}
QPushButton#btn_anonymize:hover {
    background-color: #2b5a3e;
}
QPushButton#btn_verify {
    background-color: #1e3f3f;
    border-color: #94e2d5;
    color: #94e2d5;
    font-weight: bold;
}
QPushButton#btn_verify:hover {
    background-color: #2b5a5a;
}
QPushButton#btn_info {
    background-color: #2e1f5e;
    border-color: #cba6f7;
    color: #cba6f7;
    font-weight: bold;
}
QPushButton#btn_info:hover {
    background-color: #3d2b73;
}
QPushButton#btn_stop {
    background-color: #3f1e1e;
    border-color: #f38ba8;
    color: #f38ba8;
    font-weight: bold;
}
QPushButton#btn_stop:hover {
    background-color: #5a2b2b;
}
QPushButton#btn_convert {
    background-color: #3f2e1e;
    border-color: #fab387;
    color: #fab387;
    font-weight: bold;
}
QPushButton#btn_convert:hover {
    background-color: #5a3d2b;
}
QRadioButton, QCheckBox {
    color: #cdd6f4;
    spacing: 6px;
}
QRadioButton::indicator, QCheckBox::indicator {
    width: 16px;
    height: 16px;
}
QSpinBox {
    background-color: #313244;
    color: #cdd6f4;
    border: 1px solid #45475a;
    border-radius: 4px;
    padding: 4px;
}
QComboBox {
    background-color: #313244;
    color: #cdd6f4;
    border: 1px solid #45475a;
    border-radius: 4px;
    padding: 4px 8px;
    min-height: 22px;
}
QComboBox:hover {
    border-color: #585b70;
}
QComboBox::drop-down {
    border: none;
    width: 20px;
}
QComboBox QAbstractItemView {
    background-color: #313244;
    color: #cdd6f4;
    border: 1px solid #45475a;
    selection-background-color: #45475a;
}
QSlider {
    min-height: 28px;
}
QSlider::groove:horizontal {
    height: 6px;
    background-color: #313244;
    border-radius: 3px;
}
QSlider::handle:horizontal {
    width: 16px;
    height: 16px;
    margin: -5px 0;
    background-color: #89b4fa;
    border-radius: 8px;
}
QSlider::handle:horizontal:hover {
    background-color: #b4d0fb;
}
QSlider::sub-page:horizontal {
    background-color: #89b4fa;
    border-radius: 3px;
}
QProgressBar {
    background-color: #313244;
    border: 1px solid #45475a;
    border-radius: 4px;
    text-align: center;
    color: #cdd6f4;
    min-height: 20px;
}
QProgressBar::chunk {
    background-color: #89b4fa;
    border-radius: 3px;
}
QTextEdit {
    background-color: #11111b;
    color: #a6adc8;
    border: 1px solid #313244;
    border-radius: 4px;
    selection-background-color: #45475a;
}
QScrollBar:vertical {
    background-color: #181825;
    width: 12px;
    border-radius: 6px;
}
QScrollBar::handle:vertical {
    background-color: #585b70;
    min-height: 30px;
    border-radius: 6px;
}
QScrollBar::handle:vertical:hover {
    background-color: #6c7086;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
    background: none;
}
QScrollBar:horizontal {
    background-color: #181825;
    height: 12px;
    border-radius: 6px;
}
QScrollBar::handle:horizontal {
    background-color: #585b70;
    min-width: 30px;
    border-radius: 6px;
}
QScrollBar::handle:horizontal:hover {
    background-color: #6c7086;
}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    width: 0px;
}
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {
    background: none;
}
QTabWidget::pane {
    border: 1px solid #45475a;
    border-radius: 4px;
    background-color: #1e1e2e;
}
QTabBar::tab {
    background-color: #313244;
    color: #6c7086;
    border: 1px solid #45475a;
    padding: 6px 16px;
    margin-right: 2px;
    border-top-left-radius: 4px;
    border-top-right-radius: 4px;
}
QTabBar::tab:selected {
    background-color: #1e1e2e;
    color: #cdd6f4;
    border-bottom-color: #1e1e2e;
}
QStatusBar {
    background-color: #181825;
    border-top: 1px solid #313244;
    color: #6c7086;
    padding: 2px;
}
QMenuBar {
    background-color: #181825;
    color: #cdd6f4;
    border-bottom: 1px solid #313244;
}
QMenuBar::item:selected {
    background-color: #313244;
}
QMenu {
    background-color: #1e1e2e;
    color: #cdd6f4;
    border: 1px solid #45475a;
}
QMenu::item:selected {
    background-color: #313244;
}
QToolBar {
    background-color: #181825;
    border-bottom: 1px solid #313244;
    spacing: 4px;
    padding: 2px;
}
QToolTip {
    background-color: #313244;
    color: #cdd6f4;
    border: 1px solid #45475a;
    border-radius: 4px;
    padding: 4px 8px;
}
"""

LIGHT_QSS = """
QMainWindow, QWidget {
    background-color: #f5f5f5;
    color: #1e1e2e;
    font-size: 14px;
}
QGroupBox {
    border: 1px solid #c0c0c0;
    border-radius: 6px;
    margin-top: 8px;
    padding-top: 14px;
    font-weight: bold;
    color: #1a65c0;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 6px;
}
QLineEdit {
    background-color: #ffffff;
    color: #1e1e2e;
    border: 1px solid #c0c0c0;
    border-radius: 4px;
    padding: 8px 10px;
    font-size: 14px;
    selection-background-color: #a8d0f0;
}
QLineEdit:focus {
    border: 1px solid #1a65c0;
}
QPushButton {
    background-color: #e8e8e8;
    color: #1e1e2e;
    border: 1px solid #c0c0c0;
    border-radius: 4px;
    padding: 6px 14px;
    min-height: 24px;
}
QPushButton:hover {
    background-color: #d0d0d0;
    border-color: #a0a0a0;
}
QPushButton:pressed {
    background-color: #b8b8b8;
}
QPushButton:disabled {
    color: #a0a0a0;
    background-color: #f0f0f0;
    border-color: #d8d8d8;
}
QPushButton#btn_scan {
    background-color: #dce8f5;
    border-color: #1a65c0;
    color: #1a65c0;
    font-weight: bold;
}
QPushButton#btn_scan:hover {
    background-color: #c5d8ee;
}
QPushButton#btn_anonymize {
    background-color: #dcf0de;
    border-color: #2e8b3e;
    color: #2e8b3e;
    font-weight: bold;
}
QPushButton#btn_anonymize:hover {
    background-color: #c0e4c4;
}
QPushButton#btn_verify {
    background-color: #dcf0ee;
    border-color: #1a8a7a;
    color: #1a8a7a;
    font-weight: bold;
}
QPushButton#btn_verify:hover {
    background-color: #c0e4e0;
}
QPushButton#btn_info {
    background-color: #ece0f5;
    border-color: #7b2dbd;
    color: #7b2dbd;
    font-weight: bold;
}
QPushButton#btn_info:hover {
    background-color: #ddd0e8;
}
QPushButton#btn_stop {
    background-color: #f5dcdc;
    border-color: #c03030;
    color: #c03030;
    font-weight: bold;
}
QPushButton#btn_stop:hover {
    background-color: #eac4c4;
}
QPushButton#btn_convert {
    background-color: #f5eadc;
    border-color: #c06a1e;
    color: #c06a1e;
    font-weight: bold;
}
QPushButton#btn_convert:hover {
    background-color: #e8dcc8;
}
QRadioButton, QCheckBox {
    color: #1e1e2e;
    spacing: 6px;
}
QRadioButton::indicator, QCheckBox::indicator {
    width: 16px;
    height: 16px;
}
QSpinBox {
    background-color: #ffffff;
    color: #1e1e2e;
    border: 1px solid #c0c0c0;
    border-radius: 4px;
    padding: 4px;
}
QComboBox {
    background-color: #ffffff;
    color: #1e1e2e;
    border: 1px solid #c0c0c0;
    border-radius: 4px;
    padding: 4px 8px;
    min-height: 22px;
}
QComboBox:hover {
    border-color: #a0a0a0;
}
QComboBox::drop-down {
    border: none;
    width: 20px;
}
QComboBox QAbstractItemView {
    background-color: #ffffff;
    color: #1e1e2e;
    border: 1px solid #c0c0c0;
    selection-background-color: #d0d0d0;
}
QSlider {
    min-height: 28px;
}
QSlider::groove:horizontal {
    height: 6px;
    background-color: #d0d0d0;
    border-radius: 3px;
}
QSlider::handle:horizontal {
    width: 16px;
    height: 16px;
    margin: -5px 0;
    background-color: #1a65c0;
    border-radius: 8px;
}
QSlider::handle:horizontal:hover {
    background-color: #2878d8;
}
QSlider::sub-page:horizontal {
    background-color: #1a65c0;
    border-radius: 3px;
}
QProgressBar {
    background-color: #e0e0e0;
    border: 1px solid #c0c0c0;
    border-radius: 4px;
    text-align: center;
    color: #1e1e2e;
    min-height: 20px;
}
QProgressBar::chunk {
    background-color: #1a65c0;
    border-radius: 3px;
}
QTextEdit {
    background-color: #ffffff;
    color: #333333;
    border: 1px solid #c0c0c0;
    border-radius: 4px;
    selection-background-color: #a8d0f0;
}
QScrollBar:vertical {
    background-color: #f0f0f0;
    width: 12px;
    border-radius: 6px;
}
QScrollBar::handle:vertical {
    background-color: #a0a0a0;
    min-height: 30px;
    border-radius: 6px;
}
QScrollBar::handle:vertical:hover {
    background-color: #888888;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
    background: none;
}
QScrollBar:horizontal {
    background-color: #f0f0f0;
    height: 12px;
    border-radius: 6px;
}
QScrollBar::handle:horizontal {
    background-color: #a0a0a0;
    min-width: 30px;
    border-radius: 6px;
}
QScrollBar::handle:horizontal:hover {
    background-color: #888888;
}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    width: 0px;
}
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {
    background: none;
}
QTabWidget::pane {
    border: 1px solid #c0c0c0;
    border-radius: 4px;
    background-color: #f5f5f5;
}
QTabBar::tab {
    background-color: #e8e8e8;
    color: #666666;
    border: 1px solid #c0c0c0;
    padding: 6px 16px;
    margin-right: 2px;
    border-top-left-radius: 4px;
    border-top-right-radius: 4px;
}
QTabBar::tab:selected {
    background-color: #f5f5f5;
    color: #1e1e2e;
    border-bottom-color: #f5f5f5;
}
QStatusBar {
    background-color: #ebebeb;
    border-top: 1px solid #c0c0c0;
    color: #666666;
    padding: 2px;
}
QMenuBar {
    background-color: #ebebeb;
    color: #1e1e2e;
    border-bottom: 1px solid #c0c0c0;
}
QMenuBar::item:selected {
    background-color: #d0d0d0;
}
QMenu {
    background-color: #f5f5f5;
    color: #1e1e2e;
    border: 1px solid #c0c0c0;
}
QMenu::item:selected {
    background-color: #d0d0d0;
}
QToolBar {
    background-color: #ebebeb;
    border-bottom: 1px solid #c0c0c0;
    spacing: 4px;
    padding: 2px;
}
QToolTip {
    background-color: #f5f5f5;
    color: #1e1e2e;
    border: 1px solid #c0c0c0;
    border-radius: 4px;
    padding: 4px 8px;
}
"""

# Theme color constants for paintEvent widgets
THEME_COLORS = {
    'dark': {
        'completed': '#a6e3a1',
        'active': '#89b4fa',
        'inactive_fill': '#313244',
        'inactive_border': '#45475a',
        'circle_inner': '#1e1e2e',
        'text_dim': '#6c7086',
        'text_bright': '#cdd6f4',
        'drop_border': '#45475a',
        'drop_bg': '#181825',
        'drop_hover_border': '#89b4fa',
        'drop_hover_bg': '#1e1e3e',
        'drop_text': '#6c7086',
        'drop_hint': '#585b70',
    },
    'light': {
        'completed': '#2e8b3e',
        'active': '#1a65c0',
        'inactive_fill': '#e0e0e0',
        'inactive_border': '#c0c0c0',
        'circle_inner': '#f5f5f5',
        'text_dim': '#888888',
        'text_bright': '#1e1e2e',
        'drop_border': '#c0c0c0',
        'drop_bg': '#ebebeb',
        'drop_hover_border': '#1a65c0',
        'drop_hover_bg': '#dce8f5',
        'drop_text': '#888888',
        'drop_hint': '#aaaaaa',
    },
}

# Format filter items shared between Anonymize and Convert tabs
_FORMAT_FILTER_ITEMS = [
    'All formats', 'NDPI', 'SVS', 'MRXS', 'BIF', 'SCN', 'DICOM', 'TIFF',
]


# --- Worker Threads ---

class WorkerSignals(QObject):
    """Signals for background worker threads."""
    log = Signal(str)
    progress = Signal(float)
    status = Signal(str)
    finished = Signal()
    summary = Signal(dict)  # Summary data for popup at completion


class ScanWorker(QThread):
    """Background thread for scanning files."""

    def __init__(self, input_path, workers, signals, format_filter=None,
                 institution="", output_dir=None, file_list=None):
        super().__init__()
        self.input_path = input_path
        self.workers = workers
        self.signals = signals
        self.format_filter = format_filter
        self.institution = institution
        self.output_dir = output_dir
        self.file_list = file_list
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        try:
            if self.file_list:
                files = list(self.file_list)
            else:
                files = collect_wsi_files(self.input_path,
                                          format_filter=self.format_filter)
            total = len(files)
            if total == 0:
                self.signals.log.emit(html_warning('No WSI files found.'))
                return

            fmt_str = f' [{self.format_filter.upper()}]' if self.format_filter else ''
            self.signals.log.emit(
                html_header(f'PathSafe v{pathsafe.__version__} - PHI Scan'
                            f'{fmt_str}'))
            self.signals.log.emit(
                html_info(f'Scanning {total} file(s)...'))
            self.signals.log.emit(html_separator())

            clean = 0
            phi_count = 0
            error_count = 0
            results_json = []

            def on_result(i, total_files, filepath, result):
                nonlocal clean, phi_count, error_count

                pct = i / total_files * 100
                self.signals.progress.emit(pct)
                self.signals.status.emit(
                    f'Scanning {i}/{total_files}: {filepath.name}')

                # Compute SHA-256 of the scanned file (pre-anonymization)
                sha256 = ''
                try:
                    import hashlib
                    h = hashlib.sha256()
                    with open(filepath, 'rb') as fh:
                        while True:
                            chunk = fh.read(65536)
                            if not chunk:
                                break
                            h.update(chunk)
                    sha256 = h.hexdigest()
                except OSError:
                    pass

                # Collect JSON-serializable result
                entry = {
                    'filepath': str(filepath),
                    'is_clean': result.is_clean,
                    'error': result.error,
                    'sha256': sha256,
                    'findings': [
                        {'tag_name': f.tag_name, 'value_preview': f.value_preview}
                        for f in result.findings
                    ] if result.findings else [],
                }
                results_json.append(entry)

                if result.error:
                    error_count += 1
                    self.signals.log.emit(html_error(
                        f'  [{i}/{total_files}] {filepath.name} - ERROR: {result.error}'))
                elif result.is_clean:
                    clean += 1
                    self.signals.log.emit(html_success(
                        f'  [{i}/{total_files}] {filepath.name} - CLEAN'))
                else:
                    phi_count += len(result.findings)
                    self.signals.log.emit(html_warning(
                        f'  [{i}/{total_files}] {filepath.name} - '
                        f'{len(result.findings)} finding(s):'))
                    for f in result.findings:
                        self.signals.log.emit(html_finding(
                            f'    {friendly_tag_name(f.tag_name)}: {f.value_preview}'))

            scan_batch(self.input_path, progress_callback=on_result,
                       workers=self.workers,
                       format_filter=self.format_filter,
                       stop_check=lambda: self._stop,
                       file_list=self.file_list)

            # Summary
            self.signals.log.emit(html_separator())
            self.signals.log.emit(html_header('Summary'))
            self.signals.log.emit(
                html_summary_line('Total scanned:', total, 'white'))
            if clean:
                self.signals.log.emit(
                    html_summary_line('Clean:', clean, 'green'))
            phi_files = total - clean - error_count
            if phi_files:
                self.signals.log.emit(
                    html_summary_line(
                        'PHI detected:', f'{phi_files} files ({phi_count} findings)',
                        'orange'))
            if error_count:
                self.signals.log.emit(
                    html_summary_line('Errors:', error_count, 'red'))

            if phi_files == 0 and error_count == 0:
                self.signals.log.emit(html_success(
                    'All files are clean - no PHI detected.'))

            # Generate scan report PDF
            scan_report_path = ''
            try:
                scan_data = {
                    'total': total,
                    'clean': clean,
                    'phi_files': phi_files,
                    'phi_findings': phi_count,
                    'errors': error_count,
                    'results': results_json,
                }
                if self.output_dir:
                    report_dir = Path(self.output_dir)
                    report_dir.mkdir(parents=True, exist_ok=True)
                else:
                    report_dir = Path(self.input_path) if Path(self.input_path).is_dir() \
                        else Path(self.input_path).parent
                stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                report_path = report_dir / f'pathsafe_scan_report_{stamp}.pdf'
                generate_scan_report(scan_data, report_path,
                                     institution=self.institution)
                scan_report_path = str(report_path)
                self.signals.log.emit(html_info(
                    f'Scan report saved: {report_path.name}'))
            except Exception as e:
                self.signals.log.emit(html_warning(
                    f'Could not generate scan report PDF: {e}'))

            self.signals.summary.emit({
                'type': 'scan',
                'total': total,
                'clean': clean,
                'phi_files': phi_files,
                'phi_findings': phi_count,
                'errors': error_count,
                'results_json': results_json,
                'scan_report': scan_report_path,
            })
            self.signals.status.emit('Scan complete')
        except Exception as e:
            self.signals.log.emit(html_error(f'ERROR: {e}'))
            self.signals.status.emit(f'Error: {e}')
        finally:
            self.signals.finished.emit()


class AnonymizeWorker(QThread):
    """Background thread for anonymizing files."""

    def __init__(self, input_path, output_dir, verify, workers, signals,
                 reset_timestamps=True,
                 format_filter=None,
                 dry_run=False, verify_integrity=True,
                 institution="", file_list=None):
        super().__init__()
        self.input_path = input_path
        self.output_dir = output_dir
        self.verify = verify
        self.workers = workers
        self.signals = signals
        self.reset_timestamps = reset_timestamps
        self.format_filter = format_filter
        self.institution = institution
        self.dry_run = dry_run
        self.verify_integrity = verify_integrity
        self.file_list = file_list
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        try:
            if self.file_list:
                files = list(self.file_list)
            else:
                files = collect_wsi_files(self.input_path,
                                          format_filter=self.format_filter)
            total = len(files)
            if total == 0:
                self.signals.log.emit(html_warning('No WSI files found.'))
                return

            mode_str = 'DRY RUN' if self.dry_run else (
                'copy' if self.output_dir else 'in-place')
            workers_str = f', {self.workers} workers' if self.workers > 1 else ''
            fmt_str = f' [{self.format_filter.upper()}]' if self.format_filter else ''
            self.signals.log.emit(html_header(
                f'PathSafe v{pathsafe.__version__} - {mode_str} '
                f'anonymization{fmt_str}{workers_str}'))
            self.signals.log.emit(
                html_info(f'Processing {total} file(s)...'))
            if self.dry_run:
                self.signals.log.emit(
                    html_warning('DRY RUN - no files will be modified.'))
            self.signals.log.emit(html_separator())

            t0 = time.time()

            def progress(i, total_files, filepath, result):
                if self._stop:
                    return
                elapsed = time.time() - t0
                rate = i / elapsed if elapsed > 0 else 0
                pct = i / total_files * 100
                self.signals.progress.emit(pct)
                self.signals.status.emit(
                    f'{i}/{total_files} ({rate:.1f}/s) - {filepath.name}')

                if result.error:
                    self.signals.log.emit(html_error(
                        f'  [{i}/{total_files}] {filepath.name} | '
                        f'ERROR: {result.error}'))
                elif result.findings_cleared > 0:
                    verified = ' [verified]' if result.verified else ''
                    self.signals.log.emit(html_warning(
                        f'  [{i}/{total_files}] {filepath.name} | '
                        f'cleared {result.findings_cleared} finding(s)'
                        f'{verified}'))
                else:
                    self.signals.log.emit(html_success(
                        f'  [{i}/{total_files}] {filepath.name} | '
                        f'already clean'))

                # Image integrity result
                if result.image_integrity_verified is True:
                    self.signals.log.emit(html_success(
                        '    Image data integrity: VERIFIED (SHA-256 match)'))
                elif result.image_integrity_verified is False:
                    self.signals.log.emit(html_error(
                        '    Image data integrity: FAILED'))

                # SHA-256 of output file
                if result.sha256_after:
                    self.signals.log.emit(html_dim(
                        f'    SHA-256: {result.sha256_after}'))

                # Filename PHI warning
                if result.filename_has_phi:
                    self.signals.log.emit(html_error(
                        '    WARNING: Filename contains PHI -- rename file manually'))

            batch_result = anonymize_batch(
                self.input_path, output_dir=self.output_dir,
                verify=self.verify, progress_callback=progress,
                workers=self.workers,
                reset_timestamps=self.reset_timestamps,
                dry_run=self.dry_run,
                format_filter=self.format_filter,
                verify_integrity=self.verify_integrity,
                stop_check=lambda: self._stop,
                file_list=self.file_list,
            )

            cert_path = None

            # Generate certificate (skip in dry-run mode)
            if not self.dry_run:
                if self.output_dir:
                    cert_path = self.output_dir / 'pathsafe_certificate.json'
                elif self.input_path.is_dir():
                    cert_path = self.input_path / 'pathsafe_certificate.json'
                else:
                    cert_path = self.input_path.parent / 'pathsafe_certificate.json'

                generate_certificate(
                    batch_result, output_path=cert_path,
                    timestamps_reset=self.reset_timestamps,
                    institution=self.institution,
                )

            # Summary
            self.signals.log.emit(html_separator())
            self.signals.log.emit(html_header(
                f'Done in {batch_result.total_time_seconds:.1f}s'))
            self.signals.log.emit(
                html_summary_line('Total:', batch_result.total_files, 'white'))
            if batch_result.files_anonymized:
                self.signals.log.emit(
                    html_summary_line('Anonymized:',
                                      batch_result.files_anonymized, 'orange'))
            if batch_result.files_already_clean:
                self.signals.log.emit(
                    html_summary_line('Already clean:',
                                      batch_result.files_already_clean, 'green'))
            if batch_result.files_errored:
                self.signals.log.emit(
                    html_summary_line('Errors:',
                                      batch_result.files_errored, 'red'))
            pdf_cert_path = None
            if cert_path:
                pdf_cert_path = cert_path.with_suffix('.pdf')
                self.signals.log.emit(
                    html_info(f'Certificate: {cert_path}'))
                self.signals.log.emit(
                    html_info(f'PDF certificate: {pdf_cert_path}'))
            if self.dry_run:
                self.signals.log.emit(
                    html_warning('DRY RUN - no files were modified.'))

            # Count integrity results
            integrity_verified = sum(
                1 for r in batch_result.results
                if r.image_integrity_verified is True)
            integrity_failed = sum(
                1 for r in batch_result.results
                if r.image_integrity_verified is False)
            phi_filenames = sum(
                1 for r in batch_result.results
                if r.filename_has_phi)

            # Log filename PHI warning in summary
            if phi_filenames:
                self.signals.log.emit(html_error(
                    f'WARNING: {phi_filenames} file(s) have PHI in their '
                    f'filename -- rename manually'))

            self.signals.summary.emit({
                'type': 'anonymize',
                'total': batch_result.total_files,
                'anonymized': batch_result.files_anonymized,
                'already_clean': batch_result.files_already_clean,
                'errors': batch_result.files_errored,
                'time': f'{batch_result.total_time_seconds:.1f}s',
                'certificate': str(cert_path) if cert_path else '',
                'pdf_certificate': str(pdf_cert_path) if pdf_cert_path else '',
                'output_dir': str(self.output_dir) if self.output_dir else '',
                'timestamps_reset': self.reset_timestamps,
                'dry_run': self.dry_run,
                'integrity_verified': integrity_verified,
                'integrity_failed': integrity_failed,
                'phi_filenames': phi_filenames,
                'output_paths': [
                    str(r.output_path) for r in batch_result.results
                    if not r.error
                ],
            })
            if batch_result.files_errored == 0:
                self.signals.status.emit('Anonymization complete')
            else:
                self.signals.status.emit(
                    f'Done with {batch_result.files_errored} error(s)')
        except Exception as e:
            self.signals.log.emit(html_error(f'ERROR: {e}'))
            self.signals.status.emit(f'Error: {e}')
        finally:
            self.signals.finished.emit()


class VerifyWorker(QThread):
    """Background thread for verifying files."""

    def __init__(self, input_path, signals, format_filter=None,
                 file_list=None):
        super().__init__()
        self.input_path = input_path
        self.signals = signals
        self.format_filter = format_filter
        self.file_list = file_list  # specific files to verify (from last anonymize)

    def run(self):
        try:
            if self.file_list:
                # Verify only the specific files from the last anonymize run
                files = [Path(p) for p in self.file_list if Path(p).exists()]
            else:
                files = collect_wsi_files(self.input_path,
                                          format_filter=self.format_filter)
            total = len(files)
            if total == 0:
                self.signals.log.emit(html_warning('No WSI files found.'))
                return

            fmt_str = f' [{self.format_filter.upper()}]' if self.format_filter else ''
            self.signals.log.emit(
                html_header(f'PathSafe v{pathsafe.__version__} - Verification'
                            f'{fmt_str}'))
            self.signals.log.emit(
                html_info(f'Verifying {total} file(s)...'))
            self.signals.log.emit(html_separator())

            clean = 0
            dirty = 0

            if self.file_list:
                # Verify individual files directly
                for i, filepath in enumerate(files):
                    handler = get_handler(filepath)
                    result = handler.scan(filepath)
                    pct = (i + 1) / total * 100
                    self.signals.progress.emit(pct)
                    self.signals.status.emit(
                        f'Verifying {i + 1}/{total}: {filepath.name}')
                    if result.is_clean:
                        clean += 1
                    else:
                        dirty += 1
                        findings_str = ', '.join(
                            f.tag_name for f in result.findings)
                        self.signals.log.emit(html_error(
                            f'  PHI FOUND: {filepath.name} - '
                            f'{findings_str}'))
            else:
                def progress(i, total_files, filepath, result):
                    pct = i / total_files * 100
                    self.signals.progress.emit(pct)
                    self.signals.status.emit(
                        f'Verifying {i}/{total_files}: {filepath.name}')

                results = verify_batch(
                    self.input_path, progress_callback=progress,
                    format_filter=self.format_filter)

                for result in results:
                    if result.is_clean:
                        clean += 1
                    else:
                        dirty += 1
                        findings_str = ', '.join(
                            f.tag_name for f in result.findings)
                        self.signals.log.emit(html_error(
                            f'  PHI FOUND: {result.filepath.name} - '
                            f'{findings_str}'))

            # Summary
            self.signals.log.emit(html_separator())
            self.signals.log.emit(html_header('Verification Results'))
            if clean:
                self.signals.log.emit(
                    html_summary_line('Clean:', clean, 'green'))
            if dirty:
                self.signals.log.emit(
                    html_summary_line('PHI remaining:', dirty, 'red'))

            self.signals.summary.emit({
                'type': 'verify',
                'total': total,
                'clean': clean,
                'dirty': dirty,
            })
            if dirty == 0:
                self.signals.log.emit(
                    html_success('All files verified clean.'))
                self.signals.status.emit(
                    'Verification passed - all files clean')
            else:
                self.signals.log.emit(
                    html_error('WARNING: Some files still contain PHI!'))
                self.signals.status.emit(
                    f'WARNING: {dirty} file(s) with remaining PHI')
        except Exception as e:
            self.signals.log.emit(html_error(f'ERROR: {e}'))
            self.signals.status.emit(f'Error: {e}')
        finally:
            self.signals.finished.emit()


class InfoWorker(QThread):
    """Background thread for retrieving file information."""

    def __init__(self, filepath, signals):
        super().__init__()
        self.filepath = filepath
        self.signals = signals

    def run(self):
        try:
            self.signals.log.emit(
                html_header(f'PathSafe v{pathsafe.__version__} - File Info'))
            self.signals.log.emit(
                html_info(f'File: {self.filepath.name}'))
            self.signals.log.emit(html_separator())

            fmt = detect_format(self.filepath)
            handler = get_handler(self.filepath)
            file_info = handler.get_format_info(self.filepath)
            scan_result = handler.scan(self.filepath)

            file_size = self.filepath.stat().st_size
            if file_size >= 1_073_741_824:
                size_str = f'{file_size / 1_073_741_824:.2f} GB'
            elif file_size >= 1_048_576:
                size_str = f'{file_size / 1_048_576:.1f} MB'
            elif file_size >= 1024:
                size_str = f'{file_size / 1024:.1f} KB'
            else:
                size_str = f'{file_size} bytes'

            metadata_count = len(file_info) if isinstance(file_info, dict) else 0

            self.signals.log.emit(
                html_summary_line('Format:', fmt.upper(), 'white'))
            self.signals.log.emit(
                html_summary_line('File size:', size_str, 'white'))
            self.signals.log.emit(
                html_summary_line('Metadata entries:', metadata_count, 'white'))

            if isinstance(file_info, dict):
                for key, value in file_info.items():
                    val_str = str(value)
                    if len(val_str) > 120:
                        val_str = val_str[:120] + '...'
                    self.signals.log.emit(html_dim(f'  {key}: {val_str}'))

            self.signals.log.emit(html_separator())

            if scan_result.is_clean:
                phi_status = 'Clean - no PHI detected'
                self.signals.log.emit(
                    html_success(f'PHI Status: {phi_status}'))
            else:
                phi_status = f'{len(scan_result.findings)} finding(s)'
                self.signals.log.emit(
                    html_warning(f'PHI Status: {phi_status}'))
                for f in scan_result.findings:
                    self.signals.log.emit(html_finding(
                        f'  {f.tag_name}: {f.value_preview}'))

            self.signals.summary.emit({
                'type': 'info',
                'format': fmt.upper(),
                'size': size_str,
                'metadata_count': metadata_count,
                'phi_status': phi_status,
            })
            self.signals.status.emit('File info complete')
        except Exception as e:
            self.signals.log.emit(html_error(f'ERROR: {e}'))
            self.signals.status.emit(f'Error: {e}')
        finally:
            self.signals.finished.emit()


class ConvertWorker(QThread):
    """Background thread for converting files."""

    def __init__(self, input_path, output_path, target_format, extract,
                 tile_size, quality, anonymize_after, reset_timestamps,
                 workers, format_filter, signals):
        super().__init__()
        self.input_path = input_path
        self.output_path = output_path
        self.target_format = target_format
        self.extract = extract
        self.tile_size = tile_size
        self.quality = quality
        self.anonymize_after = anonymize_after
        self.reset_timestamps = reset_timestamps
        self.workers = workers
        self.format_filter = format_filter
        self.signals = signals
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        try:
            try:
                from pathsafe.converter import convert_file, convert_batch
            except ImportError:
                self.signals.log.emit(html_error(
                    'Conversion requires openslide, tifffile, and numpy. '
                    'Install with: pip install pathsafe[convert]'))
                return

            if self.extract and self.input_path.is_dir():
                self.signals.log.emit(html_error(
                    'Extract mode (label/macro/thumbnail) is only supported '
                    'for single files, not directories.'))
                return

            t0 = time.time()

            if self.input_path.is_file():
                self.signals.log.emit(html_header(
                    f'PathSafe v{pathsafe.__version__} - File Conversion'))
                self.signals.log.emit(html_info(
                    f'Converting: {self.input_path.name}'))
                self.signals.log.emit(html_separator())

                result = convert_file(
                    self.input_path, self.output_path,
                    target_format=self.target_format,
                    tile_size=self.tile_size,
                    quality=self.quality,
                    extract=self.extract,
                    anonymize=self.anonymize_after,
                    reset_timestamps=self.reset_timestamps,
                )

                elapsed = time.time() - t0

                if result.error:
                    self.signals.log.emit(html_error(
                        f'  {self.input_path.name} - ERROR: {result.error}'))
                    self.signals.summary.emit({
                        'type': 'convert',
                        'total': 1,
                        'converted': 0,
                        'errors': 1,
                        'time': f'{elapsed:.1f}s',
                    })
                else:
                    self.signals.log.emit(html_success(
                        f'  {self.input_path.name} - converted successfully'))
                    self.signals.progress.emit(100)
                    self.signals.summary.emit({
                        'type': 'convert',
                        'total': 1,
                        'converted': 1,
                        'errors': 0,
                        'time': f'{elapsed:.1f}s',
                    })

                self.signals.status.emit('Conversion complete')

            else:
                # Directory batch conversion
                workers_str = (f', {self.workers} workers'
                               if self.workers > 1 else '')
                fmt_str = (f' [{self.format_filter.upper()}]'
                           if self.format_filter else '')
                self.signals.log.emit(html_header(
                    f'PathSafe v{pathsafe.__version__} - Batch Conversion'
                    f'{fmt_str}{workers_str}'))

                files = collect_wsi_files(self.input_path,
                                          format_filter=self.format_filter)
                total = len(files)
                if total == 0:
                    self.signals.log.emit(
                        html_warning('No WSI files found.'))
                    return

                self.signals.log.emit(html_info(
                    f'Converting {total} file(s)...'))
                self.signals.log.emit(html_separator())

                converted_count = 0
                error_count = 0

                def on_progress(i, total_files, filepath, result):
                    nonlocal converted_count, error_count
                    pct = i / total_files * 100
                    self.signals.progress.emit(pct)
                    self.signals.status.emit(
                        f'Converting {i}/{total_files}: {filepath.name}')

                    if result.error:
                        error_count += 1
                        self.signals.log.emit(html_error(
                            f'  [{i}/{total_files}] {filepath.name} - '
                            f'ERROR: {result.error}'))
                    else:
                        converted_count += 1
                        self.signals.log.emit(html_success(
                            f'  [{i}/{total_files}] {filepath.name} - '
                            f'converted'))

                convert_batch(
                    self.input_path, self.output_path,
                    target_format=self.target_format,
                    tile_size=self.tile_size,
                    quality=self.quality,
                    anonymize=self.anonymize_after,
                    format_filter=self.format_filter,
                    progress_callback=on_progress,
                    workers=self.workers,
                    reset_timestamps=self.reset_timestamps,
                )

                elapsed = time.time() - t0

                self.signals.log.emit(html_separator())
                self.signals.log.emit(html_header(
                    f'Done in {elapsed:.1f}s'))

                self.signals.summary.emit({
                    'type': 'convert',
                    'total': total,
                    'converted': converted_count,
                    'errors': error_count,
                    'time': f'{elapsed:.1f}s',
                })
                self.signals.status.emit('Conversion complete')

        except Exception as e:
            self.signals.log.emit(html_error(f'ERROR: {e}'))
            self.signals.status.emit(f'Error: {e}')
        finally:
            self.signals.finished.emit()


# --- Custom Widgets ---

class DropZoneWidget(QWidget):
    """Drag-and-drop zone for files and folders."""

    pathDropped = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setFixedHeight(36)

        layout = QHBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)
        layout.setContentsMargins(4, 2, 4, 2)

        self._icon_label = QLabel("Drag files or folders here")
        self._icon_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._icon_label)

        self._hint_label = QLabel("or use Step 1 to browse")
        self._hint_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._hint_label)

        self._theme = 'dark'
        self._apply_theme_colors()

    def set_theme(self, theme):
        self._theme = theme
        self._apply_theme_colors()

    def _apply_theme_colors(self):
        c = THEME_COLORS[self._theme]
        self._icon_label.setStyleSheet(
            f"QLabel {{ color: {c['drop_text']}; font-size: 14px; "
            f"font-weight: bold; }}")
        self._hint_label.setStyleSheet(
            f"QLabel {{ color: {c['drop_hint']}; font-size: 11px; }}")
        self._default_ss = (
            f"DropZoneWidget {{ border: 2px dashed {c['drop_border']}; "
            f"border-radius: 10px; background-color: {c['drop_bg']}; }}")
        self._hover_ss = (
            f"DropZoneWidget {{ border: 2px dashed {c['drop_hover_border']}; "
            f"border-radius: 10px; background-color: {c['drop_hover_bg']}; }}")
        self.setStyleSheet(self._default_ss)

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self.setStyleSheet(self._hover_ss)
            self._icon_label.setText("Drop to select")

    def dragLeaveEvent(self, event):
        self.setStyleSheet(self._default_ss)
        self._icon_label.setText("Drag files or folders here")

    def dropEvent(self, event: QDropEvent):
        self.setStyleSheet(self._default_ss)
        self._icon_label.setText("Drag files or folders here")
        urls = event.mimeData().urls()
        if urls:
            self.pathDropped.emit(urls[0].toLocalFile())


class StepIndicator(QFrame):
    """Visual workflow indicator: Select Files -> Scan -> Anonymize -> Verify."""

    STEPS = ['Select Files', 'Scan', 'Anonymize', 'Verify']

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(56)
        self._current = 0
        self._completed = set()
        self._theme = 'dark'

    def set_theme(self, theme):
        self._theme = theme
        self.update()

    def set_step(self, index):
        self._current = index
        self.update()

    def mark_completed(self, index):
        self._completed.add(index)
        self.update()

    def reset(self):
        self._current = 0
        self._completed.clear()
        self.update()

    def paintEvent(self, event):
        c = THEME_COLORS[self._theme]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        w = self.width()
        h = self.height()
        n = len(self.STEPS)
        spacing = w / n
        r = 13

        for i, label in enumerate(self.STEPS):
            cx = int(spacing * i + spacing / 2)
            cy = int(h / 2 - 6)

            # Connecting line
            if i > 0:
                prev_cx = int(spacing * (i - 1) + spacing / 2)
                color = QColor(c['completed']) if (i - 1) in self._completed else QColor(c['inactive_border'])
                painter.setPen(QPen(color, 2))
                painter.drawLine(prev_cx + r, cy, cx - r, cy)

            # Circle
            if i in self._completed:
                painter.setBrush(QBrush(QColor(c['completed'])))
                painter.setPen(QPen(QColor(c['completed']), 2))
            elif i == self._current:
                painter.setBrush(QBrush(QColor(c['active'])))
                painter.setPen(QPen(QColor(c['active']), 2))
            else:
                painter.setBrush(QBrush(QColor(c['inactive_fill'])))
                painter.setPen(QPen(QColor(c['inactive_border']), 2))

            painter.drawEllipse(cx - r, cy - r, r * 2, r * 2)

            # Number or check
            is_active = i in self._completed or i == self._current
            painter.setPen(QPen(QColor(c['circle_inner'] if is_active else c['text_dim'])))
            font = QFont('', 10)
            font.setBold(True)
            painter.setFont(font)
            text = 'OK' if i in self._completed else str(i + 1)
            tw = painter.fontMetrics().horizontalAdvance(text)
            painter.drawText(cx - tw // 2, cy + 5, text)

            # Label below
            painter.setPen(QPen(QColor(c['text_bright'] if i == self._current else c['text_dim'])))
            font = QFont('', 9)
            painter.setFont(font)
            tw = painter.fontMetrics().horizontalAdvance(label)
            painter.drawText(cx - tw // 2, cy + r + 15, label)

        painter.end()


# --- Main Window ---

class PathSafeWindow(QMainWindow):
    """Main application window."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle(
            f'PathSafe v{pathsafe.__version__} - WSI Anonymizer')
        # Set application icon (works both from source and PyInstaller bundle)
        base = Path(getattr(sys, '_MEIPASS', Path(__file__).parent))
        icon_path = base / 'pathsafe' / 'assets' / 'icon.png'
        if not icon_path.exists():
            icon_path = Path(__file__).parent / 'assets' / 'icon.png'
        if icon_path.exists():
            app_icon = QIcon(str(icon_path))
            self.setWindowIcon(app_icon)
            QApplication.instance().setWindowIcon(app_icon)
        self.resize(1050, 760)
        self.setMinimumSize(1050, 700)

        self._worker = None
        self._last_dir = str(Path.home())
        self._last_anonymized_paths = []  # output paths from last anonymize run
        self._last_output_dir = None  # actual output dir (date-stamped subfolder)
        self._selected_files = []  # multi-file selection list
        self._settings = QSettings('PathSafe', 'PathSafe')
        self._current_theme = self._settings.value('theme', 'dark')
        self._institution_name = self._settings.value('institution_name', '')
        self._saved_workers = int(self._settings.value('workers', 4))
        self._step_completed = set()  # track completed steps {1, 2, 3}
        self._step_labels = {
            1: ('Step 1', 'Select Files'),
            2: ('Step 2', 'Scan for PHI'),
            3: ('Step 3', 'Select File Output'),
            4: ('Step 4', 'Anonymize'),
        }
        self._step_buttons = {}  # populated in _build_ui

        self._build_menu_bar()
        self._build_ui()
        self._setup_status_bar()
        self._apply_theme(self._current_theme)

        # Set default output path
        default_output = self._get_default_output_dir()
        self.output_edit.setText(str(default_output))
        self._mark_step_default(3)

    def _build_menu_bar(self):
        menu_bar = self.menuBar()

        # File menu
        file_menu = menu_bar.addMenu("&File")

        open_file = QAction("Open &File...", self)
        open_file.setShortcut(QKeySequence.Open)
        open_file.triggered.connect(self._browse_input_file)
        file_menu.addAction(open_file)

        open_folder = QAction("Open F&older...", self)
        open_folder.setShortcut("Ctrl+Shift+O")
        open_folder.triggered.connect(self._browse_input_dir)
        file_menu.addAction(open_folder)

        file_menu.addSeparator()

        exit_action = QAction("E&xit", self)
        exit_action.setShortcut(QKeySequence.Quit)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        # Actions menu
        actions_menu = menu_bar.addMenu("&Actions")

        self._scan_action = QAction("&Scan for PHI", self)
        self._scan_action.setShortcut("Ctrl+S")
        self._scan_action.triggered.connect(self._run_scan)
        actions_menu.addAction(self._scan_action)

        self._anonymize_action = QAction("&Anonymize", self)
        self._anonymize_action.setShortcut("Ctrl+R")
        self._anonymize_action.triggered.connect(self._run_anonymize)
        actions_menu.addAction(self._anonymize_action)

        self._verify_action = QAction("&Verify", self)
        self._verify_action.setShortcut("Ctrl+E")
        self._verify_action.triggered.connect(self._run_verify)
        actions_menu.addAction(self._verify_action)

        self._info_action = QAction("File &Info", self)
        self._info_action.setShortcut("Ctrl+I")
        self._info_action.triggered.connect(self._run_info)
        actions_menu.addAction(self._info_action)

        self._convert_action = QAction("&Convert", self)
        self._convert_action.setShortcut("Ctrl+T")
        self._convert_action.triggered.connect(self._run_convert)
        actions_menu.addAction(self._convert_action)

        actions_menu.addSeparator()

        self._save_log_action = QAction("Save &Log...", self)
        self._save_log_action.setShortcut("Ctrl+L")
        self._save_log_action.triggered.connect(self._save_log)
        actions_menu.addAction(self._save_log_action)

        actions_menu.addSeparator()

        self._stop_action = QAction("S&top", self)
        self._stop_action.setShortcut("Escape")
        self._stop_action.setEnabled(False)
        self._stop_action.triggered.connect(self._request_stop)
        actions_menu.addAction(self._stop_action)

        # View menu
        view_menu = menu_bar.addMenu("&View")

        theme_group = QActionGroup(self)
        theme_group.setExclusive(True)

        self._dark_action = QAction("&Dark Theme", self)
        self._dark_action.setCheckable(True)
        self._dark_action.setChecked(self._current_theme == 'dark')
        self._dark_action.triggered.connect(lambda: self._apply_theme('dark'))
        theme_group.addAction(self._dark_action)
        view_menu.addAction(self._dark_action)

        self._light_action = QAction("&Light Theme", self)
        self._light_action.setCheckable(True)
        self._light_action.setChecked(self._current_theme == 'light')
        self._light_action.triggered.connect(lambda: self._apply_theme('light'))
        theme_group.addAction(self._light_action)
        view_menu.addAction(self._light_action)

        # Help menu
        help_menu = menu_bar.addMenu("&Help")
        about_action = QAction("&About PathSafe", self)
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(14, 8, 14, 8)
        layout.setSpacing(8)

        # === Top section: step panel (left) + controls (right) ===
        top_split = QHBoxLayout()
        top_split.setSpacing(10)

        # --- Left: Workflow step buttons ---
        step_group = QGroupBox('Workflow')
        step_layout = QVBoxLayout(step_group)
        step_layout.setSpacing(6)

        self.btn_select = QPushButton('Step 1\nSelect Files')
        self.btn_select.setObjectName('btn_info')
        self.btn_select.setToolTip(
            "Browse for WSI files or a folder to process.")
        self.btn_select.clicked.connect(self._browse_input_file_or_folder)
        step_layout.addWidget(self.btn_select)

        self.btn_scan = QPushButton('Step 2\nScan for PHI')
        self.btn_scan.setObjectName('btn_scan')
        self.btn_scan.setToolTip(
            "Scan files to detect patient information (PHI)\n"
            "without modifying anything. [Ctrl+S]")
        self.btn_scan.clicked.connect(self._run_scan)
        step_layout.addWidget(self.btn_scan)

        self.btn_output = QPushButton('Step 3\nSelect File Output')
        self.btn_output.setObjectName('btn_convert')
        self.btn_output.setToolTip(
            "Choose the output folder where anonymized\n"
            "copies will be saved.")
        self.btn_output.clicked.connect(self._browse_output_dir_step)
        step_layout.addWidget(self.btn_output)

        self.btn_anonymize = QPushButton('Step 4\nAnonymize')
        self.btn_anonymize.setObjectName('btn_anonymize')
        self.btn_anonymize.setToolTip(
            "Remove all detected patient information from files,\n"
            "then automatically verify everything was removed. [Ctrl+R]")
        self.btn_anonymize.clicked.connect(self._run_anonymize)
        step_layout.addWidget(self.btn_anonymize)

        self.btn_stop = QPushButton('Stop')
        self.btn_stop.setObjectName('btn_stop')
        self.btn_stop.setEnabled(False)
        self.btn_stop.setToolTip(
            "Stop the current operation after the\n"
            "current file finishes. [Escape]")
        self.btn_stop.clicked.connect(self._request_stop)
        step_layout.addWidget(self.btn_stop)

        # Step buttons: fixed height so they don't stretch the top section
        for btn in (self.btn_select, self.btn_scan, self.btn_output,
                    self.btn_anonymize):
            btn.setFixedHeight(70)
        self.btn_stop.setFixedHeight(50)

        step_group.setFixedWidth(170)
        self._step_buttons = {
            1: self.btn_select, 2: self.btn_scan, 3: self.btn_output,
            4: self.btn_anonymize,
        }
        top_split.addWidget(step_group)

        # --- Right: Input + options ---
        controls_layout = QVBoxLayout()
        controls_layout.setSpacing(10)

        # Input Group (drop zone + path row)
        paths_group = QGroupBox('Input')
        paths_layout = QVBoxLayout(paths_group)

        self.drop_zone = DropZoneWidget()
        self.drop_zone.pathDropped.connect(self._on_path_dropped)
        paths_layout.addWidget(self.drop_zone)

        input_row = QHBoxLayout()
        self.input_edit = QLineEdit()
        self.input_edit.setPlaceholderText('Path to WSI file or folder...')
        self.input_edit.setToolTip(
            "Path to a single WSI file (.ndpi, .svs, .mrxs, .dcm, .tiff)\n"
            "or a folder containing WSI files.\n"
            "You can also drag and drop files here.")
        input_row.addWidget(self.input_edit, 1)
        paths_layout.addLayout(input_row)

        controls_layout.addWidget(paths_group)

        # Tab Widget (Anonymize / Convert)
        self.tabs = QTabWidget()
        controls_layout.addWidget(self.tabs)

        self._build_anonymize_tab()
        self._build_convert_tab()

        top_split.addLayout(controls_layout, 1)

        # Wrap top section with max height so log gets priority
        top_widget = QWidget()
        top_widget.setLayout(top_split)
        top_widget.setMaximumHeight(440)
        layout.addWidget(top_widget)

        # === Progress bar (full width) ===
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        layout.addWidget(self.progress_bar)

        # === Log panel (full width) ===
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        log_font = QFont()
        for family in ('JetBrains Mono', 'Cascadia Code', 'Fira Code',
                        'Source Code Pro', 'Consolas', 'Ubuntu Mono',
                        'DejaVu Sans Mono', 'monospace'):
            log_font.setFamily(family)
            if log_font.exactMatch():
                break
        log_font.setPointSize(11)
        log_font.setStyleHint(QFont.Monospace)
        self.log_text.setFont(log_font)
        self.log_text.setStyleSheet(
            self.log_text.styleSheet() + 'QTextEdit { line-height: 140%; padding: 6px; }')
        layout.addWidget(self.log_text, 1)

        # === Export buttons ===
        export_row = QHBoxLayout()
        self.btn_save_log = QPushButton('Save Log')
        self.btn_save_log.setToolTip("Save the log output as an HTML file.")
        self.btn_save_log.clicked.connect(self._save_log)
        export_row.addWidget(self.btn_save_log)

        export_row.addStretch()
        layout.addLayout(export_row)

    def _build_anonymize_tab(self):
        """Build the Anonymize tab with output, options, compliance, and action buttons."""
        anon_tab = QWidget()
        anon_layout = QVBoxLayout(anon_tab)
        anon_layout.setContentsMargins(8, 8, 8, 8)
        anon_layout.setSpacing(8)

        # --- Output row ---
        output_row = QHBoxLayout()
        output_row.addWidget(QLabel('Output:'))
        self.output_edit = QLineEdit()
        self.output_edit.setPlaceholderText('Output folder for copy mode...')
        self.output_edit.setToolTip(
            "Where anonymized copies will be saved.\n"
            "Only needed in Copy mode.")
        output_row.addWidget(self.output_edit, 1)
        anon_layout.addLayout(output_row)

        # --- Options ---
        opts_group = QGroupBox('Options')
        opts_vlayout = QVBoxLayout(opts_group)
        opts_vlayout.setSpacing(8)
        opts_vlayout.setContentsMargins(12, 14, 12, 10)

        # Row 1: Mode
        mode_row = QHBoxLayout()
        mode_label = QLabel('Mode:')
        mode_label.setFixedWidth(70)
        mode_row.addWidget(mode_label)
        self.radio_copy = QRadioButton('Copy and anonymize')
        self.radio_copy.setChecked(True)
        self.radio_copy.setToolTip(
            "Creates anonymized copies in the output folder.\n"
            "Your original files are never modified. (Recommended)")
        self.radio_inplace = QRadioButton('Modify originals directly')
        self.radio_inplace.setToolTip(
            "Modifies the original files directly.\n"
            "WARNING: Original data cannot be recovered after anonymization.")
        self.radio_inplace.toggled.connect(self._on_inplace_toggled)
        mode_group = QButtonGroup(self)
        mode_group.addButton(self.radio_copy)
        mode_group.addButton(self.radio_inplace)
        mode_row.addWidget(self.radio_copy)
        mode_row.addSpacing(20)
        mode_row.addWidget(self.radio_inplace)
        mode_row.addStretch()
        opts_vlayout.addLayout(mode_row)

        # Row 2: Workers
        workers_row = QHBoxLayout()
        workers_label = QLabel('Workers (anonymize only):')
        workers_label.setMinimumWidth(70)
        workers_row.addWidget(workers_label)
        self.slider_workers = QSlider(Qt.Horizontal)
        self.slider_workers.setRange(1, 16)
        self.slider_workers.setValue(self._saved_workers)
        self.slider_workers.setToolTip(
            "Number of files to process simultaneously.\n"
            "Applies to anonymization only (scanning is single-threaded).\n"
            "Higher values are faster but use more memory.\n"
            "Recommended: 2-4 for most systems.")
        self._workers_label = QLabel(str(self._saved_workers))
        self._workers_label.setFixedWidth(24)
        self._workers_label.setAlignment(Qt.AlignCenter)
        self.slider_workers.valueChanged.connect(self._on_workers_changed)
        workers_row.addWidget(self.slider_workers, 1)
        workers_row.addWidget(self._workers_label)
        opts_vlayout.addLayout(workers_row)

        # Row 2b: Institution name
        institution_row = QHBoxLayout()
        institution_label = QLabel('Institution for report (optional):')
        institution_label.setMinimumWidth(70)
        institution_row.addWidget(institution_label)
        self.institution_edit = QLineEdit()
        self.institution_edit.setMinimumHeight(36)
        self.institution_edit.setMaximumWidth(500)
        self.institution_edit.setPlaceholderText(
            'e.g. "Memorial General Hospital"')
        self.institution_edit.setToolTip(
            "Institution name displayed on PDF scan reports\n"
            "and anonymization certificates.\n"
            "Leave empty to omit from reports.")
        self.institution_edit.setText(self._institution_name)
        self.institution_edit.textChanged.connect(self._on_institution_changed)
        institution_row.addWidget(self.institution_edit, 1)
        opts_vlayout.addLayout(institution_row)

        # Row 3: Format + Dry run
        format_row = QHBoxLayout()
        format_label = QLabel('Format:')
        format_label.setFixedWidth(70)
        format_row.addWidget(format_label)
        self.combo_format_filter = QComboBox()
        self.combo_format_filter.addItems(_FORMAT_FILTER_ITEMS)
        self.combo_format_filter.setToolTip(
            "Only process files of the selected format.\n"
            "\"All formats\" processes every supported WSI format.")
        self.combo_format_filter.setFixedWidth(150)
        format_row.addWidget(self.combo_format_filter)
        format_row.addSpacing(30)
        self.check_dry_run = QCheckBox('Dry run (preview only)')
        self.check_dry_run.setToolTip(
            "Scan and report findings without modifying any files.")
        format_row.addWidget(self.check_dry_run)
        format_row.addStretch()
        opts_vlayout.addLayout(format_row)

        anon_layout.addWidget(opts_group)

        self.tabs.addTab(anon_tab, 'Anonymize')

    def _build_convert_tab(self):
        """Build the Convert tab with output, conversion options, and action buttons."""
        conv_tab = QWidget()
        conv_layout = QVBoxLayout(conv_tab)
        conv_layout.setContentsMargins(8, 8, 8, 8)
        conv_layout.setSpacing(8)

        # --- Output row ---
        output_row = QHBoxLayout()
        output_row.addWidget(QLabel('Output:'))
        self.convert_output_edit = QLineEdit()
        self.convert_output_edit.setPlaceholderText(
            'Output path for converted files (required)...')
        self.convert_output_edit.setToolTip(
            "Where converted files will be saved.\n"
            "Required for all conversions.")
        output_row.addWidget(self.convert_output_edit, 1)
        btn_conv_out = QPushButton('Browse')
        btn_conv_out.setFixedWidth(80)
        btn_conv_out.clicked.connect(self._browse_convert_output)
        output_row.addWidget(btn_conv_out)
        conv_layout.addLayout(output_row)

        # --- Conversion Options ---
        conv_group = QGroupBox('Conversion')
        conv_grid = QHBoxLayout(conv_group)

        conv_grid.addWidget(QLabel('Target format:'))
        self.combo_target_format = QComboBox()
        self.combo_target_format.addItems(
            ['Pyramidal TIFF', 'PNG', 'JPEG'])
        self.combo_target_format.setToolTip(
            "Output format for the converted files.")
        self.combo_target_format.setFixedWidth(140)
        conv_grid.addWidget(self.combo_target_format)

        conv_grid.addSpacing(16)
        conv_grid.addWidget(QLabel('Extract:'))
        self.combo_extract = QComboBox()
        self.combo_extract.addItems(
            ['Full conversion', 'Label image', 'Macro image', 'Thumbnail'])
        self.combo_extract.setToolTip(
            "Extract a specific image from the WSI instead of\n"
            "performing full conversion. Single file only.")
        self.combo_extract.setFixedWidth(140)
        conv_grid.addWidget(self.combo_extract)

        conv_grid.addSpacing(16)
        conv_grid.addWidget(QLabel('Tile size:'))
        self.combo_tile_size = QComboBox()
        self.combo_tile_size.addItems(['128', '256', '512', '1024'])
        self.combo_tile_size.setCurrentText('256')
        self.combo_tile_size.setToolTip(
            "Tile size for pyramidal TIFF output (pixels).\n"
            "256 is the most common and compatible.\n"
            "512 may be faster for very large files.")
        self.combo_tile_size.setFixedWidth(80)
        conv_grid.addWidget(self.combo_tile_size)

        conv_grid.addSpacing(16)
        conv_grid.addWidget(QLabel('Quality:'))
        self._quality_label = QLabel('90')
        self._quality_label.setFixedWidth(24)
        self._quality_label.setAlignment(Qt.AlignCenter)
        self.slider_quality = QSlider(Qt.Horizontal)
        self.slider_quality.setRange(1, 100)
        self.slider_quality.setValue(90)
        self.slider_quality.setFixedWidth(100)
        self.slider_quality.setToolTip(
            "JPEG compression quality (1-100).\n"
            "Higher is better quality but larger files.\n"
            "Default: 90")
        self.slider_quality.valueChanged.connect(
            lambda v: self._quality_label.setText(str(v)))
        conv_grid.addWidget(self.slider_quality)
        conv_grid.addWidget(self._quality_label)

        conv_grid.addStretch()
        conv_layout.addWidget(conv_group)

        # --- General Options ---
        opts_group = QGroupBox('Options')
        opts_layout = QHBoxLayout(opts_group)

        self.check_convert_anonymize = QCheckBox('Anonymize after conversion')
        self.check_convert_anonymize.setToolTip(
            "Run anonymization on the converted output files.")
        opts_layout.addWidget(self.check_convert_anonymize)

        opts_layout.addSpacing(16)
        opts_layout.addWidget(QLabel('Workers:'))
        self._convert_workers_label = QLabel('4')
        self._convert_workers_label.setFixedWidth(20)
        self._convert_workers_label.setAlignment(Qt.AlignCenter)
        self.slider_convert_workers = QSlider(Qt.Horizontal)
        self.slider_convert_workers.setRange(1, 16)
        self.slider_convert_workers.setValue(4)
        self.slider_convert_workers.setFixedWidth(100)
        self.slider_convert_workers.setToolTip(
            "Number of files to convert simultaneously.\n"
            "Default: 4")
        self.slider_convert_workers.valueChanged.connect(
            lambda v: self._convert_workers_label.setText(str(v)))
        opts_layout.addWidget(self.slider_convert_workers)
        opts_layout.addWidget(self._convert_workers_label)

        opts_layout.addSpacing(16)
        opts_layout.addWidget(QLabel('Format:'))
        self.combo_convert_format_filter = QComboBox()
        self.combo_convert_format_filter.addItems(_FORMAT_FILTER_ITEMS)
        self.combo_convert_format_filter.setToolTip(
            "Only convert files of the selected format.\n"
            "\"All formats\" converts every supported WSI format.")
        self.combo_convert_format_filter.setFixedWidth(120)
        opts_layout.addWidget(self.combo_convert_format_filter)

        opts_layout.addStretch()
        conv_layout.addWidget(opts_group)

        # --- Action Buttons ---
        btn_layout = QHBoxLayout()

        self.btn_convert = QPushButton('  Convert')
        self.btn_convert.setObjectName('btn_convert')
        self.btn_convert.setMinimumHeight(38)
        self.btn_convert.setToolTip(
            "Convert WSI files to the selected target format.")
        self.btn_convert.clicked.connect(self._run_convert)
        btn_layout.addWidget(self.btn_convert)

        self.btn_convert_stop = QPushButton('  Stop')
        self.btn_convert_stop.setObjectName('btn_stop')
        self.btn_convert_stop.setMinimumHeight(38)
        self.btn_convert_stop.setEnabled(False)
        self.btn_convert_stop.setToolTip(
            "Stop the current conversion after the\n"
            "current file finishes. [Escape]")
        self.btn_convert_stop.clicked.connect(self._request_stop)
        btn_layout.addWidget(self.btn_convert_stop)

        btn_layout.addStretch()
        conv_layout.addLayout(btn_layout)

        conv_layout.addStretch()
        self.tabs.addTab(conv_tab, 'Convert')

    def _setup_status_bar(self):
        sb = self.statusBar()
        self._status_files = QLabel("0 files")
        self._status_elapsed = QLabel("")
        sb.addPermanentWidget(self._status_files)
        sb.addPermanentWidget(self._status_elapsed)
        sb.showMessage("Ready - drag files here or use File > Open")

    # --- Default output ---

    def _get_default_output_dir(self):
        """Return the default output directory: ~/Documents/PathSafe Output/"""
        docs = QStandardPaths.writableLocation(QStandardPaths.DocumentsLocation)
        if not docs:
            docs = str(Path.home())
        return Path(docs) / 'PathSafe Output'

    def _create_timestamped_output_dir(self, base_dir):
        """Create a date-stamped subfolder inside base_dir and return its path."""
        stamp = datetime.now().strftime('%Y-%m-%d_%H-%M')
        output_dir = Path(base_dir) / stamp
        output_dir.mkdir(parents=True, exist_ok=True)
        return output_dir

    # --- Browse ---

    def _browse_input_file_or_folder(self):
        """Step 1 button: let user choose between file or folder."""
        dlg = QMessageBox(self)
        dlg.setWindowTitle('Select Input')
        dlg.setText('What would you like to open?')
        dlg.setIcon(QMessageBox.Question)
        btn_file = dlg.addButton('Files', QMessageBox.AcceptRole)
        btn_folder = dlg.addButton('Folder', QMessageBox.AcceptRole)
        # Hidden reject button so X closes the dialog without action
        btn_cancel = dlg.addButton(QMessageBox.Cancel)
        btn_cancel.hide()
        dlg.setEscapeButton(btn_cancel)
        dlg.setWindowFlags(Qt.Dialog | Qt.WindowCloseButtonHint)
        dlg.exec()
        clicked = dlg.clickedButton()
        if clicked == btn_file:
            self._browse_input_file()
        elif clicked == btn_folder:
            self._browse_input_dir()

    def _browse_input_file(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, 'Select WSI file(s)', self._last_dir,
            'WSI files (*.ndpi *.svs *.mrxs *.bif *.scn *.dcm *.dicom *.tif *.tiff);;All files (*)')
        if not paths:
            return
        # Validate extensions
        for path in paths:
            ext = Path(path).suffix.lower()
            if ext not in WSI_EXTENSIONS:
                supported = ', '.join(sorted(WSI_EXTENSIONS))
                QMessageBox.warning(
                    self, 'Unsupported File Type',
                    f'<p>The selected file (<b>{Path(path).name}</b>) is not a '
                    f'supported whole-slide image format.</p>'
                    f'<p>Supported extensions: <code>{supported}</code></p>')
                return
        self._selected_files = [Path(p) for p in paths]
        if len(paths) == 1:
            self.input_edit.setText(paths[0])
        else:
            self.input_edit.setText(
                f'{paths[0]} (+ {len(paths) - 1} more)')
        self._last_dir = str(Path(paths[0]).parent)
        self._mark_step_completed(1)

    def _browse_input_dir(self):
        path = QFileDialog.getExistingDirectory(
            self, 'Select folder with WSI files', self._last_dir)
        if path:
            self._selected_files = []
            self.input_edit.setText(path)
            self._last_dir = path
            self._mark_step_completed(1)

    def _browse_output_dir(self):
        # Start from current output path if set, otherwise last dir
        start_dir = self.output_edit.text().strip() or self._last_dir
        path = QFileDialog.getExistingDirectory(
            self, 'Select output folder', start_dir)
        if path:
            self.output_edit.setText(path)
            self._last_dir = path
            self._mark_step_completed(3)

    def _browse_output_dir_step(self):
        self._browse_output_dir()

    def _browse_convert_output(self):
        path = QFileDialog.getExistingDirectory(
            self, 'Select conversion output folder', self._last_dir)
        if path:
            self.convert_output_edit.setText(path)
            self._last_dir = path

    def _on_inplace_toggled(self, checked):
        """Warn the user when they select in-place mode."""
        if not checked:
            return
        dlg = QMessageBox(self)
        dlg.setWindowTitle('Warning: Modify Originals')
        dlg.setIcon(QMessageBox.Warning)
        dlg.setText(
            '<h3>You have selected in-place mode</h3>'
            '<p>This will <b>permanently modify your original files</b>. '
            'Patient information will be removed directly from the source files.</p>'
            '<p><b>This cannot be undone.</b> If you do not have backups of your '
            'original files, the unmodified data will be lost forever.</p>'
            '<p>For safety, we recommend using <b>"Copy and anonymize"</b> instead, '
            'which creates clean copies and leaves your originals untouched.</p>')
        btn_continue = dlg.addButton('I understand, use in-place', QMessageBox.AcceptRole)
        btn_cancel = dlg.addButton('Switch back to Copy mode', QMessageBox.RejectRole)
        dlg.setDefaultButton(btn_cancel)
        dlg.exec()
        if dlg.clickedButton() != btn_continue:
            self.radio_copy.setChecked(True)

    def _on_path_dropped(self, path):
        p = Path(path)
        if p.exists():
            self._selected_files = []
            self.input_edit.setText(path)
            self._last_dir = str(p.parent if p.is_file() else p)
            self._mark_step_completed(1)

    # --- Logging ---

    def _log(self, msg):
        """Append an HTML-formatted log message."""
        cursor = self.log_text.textCursor()
        cursor.movePosition(QTextCursor.End)
        cursor.insertHtml(msg + '<br>')
        self.log_text.moveCursor(QTextCursor.End)

    def _set_progress(self, pct):
        self.progress_bar.setValue(int(pct))

    def _set_status(self, msg):
        self.statusBar().showMessage(msg)

    # --- Export ---

    def _save_log(self):
        path, _ = QFileDialog.getSaveFileName(
            self, 'Save Log', self._last_dir + '/pathsafe_log.html',
            'HTML files (*.html);;All files (*)')
        if path:
            with open(path, 'w', encoding='utf-8') as f:
                f.write(self.log_text.toHtml())
            self._last_dir = str(Path(path).parent)
            self.statusBar().showMessage(f'Log saved to {path}')

    def _auto_save_log(self, output_dir):
        """Auto-save the log to the output folder after anonymization."""
        try:
            log_path = Path(output_dir) / 'pathsafe_log.html'
            with open(log_path, 'w', encoding='utf-8') as f:
                f.write(self.log_text.toHtml())
            self.statusBar().showMessage(
                f'Log auto-saved to {log_path}')
        except OSError:
            pass  # non-critical, don't interrupt the user

    # --- Summary popup ---

    def _show_summary(self, data):
        """Show a summary popup dialog when an operation completes."""
        op = data.get('type', 'operation')

        if op == 'scan':
            total = data.get('total', 0)
            clean = data.get('clean', 0)
            phi_files = data.get('phi_files', 0)
            phi_findings = data.get('phi_findings', 0)
            errors = data.get('errors', 0)

            if phi_files == 0 and errors == 0:
                icon = QMessageBox.Information
                title = 'Scan Complete: All Clean'
                scan_report = data.get('scan_report', '')
                report_line = (f'<p>Scan report:<br><code>{Path(scan_report).name}</code></p>'
                               if scan_report else '')
                msg = (f'<h3>All {total} files are clean</h3>'
                       f'<p>No patient information (PHI) was detected.</p>'
                       f'{report_line}')
            else:
                icon = QMessageBox.Warning
                title = 'Scan Complete: PHI Detected'
                lines = [f'<h3>Scan Results</h3><table cellpadding="4">']
                lines.append(f'<tr><td>Total scanned:</td><td><b>{total}</b></td></tr>')
                if clean:
                    lines.append(f'<tr><td>Clean:</td><td style="color:#2e8b3e"><b>{clean}</b></td></tr>')
                if phi_files:
                    lines.append(f'<tr><td>PHI detected:</td>'
                                 f'<td style="color:#b45300"><b>{phi_files} files '
                                 f'({phi_findings} findings)</b></td></tr>')
                if errors:
                    lines.append(f'<tr><td>Errors:</td><td style="color:#c03030"><b>{errors}</b></td></tr>')
                lines.append('</table>')
                if phi_files:
                    lines.append('<p>Run <b>Anonymize</b> to remove detected PHI.</p>')
                scan_report = data.get('scan_report', '')
                if scan_report:
                    lines.append(
                        f'<p>Scan report:<br><code>{Path(scan_report).name}</code></p>')
                msg = ''.join(lines)

        elif op == 'anonymize':
            total = data.get('total', 0)
            anonymized = data.get('anonymized', 0)
            already_clean = data.get('already_clean', 0)
            errors = data.get('errors', 0)
            elapsed = data.get('time', '?')
            cert = data.get('certificate', '')
            dry_run = data.get('dry_run', False)

            # Store output paths so Verify can check just these files
            output_paths = data.get('output_paths', [])
            if output_paths:
                self._last_anonymized_paths = output_paths

            if dry_run:
                icon = QMessageBox.Information
                title = 'Anonymization DRY RUN Complete'
            elif errors == 0:
                icon = QMessageBox.Information
                title = 'Anonymization Complete'
            else:
                icon = QMessageBox.Warning
                title = 'Anonymization Complete (with errors)'

            lines = [f'<h3>Anonymization Results</h3><table cellpadding="4">']
            lines.append(f'<tr><td>Total files:</td><td><b>{total}</b></td></tr>')
            if anonymized:
                lines.append(f'<tr><td>Anonymized:</td><td style="color:#b45300"><b>{anonymized}</b></td></tr>')
            if already_clean:
                lines.append(f'<tr><td>Already clean:</td><td style="color:#2e8b3e"><b>{already_clean}</b></td></tr>')
            if errors:
                lines.append(f'<tr><td>Errors:</td><td style="color:#c03030"><b>{errors}</b></td></tr>')
            # Image integrity row
            integrity_verified = data.get('integrity_verified', 0)
            integrity_failed = data.get('integrity_failed', 0)
            if integrity_verified or integrity_failed:
                if integrity_failed:
                    lines.append(
                        f'<tr><td>Image integrity:</td>'
                        f'<td style="color:#c03030"><b>{integrity_failed} FAILED</b>, '
                        f'{integrity_verified} verified</td></tr>')
                else:
                    lines.append(
                        f'<tr><td>Image integrity:</td>'
                        f'<td style="color:#2e8b3e"><b>{integrity_verified} verified</b></td></tr>')
            # Filename PHI warning
            phi_filenames = data.get('phi_filenames', 0)
            if phi_filenames:
                lines.append(
                    f'<tr><td>Filename PHI:</td>'
                    f'<td style="color:#c03030"><b>{phi_filenames} file(s) '
                    f'need renaming</b></td></tr>')
            lines.append(f'<tr><td>Time:</td><td>{elapsed}</td></tr>')
            lines.append('</table>')

            if phi_filenames:
                lines.append(
                    '<p style="color:#c03030"><b>WARNING:</b> Some output files '
                    'have patient information in their filename. Rename them '
                    'manually before sharing.</p>')
            if dry_run:
                lines.append(
                    '<p><b>DRY RUN</b> - No files were modified.</p>')
            else:
                output_dir = data.get('output_dir', '')
                if output_dir:
                    lines.append(
                        f'<p>Output folder:<br><code>{output_dir}</code></p>')
                if cert:
                    pdf_cert = data.get('pdf_certificate', '')
                    lines.append(
                        f'<p>Certificate:<br><code>{Path(cert).name}</code>')
                    if pdf_cert:
                        lines.append(
                            f'<br><code>{Path(pdf_cert).name}</code>')
                    lines.append('</p>')


            msg = ''.join(lines)

        elif op == 'verify':
            total = data.get('total', 0)
            clean = data.get('clean', 0)
            dirty = data.get('dirty', 0)

            if dirty == 0:
                icon = QMessageBox.Information
                title = 'Verification Passed'
                msg = (f'<h3>All {total} files verified clean</h3>'
                       f'<p>No patient information remains in any file.</p>')
            else:
                icon = QMessageBox.Warning
                title = 'Verification Failed'
                msg = (f'<h3>Verification Results</h3>'
                       f'<table cellpadding="4">'
                       f'<tr><td>Clean:</td><td style="color:#2e8b3e"><b>{clean}</b></td></tr>'
                       f'<tr><td>PHI remaining:</td><td style="color:#c03030"><b>{dirty}</b></td></tr>'
                       f'</table>'
                       f'<p><b>WARNING:</b> Some files still contain PHI!</p>')

        elif op == 'info':
            fmt = data.get('format', 'Unknown')
            size = data.get('size', '?')
            metadata_count = data.get('metadata_count', 0)
            phi_status = data.get('phi_status', 'Unknown')

            icon = QMessageBox.Information
            title = 'File Information'
            lines = [f'<h3>File Information</h3><table cellpadding="4">']
            lines.append(f'<tr><td>Format:</td><td><b>{fmt}</b></td></tr>')
            lines.append(f'<tr><td>File size:</td><td><b>{size}</b></td></tr>')
            lines.append(f'<tr><td>Metadata entries:</td><td><b>{metadata_count}</b></td></tr>')
            lines.append(f'<tr><td>PHI status:</td><td><b>{phi_status}</b></td></tr>')
            lines.append('</table>')
            msg = ''.join(lines)

        elif op == 'convert':
            total = data.get('total', 0)
            converted = data.get('converted', 0)
            errors = data.get('errors', 0)
            elapsed = data.get('time', '?')

            if errors == 0:
                icon = QMessageBox.Information
                title = 'Conversion Complete'
            else:
                icon = QMessageBox.Warning
                title = 'Conversion Complete (with errors)'

            lines = [f'<h3>Conversion Results</h3><table cellpadding="4">']
            lines.append(f'<tr><td>Total files:</td><td><b>{total}</b></td></tr>')
            if converted:
                lines.append(f'<tr><td>Converted:</td><td style="color:#2e8b3e"><b>{converted}</b></td></tr>')
            if errors:
                lines.append(f'<tr><td>Errors:</td><td style="color:#c03030"><b>{errors}</b></td></tr>')
            lines.append(f'<tr><td>Time:</td><td>{elapsed}</td></tr>')
            lines.append('</table>')
            msg = ''.join(lines)

        else:
            return

        box = QMessageBox(self)
        box.setIcon(icon)
        box.setWindowTitle(title)
        box.setText(msg)
        box.exec()

    # --- Step state ---

    def _mark_step_completed(self, step):
        """Mark a workflow step as completed and update its button text."""
        self._step_completed.add(step)
        btn = self._step_buttons.get(step)
        if btn and step in self._step_labels:
            num, name = self._step_labels[step]
            btn.setText(f'{num} [Done]\n{name}')

    def _mark_step_default(self, step):
        """Mark a workflow step as using its default value."""
        self._step_completed.add(step)
        btn = self._step_buttons.get(step)
        if btn and step in self._step_labels:
            num, name = self._step_labels[step]
            btn.setText(f'{num} [Default]\n{name}')

    def _reset_step(self, step):
        """Reset a step button to its default text."""
        self._step_completed.discard(step)
        btn = self._step_buttons.get(step)
        if btn and step in self._step_labels:
            num, name = self._step_labels[step]
            btn.setText(f'{num}\n{name}')

    # --- Persistent settings callbacks ---

    def _on_workers_changed(self, value):
        self._workers_label.setText(str(value))
        self._settings.setValue('workers', value)

    def _on_institution_changed(self, text):
        self._institution_name = text
        self._settings.setValue('institution_name', text)

    # --- Run state ---

    def _set_running(self, running):
        # Step buttons
        self.btn_select.setEnabled(not running)
        self.btn_scan.setEnabled(not running)
        self.btn_output.setEnabled(not running)
        self.btn_anonymize.setEnabled(not running)
        self.btn_stop.setEnabled(running)
        self._scan_action.setEnabled(not running)
        self._anonymize_action.setEnabled(not running)
        self._verify_action.setEnabled(not running)
        self._info_action.setEnabled(not running)
        self._convert_action.setEnabled(not running)
        self._save_log_action.setEnabled(not running)
        self._stop_action.setEnabled(running)
        # Lock down options and paths while running
        self.input_edit.setEnabled(not running)
        self.output_edit.setEnabled(not running)
        self.drop_zone.setEnabled(not running)
        self.radio_copy.setEnabled(not running)
        self.radio_inplace.setEnabled(not running)
        self.slider_workers.setEnabled(not running)
        self.institution_edit.setEnabled(not running)
        self.combo_format_filter.setEnabled(not running)
        self.check_dry_run.setEnabled(not running)
        # Convert tab controls
        self.convert_output_edit.setEnabled(not running)
        self.combo_target_format.setEnabled(not running)
        self.combo_extract.setEnabled(not running)
        self.combo_tile_size.setEnabled(not running)
        self.slider_quality.setEnabled(not running)
        self.check_convert_anonymize.setEnabled(not running)
        self.slider_convert_workers.setEnabled(not running)
        self.combo_convert_format_filter.setEnabled(not running)
        self.btn_convert.setEnabled(not running)
        self.btn_convert_stop.setEnabled(running)
        # Disable tab switching while running
        self.tabs.tabBar().setEnabled(not running)

    def _on_finished(self):
        self._set_running(False)
        self._worker = None

    def _request_stop(self):
        if self._worker:
            self._worker.stop()
            self._log('Stopped.')

    def _validate_input(self):
        if self._selected_files:
            # Multi-file selection: files already validated at selection time
            return self._selected_files[0].parent
        path = self.input_edit.text().strip()
        if not path:
            QMessageBox.warning(
                self, 'Error', 'Please select an input file or folder.')
            return None
        p = Path(path)
        if not p.exists():
            QMessageBox.warning(
                self, 'Error', f'Input path does not exist:\n{path}')
            return None
        return p

    def _get_format_filter(self):
        """Read the format filter from the Anonymize tab combo box."""
        idx = self.combo_format_filter.currentIndex()
        if idx == 0:
            return None
        return self.combo_format_filter.currentText().lower()

    # --- Scan ---

    def _run_scan(self):
        input_p = self._validate_input()
        if not input_p:
            return
        self.log_text.clear()
        self.progress_bar.setValue(0)
        self._set_running(True)
        signals = WorkerSignals()
        signals.log.connect(self._log)
        signals.progress.connect(self._set_progress)
        signals.status.connect(self._set_status)
        signals.summary.connect(self._show_summary)

        def on_done():
            self._on_finished()
            self._mark_step_completed(2)

        signals.finished.connect(on_done)

        output_dir = self.output_edit.text().strip() or None
        file_list = self._selected_files if self._selected_files else None
        self._worker = ScanWorker(
            input_p, self.slider_workers.value(), signals,
            format_filter=self._get_format_filter(),
            institution=self._institution_name,
            output_dir=output_dir,
            file_list=file_list)
        self._worker.start()

    # --- Anonymize ---

    def _run_anonymize(self):
        input_p = self._validate_input()
        if not input_p:
            return

        dry_run = self.check_dry_run.isChecked()

        output_dir = None
        if not dry_run and self.radio_copy.isChecked():
            out = self.output_edit.text().strip()
            if not out:
                QMessageBox.warning(
                    self, 'Error',
                    'Copy mode requires an output folder.\n'
                    'Select an output folder or switch to in-place mode.')
                return
            # Create date-stamped subfolder inside the base output path
            output_dir = self._create_timestamped_output_dir(out)
        elif not dry_run and self.radio_inplace.isChecked():
            reply = QMessageBox.warning(
                self, 'Confirm: Modify Originals',
                'You are about to anonymize your original files in-place.\n\n'
                'This will permanently remove patient information from the '
                'source files. This cannot be undone.\n\n'
                'Do you want to proceed?',
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if reply != QMessageBox.Yes:
                return

        self.log_text.clear()
        self.progress_bar.setValue(0)
        self._set_running(True)
        signals = WorkerSignals()
        signals.log.connect(self._log)
        signals.progress.connect(self._set_progress)
        signals.status.connect(self._set_status)
        signals.summary.connect(self._show_summary)

        # Keep reference to output_dir for auto-saving log
        self._last_output_dir = output_dir

        def on_done():
            self._on_finished()
            self._mark_step_completed(4)
            # Auto-save log to the output folder
            if self._last_output_dir and not dry_run:
                self._auto_save_log(self._last_output_dir)

        signals.finished.connect(on_done)

        file_list = self._selected_files if self._selected_files else None
        self._worker = AnonymizeWorker(
            input_p, output_dir,
            True,
            self.slider_workers.value(),
            signals,
            reset_timestamps=True,
            format_filter=self._get_format_filter(),
            dry_run=dry_run,
            verify_integrity=True,
            institution=self._institution_name,
            file_list=file_list,
        )
        self._worker.start()

    # --- Verify ---

    def _run_verify(self):
        # If we just anonymized files, verify only those specific outputs
        file_list = None
        if self._last_anonymized_paths:
            file_list = self._last_anonymized_paths
            verify_path = Path(self._last_anonymized_paths[0]).parent
        elif self.radio_copy.isChecked():
            out = self.output_edit.text().strip()
            if out and Path(out).exists():
                verify_path = Path(out)
            else:
                verify_path = self._validate_input()
        else:
            verify_path = self._validate_input()
        if not verify_path:
            return
        self.log_text.clear()
        self.progress_bar.setValue(0)
        self._set_running(True)
        signals = WorkerSignals()
        signals.log.connect(self._log)
        signals.progress.connect(self._set_progress)
        signals.status.connect(self._set_status)
        signals.summary.connect(self._show_summary)

        def on_done():
            self._on_finished()
            self._last_anonymized_paths = []  # clear after verify

        signals.finished.connect(on_done)

        self._worker = VerifyWorker(
            verify_path, signals,
            format_filter=self._get_format_filter(),
            file_list=file_list)
        self._worker.start()

    # --- Info ---

    def _run_info(self):
        input_p = self._validate_input()
        if not input_p:
            return
        if input_p.is_dir():
            QMessageBox.warning(
                self, 'Error',
                'File Info requires a single file, not a directory.')
            return

        self.log_text.clear()
        self.progress_bar.setValue(0)
        self._set_running(True)

        signals = WorkerSignals()
        signals.log.connect(self._log)
        signals.progress.connect(self._set_progress)
        signals.status.connect(self._set_status)
        signals.summary.connect(self._show_summary)

        def on_done():
            self._on_finished()

        signals.finished.connect(on_done)

        self._worker = InfoWorker(input_p, signals)
        self._worker.start()

    # --- Convert ---

    def _run_convert(self):
        input_p = self._validate_input()
        if not input_p:
            return

        output_text = self.convert_output_edit.text().strip()
        if not output_text:
            QMessageBox.warning(
                self, 'Error',
                'Please specify an output path for conversion.')
            return
        output_p = Path(output_text)

        # For batch (directory) input, output must be a directory path
        if input_p.is_dir() and output_p.suffix:
            QMessageBox.warning(
                self, 'Error',
                'When converting a folder, the output path must be a directory,\n'
                'not a file path.')
            return

        # Create output directory if it doesn't exist
        try:
            out_dir = output_p if input_p.is_dir() else output_p.parent
            out_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            QMessageBox.warning(
                self, 'Error',
                f'Cannot create output directory:\n{e}')
            return

        # Read conversion options
        target_values = ['tiff', 'png', 'jpeg']
        target_format = target_values[self.combo_target_format.currentIndex()]

        extract_values = [None, 'label', 'macro', 'thumbnail']
        extract = extract_values[self.combo_extract.currentIndex()]

        tile_size = int(self.combo_tile_size.currentText())
        quality = self.slider_quality.value()

        anonymize_after = self.check_convert_anonymize.isChecked()
        reset_timestamps = anonymize_after
        workers = self.slider_convert_workers.value()

        fmt_idx = self.combo_convert_format_filter.currentIndex()
        format_filter = (None if fmt_idx == 0
                         else self.combo_convert_format_filter.currentText().lower())

        self.log_text.clear()
        self.progress_bar.setValue(0)
        self._set_running(True)

        signals = WorkerSignals()
        signals.log.connect(self._log)
        signals.progress.connect(self._set_progress)
        signals.status.connect(self._set_status)
        signals.summary.connect(self._show_summary)

        def on_done():
            self._on_finished()

        signals.finished.connect(on_done)

        self._worker = ConvertWorker(
            input_p, output_p, target_format, extract,
            tile_size, quality, anonymize_after, reset_timestamps,
            workers, format_filter, signals)
        self._worker.start()

    # --- Theme ---

    def _apply_theme(self, theme):
        self._current_theme = theme
        qss = DARK_QSS if theme == 'dark' else LIGHT_QSS
        QApplication.instance().setStyleSheet(qss)
        self.drop_zone.set_theme(theme)
        set_html_theme(theme)
        self._dark_action.setChecked(theme == 'dark')
        self._light_action.setChecked(theme == 'light')
        self._settings.setValue('theme', theme)

    # --- Close guard ---

    def closeEvent(self, event):
        if self._worker is not None:
            is_read_only = isinstance(self._worker, (ScanWorker, VerifyWorker, InfoWorker))
            if is_read_only:
                reply = QMessageBox.question(
                    self, 'Scan In Progress',
                    'A scan is still running. It is safe to quit now -- '
                    'scanning is read-only and will not corrupt any files.\n\n'
                    'Close the application?',
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
                if reply == QMessageBox.No:
                    event.ignore()
                    return
                self._worker.stop()
                self._worker.terminate()
                self._worker.wait(2000)
            else:
                reply = QMessageBox.question(
                    self, 'Operation In Progress',
                    'An anonymization or conversion is still running. '
                    'Closing now may leave partially written output files.\n\n'
                    'Are you sure you want to quit?',
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
                if reply == QMessageBox.No:
                    event.ignore()
                    return
                self._worker.stop()
        event.accept()

    # --- About ---

    def _show_about(self):
        QMessageBox.about(
            self, "About PathSafe",
            f"<h3>PathSafe v{pathsafe.__version__}</h3>"
            "<p>Production-tested WSI anonymizer for pathology slide files.</p>"
            "<p>Removes patient-identifying information (PHI) from "
            "NDPI, SVS, MRXS, DICOM, and other whole-slide image formats.</p>"
            "<p>Includes label/macro image blanking, post-anonymization "
            "verification, and PDF compliance certificates.</p>"
        )


def main():
    """Launch the PathSafe Qt GUI."""
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    app.setStyleSheet(DARK_QSS)
    window = PathSafeWindow()

    # Accept a file/folder path as command-line argument (e.g., "Open with")
    args = app.arguments()[1:]  # skip the program name
    if args:
        path = Path(args[0])
        if path.exists():
            window.input_edit.setText(str(path))
            window._last_dir = str(path.parent if path.is_file() else path)
            window._mark_step_completed(1)

    window.show()
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
