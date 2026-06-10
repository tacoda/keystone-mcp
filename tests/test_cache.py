import time

from keystone_mcp.cache import SqliteCache, TTLCache, make_key, parse_ttl


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


# SqliteCache --------------------------------------------------------


def test_sqlite_put_get_roundtrip(tmp_path):
    cache = SqliteCache(tmp_path / "c.db")
    cache.put("k", {"hello": [1, 2, 3]}, ttl_seconds=10)
    assert cache.get("k") == {"hello": [1, 2, 3]}


def test_sqlite_get_miss_returns_none(tmp_path):
    cache = SqliteCache(tmp_path / "c.db")
    assert cache.get("missing") is None


def test_sqlite_get_returns_none_after_expiry(tmp_path, monkeypatch):
    cache = SqliteCache(tmp_path / "c.db")
    now = [1700000000.0]
    monkeypatch.setattr(time, "time", lambda: now[0])
    cache.put("k", "v", ttl_seconds=5)
    now[0] += 6
    assert cache.get("k") is None
    # Row should have been deleted opportunistically.
    row = cache._conn.execute(
        "SELECT 1 FROM cache WHERE key = ?", ("k",)
    ).fetchone()
    assert row is None


def test_sqlite_persists_across_instances(tmp_path):
    path = tmp_path / "c.db"
    a = SqliteCache(path)
    a.put("k", "v", ttl_seconds=60)
    a.close()
    b = SqliteCache(path)
    assert b.get("k") == "v"


def test_sqlite_overwrite_value(tmp_path):
    cache = SqliteCache(tmp_path / "c.db")
    cache.put("k", "first", ttl_seconds=60)
    cache.put("k", "second", ttl_seconds=60)
    assert cache.get("k") == "second"


def test_sqlite_creates_parent_directory(tmp_path):
    path = tmp_path / "nested" / "dirs" / "c.db"
    cache = SqliteCache(path)
    cache.put("k", "v", ttl_seconds=60)
    assert path.exists()


def test_sqlite_corrupt_entry_treated_as_miss(tmp_path):
    cache = SqliteCache(tmp_path / "c.db")
    cache._conn.execute(
        "INSERT INTO cache (key, value, expires_at) VALUES (?, ?, ?)",
        ("k", b"not-a-pickle", time.time() + 60),
    )
    assert cache.get("k") is None
    # Corrupt row should be evicted.
    row = cache._conn.execute(
        "SELECT 1 FROM cache WHERE key = ?", ("k",)
    ).fetchone()
    assert row is None
