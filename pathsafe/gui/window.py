"""PathSafe main application window.

Construction is split across mixins (menus, dialogs, panels) so this file
stays focused on window state, run dispatch, and event handling.
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QSettings, QStandardPaths, Qt, QTimer
from PySide6.QtGui import QFont, QIcon, QTextCursor
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

import pathsafe
from pathsafe.deidentifier import WSI_EXTENSIONS
from pathsafe.gui.dialogs import DialogsMixin
from pathsafe.gui.menus import MenuBuilderMixin
from pathsafe.gui.panels.convert_panel import ConvertPanelMixin
from pathsafe.gui.panels.deidentify_panel import DeidentifyPanelMixin
from pathsafe.gui.themes import DARK_QSS, LIGHT_QSS
from pathsafe.gui.widgets import DropZoneWidget
from pathsafe.gui.workers import (
    ConvertWorker,
    DeidentifyWorker,
    InfoWorker,
    ScanWorker,
    VerifyWorker,
    WorkerSignals,
)
from pathsafe.log import set_html_theme


class PathSafeWindow(
    MenuBuilderMixin,
    DialogsMixin,
    DeidentifyPanelMixin,
    ConvertPanelMixin,
    QMainWindow,
):
    """Main application window."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"PathSafe v{pathsafe.__version__} - WSI Deidentifier")
        # Set application icon (works both from source and PyInstaller bundle)
        base = Path(getattr(sys, "_MEIPASS", Path(__file__).parent.parent))
        icon_path = base / "pathsafe" / "assets" / "icon.png"
        if not icon_path.exists():
            icon_path = Path(__file__).parent.parent / "assets" / "icon.png"
        if icon_path.exists():
            app_icon = QIcon(str(icon_path))
            self.setWindowIcon(app_icon)
            QApplication.instance().setWindowIcon(app_icon)
        self.resize(1150, 900)
        self.setMinimumSize(1100, 820)

        self._worker = None
        self._last_dir = str(Path.home())
        self._last_deidentified_paths = []  # output paths from last deidentify run
        self._last_output_dir = None  # actual output dir (date-stamped subfolder)
        self._selected_files = []  # multi-file selection list
        self._settings = QSettings("PathSafe", "PathSafe")
        self._current_theme = self._settings.value("theme", "dark")
        self._institution_name = self._settings.value("institution_name", "")
        from pathsafe.deidentifier import auto_workers

        self._auto_workers = auto_workers()
        self._step_completed = set()  # track completed steps {1, 2, 3}
        self._step_labels = {
            1: ("Step 1", "Select Files"),
            2: ("Step 2", "Scan for PHI"),
            3: ("Step 3", "Select File Output"),
            4: ("Step 4", "Deidentify"),
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

        # Check for updates on startup (if enabled)
        self._update_thread = None
        if self._settings.value("check_updates", "true") == "true":
            QTimer.singleShot(500, self._check_for_updates)

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(14, 8, 14, 8)
        layout.setSpacing(8)

        # === Top section: step panel (left) + controls (right) ===
        top_split = QHBoxLayout()
        top_split.setSpacing(10)

        # --- Left: Workflow step buttons ---
        step_group = QGroupBox("Workflow")
        step_layout = QVBoxLayout(step_group)
        step_layout.setSpacing(6)

        self.btn_select = QPushButton("Step 1\nSelect Files")
        self.btn_select.setObjectName("btn_info")
        self.btn_select.setToolTip("Browse for WSI files or a folder to process.")
        self.btn_select.clicked.connect(self._browse_input_file_or_folder)
        step_layout.addWidget(self.btn_select)

        self.btn_scan = QPushButton("Step 2\nScan for PHI")
        self.btn_scan.setObjectName("btn_scan")
        self.btn_scan.setToolTip(
            "Scan files to detect patient information (PHI)\nwithout modifying anything. [Ctrl+S]"
        )
        self.btn_scan.clicked.connect(self._run_scan)
        step_layout.addWidget(self.btn_scan)

        self.btn_output = QPushButton("Step 3\nSelect File Output")
        self.btn_output.setObjectName("btn_convert")
        self.btn_output.setToolTip(
            "Choose the output folder where deidentified\ncopies will be saved."
        )
        self.btn_output.clicked.connect(self._browse_output_dir_step)
        step_layout.addWidget(self.btn_output)

        self.btn_deidentify = QPushButton("Step 4\nDeidentify")
        self.btn_deidentify.setObjectName("btn_deidentify")
        self.btn_deidentify.setToolTip(
            "Remove all detected patient information from files.\n"
            "Enable 'Verify after deidentify' to confirm removal. [Ctrl+R]"
        )
        self.btn_deidentify.clicked.connect(self._run_deidentify)
        step_layout.addWidget(self.btn_deidentify)

        self.btn_stop = QPushButton("Stop")
        self.btn_stop.setObjectName("btn_stop")
        self.btn_stop.setEnabled(False)
        self.btn_stop.setToolTip(
            "Stop the current operation after the\ncurrent file finishes. [Escape]"
        )
        self.btn_stop.clicked.connect(self._request_stop)
        step_layout.addWidget(self.btn_stop)

        # Step buttons: fixed height so they don't stretch the top section
        for btn in (self.btn_select, self.btn_scan, self.btn_output, self.btn_deidentify):
            btn.setFixedHeight(70)
        self.btn_stop.setFixedHeight(50)

        step_group.setFixedWidth(170)
        self._step_buttons = {
            1: self.btn_select,
            2: self.btn_scan,
            3: self.btn_output,
            4: self.btn_deidentify,
        }
        top_split.addWidget(step_group)

        # --- Right: Input + options ---
        controls_layout = QVBoxLayout()
        controls_layout.setSpacing(10)

        # Input Group (drop zone + path row)
        paths_group = QGroupBox("Input")
        paths_layout = QVBoxLayout(paths_group)

        self.drop_zone = DropZoneWidget()
        self.drop_zone.pathDropped.connect(self._on_path_dropped)
        self.drop_zone.pathsDropped.connect(self._on_paths_dropped)
        paths_layout.addWidget(self.drop_zone)

        input_row = QHBoxLayout()
        self.input_edit = QLineEdit()
        self.input_edit.setPlaceholderText("Path to WSI file or folder...")
        self.input_edit.setToolTip(
            "Path to a single WSI file (.ndpi, .svs, .mrxs, .dcm, .tiff)\n"
            "or a folder containing WSI files.\n"
            "You can also drag and drop files here."
        )
        input_row.addWidget(self.input_edit, 1)
        paths_layout.addLayout(input_row)

        controls_layout.addWidget(paths_group)

        # Tab Widget (Deidentify / Convert)
        self.tabs = QTabWidget()
        controls_layout.addWidget(self.tabs)

        self._build_deidentify_tab()
        self._build_convert_tab()

        try:
            from pathsafe.gui.pipeline_tab import PipelineTab

            self.tabs.addTab(PipelineTab(self), "Pipeline")
        except ImportError:
            pass  # Pipeline extras not installed

        top_split.addLayout(controls_layout, 1)

        # Wrap top section with max height so log gets priority
        top_widget = QWidget()
        top_widget.setLayout(top_split)
        top_widget.setMaximumHeight(560)
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
        for family in (
            "JetBrains Mono",
            "Cascadia Code",
            "Fira Code",
            "Source Code Pro",
            "Consolas",
            "Ubuntu Mono",
            "DejaVu Sans Mono",
            "monospace",
        ):
            log_font.setFamily(family)
            if log_font.exactMatch():
                break
        log_font.setPointSize(11)
        log_font.setStyleHint(QFont.Monospace)
        self.log_text.setFont(log_font)
        self.log_text.setStyleSheet(
            self.log_text.styleSheet() + "QTextEdit { line-height: 140%; padding: 6px; }"
        )
        layout.addWidget(self.log_text, 1)

        # === Export buttons ===
        export_row = QHBoxLayout()
        self.btn_save_log = QPushButton("Save Log")
        self.btn_save_log.setToolTip("Save the log output as an HTML file.")
        self.btn_save_log.clicked.connect(self._save_log)
        export_row.addWidget(self.btn_save_log)

        export_row.addStretch()
        layout.addLayout(export_row)

    def _setup_status_bar(self) -> None:
        sb = self.statusBar()
        self._status_files = QLabel("0 files")
        self._status_elapsed = QLabel("")
        sb.addPermanentWidget(self._status_files)
        sb.addPermanentWidget(self._status_elapsed)
        sb.showMessage("Ready - drag files here or use File > Open")

    # --- Default output ---

    def _get_default_output_dir(self) -> Path:
        """Return the default output directory: ~/Documents/PathSafe Output/"""
        docs = QStandardPaths.writableLocation(QStandardPaths.DocumentsLocation)
        if not docs:
            docs = str(Path.home())
        return Path(docs) / "PathSafe Output"

    def _create_timestamped_output_dir(self, base_dir: str | Path) -> Path:
        """Create a date-stamped subfolder inside base_dir and return its path."""
        stamp = datetime.now().strftime("%Y-%m-%d_%H-%M")
        output_dir = Path(base_dir) / stamp
        output_dir.mkdir(parents=True, exist_ok=True)
        return output_dir

    # --- Browse ---

    def _browse_input_file_or_folder(self) -> None:
        """Step 1 button: let user choose between file or folder."""
        dlg = QMessageBox(self)
        dlg.setWindowTitle("Select Input")
        dlg.setText("What would you like to open?")
        dlg.setIcon(QMessageBox.Question)
        btn_file = dlg.addButton("Files", QMessageBox.AcceptRole)
        btn_folder = dlg.addButton("Folder", QMessageBox.AcceptRole)
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

    def _browse_input_file(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Select WSI file(s)",
            self._last_dir,
            "WSI files (*.ndpi *.svs *.mrxs *.bif *.scn *.dcm *.dicom *.tif *.tiff);;All files (*)",
        )
        if not paths:
            return
        # Validate extensions
        for path in paths:
            ext = Path(path).suffix.lower()
            if ext not in WSI_EXTENSIONS:
                supported = ", ".join(sorted(WSI_EXTENSIONS))
                QMessageBox.warning(
                    self,
                    "Unsupported File Type",
                    f"<p>The selected file (<b>{Path(path).name}</b>) is not a "
                    f"supported whole-slide image format.</p>"
                    f"<p>Supported extensions: <code>{supported}</code></p>",
                )
                return
        self._selected_files = [Path(p) for p in paths]
        if len(paths) == 1:
            self.input_edit.setText(paths[0])
        else:
            self.input_edit.setText(f"{paths[0]} (+ {len(paths) - 1} more)")
        self._last_dir = str(Path(paths[0]).parent)
        self._mark_step_completed(1)

    def _browse_input_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self, "Select folder with WSI files", self._last_dir
        )
        if path:
            self._selected_files = []
            self.input_edit.setText(path)
            self._last_dir = path
            self._mark_step_completed(1)

    def _browse_output_dir(self) -> None:
        # Start from current output path if set, otherwise last dir
        start_dir = self.output_edit.text().strip() or self._last_dir
        path = QFileDialog.getExistingDirectory(self, "Select output folder", start_dir)
        if path:
            self.output_edit.setText(path)
            self._last_dir = path
            self._mark_step_completed(3)

    def _browse_output_dir_step(self) -> None:
        self._browse_output_dir()

    def _browse_convert_output(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self, "Select conversion output folder", self._last_dir
        )
        if path:
            self.convert_output_edit.setText(path)
            self._last_dir = path

    def _on_inplace_toggled(self, checked: bool) -> None:
        """Warn the user when they select in-place mode."""
        if not checked:
            return
        dlg = QMessageBox(self)
        dlg.setWindowTitle("Warning: Modify Originals")
        dlg.setIcon(QMessageBox.Warning)
        dlg.setText(
            "<h3>You have selected in-place mode</h3>"
            "<p>This will <b>permanently modify your original files</b>. "
            "Patient information will be removed directly from the source files.</p>"
            "<p><b>This cannot be undone.</b> If you do not have backups of your "
            "original files, the unmodified data will be lost forever.</p>"
            '<p>For safety, we recommend using <b>"Copy and deidentify"</b> instead, '
            "which creates clean copies and leaves your originals untouched.</p>"
        )
        btn_continue = dlg.addButton("I understand, use in-place", QMessageBox.AcceptRole)
        btn_cancel = dlg.addButton("Switch back to Copy mode", QMessageBox.RejectRole)
        dlg.setDefaultButton(btn_cancel)
        dlg.exec()
        if dlg.clickedButton() != btn_continue:
            self.radio_copy.setChecked(True)
            return
        # Disable rename when in-place mode is active
        self.rename_group.setChecked(False)
        self.rename_group.setEnabled(False)
        self.rename_group.setToolTip(
            "File renaming is only available in Copy mode.\n"
            "Switch to 'Copy and deidentify' above to enable this."
        )

    def _on_copy_mode_restored(self):
        """Re-enable rename group when switching back to copy mode."""
        self.rename_group.setEnabled(True)
        self.rename_group.setToolTip(
            "Rename deidentified files to remove PHI from filenames.\nOnly available in Copy mode."
        )

    def _on_path_dropped(self, path: str) -> None:
        p = Path(path)
        if p.exists():
            self._selected_files = []
            self.input_edit.setText(path)
            self._last_dir = str(p.parent if p.is_file() else p)
            self._mark_step_completed(1)

    def _on_paths_dropped(self, paths: list) -> None:
        """Handle multiple files dropped at once."""
        if not paths:
            return
        self._selected_files = [Path(p) for p in paths if Path(p).exists()]
        if len(self._selected_files) == 1:
            self.input_edit.setText(str(self._selected_files[0]))
        elif self._selected_files:
            self.input_edit.setText(
                f"{self._selected_files[0]} (+ {len(self._selected_files) - 1} more)"
            )
        if self._selected_files:
            self._last_dir = str(self._selected_files[0].parent)
            self._mark_step_completed(1)

    # --- Logging ---

    def _log(self, msg: str) -> None:
        """Append an HTML-formatted log message."""
        cursor = self.log_text.textCursor()
        cursor.movePosition(QTextCursor.End)
        cursor.insertHtml(msg + "<br>")
        self.log_text.moveCursor(QTextCursor.End)

    def _set_progress(self, pct: float) -> None:
        self.progress_bar.setValue(int(pct))

    def _set_status(self, msg: str) -> None:
        self.statusBar().showMessage(msg)

    # --- Export ---

    def _save_log(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Log",
            self._last_dir + "/pathsafe_log.html",
            "HTML files (*.html);;All files (*)",
        )
        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.log_text.toHtml())
            self._last_dir = str(Path(path).parent)
            self.statusBar().showMessage(f"Log saved to {path}")

    def _auto_save_log(self, output_dir: str | Path) -> None:
        """Auto-save the log to the output folder after deidentification."""
        try:
            log_path = Path(output_dir) / "pathsafe_log.html"
            with open(log_path, "w", encoding="utf-8") as f:
                f.write(self.log_text.toHtml())
            self.statusBar().showMessage(f"Log auto-saved to {log_path}")
        except OSError:
            pass  # non-critical, don't interrupt the user

    # --- Summary popup ---

    # --- Step state ---

    def _mark_step_completed(self, step: int) -> None:
        """Mark a workflow step as completed and update its button text."""
        self._step_completed.add(step)
        btn = self._step_buttons.get(step)
        if btn and step in self._step_labels:
            num, name = self._step_labels[step]
            btn.setText(f"{num} [Done]\n{name}")

    def _mark_step_default(self, step: int) -> None:
        """Mark a workflow step as using its default value."""
        self._step_completed.add(step)
        btn = self._step_buttons.get(step)
        if btn and step in self._step_labels:
            num, name = self._step_labels[step]
            btn.setText(f"{num} [Default]\n{name}")

    def _reset_step(self, step: int) -> None:
        """Reset a step button to its default text."""
        self._step_completed.discard(step)
        btn = self._step_buttons.get(step)
        if btn and step in self._step_labels:
            num, name = self._step_labels[step]
            btn.setText(f"{num}\n{name}")

    # --- Persistent settings callbacks ---

    def _on_institution_changed(self, text: str) -> None:
        self._institution_name = text
        self._settings.setValue("institution_name", text)

    # --- Update checker ---

    def _on_update_check_toggled(self, checked):
        self._settings.setValue("check_updates", "true" if checked else "false")

    def _check_for_updates(self):
        """Launch background thread to check for updates."""
        from pathsafe.gui.toast import UpdateCheckThread

        self._update_thread = UpdateCheckThread()
        self._update_thread.update_available.connect(self._show_update_toast)
        self._update_thread.start()

    def _show_update_toast(self, update_info):
        """Show a toast notification when an update is available."""
        from pathsafe.gui.toast import ToastNotification

        url = update_info.download_url or update_info.release_url
        toast = ToastNotification(
            self,
            title=f"PathSafe {update_info.latest_version} available",
            message=f"You are running v{update_info.current_version}. A new version is available.",
            action_text="Download",
            action_url=url,
            duration_ms=20000,
        )
        toast.show_toast()

        # Also update status bar with persistent badge
        self.statusBar().showMessage(f"Update available: PathSafe v{update_info.latest_version}", 0)

    # --- Rename handlers ---

    def _on_rename_toggled(self, checked):
        """Enable/disable rename sub-panel contents."""
        if checked and self.radio_inplace.isChecked():
            QMessageBox.information(
                self,
                "Rename Unavailable",
                "File renaming is only available in Copy mode.\n"
                'Switch to "Copy and deidentify" to enable renaming.',
            )
            self.rename_group.setChecked(False)
            return
        self._on_rename_mode_toggled()
        if checked:
            self._schedule_rename_preview()
        else:
            self._rename_preview_label.setText("")

    def _on_rename_mode_toggled(self, _checked=None):
        """Show/hide the appropriate sub-panel for the selected rename mode."""
        self._rename_auto_widget.setVisible(self.radio_rename_auto.isChecked())
        self._rename_mapping_widget.setVisible(self.radio_rename_mapping.isChecked())
        self._rename_template_widget.setVisible(self.radio_rename_template.isChecked())
        self._schedule_rename_preview()

    def _browse_mapping_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select mapping CSV", self._last_dir, "CSV files (*.csv);;All files (*)"
        )
        if path:
            self.rename_mapping_edit.setText(path)
            self._last_dir = str(Path(path).parent)

    def _on_filter_toggled(self, checked: bool) -> None:
        """Enable/disable the filter controls."""
        self.filter_include_edit.setEnabled(checked)
        self.filter_exclude_edit.setEnabled(checked)
        self.filter_file_edit.setEnabled(checked)
        self.btn_filter_browse.setEnabled(checked)
        if not checked:
            self.filter_include_edit.clear()
            self.filter_exclude_edit.clear()
            self.filter_file_edit.clear()

    def _browse_filter_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select filter file",
            self._last_dir,
            "Filter files (*.txt *.csv *.json);;All files (*)",
        )
        if path:
            self.filter_file_edit.setText(path)
            self._last_dir = str(Path(path).parent)

    def _schedule_rename_preview(self, _text=None):
        """Schedule a preview update with 300ms debounce."""
        if self.rename_group.isChecked():
            self._rename_preview_timer.start()

    def _update_rename_preview(self):
        """Update the live preview showing 3+ example renames."""
        if not self.rename_group.isChecked():
            self._rename_preview_label.setText("")
            return

        from pathsafe.serializer import (
            RenameMode,
            load_mapping,
            preview_names,
        )

        try:
            config = self._build_serializer_config()
        except Exception:
            self._rename_preview_label.setText("<i>Invalid settings</i>")
            return

        # Gather source paths for preview
        source_paths = list(self._selected_files) if self._selected_files else []
        if not source_paths:
            input_text = self.input_edit.text().strip()
            if input_text:
                input_path = Path(input_text)
                from pathsafe.deidentifier import WSI_EXTENSIONS

                if input_path.is_file() and input_path.suffix.lower() in WSI_EXTENSIONS:
                    source_paths = [input_path]
                elif input_path.is_dir():
                    try:
                        found = sorted(input_path.iterdir(), key=lambda p: p.name.lower())
                        source_paths = [p for p in found if p.suffix.lower() in WSI_EXTENSIONS][:10]
                    except OSError:
                        pass

        if not source_paths:
            self._rename_preview_label.setText("<i>Select files first to see preview</i>")
            return

        # Load mapping if needed
        if config.mode == RenameMode.MAPPING and config.mapping_path:
            try:
                load_mapping(config)
            except Exception as e:
                self._rename_preview_label.setText(f"<i>Mapping error: {e}</i>")
                return

        try:
            previews = preview_names(config, source_paths, count=5)
        except Exception as e:
            self._rename_preview_label.setText(f"<i>Preview error: {e}</i>")
            return

        if not previews:
            self._rename_preview_label.setText("<i>No files match the current settings</i>")
            return

        # Build preview text showing at least 3 examples
        lines = []
        for orig, new in previews[:5]:
            lines.append(f"{orig}  →  <b>{new}</b>")
        if len(source_paths) > len(previews):
            remaining = len(source_paths) - len(previews)
            lines.append(f"<i>... and {remaining} more file(s)</i>")

        self._rename_preview_label.setText("<br>".join(lines))

    def _build_serializer_config(self):
        """Build a SerializerConfig from the current GUI state."""
        from pathsafe.serializer import RenameMode, SerializerConfig

        if self.radio_rename_auto.isChecked():
            mode = RenameMode.AUTO
        elif self.radio_rename_mapping.isChecked():
            mode = RenameMode.MAPPING
        elif self.radio_rename_template.isChecked():
            mode = RenameMode.TEMPLATE
        else:
            mode = RenameMode.KEEP

        mapping_path = None
        if mode == RenameMode.MAPPING:
            mp = self.rename_mapping_edit.text().strip()
            if mp:
                mapping_path = Path(mp)

        unmatched_map = {"Skip": "skip", "Auto-number": "auto", "Keep name": "keep"}
        unmatched = unmatched_map.get(self.combo_unmatched.currentText(), "skip")

        return SerializerConfig(
            mode=mode,
            prefix=self.rename_prefix.text().strip() or "ANON",
            start=int(self.rename_start.text() or "1"),
            digits=int(self.rename_digits.text() or "4"),
            separator=self.combo_rename_sep.currentText(),
            mapping_path=mapping_path,
            unmatched=unmatched,
            template=self.rename_template_edit.text().strip() or "{prefix}_{index}.{ext}",
        )

    # --- Run state ---

    def _set_running(self, running: bool) -> None:
        # Step buttons
        self.btn_select.setEnabled(not running)
        self.btn_scan.setEnabled(not running)
        self.btn_output.setEnabled(not running)
        self.btn_deidentify.setEnabled(not running)
        self.btn_stop.setEnabled(running)
        self._scan_action.setEnabled(not running)
        self._deidentify_action.setEnabled(not running)
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
        # (workers slider removed, now auto-detected)
        self.institution_edit.setEnabled(not running)
        self.combo_format_filter.setEnabled(not running)
        self.check_dry_run.setEnabled(not running)
        self.check_checksum.setEnabled(not running)
        self.check_verify.setEnabled(not running)
        self.check_integrity.setEnabled(not running)
        # Convert tab controls
        self.convert_output_edit.setEnabled(not running)
        self.combo_target_format.setEnabled(not running)
        self.combo_extract.setEnabled(not running)
        self.combo_tile_size.setEnabled(not running)
        self.slider_quality.setEnabled(not running)
        self.check_convert_deidentify.setEnabled(not running)
        self.slider_convert_workers.setEnabled(not running)
        self.combo_convert_format_filter.setEnabled(not running)
        self.btn_convert.setEnabled(not running)
        self.btn_convert_stop.setEnabled(running)
        # Rename controls
        self.rename_group.setEnabled(not running)
        if running:
            self._rename_preview_timer.stop()
        # Disable tab switching while running
        self.tabs.tabBar().setEnabled(not running)

    def _on_finished(self) -> None:
        self._set_running(False)
        self._worker = None

    def _request_stop(self) -> None:
        if self._worker:
            self._worker.stop()
            self._log("Stopped.")

    def _validate_input(self) -> Path | None:
        if self._selected_files:
            # Multi-file selection: files already validated at selection time
            return self._selected_files[0].parent
        path = self.input_edit.text().strip()
        if not path:
            QMessageBox.warning(self, "Error", "Please select an input file or folder.")
            return None
        p = Path(path)
        if not p.exists():
            QMessageBox.warning(self, "Error", f"Input path does not exist:\n{path}")
            return None
        return p

    def _get_format_filter(self) -> str | None:
        """Read the format filter from the Deidentify tab combo box."""
        idx = self.combo_format_filter.currentIndex()
        if idx == 0:
            return None
        return self.combo_format_filter.currentText().lower()

    # --- Scan ---

    def _run_scan(self) -> None:
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

        def on_done() -> None:
            self._on_finished()
            self._mark_step_completed(2)

        signals.finished.connect(on_done)

        output_dir = self.output_edit.text().strip() or None
        file_list = self._selected_files if self._selected_files else None
        self._worker = ScanWorker(
            input_p,
            self._auto_workers,
            signals,
            format_filter=self._get_format_filter(),
            institution=self._institution_name,
            output_dir=output_dir,
            file_list=file_list,
        )
        self._worker.start()

    # --- Deidentify ---

    def _run_deidentify(self) -> None:
        input_p = self._validate_input()
        if not input_p:
            return

        dry_run = self.check_dry_run.isChecked()

        output_dir = None
        if not dry_run and self.radio_copy.isChecked():
            out = self.output_edit.text().strip()
            if not out:
                QMessageBox.warning(
                    self,
                    "Error",
                    "Copy mode requires an output folder.\n"
                    "Select an output folder or switch to in-place mode.",
                )
                return
            # Create date-stamped subfolder inside the base output path
            output_dir = self._create_timestamped_output_dir(out)
        elif not dry_run and self.radio_inplace.isChecked():
            reply = QMessageBox.warning(
                self,
                "Confirm: Modify Originals",
                "You are about to deidentify your original files in-place.\n\n"
                "This will permanently remove patient information from the "
                "source files. This cannot be undone.\n\n"
                "Do you want to proceed?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
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

        def on_done() -> None:
            self._on_finished()
            self._mark_step_completed(4)
            # Auto-save log to the output folder
            if self._last_output_dir and not dry_run:
                self._auto_save_log(self._last_output_dir)

        signals.finished.connect(on_done)

        file_list = self._selected_files if self._selected_files else None

        # --- Apply file filters if enabled ---
        if self.check_filter.isChecked():
            from pathsafe.deidentifier import collect_wsi_files
            from pathsafe.serializer import apply_filters

            # Get file list to filter
            if file_list:
                to_filter = list(file_list)
            else:
                to_filter = collect_wsi_files(input_p, format_filter=self._get_format_filter())
            include_pat = self.filter_include_edit.text().strip()
            exclude_pat = self.filter_exclude_edit.text().strip()
            ff_path = self.filter_file_edit.text().strip()
            try:
                filtered = apply_filters(
                    to_filter,
                    include=[include_pat] if include_pat else None,
                    exclude=[exclude_pat] if exclude_pat else None,
                    filter_file=Path(ff_path) if ff_path else None,
                )
            except (ValueError, FileNotFoundError, OSError) as e:
                QMessageBox.warning(self, "Filter Error", f"Could not apply file filter:\n\n{e}")
                return
            dropped = len(to_filter) - len(filtered)
            if dropped:
                self._log(
                    f'<span style="color:#888;">Filter: {len(filtered)} of '
                    f"{len(to_filter)} files selected ({dropped} excluded)</span>"
                )
            if not filtered:
                QMessageBox.warning(
                    self,
                    "No Files",
                    "No files remain after filtering.\n"
                    "Check your include/exclude patterns or filter file.",
                )
                return
            file_list = filtered

        # --- Build rename plan if rename is enabled ---
        precomputed_pairs = None
        rename_plan = None
        serializer_config = None
        if (
            self.rename_group.isChecked()
            and self.rename_group.isEnabled()
            and output_dir
            and not dry_run
        ):
            from pathsafe.serializer import (
                RenameMode,
                compute_rename_plan,
                load_mapping,
            )

            try:
                serializer_config = self._build_serializer_config()
                if serializer_config.mode == RenameMode.MAPPING:
                    load_mapping(serializer_config)
                # Collect source files for the plan
                if file_list:
                    source_files = list(file_list)
                else:
                    from pathsafe.deidentifier import collect_wsi_files

                    source_files = collect_wsi_files(
                        input_p, format_filter=self._get_format_filter()
                    )
                rename_plan = compute_rename_plan(serializer_config, source_files, output_dir)
                precomputed_pairs = rename_plan
            except (ValueError, KeyError, FileNotFoundError) as e:
                QMessageBox.warning(
                    self,
                    "Rename Error",
                    f"Could not compute rename plan:\n\n{e}\n\nFiles will not be renamed.",
                )
                precomputed_pairs = None
                rename_plan = None

        self._worker = DeidentifyWorker(
            input_p,
            output_dir,
            self.check_verify.isChecked(),
            self._auto_workers,
            signals,
            reset_timestamps=True,
            format_filter=self._get_format_filter(),
            dry_run=dry_run,
            verify_integrity=self.check_integrity.isChecked(),
            institution=self._institution_name,
            file_list=file_list,
            compute_checksum=self.check_checksum.isChecked(),
            precomputed_pairs=precomputed_pairs,
            rename_plan=rename_plan,
            serializer_config=serializer_config,
        )
        self._worker.start()

    # --- Verify ---

    def _run_verify(self) -> None:
        # If we just deidentified files, verify only those specific outputs
        file_list = None
        if self._last_deidentified_paths:
            file_list = self._last_deidentified_paths
            verify_path = Path(self._last_deidentified_paths[0]).parent
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

        def on_done() -> None:
            self._on_finished()
            self._last_deidentified_paths = []  # clear after verify

        signals.finished.connect(on_done)

        self._worker = VerifyWorker(
            verify_path, signals, format_filter=self._get_format_filter(), file_list=file_list
        )
        self._worker.start()

    # --- Info ---

    def _run_info(self) -> None:
        input_p = self._validate_input()
        if not input_p:
            return
        if input_p.is_dir():
            QMessageBox.warning(self, "Error", "File Info requires a single file, not a directory.")
            return

        self.log_text.clear()
        self.progress_bar.setValue(0)
        self._set_running(True)

        signals = WorkerSignals()
        signals.log.connect(self._log)
        signals.progress.connect(self._set_progress)
        signals.status.connect(self._set_status)
        signals.summary.connect(self._show_summary)

        def on_done() -> None:
            self._on_finished()

        signals.finished.connect(on_done)

        self._worker = InfoWorker(input_p, signals)
        self._worker.start()

    # --- Convert ---

    def _run_convert(self) -> None:
        input_p = self._validate_input()
        if not input_p:
            return

        output_text = self.convert_output_edit.text().strip()
        if not output_text:
            QMessageBox.warning(self, "Error", "Please specify an output path for conversion.")
            return
        output_p = Path(output_text)

        # For batch (directory) input, output must be a directory path
        if input_p.is_dir() and output_p.suffix:
            QMessageBox.warning(
                self,
                "Error",
                "When converting a folder, the output path must be a directory,\nnot a file path.",
            )
            return

        # Create output directory if it doesn't exist
        try:
            out_dir = output_p if input_p.is_dir() else output_p.parent
            out_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            QMessageBox.warning(self, "Error", f"Cannot create output directory:\n{e}")
            return

        # Read conversion options
        target_values = ["tiff", "png", "jpeg"]
        target_format = target_values[self.combo_target_format.currentIndex()]

        extract_values = [None, "label", "macro", "thumbnail"]
        extract = extract_values[self.combo_extract.currentIndex()]

        tile_size = int(self.combo_tile_size.currentText())
        quality = self.slider_quality.value()

        deidentify_after = self.check_convert_deidentify.isChecked()
        reset_timestamps = deidentify_after
        workers = self.slider_convert_workers.value()

        fmt_idx = self.combo_convert_format_filter.currentIndex()
        format_filter = (
            None if fmt_idx == 0 else self.combo_convert_format_filter.currentText().lower()
        )

        self.log_text.clear()
        self.progress_bar.setValue(0)
        self._set_running(True)

        signals = WorkerSignals()
        signals.log.connect(self._log)
        signals.progress.connect(self._set_progress)
        signals.status.connect(self._set_status)
        signals.summary.connect(self._show_summary)

        def on_done() -> None:
            self._on_finished()

        signals.finished.connect(on_done)

        self._worker = ConvertWorker(
            input_p,
            output_p,
            target_format,
            extract,
            tile_size,
            quality,
            deidentify_after,
            reset_timestamps,
            workers,
            format_filter,
            signals,
        )
        self._worker.start()

    # --- Theme ---

    def _apply_theme(self, theme: str) -> None:
        self._current_theme = theme
        qss = DARK_QSS if theme == "dark" else LIGHT_QSS
        QApplication.instance().setStyleSheet(qss)
        self.drop_zone.set_theme(theme)
        set_html_theme(theme)
        self._dark_action.setChecked(theme == "dark")
        self._light_action.setChecked(theme == "light")
        self._settings.setValue("theme", theme)

    # --- Close guard ---

    def closeEvent(self, event: object) -> None:
        if self._worker is not None:
            is_read_only = isinstance(self._worker, (ScanWorker, VerifyWorker, InfoWorker))
            if is_read_only:
                reply = QMessageBox.question(
                    self,
                    "Scan In Progress",
                    "A scan is still running. It is safe to quit now -- "
                    "scanning is read-only and will not corrupt any files.\n\n"
                    "Close the application?",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.No,
                )
                if reply == QMessageBox.No:
                    event.ignore()
                    return
                self._worker.stop()
                self._worker.terminate()
                self._worker.wait(2000)
            else:
                reply = QMessageBox.question(
                    self,
                    "Operation In Progress",
                    "An deidentification or conversion is still running. "
                    "Closing now may leave partially written output files.\n\n"
                    "Are you sure you want to quit?",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.No,
                )
                if reply == QMessageBox.No:
                    event.ignore()
                    return
                self._worker.stop()
                self._worker.terminate()
                self._worker.wait(3000)
        event.accept()
