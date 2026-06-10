import time

from keystone_mcp.cache import TTLCache, make_key, parse_ttl


def test_get_returns_value_before_expiry():
    cache = TTLCache()
    cache.put("k", "v", ttl_seconds=10)
    assert cache.get("k") == "v"


def test_get_returns_none_after_expiry(monkeypatch):
    cache = TTLCache()
    now = [1000.0]
    monkeypatch.setattr(time, "monotonic", lambda: now[0])
    cache.put("k", "v", ttl_seconds=5)
    now[0] += 6
    assert cache.get("k") is None


def test_distinct_queries_distinct_keys():
    a = make_key("s", {"q": 1})
    b = make_key("s", {"q": 2})
    assert a != b


def test_same_query_stable_key():
    a = make_key("s", {"q": 1, "r": 2})
    b = make_key("s", {"r": 2, "q": 1})
    assert a == b


def test_parse_ttl_units():
    assert parse_ttl("5s") == 5
    assert parse_ttl("5m") == 300
    assert parse_ttl("2h") == 7200
    assert parse_ttl(None) is None
    assert parse_ttl("30") == 30
