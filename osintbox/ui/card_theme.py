"""A light geometric visual theme shared by the OSINTBox desktop window."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget


APP_STYLESHEET = """
QMainWindow, QWidget { background: #fafaf9; color: #101010; font-family: 'Segoe UI'; font-size: 13px; }
QFrame#brandHeader { background: #ffffff; border-bottom: 8px solid #303030; }
QLabel#brandTitle { font-size: 30px; font-weight: 700; color: #101010; }
QLabel#brandSubtitle { color: #575757; font-size: 12px; }
QLineEdit, QListWidget, QTableWidget {
    background: #ffffff; color: #101010; border: 1px solid #dedfdf;
    border-radius: 2px; padding: 7px; selection-background-color: #303030;
    selection-color: #ffffff;
}
QLineEdit:focus, QListWidget:focus, QTableWidget:focus { border: 2px solid #303030; }
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
"""


class GeometryMark(QWidget):
    """Thin intersecting lines from the card's abstract corner motif."""

    def __init__(self) -> None:
        super().__init__()
        self.setFixedSize(84, 62)
        self.setAttribute(Qt.WA_TranslucentBackground)

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt API
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QPen(QColor("#e3e4e4"), 1))
        painter.drawLine(0, 0, 62, 62)
        painter.drawLine(28, 0, 84, 56)
        painter.drawLine(0, 42, 20, 62)
        painter.drawLine(84, 0, 22, 62)
        painter.drawLine(84, 36, 58, 62)
        painter.end()
