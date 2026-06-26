"""Offline tests for the retry/backoff and request-shaping logic.

A fake requests session is injected, so these run without network or
credentials. They lock in the safety-critical behaviour: idempotent methods are
retried on 5xx / network errors, but a non-idempotent create POST is not.
"""
import json

import pytest
import requests

import contentstack_client as cc
from contentstack_client import ContentstackClient, ContentstackError


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    # Don't actually sleep during backoff.
    monkeypatch.setattr(cc.time, "sleep", lambda *a, **k: None)


def make_client():
    return ContentstackClient(
        "key", "mtoken", "dtoken",
        "https://cdn.example", "https://api.example",
        "production", "en-us", max_retries=3,
    )


class Resp:
    def __init__(self, status, body=b"{}", headers=None, json_data=None):
        self.status_code = status
        self.content = body
        self.headers = headers or {}
        self.text = body.decode() if isinstance(body, bytes) else str(body)
        self._json = json_data

    @property
    def ok(self):
        return self.status_code < 400

    def json(self):
        return self._json if self._json is not None else json.loads(self.content)


class FakeSession:
    """Returns (or raises) the next scripted item per request() call."""

    def __init__(self, script):
        self.script = list(script)
        self.calls = []

    def request(self, method, url, headers=None, params=None, json=None, timeout=None):
        self.calls.append(method.upper())
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


ENTRY_OK = Resp(200, json_data={"entry": {"uid": "x"}})


def test_get_retries_on_5xx_then_succeeds():
    c = make_client()
    c.session = FakeSession([Resp(500, b"err"), ENTRY_OK])
    assert c.get_entry("ct", "x") == {"uid": "x"}
    assert c.session.calls == ["GET", "GET"]


def test_create_post_is_not_retried_on_5xx():
    c = make_client()
    c.session = FakeSession([Resp(500, b"boom")])
    with pytest.raises(ContentstackError):
        c.create_entry("ct", {"a": 1})
    assert c.session.calls == ["POST"]  # no retry


def test_create_post_is_retried_on_429():
    c = make_client()
    c.session = FakeSession([
        Resp(429, b"slow", headers={"Retry-After": "0"}),
        Resp(201, json_data={"entry": {"uid": "n"}}),
    ])
    assert c.create_entry("ct", {"a": 1}) == {"uid": "n"}
    assert c.session.calls == ["POST", "POST"]


def test_get_retries_on_network_error():
    c = make_client()
    c.session = FakeSession([requests.exceptions.ConnectionError("reset"), ENTRY_OK])
    assert c.get_entry("ct", "x") == {"uid": "x"}
    assert c.session.calls == ["GET", "GET"]


def test_create_post_network_error_raises_without_retry():
    c = make_client()
    c.session = FakeSession([requests.exceptions.Timeout("t")])
    with pytest.raises(ContentstackError):
        c.create_entry("ct", {"a": 1})
    assert c.session.calls == ["POST"]


def test_retry_delay_clamps_negative_retry_after():
    assert ContentstackClient._retry_delay(Resp(429, headers={"Retry-After": "-5"}), 1) == 0.0


def test_retry_delay_caps_large_retry_after():
    assert ContentstackClient._retry_delay(Resp(429, headers={"Retry-After": "120"}), 1) == 60.0


def test_retry_delay_http_date_falls_back_to_backoff():
    r = Resp(429, headers={"Retry-After": "Mon, 01 Jan 2099 00:00:00 GMT"})
    assert ContentstackClient._retry_delay(r, 1) == 1.0  # 2 ** 0


def test_retry_delay_network_path_uses_exponential_backoff():
    assert ContentstackClient._retry_delay(None, 3) == 4.0  # 2 ** 2


def test_find_entry_by_url_returns_entry_and_total_count():
    c = make_client()
    c.session = FakeSession([Resp(200, json_data={"entries": [{"uid": "e1"}], "count": 3})])
    entry, count = c.find_entry_by_url("ct", "/x")
    assert entry == {"uid": "e1"}
    assert count == 3
