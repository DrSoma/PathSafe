"""Pipeline tab for the PathSafe GUI -- single-action slide workflow.

This tab provides a streamlined "just do it" interface that chains
classify -> deidentify -> transfer in one click.  It only appears when
the pipeline module is available (i.e. the pipeline extras are installed).
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QThread
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from pathsafe.gui.workers import WorkerSignals
from pathsafe.log import (
    html_error,
    html_header,
    html_info,
    html_separator,
    html_success,
    html_summary_line,
    html_warning,
)
from pathsafe.pipeline import PipelineConfig, run_pipeline


class PipelineWorker(QThread):
    """Background thread for the full pipeline."""

    def __init__(
        self,
        config: PipelineConfig,
        signals: WorkerSignals,
    ) -> None:
        super().__init__()
        self.config = config
        self.signals = signals
        self._stop = False

    def stop(self) -> None:
        self._stop = True

    def run(self) -> None:
        try:
            self.signals.log.emit(html_header("PathSafe Pipeline"))
            self.signals.log.emit(html_info(f"Input: {self.config.input_path}"))
            self.signals.log.emit(html_info(f"Output: {self.config.output_dir}"))
            if self.config.do_classify:
                filt = self.config.stain_filter or "all"
                self.signals.log.emit(html_info(f"Classify stains: yes (filter: {filt})"))
            if self.config.do_transfer and self.config.remote:
                self.signals.log.emit(html_info(f"Transfer to: {self.config.remote}"))
            self.signals.log.emit(html_separator())

            total_files = [0]
            last_stage = [""]

            def progress(stage, i, total, filepath, message):
                total_files[0] = max(total_files[0], total)
                if stage != last_stage[0]:
                    last_stage[0] = stage
                    self.signals.log.emit(html_info(f"Stage: {stage}"))
                if total > 0:
                    pct = i / total * 100
                    self.signals.progress.emit(min(pct, 99))
                if filepath:
                    fname = Path(filepath).name if not isinstance(filepath, str) else filepath
                    if fname:
                        self.signals.status.emit(f"{stage}: {fname} ({i}/{total})")

            manifest = run_pipeline(
                self.config,
                progress_callback=progress,
            )

            self.signals.progress.emit(100)

            # Summary
            self.signals.log.emit(html_separator())
            self.signals.log.emit(html_header("Pipeline Complete"))

            total = len(manifest.entries)
            anon = sum(1 for e in manifest.entries.values() if e.status == "deidentified")
            transferred = sum(1 for e in manifest.entries.values() if e.status == "transferred")
            errors = sum(1 for e in manifest.entries.values() if e.status == "error")
            filtered_out = sum(1 for e in manifest.entries.values() if e.status == "filtered")

            self.signals.log.emit(html_summary_line("Total files:", total, "white"))
            if anon:
                self.signals.log.emit(html_summary_line("Deidentified:", anon, "green"))
            if transferred:
                self.signals.log.emit(html_summary_line("Transferred:", transferred, "green"))
            if filtered_out:
                self.signals.log.emit(html_summary_line("Filtered out:", filtered_out, "orange"))
            if errors:
                self.signals.log.emit(html_summary_line("Errors:", errors, "red"))

            if errors == 0:
                self.signals.log.emit(html_success("Pipeline completed successfully."))
                self.signals.status.emit("Pipeline complete")
            else:
                self.signals.log.emit(html_warning(f"Pipeline finished with {errors} error(s)."))
                self.signals.status.emit(f"Pipeline done with {errors} error(s)")

        except ImportError as e:
            self.signals.log.emit(html_error(f"Missing dependency: {e}"))
            self.signals.status.emit(f"Error: {e}")
        except Exception as e:
            self.signals.log.emit(html_error(f"ERROR: {e}"))
            self.signals.status.emit(f"Error: {e}")
        finally:
            self.signals.finished.emit()


class PipelineTab(QWidget):
    """Streamlined pipeline tab -- classify, deidentify, transfer in one click."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self._window = parent  # PathSafeWindow reference
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        # --- Output row ---
        output_row = QHBoxLayout()
        output_row.addWidget(QLabel("Output:"))
        self.output_edit = QLineEdit()
        self.output_edit.setPlaceholderText("Output folder for pipeline results...")
        self.output_edit.setToolTip(
            "Where deidentified files will be saved.\n"
            "A date-stamped subfolder is created automatically."
        )
        output_row.addWidget(self.output_edit, 1)
        btn_browse = QPushButton("Browse")
        btn_browse.setFixedWidth(80)
        btn_browse.clicked.connect(self._browse_output)
        output_row.addWidget(btn_browse)
        layout.addLayout(output_row)

        # --- Pipeline Options ---
        opts_group = QGroupBox("Pipeline Options")
        opts_layout = QVBoxLayout(opts_group)
        opts_layout.setSpacing(8)
        opts_layout.setContentsMargins(12, 14, 12, 10)

        # Row 1: Classify + stain filter
        row1 = QHBoxLayout()
        self.check_classify = QCheckBox("Classify stains")
        self.check_classify.setToolTip(
            "Run stain classification on each slide before deidentifying.\n"
            "Requires the pathsafe-classify extra.\n"
            "Use the filter dropdown to keep only specific stain types."
        )
        self.check_classify.toggled.connect(self._on_classify_toggled)
        row1.addWidget(self.check_classify)
        row1.addSpacing(12)
        row1.addWidget(QLabel("Stain filter:"))
        self.combo_stain = QComboBox()
        self.combo_stain.addItems(["All", "H&E only", "IHC only"])
        self.combo_stain.setFixedWidth(120)
        self.combo_stain.setEnabled(False)
        self.combo_stain.setToolTip(
            "Filter slides by stain type after classification.\n"
            "  All      -- keep every slide\n"
            "  H&E only -- keep only H&E-stained slides\n"
            "  IHC only -- keep only immunohistochemistry slides"
        )
        row1.addWidget(self.combo_stain)
        row1.addStretch()
        opts_layout.addLayout(row1)

        # Row 2: Transfer + remote
        row2 = QHBoxLayout()
        self.check_transfer = QCheckBox("Transfer to remote")
        self.check_transfer.setToolTip(
            "Transfer deidentified files to a remote destination\n"
            "after processing. Requires the pathsafe-transfer extra.\n"
            "Supports SFTP and S3 destinations."
        )
        self.check_transfer.toggled.connect(self._on_transfer_toggled)
        row2.addWidget(self.check_transfer)
        row2.addSpacing(12)
        row2.addWidget(QLabel("Destination:"))
        self.remote_edit = QLineEdit()
        self.remote_edit.setPlaceholderText("e.g. sftp://host/path or s3://bucket/prefix")
        self.remote_edit.setEnabled(False)
        self.remote_edit.setToolTip(
            "Remote destination for file transfer.\n\n"
            "Examples:\n"
            "  sftp://server.hospital.org/slides/\n"
            "  s3://my-bucket/deidentified/"
        )
        row2.addWidget(self.remote_edit, 1)
        opts_layout.addLayout(row2)

        layout.addWidget(opts_group)

        # --- Action button ---
        btn_layout = QHBoxLayout()
        self.btn_run = QPushButton("  Run Pipeline")
        self.btn_run.setObjectName("btn_deidentify")
        self.btn_run.setMinimumHeight(38)
        self.btn_run.setToolTip(
            "Run the full pipeline: collect files, classify (optional),\n"
            "deidentify, and transfer (optional) in one step."
        )
        self.btn_run.clicked.connect(self._run_pipeline)
        btn_layout.addWidget(self.btn_run)

        self.btn_stop = QPushButton("  Stop")
        self.btn_stop.setObjectName("btn_stop")
        self.btn_stop.setMinimumHeight(38)
        self.btn_stop.setEnabled(False)
        self.btn_stop.setToolTip("Stop the pipeline after the current file finishes.")
        self.btn_stop.clicked.connect(self._request_stop)
        btn_layout.addWidget(self.btn_stop)

        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        layout.addStretch()

    # --- Signal handlers ---

    def _on_classify_toggled(self, checked: bool) -> None:
        self.combo_stain.setEnabled(checked)
        if not checked:
            self.combo_stain.setCurrentIndex(0)

    def _on_transfer_toggled(self, checked: bool) -> None:
        self.remote_edit.setEnabled(checked)
        if not checked:
            self.remote_edit.clear()

    def _browse_output(self) -> None:
        start = self.output_edit.text().strip() or self._window._last_dir
        path = QFileDialog.getExistingDirectory(self, "Select pipeline output folder", start)
        if path:
            self.output_edit.setText(path)
            self._window._last_dir = path

    # --- Run pipeline ---

    def _run_pipeline(self) -> None:
        # Validate input from the parent window
        input_text = self._window.input_edit.text().strip()
        if not input_text:
            QMessageBox.warning(
                self,
                "No Input",
                "Select input files or a folder first\n"
                "using Step 1 or drag-and-drop in the main window.",
            )
            return

        # Resolve input path (multi-file uses parent dir)
        if self._window._selected_files:
            input_path = self._window._selected_files[0].parent
        else:
            input_path = Path(input_text)
        if not input_path.exists():
            QMessageBox.warning(
                self, "Input Not Found", f"Input path does not exist:\n{input_path}"
            )
            return

        # Validate output
        output_text = self.output_edit.text().strip()
        if not output_text:
            QMessageBox.warning(self, "No Output", "Select an output folder for the pipeline.")
            return
        output_dir = Path(output_text)
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            QMessageBox.warning(self, "Output Error", f"Cannot create output directory:\n{e}")
            return

        # Stain filter mapping
        stain_map = {0: None, 1: "he", 2: "ihc"}
        stain_filter = stain_map.get(self.combo_stain.currentIndex())

        # Build config
        config = PipelineConfig(
            input_path=input_path,
            output_dir=output_dir,
            do_classify=self.check_classify.isChecked(),
            stain_filter=stain_filter,
            do_transfer=self.check_transfer.isChecked(),
            remote=self.remote_edit.text().strip() or None,
        )

        # Validate transfer destination
        if config.do_transfer and not config.remote:
            QMessageBox.warning(
                self,
                "No Destination",
                'Enable "Transfer to remote" but no destination specified.\n'
                "Enter a remote path (e.g. sftp://host/path).",
            )
            return

        # Clear log and set running state
        self._window.log_text.clear()
        self._window.progress_bar.setValue(0)
        self._window._set_running(True)
        self.btn_run.setEnabled(False)
        self.btn_stop.setEnabled(True)

        signals = WorkerSignals()
        signals.log.connect(self._window._log)
        signals.progress.connect(self._window._set_progress)
        signals.status.connect(self._window._set_status)

        def on_done():
            self._window._on_finished()
            self.btn_run.setEnabled(True)
            self.btn_stop.setEnabled(False)

        signals.finished.connect(on_done)

        self._worker = PipelineWorker(config, signals)
        self._window._worker = self._worker
        self._worker.start()

    def _request_stop(self) -> None:
        if hasattr(self, "_worker") and self._worker:
            self._worker.stop()
            self._window._log(
                '<span style="color:#f38ba8;">Pipeline stop requested '
                "-- finishing current file...</span>"
            )
