"""Convert tab UI builder."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from pathsafe.gui.themes import _FORMAT_FILTER_ITEMS


class ConvertPanelMixin:
    """Builds the Convert tab content."""

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

        self.check_convert_deidentify = QCheckBox("Deidentify after conversion")
        self.check_convert_deidentify.setToolTip(
            "Run deidentification on the converted output files."
        )
        opts_layout.addWidget(self.check_convert_deidentify)

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
