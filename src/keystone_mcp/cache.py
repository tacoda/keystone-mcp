import hashlib
import json
import time
from dataclasses import dataclass
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
