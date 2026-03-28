"""Non-blocking toast notification widget for the PathSafe GUI.

Shows a slide-in notification in the top-right corner of the parent window.
Auto-dismisses after a configurable duration. Used for update notifications.
"""

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QCursor, QDesktopServices
from PySide6.QtWidgets import (
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class UpdateCheckThread(QThread):
    """Background thread that checks for updates without blocking the GUI."""

    update_available = Signal(object)  # emits UpdateInfo or None

    def run(self):
        from pathsafe.updater import check_for_update

        result = check_for_update()
        if result and result.is_newer:
            self.update_available.emit(result)


class ToastNotification(QWidget):
    """A non-blocking toast notification that appears in the top-right corner."""

    def __init__(
        self, parent, title, message, action_text=None, action_url=None, duration_ms=20000
    ):
        super().__init__(parent)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.SubWindow)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFixedWidth(340)

        self._action_url = action_url
        self._duration = duration_ms

        # Styling
        self.setStyleSheet("""
            ToastNotification {
                background-color: #1e1e2e;
                border: 2px solid #5b6abf;
                border-radius: 10px;
            }
            QLabel#toast_title {
                color: #e0e0ff;
                font-size: 13px;
                font-weight: bold;
            }
            QLabel#toast_message {
                color: #b0b0cc;
                font-size: 11px;
            }
            QPushButton#toast_action {
                background-color: #5b6abf;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 6px 16px;
                font-size: 12px;
                font-weight: bold;
            }
            QPushButton#toast_action:hover {
                background-color: #6b7acf;
            }
            QPushButton#toast_dismiss {
                background: transparent;
                color: #888;
                border: none;
                font-size: 16px;
                padding: 2px 6px;
            }
            QPushButton#toast_dismiss:hover {
                color: #ccc;
            }
        """)

        # Layout
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(14, 12, 10, 12)
        main_layout.setSpacing(10)

        # Text column
        text_layout = QVBoxLayout()
        text_layout.setSpacing(2)

        title_label = QLabel(title)
        title_label.setObjectName("toast_title")
        text_layout.addWidget(title_label)

        msg_label = QLabel(message)
        msg_label.setObjectName("toast_message")
        msg_label.setWordWrap(True)
        text_layout.addWidget(msg_label)

        if action_text and action_url:
            action_btn = QPushButton(action_text)
            action_btn.setObjectName("toast_action")
            action_btn.setCursor(QCursor(Qt.PointingHandCursor))
            action_btn.clicked.connect(self._on_action)
            text_layout.addWidget(action_btn, alignment=Qt.AlignLeft)

        main_layout.addLayout(text_layout, 1)

        # Dismiss button
        dismiss_btn = QPushButton("\u2715")  # ✕
        dismiss_btn.setObjectName("toast_dismiss")
        dismiss_btn.setFixedSize(20, 20)
        dismiss_btn.clicked.connect(self._dismiss)
        main_layout.addWidget(dismiss_btn, alignment=Qt.AlignTop)

        # Opacity effect for fade-out
        self._opacity = QGraphicsOpacityEffect(self)
        self._opacity.setOpacity(1.0)
        self.setGraphicsEffect(self._opacity)

        # Auto-dismiss timer
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(self._duration)
        self._timer.timeout.connect(self._fade_out)

    def show_toast(self):
        """Position and show the toast in the parent's top-right corner."""
        parent = self.parentWidget()
        if parent:
            self.adjustSize()
            x = parent.width() - self.width() - 16
            y = 50  # Below menu bar
            self.move(x, y)
        self.show()
        self.raise_()
        self._timer.start()

    def _on_action(self):
        """Open the action URL in an external browser."""
        if self._action_url:
            from PySide6.QtCore import QUrl

            QDesktopServices.openUrl(QUrl(self._action_url))
        self._dismiss()

    def _fade_out(self):
        """Animate fade-out then hide."""
        self._anim = QPropertyAnimation(self._opacity, b"opacity")
        self._anim.setDuration(500)
        self._anim.setStartValue(1.0)
        self._anim.setEndValue(0.0)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._anim.finished.connect(self._dismiss)
        self._anim.start()

    def _dismiss(self):
        """Hide and clean up."""
        self._timer.stop()
        self.hide()
        self.deleteLater()
