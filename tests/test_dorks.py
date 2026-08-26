from osintbox.dorks import DORK_TEMPLATES, build_dorks


def test_build_dorks_substitutes_target_in_every_template():
    dorks = build_dorks("example.com")
    assert len(dorks) == len(DORK_TEMPLATES)
    for label, query in dorks:
        assert "example.com" in query
        assert "{target}" not in query


def test_build_dorks_labels_are_unique():
    labels = [label for label, _ in build_dorks("example.com")]
    assert len(labels) == len(set(labels))
