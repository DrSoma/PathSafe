"""PathSafe Qt GUI — modern cross-platform interface for hospital staff.

One-click anonymize workflow: browse files, scan, anonymize, verify.
Uses PySide6 (Qt6) for native look and crisp text on all platforms.
"""

import os
import sys
import time
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal, QObject
from PySide6.QtGui import QFont, QTextCursor
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QGroupBox, QLabel, QLineEdit, QPushButton, QRadioButton,
    QCheckBox, QSpinBox, QProgressBar, QTextEdit, QFileDialog,
    QMessageBox, QButtonGroup, QSizePolicy,
)

import pathsafe
from pathsafe.anonymizer import anonymize_batch, anonymize_file, collect_wsi_files
from pathsafe.formats import detect_format, get_handler
from pathsafe.report import generate_certificate
from pathsafe.verify import verify_batch


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


class PathSafeWindow(QMainWindow):
    """Main application window."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle(
            f'PathSafe v{pathsafe.__version__} — WSI Anonymizer')
        self.resize(950, 720)
        self.setMinimumSize(750, 550)

        self._worker = None
        self._last_dir = str(Path.home())

        self._build_ui()

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # --- File Paths ---
        paths_group = QGroupBox('File Paths')
        paths_layout = QVBoxLayout(paths_group)

        # Input row
        input_row = QHBoxLayout()
        input_row.addWidget(QLabel('Input (file or folder):'))
        self.input_edit = QLineEdit()
        self.input_edit.setPlaceholderText('Select a WSI file or folder...')
        input_row.addWidget(self.input_edit, 1)
        btn_file = QPushButton('File')
        btn_file.setFixedWidth(60)
        btn_file.clicked.connect(self._browse_input_file)
        input_row.addWidget(btn_file)
        btn_folder = QPushButton('Folder')
        btn_folder.setFixedWidth(60)
        btn_folder.clicked.connect(self._browse_input_dir)
        input_row.addWidget(btn_folder)
        paths_layout.addLayout(input_row)

        # Output row
        output_row = QHBoxLayout()
        output_row.addWidget(QLabel('Output folder:'))
        self.output_edit = QLineEdit()
        self.output_edit.setPlaceholderText(
            'Select output folder for copy mode...')
        output_row.addWidget(self.output_edit, 1)
        btn_out = QPushButton('Browse')
        btn_out.setFixedWidth(70)
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
        self.radio_inplace = QRadioButton('In-place')
        mode_group = QButtonGroup(self)
        mode_group.addButton(self.radio_copy)
        mode_group.addButton(self.radio_inplace)
        opts_layout.addWidget(self.radio_copy)
        opts_layout.addWidget(self.radio_inplace)

        opts_layout.addSpacing(20)
        self.check_verify = QCheckBox('Verify after')
        self.check_verify.setChecked(True)
        opts_layout.addWidget(self.check_verify)

        opts_layout.addSpacing(20)
        opts_layout.addWidget(QLabel('Workers:'))
        self.spin_workers = QSpinBox()
        self.spin_workers.setRange(1, 16)
        self.spin_workers.setValue(4)
        self.spin_workers.setFixedWidth(60)
        opts_layout.addWidget(self.spin_workers)

        opts_layout.addStretch()
        layout.addWidget(opts_group)

        # --- Action Buttons ---
        btn_layout = QHBoxLayout()
        self.btn_scan = QPushButton('Scan for PHI')
        self.btn_scan.clicked.connect(self._run_scan)
        btn_layout.addWidget(self.btn_scan)

        self.btn_anonymize = QPushButton('Anonymize')
        self.btn_anonymize.clicked.connect(self._run_anonymize)
        btn_layout.addWidget(self.btn_anonymize)

        self.btn_verify = QPushButton('Verify')
        self.btn_verify.clicked.connect(self._run_verify)
        btn_layout.addWidget(self.btn_verify)

        self.btn_stop = QPushButton('Stop')
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self._request_stop)
        btn_layout.addWidget(self.btn_stop)

        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        # --- Progress ---
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)

        self.status_label = QLabel('Ready')
        layout.addWidget(self.status_label)

        # --- Log ---
        log_group = QGroupBox('Log')
        log_layout = QVBoxLayout(log_group)
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setFont(QFont('monospace', 10))
        log_layout.addWidget(self.log_text)
        log_group.setSizePolicy(
            QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout.addWidget(log_group, 1)

    # --- Browse ---

    def _browse_input_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, 'Select WSI file', self._last_dir,
            'WSI files (*.ndpi *.svs *.tif *.tiff);;All files (*)')
        if path:
            self.input_edit.setText(path)
            self._last_dir = str(Path(path).parent)

    def _browse_input_dir(self):
        path = QFileDialog.getExistingDirectory(
            self, 'Select folder with WSI files', self._last_dir)
        if path:
            self.input_edit.setText(path)
            self._last_dir = path

    def _browse_output_dir(self):
        path = QFileDialog.getExistingDirectory(
            self, 'Select output folder', self._last_dir)
        if path:
            self.output_edit.setText(path)
            self._last_dir = path

    # --- Logging ---

    def _log(self, msg):
        self.log_text.append(msg)
        self.log_text.moveCursor(QTextCursor.End)

    def _set_progress(self, pct):
        self.progress_bar.setValue(int(pct))

    def _set_status(self, msg):
        self.status_label.setText(msg)

    # --- Run state ---

    def _set_running(self, running):
        self.btn_scan.setEnabled(not running)
        self.btn_anonymize.setEnabled(not running)
        self.btn_verify.setEnabled(not running)
        self.btn_stop.setEnabled(running)

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

        signals = WorkerSignals()
        signals.log.connect(self._log)
        signals.progress.connect(self._set_progress)
        signals.status.connect(self._set_status)
        signals.finished.connect(self._on_finished)

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

        signals = WorkerSignals()
        signals.log.connect(self._log)
        signals.progress.connect(self._set_progress)
        signals.status.connect(self._set_status)
        signals.finished.connect(self._on_finished)

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

        signals = WorkerSignals()
        signals.log.connect(self._log)
        signals.progress.connect(self._set_progress)
        signals.status.connect(self._set_status)
        signals.finished.connect(self._on_finished)

        self._worker = VerifyWorker(input_p, signals)
        self._worker.start()


def main():
    """Launch the PathSafe Qt GUI."""
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    window = PathSafeWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
