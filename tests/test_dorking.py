from osintbox.dorking import run_dorking
from osintbox.dorks import DORK_TEMPLATES
from osintbox.search_providers import SearchProviderError, SearchRateLimited, SearchResult


def test_findings_built_from_every_dork(monkeypatch):
    sleeps = []

    def fake_search(query, api_key, cx):
        return [SearchResult(title="T", url=f"https://x/{query}", snippet="s")]

    findings, errors = run_dorking(
        "example.com", "key", "cx", search_fn=fake_search, sleep_fn=sleeps.append,
    )
    assert len(findings) == len(DORK_TEMPLATES)
    assert errors == []
    assert all(f.source == "dorking" and f.category == "dorking" for f in findings)
    # un sleep entre chaque paire de dorks consecutifs, pas avant le premier
    assert len(sleeps) == len(DORK_TEMPLATES) - 1


def test_rate_limit_stops_early_and_keeps_prior_findings():
    calls = []

    def fake_search(query, api_key, cx):
        calls.append(query)
        if len(calls) == 2:
            raise SearchRateLimited("quota depasse")
        return [SearchResult(title="T", url="https://x", snippet="s")]

    findings, errors = run_dorking(
        "example.com", "key", "cx", search_fn=fake_search, sleep_fn=lambda s: None,
    )
    assert len(calls) == 2  # s'arrete au rate-limit, ne tente pas les dorks suivants
    assert len(findings) == 1  # le premier dork a reussi avant le rate-limit
    assert len(errors) == 1


def test_provider_error_on_one_dork_does_not_stop_the_others():
    calls = []

    def fake_search(query, api_key, cx):
        calls.append(query)
        if len(calls) == 1:
            raise SearchProviderError("boom")
        return [SearchResult(title="T", url="https://x", snippet="s")]

    findings, errors = run_dorking(
        "example.com", "key", "cx", search_fn=fake_search, sleep_fn=lambda s: None,
    )
    assert len(calls) == len(DORK_TEMPLATES)
    assert len(errors) == 1
    assert len(findings) == len(DORK_TEMPLATES) - 1


def test_no_results_no_error():
    findings, errors = run_dorking(
        "example.com", "key", "cx", search_fn=lambda q, k, c: [], sleep_fn=lambda s: None,
    )
    assert findings == []
    assert errors == []


def test_should_cancel_stops_before_next_dork():
    calls = []

    def fake_search(query, api_key, cx):
        calls.append(query)
        return [SearchResult(title="T", url="https://x", snippet="s")]

    findings, errors = run_dorking(
        "example.com", "key", "cx", search_fn=fake_search, sleep_fn=lambda s: None,
        should_cancel=lambda: True,
    )
    assert calls == []
    assert findings == []
    assert errors == []


def test_should_cancel_checked_after_first_dork_stops_the_rest():
    calls = []

    def fake_search(query, api_key, cx):
        calls.append(query)
        return [SearchResult(title="T", url="https://x", snippet="s")]

    findings, errors = run_dorking(
        "example.com", "key", "cx", search_fn=fake_search, sleep_fn=lambda s: None,
        should_cancel=lambda: len(calls) >= 1,
    )
    assert len(calls) == 1
    assert len(findings) == 1
