from osintbox.runner import looks_rate_limited


def test_detects_marker_from_real_maigret_output():
    # Message reellement observe en testant Maigret contre une vraie cible (pas invente).
    stdout = '[!] Too many errors of type "Bot protection" (7.14%). Try to switch to another ip address'
    assert looks_rate_limited(stdout, "")


def test_detects_access_denied_marker():
    stdout = '[!] Too many errors of type "Access denied" (3.57%).'
    assert looks_rate_limited(stdout, "")


def test_detects_generic_429():
    assert looks_rate_limited("", "HTTP 429 received from server")


def test_detects_marker_in_stderr_too():
    assert looks_rate_limited("", "Error: rate limit exceeded")


def test_case_insensitive():
    assert looks_rate_limited("BANNED from this site", "")


def test_clean_output_not_flagged():
    stdout = "[+] GitHub: https://github.com/torvalds\n[+] Reddit: https://reddit.com/user/torvalds"
    assert not looks_rate_limited(stdout, "")


def test_empty_output_not_flagged():
    assert not looks_rate_limited("", "")


def test_holehe_legend_line_not_flagged_as_rate_limit():
    # Faux positif reel rencontre en integrant holehe (Phase 5) : cette ligne de legende est
    # toujours presente dans sa sortie, meme sans aucun blocage reel.
    stdout = "[+] Email used, [-] Email not used, [x] Rate limit"
    assert not looks_rate_limited(stdout, "")


def test_rate_limited_past_tense_still_flagged():
    assert looks_rate_limited("", "You have been rate limited, try again later")
