import pytest

from osintbox.catalog import CatalogError, ToolSpec, load_catalog


def _write_catalog(tmp_path, content: str):
    path = tmp_path / "catalog.yaml"
    path.write_text(content, encoding="utf-8")
    return path


def test_load_valid_catalog(tmp_path):
    path = _write_catalog(
        tmp_path,
        """
        - id: sherlock
          category: username
          desc: "test"
          command: ["sherlock", "--print-found", "{target}"]
          target_type: username
        """,
    )
    tools = load_catalog(path)
    assert set(tools) == {"sherlock"}
    assert tools["sherlock"].default_timeout_s == 60  # valeur par defaut


def test_missing_required_field(tmp_path):
    path = _write_catalog(
        tmp_path,
        """
        - id: broken
          category: username
          command: ["x", "{target}"]
          target_type: username
        """,
    )
    with pytest.raises(CatalogError, match="desc"):
        load_catalog(path)


def test_invalid_target_type(tmp_path):
    path = _write_catalog(
        tmp_path,
        """
        - id: broken
          category: username
          desc: "test"
          command: ["x", "{target}"]
          target_type: not_a_real_type
        """,
    )
    with pytest.raises(CatalogError, match="target_type"):
        load_catalog(path)


def test_command_missing_target_placeholder(tmp_path):
    path = _write_catalog(
        tmp_path,
        """
        - id: broken
          category: username
          desc: "test"
          command: ["x", "--no-placeholder"]
          target_type: username
        """,
    )
    with pytest.raises(CatalogError, match=r"\{target\}"):
        load_catalog(path)


def test_duplicate_id(tmp_path):
    path = _write_catalog(
        tmp_path,
        """
        - id: dup
          category: username
          desc: "a"
          command: ["x", "{target}"]
          target_type: username
        - id: dup
          category: username
          desc: "b"
          command: ["y", "{target}"]
          target_type: username
        """,
    )
    with pytest.raises(CatalogError, match="duplique"):
        load_catalog(path)


def test_not_a_list(tmp_path):
    path = _write_catalog(tmp_path, "id: not_a_list\n")
    with pytest.raises(CatalogError, match="liste"):
        load_catalog(path)


def test_build_argv_substitutes_target():
    spec = ToolSpec(
        id="t", category="c", desc="d",
        command=["tool", "--flag", "{target}", "--other"],
        target_type="username",
    )
    assert spec.build_argv("alice") == ["tool", "--flag", "alice", "--other"]


def test_with_territory_appends_flag_and_value():
    spec = ToolSpec(
        id="maigret", category="c", desc="d",
        command=["maigret", "{target}"], target_type="username",
        territory_flag="--tags",
    )
    new_spec = spec.with_territory("fr")
    assert new_spec.command == ["maigret", "{target}", "--tags", "fr"]
    assert new_spec.build_argv("alice") == ["maigret", "alice", "--tags", "fr"]
    # spec d'origine non mutee.
    assert spec.command == ["maigret", "{target}"]


def test_with_territory_ignored_when_tool_has_no_territory_flag():
    spec = ToolSpec(
        id="sherlock", category="c", desc="d",
        command=["sherlock", "{target}"], target_type="username",
    )
    assert spec.with_territory("fr") is spec


def test_with_territory_ignored_when_territory_is_none_or_empty():
    spec = ToolSpec(
        id="maigret", category="c", desc="d",
        command=["maigret", "{target}"], target_type="username",
        territory_flag="--tags",
    )
    assert spec.with_territory(None) is spec
    assert spec.with_territory("") is spec


def test_catalog_loads_territory_flag(tmp_path):
    path = _write_catalog(
        tmp_path,
        """
        - id: maigret
          category: username
          desc: "test"
          command: ["maigret", "{target}"]
          target_type: username
          territory_flag: "--tags"
        """,
    )
    tools = load_catalog(path)
    assert tools["maigret"].territory_flag == "--tags"


def test_resolve_executable_missing_returns_none():
    spec = ToolSpec(
        id="t", category="c", desc="d",
        command=["this-binary-does-not-exist-anywhere", "{target}"],
        target_type="username",
    )
    assert spec.resolve_executable() is None


def test_json_file_mode_requires_output_path_template(tmp_path):
    path = _write_catalog(
        tmp_path,
        """
        - id: broken
          category: username
          desc: "test"
          command: ["x", "{target}"]
          target_type: username
          output_mode: json_file
        """,
    )
    with pytest.raises(CatalogError, match="output_path_template"):
        load_catalog(path)


def test_json_file_mode_with_template_loads_ok(tmp_path):
    path = _write_catalog(
        tmp_path,
        """
        - id: ok
          category: username
          desc: "test"
          command: ["x", "{target}"]
          target_type: username
          output_mode: json_file
          output_path_template: "reports/report_{target}.json"
        """,
    )
    tools = load_catalog(path)
    assert tools["ok"].output_path_template == "reports/report_{target}.json"


def test_resolve_executable_falls_back_to_interpreter_scripts_dir(tmp_path, monkeypatch):
    # Reproduit le cas reel : un outil pip-installe dans le venv courant (ex. sherlock-project)
    # n'est pas sur le PATH du process si le venv n'a pas ete "active" au sens shell -- doit
    # quand meme etre trouve a cote de l'interpreteur qui execute OSINTBox.
    fake_interpreter = tmp_path / "python.exe"
    fake_interpreter.write_text("", encoding="utf-8")
    fake_tool = tmp_path / "mytool.exe"
    fake_tool.write_text("", encoding="utf-8")
    monkeypatch.setattr("osintbox.catalog.shutil.which", lambda name: None)
    monkeypatch.setattr("osintbox.catalog.sys.executable", str(fake_interpreter))

    spec = ToolSpec(id="t", category="c", desc="d", command=["mytool", "{target}"], target_type="username")
    assert spec.resolve_executable() == str(fake_tool)
