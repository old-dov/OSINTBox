#!/usr/bin/env python3
"""OSINTBox — GUI desktop PySide6, meme convention de lancement que PenBox (voir
../[Scripts (cybersec)]/penbox_app.py).

Usage:
    .venv\\Scripts\\python.exe osintbox_app.py
"""

import sys
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from osintbox.ui.main_window import MainWindow


def resource_path(relative: str) -> Path:
    """Resout un fichier ressource bundle (icone...), en script comme en exe PyInstaller
    --onefile (extrait dans sys._MEIPASS a l'execution) -- meme pattern que scan_system."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base / relative


ICON_PATH = resource_path("pictures/osint_box.ico")


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("OSINTBox")
    app.setOrganizationName("OSINTBox")
    if ICON_PATH.exists():
        app.setWindowIcon(QIcon(str(ICON_PATH)))

    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
