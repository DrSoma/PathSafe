"""PathSafe main application window."""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QSettings, QStandardPaths, Qt, QTimer
from PySide6.QtGui import (
    QAction,
    QActionGroup,
    QFont,
    QIcon,
    QIntValidator,
    QKeySequence,
    QTextCursor,
)
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QSlider,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

import pathsafe
from pathsafe.anonymizer import WSI_EXTENSIONS
from pathsafe.gui.themes import _FORMAT_FILTER_ITEMS, DARK_QSS, LIGHT_QSS
from pathsafe.gui.widgets import DropZoneWidget
from pathsafe.gui.workers import (
    AnonymizeWorker,
    ConvertWorker,
    InfoWorker,
    ScanWorker,
    VerifyWorker,
    WorkerSignals,
)
from pathsafe.log import set_html_theme


class PathSafeWindow(QMainWindow):
    """Main application window."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"PathSafe v{pathsafe.__version__} - WSI Anonymizer")
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
        self._last_anonymized_paths = []  # output paths from last anonymize run
        self._last_output_dir = None  # actual output dir (date-stamped subfolder)
        self._selected_files = []  # multi-file selection list
        self._settings = QSettings("PathSafe", "PathSafe")
        self._current_theme = self._settings.value("theme", "dark")
        self._institution_name = self._settings.value("institution_name", "")
        from pathsafe.anonymizer import auto_workers

        self._auto_workers = auto_workers()
        self._step_completed = set()  # track completed steps {1, 2, 3}
        self._step_labels = {
            1: ("Step 1", "Select Files"),
            2: ("Step 2", "Scan for PHI"),
            3: ("Step 3", "Select File Output"),
            4: ("Step 4", "Anonymize"),
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
        if self._settings.value("check_updates", "false") == "true":
            QTimer.singleShot(500, self._check_for_updates)

    def _build_menu_bar(self) -> None:
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
        self._dark_action.setChecked(self._current_theme == "dark")
        self._dark_action.triggered.connect(lambda: self._apply_theme("dark"))
        theme_group.addAction(self._dark_action)
        view_menu.addAction(self._dark_action)

        self._light_action = QAction("&Light Theme", self)
        self._light_action.setCheckable(True)
        self._light_action.setChecked(self._current_theme == "light")
        self._light_action.triggered.connect(lambda: self._apply_theme("light"))
        theme_group.addAction(self._light_action)
        view_menu.addAction(self._light_action)

        # Settings menu
        settings_menu = menu_bar.addMenu("&Settings")
        self._update_check_action = QAction("Check for &updates on startup", self)
        self._update_check_action.setCheckable(True)
        self._update_check_action.setChecked(
            self._settings.value("check_updates", "false") == "true"
        )
        self._update_check_action.setToolTip(
            "When enabled, PathSafe checks GitHub for new releases\n"
            "on startup. Disabled by default for network privacy."
        )
        self._update_check_action.toggled.connect(self._on_update_check_toggled)
        settings_menu.addAction(self._update_check_action)

        check_now_action = QAction("Check for updates &now", self)
        check_now_action.triggered.connect(self._check_for_updates)
        settings_menu.addAction(check_now_action)

        # Help menu
        help_menu = menu_bar.addMenu("&Help")
        about_action = QAction("&About PathSafe", self)
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)

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
            "Choose the output folder where anonymized\ncopies will be saved."
        )
        self.btn_output.clicked.connect(self._browse_output_dir_step)
        step_layout.addWidget(self.btn_output)

        self.btn_anonymize = QPushButton("Step 4\nAnonymize")
        self.btn_anonymize.setObjectName("btn_anonymize")
        self.btn_anonymize.setToolTip(
            "Remove all detected patient information from files.\n"
            "Enable 'Verify after anonymize' to confirm removal. [Ctrl+R]"
        )
        self.btn_anonymize.clicked.connect(self._run_anonymize)
        step_layout.addWidget(self.btn_anonymize)

        self.btn_stop = QPushButton("Stop")
        self.btn_stop.setObjectName("btn_stop")
        self.btn_stop.setEnabled(False)
        self.btn_stop.setToolTip(
            "Stop the current operation after the\ncurrent file finishes. [Escape]"
        )
        self.btn_stop.clicked.connect(self._request_stop)
        step_layout.addWidget(self.btn_stop)

        # Step buttons: fixed height so they don't stretch the top section
        for btn in (self.btn_select, self.btn_scan, self.btn_output, self.btn_anonymize):
            btn.setFixedHeight(70)
        self.btn_stop.setFixedHeight(50)

        step_group.setFixedWidth(170)
        self._step_buttons = {
            1: self.btn_select,
            2: self.btn_scan,
            3: self.btn_output,
            4: self.btn_anonymize,
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

        # Tab Widget (Anonymize / Convert)
        self.tabs = QTabWidget()
        controls_layout.addWidget(self.tabs)

        self._build_anonymize_tab()
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

    def _build_anonymize_tab(self) -> None:
        """Build the Anonymize tab with output, options, compliance, and action buttons."""
        anon_tab = QWidget()
        anon_layout = QVBoxLayout(anon_tab)
        anon_layout.setContentsMargins(8, 8, 8, 8)
        anon_layout.setSpacing(8)

        # --- Output row ---
        output_row = QHBoxLayout()
        output_row.addWidget(QLabel("Output:"))
        self.output_edit = QLineEdit()
        self.output_edit.setPlaceholderText("Output folder for copy mode...")
        self.output_edit.setToolTip(
            "Where anonymized copies will be saved.\nOnly needed in Copy mode."
        )
        output_row.addWidget(self.output_edit, 1)
        anon_layout.addLayout(output_row)

        # --- Options (use QFormLayout-like rows with generous spacing) ---
        opts_group = QGroupBox("Options")
        opts_vlayout = QVBoxLayout(opts_group)
        opts_vlayout.setSpacing(10)
        opts_vlayout.setContentsMargins(12, 14, 12, 12)

        # Row 1: Mode
        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("Mode:"))
        self.radio_copy = QRadioButton("Copy and anonymize")
        self.radio_copy.setChecked(True)
        self.radio_copy.setToolTip(
            "Creates anonymized copies in the output folder.\n"
            "Your original files are never modified. (Recommended)"
        )
        self.radio_inplace = QRadioButton("Modify originals directly")
        self.radio_inplace.setToolTip(
            "Modifies the original files directly.\n"
            "WARNING: Original data cannot be recovered after anonymization."
        )
        self.radio_inplace.toggled.connect(self._on_inplace_toggled)
        self.radio_copy.toggled.connect(lambda checked: checked and self._on_copy_mode_restored())
        mode_group = QButtonGroup(self)
        mode_group.addButton(self.radio_copy)
        mode_group.addButton(self.radio_inplace)
        mode_row.addWidget(self.radio_copy)
        mode_row.addSpacing(20)
        mode_row.addWidget(self.radio_inplace)
        mode_row.addStretch()
        opts_vlayout.addLayout(mode_row)

        # Row 2: Institution name
        institution_row = QHBoxLayout()
        institution_row.addWidget(QLabel("Institution (optional):"))
        self.institution_edit = QLineEdit()
        self.institution_edit.setMinimumHeight(28)
        self.institution_edit.setPlaceholderText('e.g. "Memorial General Hospital"')
        self.institution_edit.setToolTip(
            "Institution name displayed on PDF scan reports\n"
            "and anonymization certificates.\n"
            "Leave empty to omit from reports."
        )
        self.institution_edit.setText(self._institution_name)
        self.institution_edit.textChanged.connect(self._on_institution_changed)
        institution_row.addWidget(self.institution_edit, 1)
        opts_vlayout.addLayout(institution_row)

        # Row 3: Format + Dry run + Checksum
        format_row = QHBoxLayout()
        format_row.addWidget(QLabel("Format:"))
        self.combo_format_filter = QComboBox()
        self.combo_format_filter.addItems(_FORMAT_FILTER_ITEMS)
        self.combo_format_filter.setToolTip(
            "Only process files of the selected format.\n"
            '"All formats" processes every supported WSI format.'
        )
        self.combo_format_filter.setFixedWidth(150)
        format_row.addWidget(self.combo_format_filter)
        format_row.addSpacing(30)
        self.check_dry_run = QCheckBox("Dry run (preview only)")
        self.check_dry_run.setToolTip("Scan and report findings without modifying any files.")
        format_row.addWidget(self.check_dry_run)
        format_row.addSpacing(20)
        self.check_checksum = QCheckBox("SHA-256 checksum")
        self.check_checksum.setToolTip(
            "Compute a SHA-256 hash for each output file.\n"
            "Useful for audit trails but adds processing time."
        )
        format_row.addWidget(self.check_checksum)
        format_row.addSpacing(20)
        self.check_verify = QCheckBox("Verify after anonymize")
        self.check_verify.setChecked(True)
        self.check_verify.setToolTip(
            "Re-scan each file after anonymization to confirm\nall PHI was successfully removed."
        )
        format_row.addWidget(self.check_verify)
        format_row.addSpacing(20)
        self.check_integrity = QCheckBox("Verify image integrity")
        self.check_integrity.setToolTip(
            "Compare tile hashes before and after anonymization\n"
            "to prove tissue image data was not altered.\n"
            "Adds processing time but valuable for compliance."
        )
        format_row.addWidget(self.check_integrity)
        format_row.addStretch()
        opts_vlayout.addLayout(format_row)

        # Row 4: File filter (optional — collapsible via checkbox)
        filter_row = QHBoxLayout()
        self.check_filter = QCheckBox("Filter files:")
        self.check_filter.setToolTip(
            "Only process a subset of the input files.\n"
            "Use a pattern to match filenames (e.g. *HE*)\n"
            "or load a file listing which slides to include."
        )
        self.check_filter.toggled.connect(self._on_filter_toggled)
        filter_row.addWidget(self.check_filter)

        self.filter_include_edit = QLineEdit()
        self.filter_include_edit.setPlaceholderText("Pattern, e.g. *HE*")
        self.filter_include_edit.setFixedWidth(150)
        self.filter_include_edit.setEnabled(False)
        self.filter_include_edit.setToolTip(
            "Glob pattern to match filenames.\n\n"
            "Examples:\n"
            "  *HE*     — only files containing 'HE'\n"
            "  *H&E*    — only files containing 'H&E'\n"
            "  *.ndpi   — only NDPI files\n\n"
            "Leave empty to include all files.\n"
            "Combine with a filter file for advanced workflows."
        )
        filter_row.addWidget(self.filter_include_edit)

        self.filter_exclude_edit = QLineEdit()
        self.filter_exclude_edit.setPlaceholderText("Exclude, e.g. *IHC*")
        self.filter_exclude_edit.setFixedWidth(150)
        self.filter_exclude_edit.setEnabled(False)
        self.filter_exclude_edit.setToolTip(
            "Glob pattern to exclude filenames.\n\n"
            "Examples:\n"
            "  *IHC*     — skip IHC stains\n"
            "  *frozen*  — skip frozen sections\n"
            "  *CK7*     — skip CK7 slides"
        )
        filter_row.addWidget(self.filter_exclude_edit)

        filter_row.addSpacing(8)
        self.filter_file_edit = QLineEdit()
        self.filter_file_edit.setPlaceholderText("Filter file (optional)...")
        self.filter_file_edit.setEnabled(False)
        self.filter_file_edit.setToolTip(
            "Load a text, CSV, or JSON file listing which slides to include.\n\n"
            "Accepted formats:\n"
            "  • Text (.txt): one filename per line\n"
            "  • CSV (.csv): must have a column with 'file' in its header\n"
            "  • JSON (.json): list of filenames, or {filename: stain} dict\n\n"
            "The JSON dict format works directly with OCR stain\n"
            "classification outputs (e.g. from extract_svs_labels.py)."
        )
        filter_row.addWidget(self.filter_file_edit, 1)
        self.btn_filter_browse = QPushButton("...")
        self.btn_filter_browse.setFixedWidth(30)
        self.btn_filter_browse.setEnabled(False)
        self.btn_filter_browse.clicked.connect(self._browse_filter_file)
        filter_row.addWidget(self.btn_filter_browse)

        opts_vlayout.addLayout(filter_row)

        anon_layout.addWidget(opts_group)

        # --- Rename section ---
        rename_group = QGroupBox("Rename Output Files")
        rename_group.setCheckable(True)
        rename_group.setChecked(False)
        rename_group.setToolTip(
            "Enable this to give your output files new, clean names.\n"
            "Without renaming, the output keeps the original filename\n"
            "(which often contains accession numbers or patient info).\n\n"
            "Only available in Copy mode."
        )
        self.rename_group = rename_group
        rename_layout = QVBoxLayout(rename_group)
        rename_layout.setSpacing(6)
        rename_layout.setContentsMargins(12, 14, 12, 10)

        # Mode radio buttons
        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("Mode:"))
        self.radio_rename_auto = QRadioButton("Auto-sequential")
        self.radio_rename_auto.setChecked(True)
        self.radio_rename_auto.setToolTip(
            "Gives each file a simple numbered name.\n\n"
            "Example: If prefix is 'ANON' and start is 1:\n"
            "  original_slide_A.ndpi  ->  ANON_0001.ndpi\n"
            "  original_slide_B.ndpi  ->  ANON_0002.ndpi\n"
            "  original_slide_C.svs   ->  ANON_0003.svs\n\n"
            "Use when you just need clean sequential IDs\n"
            "and don't care about specific output names."
        )
        self.radio_rename_mapping = QRadioButton("From mapping file")
        self.radio_rename_mapping.setToolTip(
            "Rename each file using a spreadsheet you prepare in advance.\n\n"
            "Create a CSV file with two columns:\n"
            "  source_filename, output_name\n\n"
            "Example CSV:\n"
            "  source_filename,output_name\n"
            "  original_slide_A.ndpi,PROJECT_CASE_042.ndpi\n"
            "  original_slide_B.ndpi,PROJECT_CASE_043.ndpi\n\n"
            "Use when you already know exactly what each file\n"
            "should be called (e.g. from a study protocol)."
        )
        self.radio_rename_template = QRadioButton("Custom pattern")
        self.radio_rename_template.setToolTip(
            "Build your own naming pattern using placeholders.\n\n"
            "Available placeholders:\n"
            "  {prefix}  - the prefix text you set (e.g. 'ANON')\n"
            "  {index}   - sequential number (0001, 0002, ...)\n"
            "  {ext}     - original file extension (ndpi, svs, ...)\n"
            "  {format}  - detected scanner format name\n"
            "  {date}    - today's date (YYYYMMDD)\n"
            "  {sha8}    - first 8 characters of the file's hash\n\n"
            "Example pattern: {prefix}_{date}_{index}.{ext}\n"
            "  -> ANON_20260324_0001.ndpi\n"
            "  -> ANON_20260324_0002.svs\n\n"
            "Use when you need names that include dates,\n"
            "format info, or other structured metadata."
        )
        rename_mode_group = QButtonGroup(self)
        rename_mode_group.addButton(self.radio_rename_auto)
        rename_mode_group.addButton(self.radio_rename_mapping)
        rename_mode_group.addButton(self.radio_rename_template)
        mode_row.addWidget(self.radio_rename_auto)
        mode_row.addSpacing(10)
        mode_row.addWidget(self.radio_rename_mapping)
        mode_row.addSpacing(10)
        mode_row.addWidget(self.radio_rename_template)
        mode_row.addStretch()
        rename_layout.addLayout(mode_row)

        # Auto-sequential settings row
        self._rename_auto_widget = QWidget()
        auto_row = QHBoxLayout(self._rename_auto_widget)
        auto_row.setContentsMargins(0, 0, 0, 0)
        auto_row.addWidget(QLabel("Prefix:"))
        self.rename_prefix = QLineEdit("ANON")
        self.rename_prefix.setFixedWidth(120)
        self.rename_prefix.setToolTip(
            "The text that appears before the number in each filename.\n\n"
            "Example: prefix 'ANON' produces ANON_0001.ndpi\n"
            "         prefix 'PROJ' produces PROJ_0001.ndpi"
        )
        auto_row.addWidget(self.rename_prefix)
        auto_row.addSpacing(12)
        auto_row.addWidget(QLabel("Start:"))
        self.rename_start = QLineEdit("1")
        self.rename_start.setFixedWidth(60)
        self.rename_start.setValidator(QIntValidator(0, 999999, self))
        self.rename_start.setToolTip(
            "The first number in the sequence.\n\n"
            "Start=1  -> 0001, 0002, 0003, ...\n"
            "Start=50 -> 0050, 0051, 0052, ...\n\n"
            "Useful when adding files to an existing batch\n"
            "(e.g. batch 1 ended at 0500, set start to 501)."
        )
        auto_row.addWidget(self.rename_start)
        auto_row.addSpacing(12)
        auto_row.addWidget(QLabel("Digits:"))
        self.rename_digits = QLineEdit("4")
        self.rename_digits.setFixedWidth(40)
        self.rename_digits.setValidator(QIntValidator(1, 10, self))
        self.rename_digits.setToolTip(
            "How many digits the number should have\n"
            "(padded with leading zeros).\n\n"
            "Digits=4 -> 0001, 0002, ..., 9999\n"
            "Digits=5 -> 00001, 00002, ..., 99999\n\n"
            "Use 4 for most batches. Use 5+ if you\n"
            "have more than 9,999 files."
        )
        auto_row.addWidget(self.rename_digits)
        auto_row.addSpacing(12)
        auto_row.addWidget(QLabel("Sep:"))
        self.combo_rename_sep = QComboBox()
        self.combo_rename_sep.addItems(["_", "-", "."])
        self.combo_rename_sep.setFixedWidth(50)
        self.combo_rename_sep.setToolTip(
            "The character between the prefix and the number.\n\n"
            "  _  ->  ANON_0001.ndpi  (underscore, most common)\n"
            "  -  ->  ANON-0001.ndpi  (hyphen)\n"
            "  .  ->  ANON.0001.ndpi  (dot)"
        )
        auto_row.addWidget(self.combo_rename_sep)
        auto_row.addStretch()
        rename_layout.addWidget(self._rename_auto_widget)

        # Mapping file row
        self._rename_mapping_widget = QWidget()
        mapping_row = QHBoxLayout(self._rename_mapping_widget)
        mapping_row.setContentsMargins(0, 0, 0, 0)
        mapping_row.addWidget(QLabel("CSV file:"))
        self.rename_mapping_edit = QLineEdit()
        self.rename_mapping_edit.setPlaceholderText(
            "Select CSV with columns: source_filename, output_name"
        )
        self.rename_mapping_edit.setToolTip(
            "Path to a CSV spreadsheet that maps old names to new names.\n\n"
            "The CSV must have two columns with these exact headers:\n"
            "  source_filename  - the original filename (e.g. slide_A.ndpi)\n"
            "  output_name      - the new name you want (e.g. CASE_042.ndpi)\n\n"
            "You can create this file in Excel or Google Sheets\n"
            "and export as CSV."
        )
        mapping_row.addWidget(self.rename_mapping_edit, 1)
        btn_mapping_browse = QPushButton("Browse...")
        mapping_row.addWidget(btn_mapping_browse)
        btn_mapping_browse.clicked.connect(self._browse_mapping_file)
        mapping_row.addSpacing(12)
        mapping_row.addWidget(QLabel("Unmatched:"))
        self.combo_unmatched = QComboBox()
        self.combo_unmatched.addItems(["Skip", "Auto-number", "Keep name"])
        self.combo_unmatched.setToolTip(
            "What to do with files NOT listed in your CSV.\n\n"
            "  Skip        - don't process them at all\n"
            "  Auto-number - give them sequential names (ANON_0001, ...)\n"
            "  Keep name   - keep their original filename as-is"
        )
        self.combo_unmatched.setStyleSheet(
            "QComboBox { padding-left: 4px; padding-right: 0px; margin: 0px; }"
            "QComboBox::drop-down { width: 8px; }"
        )
        self.combo_unmatched.setFixedWidth(41)
        mapping_row.addWidget(self.combo_unmatched)
        rename_layout.addWidget(self._rename_mapping_widget)
        self._rename_mapping_widget.setVisible(False)

        # Template row
        self._rename_template_widget = QWidget()
        tpl_row = QHBoxLayout(self._rename_template_widget)
        tpl_row.setContentsMargins(0, 0, 0, 0)
        tpl_row.addWidget(QLabel("Pattern:"))
        self.rename_template_edit = QLineEdit("{prefix}_{index}.{ext}")
        self.rename_template_edit.setToolTip(
            "Type a naming pattern using placeholders in curly braces.\n"
            "Each placeholder gets replaced with a real value:\n\n"
            "  {prefix}  - the prefix text from the Auto-sequential settings\n"
            "  {index}   - a sequential number (0001, 0002, ...)\n"
            "  {ext}     - the file's original extension (ndpi, svs, ...)\n"
            "  {format}  - the detected scanner format\n"
            "  {date}    - today's date as YYYYMMDD (e.g. 20260324)\n"
            "  {sha8}    - first 8 characters of the file's hash (unique ID)\n\n"
            "Examples:\n"
            "  {prefix}_{index}.{ext}           -> ANON_0001.ndpi\n"
            "  {prefix}_{date}_{index}.{ext}    -> ANON_20260324_0001.ndpi\n"
            "  PROJ_{index}_{format}.{ext}      -> PROJ_0001_ndpi.ndpi"
        )
        tpl_row.addWidget(self.rename_template_edit, 1)
        rename_layout.addWidget(self._rename_template_widget)
        self._rename_template_widget.setVisible(False)

        # Live preview (always visible when rename is on)
        self._rename_preview_label = QLabel("")
        self._rename_preview_label.setTextFormat(Qt.RichText)
        self._rename_preview_label.setWordWrap(True)
        self._rename_preview_label.setStyleSheet(
            "color: #888; font-family: monospace; font-size: 11px; "
            "padding: 4px 8px; border-radius: 4px;"
        )
        rename_layout.addWidget(self._rename_preview_label)

        anon_layout.addWidget(rename_group)

        # Connect signals for mode switching and live preview
        self.radio_rename_auto.toggled.connect(self._on_rename_mode_toggled)
        self.radio_rename_mapping.toggled.connect(self._on_rename_mode_toggled)
        self.radio_rename_template.toggled.connect(self._on_rename_mode_toggled)
        rename_group.toggled.connect(self._on_rename_toggled)

        # Connect preview updates (with 300ms debounce via QTimer)
        from PySide6.QtCore import QTimer

        self._rename_preview_timer = QTimer(self)
        self._rename_preview_timer.setSingleShot(True)
        self._rename_preview_timer.setInterval(300)
        self._rename_preview_timer.timeout.connect(self._update_rename_preview)
        for widget in (
            self.rename_prefix,
            self.rename_start,
            self.rename_digits,
            self.rename_template_edit,
            self.rename_mapping_edit,
        ):
            widget.textChanged.connect(self._schedule_rename_preview)
        self.combo_rename_sep.currentTextChanged.connect(self._schedule_rename_preview)
        self.combo_unmatched.currentTextChanged.connect(self._schedule_rename_preview)
        self.input_edit.textChanged.connect(self._schedule_rename_preview)

        self.tabs.addTab(anon_tab, "Anonymize")

    def _build_convert_tab(self) -> None:
        """Build the Convert tab with output, conversion options, and action buttons."""
        conv_tab = QWidget()
        conv_layout = QVBoxLayout(conv_tab)
        conv_layout.setContentsMargins(8, 8, 8, 8)
        conv_layout.setSpacing(8)

        # --- Output row ---
        output_row = QHBoxLayout()
        output_row.addWidget(QLabel("Output:"))
        self.convert_output_edit = QLineEdit()
        self.convert_output_edit.setPlaceholderText("Output path for converted files (required)...")
        self.convert_output_edit.setToolTip(
            "Where converted files will be saved.\nRequired for all conversions."
        )
        output_row.addWidget(self.convert_output_edit, 1)
        btn_conv_out = QPushButton("Browse")
        btn_conv_out.setFixedWidth(80)
        btn_conv_out.clicked.connect(self._browse_convert_output)
        output_row.addWidget(btn_conv_out)
        conv_layout.addLayout(output_row)

        # --- Conversion Options ---
        conv_group = QGroupBox("Conversion")
        conv_grid = QHBoxLayout(conv_group)

        conv_grid.addWidget(QLabel("Target format:"))
        self.combo_target_format = QComboBox()
        self.combo_target_format.addItems(["Pyramidal TIFF", "PNG", "JPEG"])
        self.combo_target_format.setToolTip("Output format for the converted files.")
        self.combo_target_format.setFixedWidth(140)
        conv_grid.addWidget(self.combo_target_format)

        conv_grid.addSpacing(16)
        conv_grid.addWidget(QLabel("Extract:"))
        self.combo_extract = QComboBox()
        self.combo_extract.addItems(["Full conversion", "Label image", "Macro image", "Thumbnail"])
        self.combo_extract.setToolTip(
            "Extract a specific image from the WSI instead of\n"
            "performing full conversion. Single file only."
        )
        self.combo_extract.setFixedWidth(140)
        conv_grid.addWidget(self.combo_extract)

        conv_grid.addSpacing(16)
        conv_grid.addWidget(QLabel("Tile size:"))
        self.combo_tile_size = QComboBox()
        self.combo_tile_size.addItems(["128", "256", "512", "1024"])
        self.combo_tile_size.setCurrentText("256")
        self.combo_tile_size.setToolTip(
            "Tile size for pyramidal TIFF output (pixels).\n"
            "256 is the most common and compatible.\n"
            "512 may be faster for very large files."
        )
        self.combo_tile_size.setFixedWidth(80)
        conv_grid.addWidget(self.combo_tile_size)

        conv_grid.addSpacing(16)
        conv_grid.addWidget(QLabel("Quality:"))
        self._quality_label = QLabel("90")
        self._quality_label.setFixedWidth(24)
        self._quality_label.setAlignment(Qt.AlignCenter)
        self.slider_quality = QSlider(Qt.Horizontal)
        self.slider_quality.setRange(1, 100)
        self.slider_quality.setValue(90)
        self.slider_quality.setFixedWidth(100)
        self.slider_quality.setToolTip(
            "JPEG compression quality (1-100).\n"
            "Higher is better quality but larger files.\n"
            "Default: 90"
        )
        self.slider_quality.valueChanged.connect(lambda v: self._quality_label.setText(str(v)))
        conv_grid.addWidget(self.slider_quality)
        conv_grid.addWidget(self._quality_label)

        conv_grid.addStretch()
        conv_layout.addWidget(conv_group)

        # --- General Options ---
        opts_group = QGroupBox("Options")
        opts_layout = QHBoxLayout(opts_group)

        self.check_convert_anonymize = QCheckBox("Anonymize after conversion")
        self.check_convert_anonymize.setToolTip("Run anonymization on the converted output files.")
        opts_layout.addWidget(self.check_convert_anonymize)

        opts_layout.addSpacing(16)
        opts_layout.addWidget(QLabel("Workers:"))
        self._convert_workers_label = QLabel("4")
        self._convert_workers_label.setFixedWidth(20)
        self._convert_workers_label.setAlignment(Qt.AlignCenter)
        self.slider_convert_workers = QSlider(Qt.Horizontal)
        self.slider_convert_workers.setRange(1, 16)
        self.slider_convert_workers.setValue(4)
        self.slider_convert_workers.setFixedWidth(100)
        self.slider_convert_workers.setToolTip(
            "Number of files to convert simultaneously.\nDefault: 4"
        )
        self.slider_convert_workers.valueChanged.connect(
            lambda v: self._convert_workers_label.setText(str(v))
        )
        opts_layout.addWidget(self.slider_convert_workers)
        opts_layout.addWidget(self._convert_workers_label)

        opts_layout.addSpacing(16)
        opts_layout.addWidget(QLabel("Format:"))
        self.combo_convert_format_filter = QComboBox()
        self.combo_convert_format_filter.addItems(_FORMAT_FILTER_ITEMS)
        self.combo_convert_format_filter.setToolTip(
            "Only convert files of the selected format.\n"
            '"All formats" converts every supported WSI format.'
        )
        self.combo_convert_format_filter.setFixedWidth(120)
        opts_layout.addWidget(self.combo_convert_format_filter)

        opts_layout.addStretch()
        conv_layout.addWidget(opts_group)

        # --- Action Buttons ---
        btn_layout = QHBoxLayout()

        self.btn_convert = QPushButton("  Convert")
        self.btn_convert.setObjectName("btn_convert")
        self.btn_convert.setMinimumHeight(38)
        self.btn_convert.setToolTip("Convert WSI files to the selected target format.")
        self.btn_convert.clicked.connect(self._run_convert)
        btn_layout.addWidget(self.btn_convert)

        self.btn_convert_stop = QPushButton("  Stop")
        self.btn_convert_stop.setObjectName("btn_stop")
        self.btn_convert_stop.setMinimumHeight(38)
        self.btn_convert_stop.setEnabled(False)
        self.btn_convert_stop.setToolTip(
            "Stop the current conversion after the\ncurrent file finishes. [Escape]"
        )
        self.btn_convert_stop.clicked.connect(self._request_stop)
        btn_layout.addWidget(self.btn_convert_stop)

        btn_layout.addStretch()
        conv_layout.addLayout(btn_layout)

        conv_layout.addStretch()
        self.tabs.addTab(conv_tab, "Convert")

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
            '<p>For safety, we recommend using <b>"Copy and anonymize"</b> instead, '
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
            "Switch to 'Copy and anonymize' above to enable this."
        )

    def _on_copy_mode_restored(self):
        """Re-enable rename group when switching back to copy mode."""
        self.rename_group.setEnabled(True)
        self.rename_group.setToolTip(
            "Rename anonymized files to remove PHI from filenames.\nOnly available in Copy mode."
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
        """Auto-save the log to the output folder after anonymization."""
        try:
            log_path = Path(output_dir) / "pathsafe_log.html"
            with open(log_path, "w", encoding="utf-8") as f:
                f.write(self.log_text.toHtml())
            self.statusBar().showMessage(f"Log auto-saved to {log_path}")
        except OSError:
            pass  # non-critical, don't interrupt the user

    # --- Summary popup ---

    def _show_summary(self, data: dict[str, object]) -> None:
        """Show a summary popup dialog when an operation completes."""
        op = data.get("type", "operation")

        if op == "scan":
            total = data.get("total", 0)
            clean = data.get("clean", 0)
            phi_files = data.get("phi_files", 0)
            phi_findings = data.get("phi_findings", 0)
            errors = data.get("errors", 0)

            if phi_files == 0 and errors == 0:
                icon = QMessageBox.Information
                title = "Scan Complete: All Clean"
                scan_report = data.get("scan_report", "")
                report_line = (
                    f"<p>Scan report:<br><code>{Path(scan_report).name}</code></p>"
                    if scan_report
                    else ""
                )
                msg = (
                    f"<h3>All {total} files are clean</h3>"
                    f"<p>No patient information (PHI) was detected.</p>"
                    f"{report_line}"
                )
            else:
                icon = QMessageBox.Warning
                title = "Scan Complete: PHI Detected"
                lines = ['<h3>Scan Results</h3><table cellpadding="4">']
                lines.append(f"<tr><td>Total scanned:</td><td><b>{total}</b></td></tr>")
                if clean:
                    lines.append(
                        f'<tr><td>Clean:</td><td style="color:#2e8b3e"><b>{clean}</b></td></tr>'
                    )
                if phi_files:
                    lines.append(
                        f"<tr><td>PHI detected:</td>"
                        f'<td style="color:#b45300"><b>{phi_files} files '
                        f"({phi_findings} findings)</b></td></tr>"
                    )
                if errors:
                    lines.append(
                        f'<tr><td>Errors:</td><td style="color:#c03030"><b>{errors}</b></td></tr>'
                    )
                lines.append("</table>")
                if phi_files:
                    lines.append("<p>Run <b>Anonymize</b> to remove detected PHI.</p>")
                scan_report = data.get("scan_report", "")
                if scan_report:
                    lines.append(f"<p>Scan report:<br><code>{Path(scan_report).name}</code></p>")
                msg = "".join(lines)

        elif op == "anonymize":
            total = data.get("total", 0)
            anonymized = data.get("anonymized", 0)
            already_clean = data.get("already_clean", 0)
            errors = data.get("errors", 0)
            elapsed = data.get("time", "?")
            cert = data.get("certificate", "")
            dry_run = data.get("dry_run", False)

            # Store output paths so Verify can check just these files
            output_paths = data.get("output_paths", [])
            if output_paths:
                self._last_anonymized_paths = output_paths

            if dry_run:
                icon = QMessageBox.Information
                title = "Anonymization DRY RUN Complete"
            elif errors == 0:
                icon = QMessageBox.Information
                title = "Anonymization Complete"
            else:
                icon = QMessageBox.Warning
                title = "Anonymization Complete (with errors)"

            lines = ['<h3>Anonymization Results</h3><table cellpadding="4">']
            lines.append(f"<tr><td>Total files:</td><td><b>{total}</b></td></tr>")
            if anonymized:
                lines.append(
                    f'<tr><td>Anonymized:</td><td style="color:#b45300"><b>{anonymized}</b></td></tr>'
                )
            if already_clean:
                lines.append(
                    f'<tr><td>Already clean:</td><td style="color:#2e8b3e"><b>{already_clean}</b></td></tr>'
                )
            if errors:
                lines.append(
                    f'<tr><td>Errors:</td><td style="color:#c03030"><b>{errors}</b></td></tr>'
                )
            # Image integrity row
            integrity_verified = data.get("integrity_verified", 0)
            integrity_failed = data.get("integrity_failed", 0)
            if integrity_verified or integrity_failed:
                if integrity_failed:
                    lines.append(
                        f"<tr><td>Image integrity:</td>"
                        f'<td style="color:#c03030"><b>{integrity_failed} FAILED</b>, '
                        f"{integrity_verified} verified</td></tr>"
                    )
                else:
                    lines.append(
                        f"<tr><td>Image integrity:</td>"
                        f'<td style="color:#2e8b3e"><b>{integrity_verified} verified</b></td></tr>'
                    )
            # Filename PHI warning
            phi_filenames = data.get("phi_filenames", 0)
            if phi_filenames:
                lines.append(
                    f"<tr><td>Filename PHI:</td>"
                    f'<td style="color:#c03030"><b>{phi_filenames} file(s) '
                    f"need renaming</b></td></tr>"
                )
            lines.append(f"<tr><td>Time:</td><td>{elapsed}</td></tr>")
            lines.append("</table>")

            if phi_filenames:
                lines.append(
                    '<p style="color:#c03030"><b>WARNING:</b> Some output files '
                    "have patient information in their filename. Rename them "
                    "manually before sharing.</p>"
                )
            if dry_run:
                lines.append("<p><b>DRY RUN</b> - No files were modified.</p>")
            else:
                output_dir = data.get("output_dir", "")
                if output_dir:
                    lines.append(f"<p>Output folder:<br><code>{output_dir}</code></p>")
                if cert:
                    pdf_cert = data.get("pdf_certificate", "")
                    lines.append(f"<p>Certificate:<br><code>{Path(cert).name}</code>")
                    if pdf_cert:
                        lines.append(f"<br><code>{Path(pdf_cert).name}</code>")
                    lines.append("</p>")

            msg = "".join(lines)

        elif op == "verify":
            total = data.get("total", 0)
            clean = data.get("clean", 0)
            dirty = data.get("dirty", 0)

            if dirty == 0:
                icon = QMessageBox.Information
                title = "Verification Passed"
                msg = (
                    f"<h3>All {total} files verified clean</h3>"
                    f"<p>No patient information remains in any file.</p>"
                )
            else:
                icon = QMessageBox.Warning
                title = "Verification Failed"
                msg = (
                    f"<h3>Verification Results</h3>"
                    f'<table cellpadding="4">'
                    f'<tr><td>Clean:</td><td style="color:#2e8b3e"><b>{clean}</b></td></tr>'
                    f'<tr><td>PHI remaining:</td><td style="color:#c03030"><b>{dirty}</b></td></tr>'
                    f"</table>"
                    f"<p><b>WARNING:</b> Some files still contain PHI!</p>"
                )

        elif op == "info":
            fmt = data.get("format", "Unknown")
            size = data.get("size", "?")
            metadata_count = data.get("metadata_count", 0)
            phi_status = data.get("phi_status", "Unknown")

            icon = QMessageBox.Information
            title = "File Information"
            lines = ['<h3>File Information</h3><table cellpadding="4">']
            lines.append(f"<tr><td>Format:</td><td><b>{fmt}</b></td></tr>")
            lines.append(f"<tr><td>File size:</td><td><b>{size}</b></td></tr>")
            lines.append(f"<tr><td>Metadata entries:</td><td><b>{metadata_count}</b></td></tr>")
            lines.append(f"<tr><td>PHI status:</td><td><b>{phi_status}</b></td></tr>")
            lines.append("</table>")
            msg = "".join(lines)

        elif op == "convert":
            total = data.get("total", 0)
            converted = data.get("converted", 0)
            errors = data.get("errors", 0)
            elapsed = data.get("time", "?")

            if errors == 0:
                icon = QMessageBox.Information
                title = "Conversion Complete"
            else:
                icon = QMessageBox.Warning
                title = "Conversion Complete (with errors)"

            lines = ['<h3>Conversion Results</h3><table cellpadding="4">']
            lines.append(f"<tr><td>Total files:</td><td><b>{total}</b></td></tr>")
            if converted:
                lines.append(
                    f'<tr><td>Converted:</td><td style="color:#2e8b3e"><b>{converted}</b></td></tr>'
                )
            if errors:
                lines.append(
                    f'<tr><td>Errors:</td><td style="color:#c03030"><b>{errors}</b></td></tr>'
                )
            lines.append(f"<tr><td>Time:</td><td>{elapsed}</td></tr>")
            lines.append("</table>")
            msg = "".join(lines)

        else:
            return

        box = QMessageBox(self)
        box.setIcon(icon)
        box.setWindowTitle(title)
        box.setText(msg)
        box.exec()

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
                'Switch to "Copy and anonymize" to enable renaming.',
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
                from pathsafe.anonymizer import WSI_EXTENSIONS

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
        self.check_convert_anonymize.setEnabled(not running)
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
        """Read the format filter from the Anonymize tab combo box."""
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

    # --- Anonymize ---

    def _run_anonymize(self) -> None:
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
                "You are about to anonymize your original files in-place.\n\n"
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
            from pathsafe.anonymizer import collect_wsi_files
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
                    from pathsafe.anonymizer import collect_wsi_files

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

        self._worker = AnonymizeWorker(
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

        def on_done() -> None:
            self._on_finished()
            self._last_anonymized_paths = []  # clear after verify

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

        anonymize_after = self.check_convert_anonymize.isChecked()
        reset_timestamps = anonymize_after
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
            anonymize_after,
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
                    "An anonymization or conversion is still running. "
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

    # --- About ---

    def _show_about(self) -> None:
        QMessageBox.about(
            self,
            "About PathSafe",
            f"<h3>PathSafe v{pathsafe.__version__}</h3>"
            "<p>Production-tested WSI anonymizer for pathology slide files.</p>"
            "<p>Removes patient-identifying information (PHI) from "
            "NDPI, SVS, MRXS, DICOM, and other whole-slide image formats.</p>"
            "<p>Includes label/macro image blanking, post-anonymization "
            "verification, and PDF compliance certificates.</p>"
            "<hr>"
            "<p style='font-size:small; color:gray;'>"
            "<b>Disclaimer:</b> PathSafe is not a medical device and is not "
            "intended for clinical diagnosis. De-identification completeness "
            "should be verified per institutional requirements.</p>",
        )
