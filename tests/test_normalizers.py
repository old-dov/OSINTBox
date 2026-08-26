from osintbox.normalizers import Finding, group_by_category, normalize


def test_sherlock_parses_found_lines():
    stdout = (
        "[*] Checking username torvalds on:\n"
        "[+] GitHub: https://www.github.com/torvalds\n"
        "[+] Reddit: https://www.reddit.com/user/torvalds\n"
    )
    findings = normalize("sherlock", stdout, "torvalds")
    assert len(findings) == 2
    assert findings[0].source == "sherlock"
    assert findings[0].category == "username"
    assert findings[0].type == "social_profile"
    assert findings[0].value == "https://www.github.com/torvalds"
    assert findings[0].confidence == "high"
    assert findings[0].raw == {"site": "GitHub", "username": "torvalds"}


def test_sherlock_ignores_non_result_lines():
    stdout = "[*] Checking username x on:\n[-] SomeSite: Not Found!\n"
    findings = normalize("sherlock", stdout, "x")
    assert findings == []


def test_sherlock_empty_stdout():
    assert normalize("sherlock", "", "x") == []


def test_generic_fallback_one_finding_per_nonblank_line():
    stdout = "line one\n\nline two\n"
    findings = normalize("unknown_tool", stdout, "x")
    assert len(findings) == 2
    assert findings[0].source == "unknown_tool"
    assert findings[0].confidence == "low"
    assert findings[0].value == "line one"
    assert findings[1].value == "line two"


def test_generic_fallback_wraps_unstructured_json():
    raw = {"weird": "shape", "not": ["a", "known", "schema"]}
    findings = normalize("unknown_tool", raw, "x")
    assert len(findings) == 1
    assert findings[0].confidence == "low"
    assert findings[0].raw == raw


# ── maigret ──────────────────────────────────────────────────────────────────

_MAIGRET_SAMPLE = {
    "GitHub": {
        "status": {
            "status": "Claimed",
            "url": "https://github.com/torvalds",
            "ids": {"fullname": "Linus Torvalds", "follower_count": "318006"},
        },
        "url_user": "https://github.com/torvalds",
    },
    "WordPress": {
        "status": {"status": "Available", "url": "https://torvalds.wordpress.com/", "ids": {}},
        "url_user": "https://torvalds.wordpress.com/",
    },
}


def test_maigret_keeps_only_claimed_entries():
    findings = normalize("maigret", _MAIGRET_SAMPLE, "torvalds")
    assert len(findings) == 1
    assert findings[0].source == "maigret"
    assert findings[0].category == "username"
    assert findings[0].type == "social_profile"
    assert findings[0].value == "https://github.com/torvalds"
    assert findings[0].confidence == "high"
    assert findings[0].raw["site"] == "GitHub"
    assert findings[0].raw["extracted"]["fullname"] == "Linus Torvalds"


def test_maigret_empty_report():
    assert normalize("maigret", {}, "x") == []


def test_maigret_non_dict_input_returns_empty():
    assert normalize("maigret", ["not", "a", "dict"], "x") == []


# ── holehe ───────────────────────────────────────────────────────────────────

# Sortie stdout reellement observee en lancant `holehe test@gmail.com --only-used --no-clear`
# (pas inventee) : banniere donation/GitHub avant ET apres les resultats, ligne de legende qui
# commence aussi par "[+] " -- c'est exactement le piege que la regex doit eviter.
_HOLEHE_SAMPLE_STDOUT = (
    "Twitter : @palenath\n"
    "Github : https://github.com/megadose/holehe\n"
    "For BTC Donations : 1FHDM49QfZX6pJmhjLE5tB2K6CaTLMZpXZ\n"
    "\n\n********************\n"
    "   test@gmail.com\n"
    "********************\n"
    "[+] any.do\n"
    "[+] devrant.com\n"
    "[+] firefox.com\n"
    "\n"
    "[+] Email used, [-] Email not used, [x] Rate limit\n"
    "121 websites checked in 5.96 seconds\n"
    "Twitter : @palenath\n"
    "Github : https://github.com/megadose/holehe\n"
    "For BTC Donations : 1FHDM49QfZX6pJmhjLE5tB2K6CaTLMZpXZ\n"
)


def test_holehe_parses_used_sites_only():
    findings = normalize("holehe", _HOLEHE_SAMPLE_STDOUT, "test@gmail.com")
    assert [f.value for f in findings] == ["any.do", "devrant.com", "firefox.com"]
    assert all(f.source == "holehe" and f.category == "email" and f.type == "account_exists" for f in findings)
    assert all(f.confidence == "high" for f in findings)


def test_holehe_ignores_legend_line_despite_leading_plus_bracket():
    findings = normalize("holehe", _HOLEHE_SAMPLE_STDOUT, "test@gmail.com")
    assert "Email used, [-] Email not used, [x] Rate limit" not in [f.value for f in findings]


def test_holehe_empty_stdout():
    assert normalize("holehe", "", "x@example.com") == []


# ── theharvester ─────────────────────────────────────────────────────────────

# Structure reellement observee en lancant `theHarvester -d python.org -b crtsh -f <path>` :
# la cle "emails" est absente quand crt.sh n'en trouve pas (pas une liste vide) -- pas invente.
_THEHARVESTER_SAMPLE = {
    "cmd": "-d python.org -b crtsh -f report",
    "hosts": ["blog.python.org", "wiki.python.org"],
    "shodan": [],
}


def test_theharvester_parses_hosts_as_domain_findings():
    findings = normalize("theharvester", _THEHARVESTER_SAMPLE, "python.org")
    assert [f.value for f in findings] == ["blog.python.org", "wiki.python.org"]
    assert all(f.source == "theharvester" and f.category == "domain" and f.type == "subdomain" for f in findings)


def test_theharvester_parses_emails_when_present():
    raw = {"hosts": [], "emails": ["contact@python.org"]}
    findings = normalize("theharvester", raw, "python.org")
    assert len(findings) == 1
    assert findings[0].category == "email"
    assert findings[0].type == "email_address"
    assert findings[0].value == "contact@python.org"


def test_theharvester_parses_ips_when_present():
    raw = {"hosts": [], "ips": ["1.2.3.4"]}
    findings = normalize("theharvester", raw, "python.org")
    assert len(findings) == 1
    assert findings[0].category == "domain"
    assert findings[0].type == "ip"
    assert findings[0].confidence == "medium"


def test_theharvester_missing_keys_return_empty():
    assert normalize("theharvester", {"cmd": "..."}, "python.org") == []


def test_theharvester_non_dict_input_returns_empty():
    assert normalize("theharvester", ["not", "a", "dict"], "python.org") == []


# ── group_by_category ───────────────────────────────────────────────────────


def test_group_by_category_groups_across_sources():
    findings = [
        Finding(source="sherlock", category="username", type="social_profile", value="a"),
        Finding(source="maigret", category="username", type="social_profile", value="b"),
        Finding(source="holehe", category="email", type="account", value="c"),
    ]
    grouped = group_by_category(findings)
    assert list(grouped.keys()) == ["username", "email"]
    assert [f.value for f in grouped["username"]] == ["a", "b"]
    assert [f.value for f in grouped["email"]] == ["c"]


def test_group_by_category_empty_input():
    assert group_by_category([]) == {}
