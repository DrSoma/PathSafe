"""Theme stylesheets and color constants for the PathSafe GUI."""

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
