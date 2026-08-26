import pytest

from osintbox.config import ConfigError, get_google_cse_credentials, load_config


def test_load_config_missing_file_raises_clear_error(tmp_path):
    missing = tmp_path / "does_not_exist.yaml"
    with pytest.raises(ConfigError, match="osintbox.local.yaml.example"):
        load_config(missing)


def test_load_config_reads_yaml(tmp_path):
    path = tmp_path / "osintbox.local.yaml"
    path.write_text("google_cse:\n  api_key: k\n  cx: c\n", encoding="utf-8")
    config = load_config(path)
    assert config == {"google_cse": {"api_key": "k", "cx": "c"}}


def test_load_config_empty_file_returns_empty_dict(tmp_path):
    path = tmp_path / "osintbox.local.yaml"
    path.write_text("", encoding="utf-8")
    assert load_config(path) == {}


def test_get_google_cse_credentials_ok():
    assert get_google_cse_credentials({"google_cse": {"api_key": "k", "cx": "c"}}) == ("k", "c")


def test_get_google_cse_credentials_missing_section_raises():
    with pytest.raises(ConfigError):
        get_google_cse_credentials({})


def test_get_google_cse_credentials_partial_raises():
    with pytest.raises(ConfigError):
        get_google_cse_credentials({"google_cse": {"api_key": "k"}})
