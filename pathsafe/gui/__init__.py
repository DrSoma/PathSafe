"""PathSafe Qt GUI package - modern cross-platform interface for hospital staff.

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

import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

from pathsafe.gui.themes import DARK_QSS
from pathsafe.gui.window import PathSafeWindow


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
