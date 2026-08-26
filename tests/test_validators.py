from osintbox.validators import validate_target, validate_territory


def test_username_valid():
    assert validate_target("torvalds", "username") == (True, "")


def test_username_rejects_special_chars():
    ok, _ = validate_target("torv alds!", "username")
    assert not ok


def test_email_valid():
    assert validate_target("user@example.com", "email") == (True, "")


def test_email_invalid():
    ok, _ = validate_target("not-an-email", "email")
    assert not ok


def test_domain_valid():
    assert validate_target("example.com", "domain") == (True, "")


def test_domain_rejects_bare_hostname():
    ok, _ = validate_target("localhost", "domain")
    assert not ok


def test_host_accepts_ip_or_hostname():
    assert validate_target("192.168.1.1", "host") == (True, "")
    assert validate_target("myhost", "host") == (True, "")


def test_ip_valid_and_invalid():
    assert validate_target("8.8.8.8", "ip") == (True, "")
    ok, _ = validate_target("999.999.999.999", "ip")
    assert not ok


def test_url_valid_and_invalid():
    assert validate_target("https://example.com/path", "url") == (True, "")
    ok, _ = validate_target("ftp://example.com", "url")
    assert not ok


def test_rejects_empty_value():
    ok, msg = validate_target("", "username")
    assert not ok and msg


def test_rejects_value_starting_with_dash():
    # Empecher qu'une valeur ressemblant a une option (--flag) se glisse dans l'argv du
    # sous-processus -- meme protection que PenBox.
    ok, msg = validate_target("--evil-flag", "username")
    assert not ok
    assert "commencer par" in msg


def test_unknown_target_type():
    ok, msg = validate_target("whatever", "not_a_type")
    assert not ok
    assert "inconnu" in msg


# ── validate_territory ───────────────────────────────────────────────────────


def test_territory_valid_code():
    assert validate_territory("fr") == (True, "")


def test_territory_case_insensitive():
    assert validate_territory("FR") == (True, "")


def test_territory_rejects_unknown_code():
    ok, msg = validate_territory("zz")
    assert not ok
    assert "inconnu" in msg


def test_territory_rejects_empty():
    ok, msg = validate_territory("")
    assert not ok and msg


def test_territory_rejects_value_starting_with_dash():
    ok, msg = validate_territory("--evil-flag")
    assert not ok
    assert "commencer par" in msg
