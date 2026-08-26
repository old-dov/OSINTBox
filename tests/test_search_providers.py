import pytest

from osintbox.search_providers import (
    SearchProviderError,
    SearchRateLimited,
    google_cse_search,
)


class _FakeResponse:
    def __init__(self, status_code, json_data=None, text=""):
        self.status_code = status_code
        self._json_data = json_data or {}
        self.text = text

    def json(self):
        return self._json_data


def test_parses_items_into_search_results():
    def fake_get(url, params, timeout):
        return _FakeResponse(200, {"items": [
            {"title": "Foo", "link": "https://foo.example.com", "snippet": "a foo page"},
            {"title": "Bar", "link": "https://bar.example.com", "snippet": "a bar page"},
        ]})

    results = google_cse_search("site:example.com", "key", "cx", request_fn=fake_get)
    assert len(results) == 2
    assert results[0].url == "https://foo.example.com"
    assert results[0].title == "Foo"
    assert results[1].snippet == "a bar page"


def test_no_items_returns_empty_list():
    results = google_cse_search("q", "key", "cx", request_fn=lambda url, **kw: _FakeResponse(200, {}))
    assert results == []


def test_429_raises_rate_limited():
    with pytest.raises(SearchRateLimited):
        google_cse_search("q", "key", "cx", request_fn=lambda url, **kw: _FakeResponse(429))


def test_other_error_status_raises_provider_error():
    with pytest.raises(SearchProviderError):
        google_cse_search("q", "key", "cx", request_fn=lambda url, **kw: _FakeResponse(403, text="Forbidden"))


def test_num_is_capped_at_ten():
    captured = {}

    def fake_get(url, params, timeout):
        captured.update(params)
        return _FakeResponse(200, {"items": []})

    google_cse_search("q", "key", "cx", num=50, request_fn=fake_get)
    assert captured["num"] == 10
