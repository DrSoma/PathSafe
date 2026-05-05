"""PathSafe Qt GUI package - modern cross-platform interface for hospital staff.

One-click deidentify workflow: browse files, scan, deidentify, verify.
Uses PySide6 (Qt6) for native look and crisp text on all platforms.

Features:
- Light and dark theme (switchable from View menu)
- Drag-and-drop file/folder support
- Workflow step indicator
- Menu bar with keyboard shortcuts
- Tooltips on all controls
- Status bar with live stats
- Tabbed interface for Deidentify and Convert workflows
- Format filtering, dry-run mode, and log export
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path


try:
    from PySide6.QtWidgets import QApplication
except ImportError as _exc:
    print(
        "Error: PySide6 is required for the GUI.\nInstall it with:  pip install pathsafe[gui]",
        file=sys.stderr,
    )
    raise SystemExit(1) from _exc

from pathsafe.gui.themes import DARK_QSS
from pathsafe.gui.window import PathSafeWindow


def _install_linux_desktop_integration() -> None:
    """Install icon and .desktop file to ~/.local/share/ for taskbar integration.

    Runs once silently on first launch. Copies the app icon into the
    user's local icon theme and writes a .desktop file so that Linux
    desktop environments can display the correct name and icon in the
    taskbar, dock, and application menu.
    """
    if sys.platform != "linux":
        return

    icon_src = Path(__file__).parent.parent / "assets" / "icon.png"
    if not icon_src.exists():
        return

    data_home = Path.home() / ".local" / "share"

    # Install icon to hicolor theme (multiple sizes for best display)
    icon_dest = data_home / "icons" / "hicolor" / "256x256" / "apps" / "pathsafe.png"
    if not icon_dest.exists():
        icon_dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(icon_src, icon_dest)

    # Write .desktop file
    desktop_dest = data_home / "applications" / "pathsafe.desktop"
    if not desktop_dest.exists():
        desktop_dest.parent.mkdir(parents=True, exist_ok=True)
        desktop_dest.write_text(
            "[Desktop Entry]\n"
            "Name=PathSafe\n"
            "Comment=Hospital-grade WSI deidentifier\n"
            "Exec=pathsafe-gui %f\n"
            "Icon=pathsafe\n"
            "Terminal=false\n"
            "Type=Application\n"
            "Categories=Science;Medical;\n"
            "MimeType=image/tiff;\n"
        )


def main() -> None:
    """Launch the PathSafe Qt GUI."""
    _install_linux_desktop_integration()
    app = QApplication(sys.argv)
    app.setApplicationName("PathSafe")
    app.setDesktopFileName("pathsafe")
    app.setStyle("Fusion")
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
