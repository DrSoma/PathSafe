"""Custom widgets for the PathSafe GUI."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import (
    QFont, QColor, QPainter, QPen, QBrush,
    QDragEnterEvent, QDropEvent,
)
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QLabel, QFrame,
)

from pathsafe.gui.themes import THEME_COLORS


class DropZoneWidget(QWidget):
    """Drag-and-drop zone for files and folders."""

    pathDropped = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setFixedHeight(36)

        layout = QHBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)
        layout.setContentsMargins(4, 2, 4, 2)

        self._icon_label = QLabel("Drag files or folders here")
        self._icon_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._icon_label)

        self._hint_label = QLabel("or use Step 1 to browse")
        self._hint_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._hint_label)

        self._theme = 'dark'
        self._apply_theme_colors()

    def set_theme(self, theme):
        self._theme = theme
        self._apply_theme_colors()

    def _apply_theme_colors(self):
        c = THEME_COLORS[self._theme]
        self._icon_label.setStyleSheet(
            f"QLabel {{ color: {c['drop_text']}; font-size: 14px; "
            f"font-weight: bold; }}")
        self._hint_label.setStyleSheet(
            f"QLabel {{ color: {c['drop_hint']}; font-size: 11px; }}")
        self._default_ss = (
            f"DropZoneWidget {{ border: 2px dashed {c['drop_border']}; "
            f"border-radius: 10px; background-color: {c['drop_bg']}; }}")
        self._hover_ss = (
            f"DropZoneWidget {{ border: 2px dashed {c['drop_hover_border']}; "
            f"border-radius: 10px; background-color: {c['drop_hover_bg']}; }}")
        self.setStyleSheet(self._default_ss)

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self.setStyleSheet(self._hover_ss)
            self._icon_label.setText("Drop to select")

    def dragLeaveEvent(self, event):
        self.setStyleSheet(self._default_ss)
        self._icon_label.setText("Drag files or folders here")

    def dropEvent(self, event: QDropEvent):
        self.setStyleSheet(self._default_ss)
        self._icon_label.setText("Drag files or folders here")
        urls = event.mimeData().urls()
        if urls:
            self.pathDropped.emit(urls[0].toLocalFile())


class StepIndicator(QFrame):
    """Visual workflow indicator: Select Files -> Scan -> Anonymize -> Verify."""

    STEPS = ['Select Files', 'Scan', 'Anonymize', 'Verify']

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(56)
        self._current = 0
        self._completed = set()
        self._theme = 'dark'

    def set_theme(self, theme):
        self._theme = theme
        self.update()

    def set_step(self, index):
        self._current = index
        self.update()

    def mark_completed(self, index):
        self._completed.add(index)
        self.update()

    def reset(self):
        self._current = 0
        self._completed.clear()
        self.update()

    def paintEvent(self, event):
        c = THEME_COLORS[self._theme]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        w = self.width()
        h = self.height()
        n = len(self.STEPS)
        spacing = w / n
        r = 13

        for i, label in enumerate(self.STEPS):
            cx = int(spacing * i + spacing / 2)
            cy = int(h / 2 - 6)

            # Connecting line
            if i > 0:
                prev_cx = int(spacing * (i - 1) + spacing / 2)
                color = QColor(c['completed']) if (i - 1) in self._completed else QColor(c['inactive_border'])
                painter.setPen(QPen(color, 2))
                painter.drawLine(prev_cx + r, cy, cx - r, cy)

            # Circle
            if i in self._completed:
                painter.setBrush(QBrush(QColor(c['completed'])))
                painter.setPen(QPen(QColor(c['completed']), 2))
            elif i == self._current:
                painter.setBrush(QBrush(QColor(c['active'])))
                painter.setPen(QPen(QColor(c['active']), 2))
            else:
                painter.setBrush(QBrush(QColor(c['inactive_fill'])))
                painter.setPen(QPen(QColor(c['inactive_border']), 2))

            painter.drawEllipse(cx - r, cy - r, r * 2, r * 2)

            # Number or check
            is_active = i in self._completed or i == self._current
            painter.setPen(QPen(QColor(c['circle_inner'] if is_active else c['text_dim'])))
            font = QFont('', 10)
            font.setBold(True)
            painter.setFont(font)
            text = 'OK' if i in self._completed else str(i + 1)
            tw = painter.fontMetrics().horizontalAdvance(text)
            painter.drawText(cx - tw // 2, cy + 5, text)

            # Label below
            painter.setPen(QPen(QColor(c['text_bright'] if i == self._current else c['text_dim'])))
            font = QFont('', 9)
            painter.setFont(font)
            tw = painter.fontMetrics().horizontalAdvance(label)
            painter.drawText(cx - tw // 2, cy + r + 15, label)

        painter.end()
