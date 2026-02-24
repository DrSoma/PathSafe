"""PathSafe Qt GUI — modern cross-platform interface for hospital staff.

One-click anonymize workflow: browse files, scan, anonymize, verify.
Uses PySide6 (Qt6) for native look and crisp text on all platforms.

Features:
- Light and dark theme (switchable from View menu)
- Drag-and-drop file/folder support
- Workflow step indicator
- Menu bar with keyboard shortcuts
- Tooltips on all controls
- Status bar with live stats
"""

import os
import sys
import time
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal, QObject, QSize, QSettings
from PySide6.QtGui import (
    QFont, QTextCursor, QAction, QKeySequence, QColor,
    QPainter, QPen, QBrush, QDragEnterEvent, QDropEvent,
    QActionGroup,
)
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QGroupBox, QLabel, QLineEdit, QPushButton, QRadioButton,
    QCheckBox, QSpinBox, QProgressBar, QTextEdit, QFileDialog,
    QMessageBox, QButtonGroup, QSizePolicy, QTabWidget, QFrame,
    QToolBar,
)

import pathsafe
from pathsafe.anonymizer import anonymize_batch, anonymize_file, collect_wsi_files
from pathsafe.formats import detect_format, get_handler
from pathsafe.report import generate_certificate
from pathsafe.verify import verify_batch


# --- Dark Theme Stylesheet (Catppuccin Mocha inspired) ---

DARK_QSS = """
QMainWindow, QWidget {
    background-color: #1e1e2e;
    color: #cdd6f4;
    font-size: 13px;
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
    padding: 6px 8px;
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
QPushButton#btn_stop {
    background-color: #3f1e1e;
    border-color: #f38ba8;
    color: #f38ba8;
    font-weight: bold;
}
QPushButton#btn_stop:hover {
    background-color: #5a2b2b;
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
    font-size: 13px;
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
    padding: 6px 8px;
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
QPushButton#btn_stop {
    background-color: #f5dcdc;
    border-color: #c03030;
    color: #c03030;
    font-weight: bold;
}
QPushButton#btn_stop:hover {
    background-color: #eac4c4;
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


# --- Worker Threads (unchanged) ---

class WorkerSignals(QObject):
    """Signals for background worker threads."""
    log = Signal(str)
    progress = Signal(float)
    status = Signal(str)
    finished = Signal()


class ScanWorker(QThread):
    """Background thread for scanning files."""

    def __init__(self, input_path, signals):
        super().__init__()
        self.input_path = input_path
        self.signals = signals
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        try:
            files = collect_wsi_files(self.input_path)
            total = len(files)
            if total == 0:
                self.signals.log.emit('No WSI files found.')
                return

            self.signals.log.emit(f'Scanning {total} file(s)...\n')
            clean = 0
            phi_count = 0

            for i, filepath in enumerate(files, 1):
                if self._stop:
                    self.signals.log.emit(f'\nStopped at {i-1}/{total}')
                    break

                handler = get_handler(filepath)
                result = handler.scan(filepath)

                pct = i / total * 100
                self.signals.progress.emit(pct)
                self.signals.status.emit(f'Scanning {i}/{total}: {filepath.name}')

                if result.is_clean:
                    clean += 1
                    self.signals.log.emit(
                        f'  [{i}/{total}] {filepath.name} — CLEAN')
                else:
                    phi_count += len(result.findings)
                    self.signals.log.emit(
                        f'  [{i}/{total}] {filepath.name} — '
                        f'{len(result.findings)} finding(s):')
                    for f in result.findings:
                        self.signals.log.emit(
                            f'      {f.tag_name}: {f.value_preview}')

            self.signals.log.emit(
                f'\nSummary: {total} files, {clean} clean, '
                f'{total - clean} with PHI ({phi_count} findings)')
            self.signals.status.emit('Scan complete')
        except Exception as e:
            self.signals.log.emit(f'\nERROR: {e}')
            self.signals.status.emit(f'Error: {e}')
        finally:
            self.signals.finished.emit()


class AnonymizeWorker(QThread):
    """Background thread for anonymizing files."""

    def __init__(self, input_path, output_dir, verify, workers, signals):
        super().__init__()
        self.input_path = input_path
        self.output_dir = output_dir
        self.verify = verify
        self.workers = workers
        self.signals = signals
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        try:
            files = collect_wsi_files(self.input_path)
            total = len(files)
            if total == 0:
                self.signals.log.emit('No WSI files found.')
                return

            mode_str = 'copy' if self.output_dir else 'in-place'
            workers_str = f', {self.workers} workers' if self.workers > 1 else ''
            self.signals.log.emit(
                f'PathSafe v{pathsafe.__version__} — {mode_str} '
                f'anonymization{workers_str}')
            self.signals.log.emit(f'Processing {total} file(s)...\n')

            t0 = time.time()

            def progress(i, total_files, filepath, result):
                if self._stop:
                    return
                elapsed = time.time() - t0
                rate = i / elapsed if elapsed > 0 else 0
                pct = i / total_files * 100
                self.signals.progress.emit(pct)
                self.signals.status.emit(
                    f'{i}/{total_files} ({rate:.1f}/s) — {filepath.name}')

                if result.error:
                    status = f'ERROR: {result.error}'
                elif result.findings_cleared > 0:
                    status = f'cleared {result.findings_cleared} finding(s)'
                    if result.verified:
                        status += ' [verified]'
                else:
                    status = 'already clean'

                self.signals.log.emit(
                    f'  [{i}/{total_files}] {filepath.name} | {status}')

            batch_result = anonymize_batch(
                self.input_path, output_dir=self.output_dir,
                verify=self.verify, progress_callback=progress,
                workers=self.workers,
            )

            # Generate certificate
            if self.output_dir:
                cert_path = self.output_dir / 'pathsafe_certificate.json'
            elif self.input_path.is_dir():
                cert_path = self.input_path / 'pathsafe_certificate.json'
            else:
                cert_path = self.input_path.parent / 'pathsafe_certificate.json'

            generate_certificate(batch_result, output_path=cert_path)

            self.signals.log.emit(
                f'\nDone in {batch_result.total_time_seconds:.1f}s')
            self.signals.log.emit(
                f'  Total:         {batch_result.total_files}')
            self.signals.log.emit(
                f'  Anonymized:    {batch_result.files_anonymized}')
            self.signals.log.emit(
                f'  Already clean: {batch_result.files_already_clean}')
            self.signals.log.emit(
                f'  Errors:        {batch_result.files_errored}')
            self.signals.log.emit(f'\nCertificate: {cert_path}')

            if batch_result.files_errored == 0:
                self.signals.status.emit('Anonymization complete')
            else:
                self.signals.status.emit(
                    f'Done with {batch_result.files_errored} error(s)')
        except Exception as e:
            self.signals.log.emit(f'\nERROR: {e}')
            self.signals.status.emit(f'Error: {e}')
        finally:
            self.signals.finished.emit()


class VerifyWorker(QThread):
    """Background thread for verifying files."""

    def __init__(self, input_path, signals):
        super().__init__()
        self.input_path = input_path
        self.signals = signals

    def run(self):
        try:
            files = collect_wsi_files(self.input_path)
            total = len(files)
            if total == 0:
                self.signals.log.emit('No WSI files found.')
                return

            self.signals.log.emit(f'Verifying {total} file(s)...\n')
            clean = 0
            dirty = 0

            def progress(i, total_files, filepath, result):
                pct = i / total_files * 100
                self.signals.progress.emit(pct)
                self.signals.status.emit(
                    f'Verifying {i}/{total_files}: {filepath.name}')

            results = verify_batch(
                self.input_path, progress_callback=progress)

            for result in results:
                if result.is_clean:
                    clean += 1
                else:
                    dirty += 1
                    findings_str = ', '.join(
                        f.tag_name for f in result.findings)
                    self.signals.log.emit(
                        f'  PHI FOUND: {result.filepath.name} — '
                        f'{findings_str}')

            self.signals.log.emit(
                f'\nVerification: {clean} clean, '
                f'{dirty} with remaining PHI')
            if dirty == 0:
                self.signals.log.emit('All files verified clean.')
                self.signals.status.emit(
                    'Verification passed — all files clean')
            else:
                self.signals.log.emit(
                    'WARNING: Some files still contain PHI!')
                self.signals.status.emit(
                    f'WARNING: {dirty} file(s) with remaining PHI')
        except Exception as e:
            self.signals.log.emit(f'\nERROR: {e}')
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
        self.setMinimumHeight(70)
        self.setMaximumHeight(80)

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)

        self._icon_label = QLabel("Drag files or folders here")
        self._icon_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._icon_label)

        self._hint_label = QLabel("or use the Browse buttons below")
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
            f'PathSafe v{pathsafe.__version__} — WSI Anonymizer')
        self.resize(1000, 760)
        self.setMinimumSize(800, 600)

        self._worker = None
        self._last_dir = str(Path.home())
        self._settings = QSettings('PathSafe', 'PathSafe')
        self._current_theme = self._settings.value('theme', 'dark')

        self._build_menu_bar()
        self._build_ui()
        self._setup_status_bar()
        self._apply_theme(self._current_theme)

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

        # --- Step Indicator ---
        self.step_indicator = StepIndicator()
        layout.addWidget(self.step_indicator)

        # --- Drop Zone + File Paths ---
        paths_group = QGroupBox('Input')
        paths_layout = QVBoxLayout(paths_group)

        self.drop_zone = DropZoneWidget()
        self.drop_zone.pathDropped.connect(self._on_path_dropped)
        paths_layout.addWidget(self.drop_zone)

        # Input row
        input_row = QHBoxLayout()
        self.input_edit = QLineEdit()
        self.input_edit.setPlaceholderText('Path to WSI file or folder...')
        self.input_edit.setToolTip(
            "Path to a single WSI file (.ndpi, .svs, .mrxs, .dcm, .tiff)\n"
            "or a folder containing WSI files.\n"
            "You can also drag and drop files here.")
        input_row.addWidget(self.input_edit, 1)
        btn_file = QPushButton('File')
        btn_file.setFixedWidth(70)
        btn_file.clicked.connect(self._browse_input_file)
        input_row.addWidget(btn_file)
        btn_folder = QPushButton('Folder')
        btn_folder.setFixedWidth(70)
        btn_folder.clicked.connect(self._browse_input_dir)
        input_row.addWidget(btn_folder)
        paths_layout.addLayout(input_row)

        # Output row
        output_row = QHBoxLayout()
        output_row.addWidget(QLabel('Output:'))
        self.output_edit = QLineEdit()
        self.output_edit.setPlaceholderText('Output folder for copy mode...')
        self.output_edit.setToolTip(
            "Where anonymized copies will be saved.\n"
            "Only needed in Copy mode.")
        output_row.addWidget(self.output_edit, 1)
        btn_out = QPushButton('Browse')
        btn_out.setFixedWidth(80)
        btn_out.clicked.connect(self._browse_output_dir)
        output_row.addWidget(btn_out)
        paths_layout.addLayout(output_row)

        layout.addWidget(paths_group)

        # --- Options ---
        opts_group = QGroupBox('Options')
        opts_layout = QHBoxLayout(opts_group)

        opts_layout.addWidget(QLabel('Mode:'))
        self.radio_copy = QRadioButton('Copy (safe)')
        self.radio_copy.setChecked(True)
        self.radio_copy.setToolTip(
            "Copy mode: Creates anonymized copies in the output folder.\n"
            "Your original files are never modified. (Recommended)")
        self.radio_inplace = QRadioButton('In-place')
        self.radio_inplace.setToolTip(
            "In-place mode: Modifies the original files directly.\n"
            "WARNING: Original data cannot be recovered after anonymization.")
        mode_group = QButtonGroup(self)
        mode_group.addButton(self.radio_copy)
        mode_group.addButton(self.radio_inplace)
        opts_layout.addWidget(self.radio_copy)
        opts_layout.addWidget(self.radio_inplace)

        opts_layout.addSpacing(20)
        self.check_verify = QCheckBox('Verify after')
        self.check_verify.setChecked(True)
        self.check_verify.setToolTip(
            "After anonymization, re-scan each file to confirm\n"
            "all patient information has been removed.")
        opts_layout.addWidget(self.check_verify)

        opts_layout.addSpacing(20)
        opts_layout.addWidget(QLabel('Workers:'))
        self.spin_workers = QSpinBox()
        self.spin_workers.setRange(1, 16)
        self.spin_workers.setValue(4)
        self.spin_workers.setFixedWidth(60)
        self.spin_workers.setToolTip(
            "Number of files to process simultaneously.\n"
            "Higher values are faster but use more memory.\n"
            "Recommended: 2-4 for most systems.")
        opts_layout.addWidget(self.spin_workers)

        opts_layout.addStretch()
        layout.addWidget(opts_group)

        # --- Action Buttons ---
        btn_layout = QHBoxLayout()

        self.btn_scan = QPushButton('  Scan for PHI')
        self.btn_scan.setObjectName('btn_scan')
        self.btn_scan.setMinimumHeight(38)
        self.btn_scan.setToolTip(
            "Scan files to detect patient information (PHI)\n"
            "without modifying anything. [Ctrl+S]")
        self.btn_scan.clicked.connect(self._run_scan)
        btn_layout.addWidget(self.btn_scan)

        self.btn_anonymize = QPushButton('  Anonymize')
        self.btn_anonymize.setObjectName('btn_anonymize')
        self.btn_anonymize.setMinimumHeight(38)
        self.btn_anonymize.setToolTip(
            "Remove all detected patient information from files. [Ctrl+R]")
        self.btn_anonymize.clicked.connect(self._run_anonymize)
        btn_layout.addWidget(self.btn_anonymize)

        self.btn_verify = QPushButton('  Verify')
        self.btn_verify.setObjectName('btn_verify')
        self.btn_verify.setMinimumHeight(38)
        self.btn_verify.setToolTip(
            "Re-scan files to confirm all patient information\n"
            "has been removed. [Ctrl+E]")
        self.btn_verify.clicked.connect(self._run_verify)
        btn_layout.addWidget(self.btn_verify)

        self.btn_stop = QPushButton('  Stop')
        self.btn_stop.setObjectName('btn_stop')
        self.btn_stop.setMinimumHeight(38)
        self.btn_stop.setEnabled(False)
        self.btn_stop.setToolTip(
            "Stop the current operation after the\n"
            "current file finishes. [Escape]")
        self.btn_stop.clicked.connect(self._request_stop)
        btn_layout.addWidget(self.btn_stop)

        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        # --- Progress ---
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        layout.addWidget(self.progress_bar)

        # --- Log (tabbed) ---
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setFont(QFont('monospace', 10))
        layout.addWidget(self.log_text, 1)

    def _setup_status_bar(self):
        sb = self.statusBar()
        self._status_files = QLabel("0 files")
        self._status_elapsed = QLabel("")
        sb.addPermanentWidget(self._status_files)
        sb.addPermanentWidget(self._status_elapsed)
        sb.showMessage("Ready — drag files here or use File > Open")

    # --- Browse ---

    def _browse_input_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, 'Select WSI file', self._last_dir,
            'WSI files (*.ndpi *.svs *.mrxs *.dcm *.tif *.tiff);;All files (*)')
        if path:
            self.input_edit.setText(path)
            self._last_dir = str(Path(path).parent)
            self.step_indicator.set_step(0)
            self.step_indicator.mark_completed(0)

    def _browse_input_dir(self):
        path = QFileDialog.getExistingDirectory(
            self, 'Select folder with WSI files', self._last_dir)
        if path:
            self.input_edit.setText(path)
            self._last_dir = path
            self.step_indicator.set_step(0)
            self.step_indicator.mark_completed(0)

    def _browse_output_dir(self):
        path = QFileDialog.getExistingDirectory(
            self, 'Select output folder', self._last_dir)
        if path:
            self.output_edit.setText(path)
            self._last_dir = path

    def _on_path_dropped(self, path):
        p = Path(path)
        if p.exists():
            self.input_edit.setText(path)
            self._last_dir = str(p.parent if p.is_file() else p)
            self.step_indicator.set_step(0)
            self.step_indicator.mark_completed(0)

    # --- Logging ---

    def _log(self, msg):
        self.log_text.append(msg)
        self.log_text.moveCursor(QTextCursor.End)

    def _set_progress(self, pct):
        self.progress_bar.setValue(int(pct))

    def _set_status(self, msg):
        self.statusBar().showMessage(msg)

    # --- Run state ---

    def _set_running(self, running):
        self.btn_scan.setEnabled(not running)
        self.btn_anonymize.setEnabled(not running)
        self.btn_verify.setEnabled(not running)
        self.btn_stop.setEnabled(running)
        self._scan_action.setEnabled(not running)
        self._anonymize_action.setEnabled(not running)
        self._verify_action.setEnabled(not running)
        self._stop_action.setEnabled(running)

    def _on_finished(self):
        self._set_running(False)
        self._worker = None

    def _request_stop(self):
        if self._worker:
            self._worker.stop()
            self._log('Stop requested... finishing current file.')

    def _validate_input(self):
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

    # --- Scan ---

    def _run_scan(self):
        input_p = self._validate_input()
        if not input_p:
            return
        self.log_text.clear()
        self.progress_bar.setValue(0)
        self._set_running(True)
        self.step_indicator.set_step(1)

        signals = WorkerSignals()
        signals.log.connect(self._log)
        signals.progress.connect(self._set_progress)
        signals.status.connect(self._set_status)

        def on_done():
            self._on_finished()
            self.step_indicator.mark_completed(1)

        signals.finished.connect(on_done)

        self._worker = ScanWorker(input_p, signals)
        self._worker.start()

    # --- Anonymize ---

    def _run_anonymize(self):
        input_p = self._validate_input()
        if not input_p:
            return

        output_dir = None
        if self.radio_copy.isChecked():
            out = self.output_edit.text().strip()
            if not out:
                QMessageBox.warning(
                    self, 'Error',
                    'Copy mode requires an output folder.\n'
                    'Select an output folder or switch to in-place mode.')
                return
            output_dir = Path(out)
        else:
            reply = QMessageBox.question(
                self, 'Confirm In-Place',
                'In-place mode will modify your original files!\n\n'
                'Are you sure you want to continue?',
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if reply != QMessageBox.Yes:
                return

        self.log_text.clear()
        self.progress_bar.setValue(0)
        self._set_running(True)
        self.step_indicator.set_step(2)

        signals = WorkerSignals()
        signals.log.connect(self._log)
        signals.progress.connect(self._set_progress)
        signals.status.connect(self._set_status)

        def on_done():
            self._on_finished()
            self.step_indicator.mark_completed(2)

        signals.finished.connect(on_done)

        self._worker = AnonymizeWorker(
            input_p, output_dir,
            self.check_verify.isChecked(),
            self.spin_workers.value(),
            signals,
        )
        self._worker.start()

    # --- Verify ---

    def _run_verify(self):
        input_p = self._validate_input()
        if not input_p:
            return
        self.log_text.clear()
        self.progress_bar.setValue(0)
        self._set_running(True)
        self.step_indicator.set_step(3)

        signals = WorkerSignals()
        signals.log.connect(self._log)
        signals.progress.connect(self._set_progress)
        signals.status.connect(self._set_status)

        def on_done():
            self._on_finished()
            self.step_indicator.mark_completed(3)

        signals.finished.connect(on_done)

        self._worker = VerifyWorker(input_p, signals)
        self._worker.start()

    # --- Theme ---

    def _apply_theme(self, theme):
        self._current_theme = theme
        qss = DARK_QSS if theme == 'dark' else LIGHT_QSS
        QApplication.instance().setStyleSheet(qss)
        self.step_indicator.set_theme(theme)
        self.drop_zone.set_theme(theme)
        self._dark_action.setChecked(theme == 'dark')
        self._light_action.setChecked(theme == 'light')
        self._settings.setValue('theme', theme)

    # --- About ---

    def _show_about(self):
        QMessageBox.about(
            self, "About PathSafe",
            f"<h3>PathSafe v{pathsafe.__version__}</h3>"
            "<p>Hospital-grade WSI anonymizer for pathology slide files.</p>"
            "<p>Removes patient-identifying information (PHI) from "
            "NDPI, SVS, MRXS, DICOM, and other whole-slide image formats.</p>"
            "<p>Includes label/macro image blanking, post-anonymization "
            "verification, and JSON compliance certificates.</p>"
        )


def main():
    """Launch the PathSafe Qt GUI."""
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    app.setStyleSheet(DARK_QSS)
    window = PathSafeWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
