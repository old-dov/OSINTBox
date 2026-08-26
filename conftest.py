import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="session")
def qapp():
    """QApplication partagee pour les tests UI -- une seule instance par processus Qt
    (creer QApplication deux fois plante). offscreen (ci-dessus) evite qu'une vraie fenetre
    tente de s'afficher pendant `pytest`."""
    app = QApplication.instance() or QApplication([])
    yield app
