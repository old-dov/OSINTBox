"""Desktop colors that follow the operating system's light or dark appearance."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QApplication, QWidget


LIGHT_STYLESHEET = """
QMainWindow, QWidget { background: #fafaf9; color: #101010; font-family: 'Segoe UI'; font-size: 13px; }
QFrame#brandHeader { background: #ffffff; border-bottom: 8px solid #303030; }
QLabel#brandTitle { font-size: 30px; font-weight: 700; color: #101010; }
QLabel#brandSubtitle { color: #575757; font-size: 12px; }
QLineEdit, QComboBox, QListWidget, QTableWidget {
    background: #ffffff; color: #101010; border: 1px solid #dedfdf;
    border-radius: 2px; padding: 7px; selection-background-color: #303030;
    selection-color: #ffffff;
}
QLineEdit:focus, QComboBox:focus, QListWidget:focus, QTableWidget:focus { border: 2px solid #303030; }
QComboBox QAbstractItemView { background: #ffffff; color: #101010; selection-background-color: #303030; selection-color: #ffffff; }
QPushButton {
    background: #303030; color: #ffffff; border: 1px solid #303030;
    border-radius: 2px; padding: 9px 16px; font-weight: 600;
}
QPushButton:hover { background: #101010; border-color: #101010; }
QPushButton:disabled { background: #ebebea; border-color: #dedfdf; color: #777777; }
QCheckBox { spacing: 7px; }
QCheckBox::indicator { width: 15px; height: 15px; }
QHeaderView::section { background: #f4f4f3; color: #303030; border: 0;
    border-right: 1px solid #dedfdf; border-bottom: 1px solid #dedfdf;
    padding: 8px; font-weight: 600; }
QTableWidget::item { padding: 4px; }
QScrollBar:vertical { background: #f4f4f3; width: 11px; }
QScrollBar::handle:vertical { background: #b7b7b7; min-height: 28px; }
QToolTip { background: #ffffff; color: #101010; border: 1px solid #dedfdf; }
"""

DARK_STYLESHEET = """
QMainWindow, QWidget { background: #171b20; color: #edf0f3; font-family: 'Segoe UI'; font-size: 13px; }
QFrame#brandHeader { background: #222830; border-bottom: 8px solid #52606e; }
QLabel#brandTitle { font-size: 30px; font-weight: 700; color: #f5f7f9; }
QLabel#brandSubtitle { color: #b4bec8; font-size: 12px; }
QLineEdit, QComboBox, QListWidget, QTableWidget {
    background: #232a32; color: #f0f3f6; border: 1px solid #4a5561;
    border-radius: 2px; padding: 7px; selection-background-color: #769cbd;
    selection-color: #10161c;
}
QLineEdit:focus, QComboBox:focus, QListWidget:focus, QTableWidget:focus { border: 2px solid #8db3d3; }
QComboBox QAbstractItemView { background: #232a32; color: #f0f3f6; selection-background-color: #769cbd; selection-color: #10161c; }
QPushButton {
    background: #46596b; color: #ffffff; border: 1px solid #62788c;
    border-radius: 2px; padding: 9px 16px; font-weight: 600;
}
QPushButton:hover { background: #587087; border-color: #88a3bc; }
QPushButton:disabled { background: #303740; border-color: #424b55; color: #a0aab4; }
QCheckBox { spacing: 7px; }
QCheckBox::indicator { width: 15px; height: 15px; background: #232a32; border: 1px solid #9cabb9; }
QCheckBox::indicator:checked { background: #8db3d3; border-color: #b8d4e9; }
QHeaderView::section { background: #2a323b; color: #e4e9ee; border: 0;
    border-right: 1px solid #49535e; border-bottom: 1px solid #49535e;
    padding: 8px; font-weight: 600; }
QTableWidget::item { padding: 4px; }
QScrollBar:vertical { background: #272e36; width: 11px; }
QScrollBar::handle:vertical { background: #667584; min-height: 28px; }
QToolTip { background: #2a323b; color: #f0f3f6; border: 1px solid #667584; }
"""


def apply_system_theme(app: QApplication, scheme: Qt.ColorScheme) -> None:
    """Apply explicit colors; Qt's default palette still follows the system."""
    dark = scheme == Qt.ColorScheme.Dark
    app.setProperty("osintbox_dark_theme", dark)
    app.setStyleSheet(DARK_STYLESHEET if dark else LIGHT_STYLESHEET)
    for widget in app.allWidgets():
        if isinstance(widget, GeometryMark):
            widget.set_dark(dark)


def install_system_theme(app: QApplication) -> None:
    hints = app.styleHints()
    apply_system_theme(app, hints.colorScheme())
    hints.colorSchemeChanged.connect(lambda scheme: apply_system_theme(app, scheme))


class GeometryMark(QWidget):
    """Thin intersecting lines from the card's abstract corner motif."""

    def __init__(self) -> None:
        super().__init__()
        self.setFixedSize(84, 62)
        self.setAttribute(Qt.WA_TranslucentBackground)
        app = QApplication.instance()
        self._dark = bool(app and app.property("osintbox_dark_theme"))

    def set_dark(self, dark: bool) -> None:
        self._dark = dark
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt API
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QPen(QColor("#657483" if self._dark else "#e3e4e4"), 1))
        painter.drawLine(0, 0, 62, 62)
        painter.drawLine(28, 0, 84, 56)
        painter.drawLine(0, 42, 20, 62)
        painter.drawLine(84, 0, 22, 62)
        painter.drawLine(84, 36, 58, 62)
        painter.end()
