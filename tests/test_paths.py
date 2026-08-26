import sys

from osintbox.paths import user_data_dir


def test_dev_mode_uses_project_root(monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)
    base = user_data_dir()
    assert base.name == "OSINTBox"


def test_frozen_mode_uses_localappdata(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    base = user_data_dir()
    assert base == tmp_path / "OSINTBox"
    assert base.is_dir()  # cree si absent


def test_frozen_mode_falls_back_to_home_without_localappdata(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    base = user_data_dir()
    assert base.name == "OSINTBox"
