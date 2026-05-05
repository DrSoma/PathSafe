"""Deidentify tab UI builder."""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QIntValidator
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from pathsafe.gui.themes import _FORMAT_FILTER_ITEMS


class DeidentifyPanelMixin:
    """Builds the Deidentify tab content."""

    def _build_deidentify_tab(self) -> None:
        """Build the Deidentify tab with output, options, compliance, and action buttons."""
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
            "Where deidentified copies will be saved.\nOnly needed in Copy mode."
        )
        output_row.addWidget(self.output_edit, 1)
        anon_layout.addLayout(output_row)

        # --- Options ---
        opts_group = QGroupBox("Options")
        opts_vlayout = QVBoxLayout(opts_group)
        opts_vlayout.setSpacing(10)
        opts_vlayout.setContentsMargins(12, 14, 12, 12)

        # Row 1: Mode
        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("Mode:"))
        self.radio_copy = QRadioButton("Copy and deidentify")
        self.radio_copy.setChecked(True)
        self.radio_copy.setToolTip(
            "Creates deidentified copies in the output folder.\n"
            "Your original files are never modified. (Recommended)"
        )
        self.radio_inplace = QRadioButton("Modify originals directly")
        self.radio_inplace.setToolTip(
            "Modifies the original files directly.\n"
            "WARNING: Original data cannot be recovered after deidentification."
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
            "and deidentification certificates.\n"
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
        self.check_verify = QCheckBox("Verify after deidentify")
        self.check_verify.setChecked(True)
        self.check_verify.setToolTip(
            "Re-scan each file after deidentification to confirm\nall PHI was successfully removed."
        )
        format_row.addWidget(self.check_verify)
        format_row.addSpacing(20)
        self.check_integrity = QCheckBox("Verify image integrity")
        self.check_integrity.setToolTip(
            "Compare tile hashes before and after deidentification\n"
            "to prove tissue image data was not altered.\n"
            "Adds processing time but valuable for compliance."
        )
        format_row.addWidget(self.check_integrity)
        format_row.addStretch()
        opts_vlayout.addLayout(format_row)

        # Row 4: File filter
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

        # Live preview
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

        self.tabs.addTab(anon_tab, "Deidentify")
