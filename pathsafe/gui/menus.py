"""Menu bar construction for the main window."""

from __future__ import annotations

from PySide6.QtGui import QAction, QActionGroup, QKeySequence


class MenuBuilderMixin:
    """Builds the QMainWindow menu bar.

    Mixed into ``PathSafeWindow`` so the menu definition lives in its own file.
    Methods reference attributes set up by ``PathSafeWindow.__init__``
    (``self._settings``, ``self._current_theme``, action handlers, etc.).
    """

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

        self._deidentify_action = QAction("&Deidentify", self)
        self._deidentify_action.setShortcut("Ctrl+R")
        self._deidentify_action.triggered.connect(self._run_deidentify)
        actions_menu.addAction(self._deidentify_action)

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
