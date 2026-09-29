from PySide6.QtCore import Qt

from osintbox.ui.card_theme import GeometryMark, install_system_theme


def test_theme_follows_color_scheme_signal(qapp):
    previous_stylesheet = qapp.styleSheet()
    previous_property = qapp.property("osintbox_dark_theme")
    mark = GeometryMark()
    try:
        install_system_theme(qapp)
        qapp.styleHints().colorSchemeChanged.emit(Qt.ColorScheme.Dark)
        assert "background: #171b20" in qapp.styleSheet()
        assert mark._dark
        assert GeometryMark()._dark

        qapp.styleHints().colorSchemeChanged.emit(Qt.ColorScheme.Light)
        assert "background: #fafaf9" in qapp.styleSheet()
        assert not mark._dark
    finally:
        qapp.setStyleSheet(previous_stylesheet)
        qapp.setProperty("osintbox_dark_theme", previous_property)
