"""Cache backends for the resolver.

Two backends share the same interface (`get(key) -> Any | None` and
`put(key, value, ttl_seconds: float) -> None`):

  - TTLCache:    in-memory dict. Lost on restart.
  - SqliteCache: pickle-serialized values in a sqlite DB on disk. Persists
                 across process restarts. Pickle is safe here because keys
                 and values are produced by this server's own code; the
                 cache file is local-only.

Both prune expired entries opportunistically on `get`. No background sweep.
"""

from __future__ import annotations

import hashlib
import json
import pickle
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class _Entry:
    value: Any
    expires_at: float


class TTLCache:
    def __init__(self) -> None:
        self._store: dict[str, _Entry] = {}

    def get(self, key: str) -> Any | None:
        entry = self._store.get(key)
        if entry is None:
            return None
        if entry.expires_at < time.monotonic():
            del self._store[key]
            return None
        return entry.value

    def put(self, key: str, value: Any, ttl_seconds: float) -> None:
        self._store[key] = _Entry(value, time.monotonic() + ttl_seconds)


class SqliteCache:
    """Persistent cache. Keyed by `(scenario, query-hash)` upstream; this
    class is agnostic to the key shape.

    Wall-clock time is used (not monotonic) so entries written by a previous
    process are still meaningful after restart.
    """

    _SCHEMA = """
        CREATE TABLE IF NOT EXISTS cache (
            key        TEXT PRIMARY KEY,
            value      BLOB NOT NULL,
            expires_at REAL NOT NULL
        )
    """

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path).expanduser()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        # `check_same_thread=False`: the resolver may be called from any
        # task in the asyncio loop. Cache calls are short and not
        # interleaved across awaits, so the GIL is sufficient guard.
        self._conn = sqlite3.connect(
            str(self._path), check_same_thread=False, isolation_level=None
        )
        self._conn.execute(self._SCHEMA)

    def get(self, key: str) -> Any | None:
        row = self._conn.execute(
            "SELECT value, expires_at FROM cache WHERE key = ?", (key,)
        ).fetchone()
        if row is None:
            return None
        blob, expires_at = row
        if expires_at < time.time():
            self._conn.execute("DELETE FROM cache WHERE key = ?", (key,))
            return None
        try:
            return pickle.loads(blob)
        except (pickle.UnpicklingError, EOFError, AttributeError):
            # Corrupt or schema-mismatched entry — drop it.
            self._conn.execute("DELETE FROM cache WHERE key = ?", (key,))
            return None

    def put(self, key: str, value: Any, ttl_seconds: float) -> None:
        blob = pickle.dumps(value, protocol=pickle.HIGHEST_PROTOCOL)
        expires_at = time.time() + ttl_seconds
        self._conn.execute(
            "INSERT OR REPLACE INTO cache (key, value, expires_at) "
            "VALUES (?, ?, ?)",
            (key, blob, expires_at),
        )

    def close(self) -> None:
        self._conn.close()


def make_key(scenario: str, query: dict[str, Any]) -> str:
    payload = json.dumps(query, sort_keys=True, default=str)
    digest = hashlib.sha256(payload.encode()).hexdigest()[:16]
    return f"{scenario}:{digest}"


_UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400}


def parse_ttl(spec: str | int | float | None) -> float | None:
    if spec is None:
        return None
    if isinstance(spec, (int, float)):
        return float(spec)
    s = spec.strip()
    if not s:
        return None
    unit = s[-1]
    if unit in _UNITS:
        return float(s[:-1]) * _UNITS[unit]
    return float(s)
