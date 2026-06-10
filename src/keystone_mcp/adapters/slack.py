"""Slack adapter — Phase 7.

Reads context from Slack via the Web API.

Auth: bot or user OAuth token (`xoxb-...` / `xoxp-...`). Required scopes:
  - `channels:read`         resolve channel name → id
  - `pins:read`             pins.list
  - `channels:history`,     conversations.history (plus the matching
    `groups:history`,        history scope for each channel type the
    `im:history`,            integration needs to read)
    `mpim:history`

Query types:

    type: pinned
        channel: deploys          # name (with or without leading #) or ID
    type: recent
        channel: deploys
        limit: 50                 # default 50, capped at 200 per Slack
        since: "2026-06-01T00:00:00Z"   # optional ISO time → oldest

Output kinds:

    pinned  → rules    (one rule per pinned message, severity from
                       MUST/SHOULD/MAY prefix, default from classify)
    recent  → reasoning (one entry per message, `recency` = message ts)

Slack returns HTTP 200 with `{ok: false, error: ...}` on application errors.
The adapter checks `ok` and raises `AuthError` for auth-flavored codes,
`AdapterError` otherwise.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

import httpx

from ..errors import AdapterError, AuthError
from ..payload import ContextDoc, Severity


_DEFAULT_BASE_URL = "https://slack.com/api"
_CHANNEL_ID_RE = re.compile(r"^[CDG][A-Z0-9]{6,}$")
_SEVERITY_PREFIX_RE = re.compile(
    r"^(MUST|SHOULD|MAY)\b[:.\s]*(.+)$", re.IGNORECASE | re.DOTALL
)
_AUTH_ERRORS = {
    "invalid_auth",
    "not_authed",
    "token_revoked",
    "token_expired",
    "no_permission",
    "missing_scope",
    "account_inactive",
}


def _ts_to_iso(ts: str) -> str | None:
    try:
        epoch = float(ts)
    except (TypeError, ValueError):
        return None
    return datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat(timespec="seconds")


def _iso_to_ts(iso: str) -> str:
    cleaned = iso.replace("Z", "+00:00")
    dt = datetime.fromisoformat(cleaned)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return f"{dt.timestamp():.6f}"


def _severity_default(classify: dict[str, Any]) -> Severity:
    rules = classify.get("rules")
    if isinstance(rules, dict):
        sev = rules.get("severity", "must")
        if sev not in ("must", "should", "may"):
            raise AdapterError(
                f"slack adapter: classify.rules.severity must be must|should|may, got {sev!r}"
            )
        return sev  # type: ignore[return-value]
    return "must"


class SlackAdapter:
    name = "slack"

    def __init__(
        self,
        *,
        token: str,
        base_url: str = _DEFAULT_BASE_URL,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if not token:
            raise AuthError("slack adapter: token is required")
        self._token = token
        self._base_url = base_url.rstrip("/")
        self._client = client
        self._channel_id_cache: dict[str, str] = {}

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/json",
        }

    async def _call(
        self, path: str, *, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        url = f"{self._base_url}{path}"
        client = self._client or httpx.AsyncClient()
        owns_client = self._client is None
        try:
            resp = await client.get(url, headers=self._headers(), params=params)
        finally:
            if owns_client:
                await client.aclose()
        if resp.status_code == 401:
            raise AuthError(f"slack adapter: 401 unauthorized at {path}")
        if resp.status_code >= 400:
            raise AdapterError(
                f"slack adapter: HTTP {resp.status_code} at {path} ({resp.text[:200]})"
            )
        data = resp.json()
        if not data.get("ok", False):
            err = data.get("error", "unknown_error")
            if err in _AUTH_ERRORS:
                raise AuthError(f"slack adapter: {err}")
            raise AdapterError(f"slack adapter: {err}")
        return data

    async def _resolve_channel(self, ref: str) -> str:
        if not ref:
            raise AdapterError("slack adapter: query.channel is required")
        normalized = ref.lstrip("#")
        if _CHANNEL_ID_RE.match(normalized):
            return normalized
        if normalized in self._channel_id_cache:
            return self._channel_id_cache[normalized]
        target = normalized.lower()
        cursor: str | None = None
        while True:
            params: dict[str, Any] = {
                "types": "public_channel,private_channel",
                "limit": 200,
                "exclude_archived": "true",
            }
            if cursor:
                params["cursor"] = cursor
            data = await self._call("/conversations.list", params=params)
            for ch in data.get("channels") or []:
                if (ch.get("name") or "").lower() == target:
                    cid = ch.get("id")
                    if cid:
                        self._channel_id_cache[normalized] = cid
                        return cid
            cursor = (data.get("response_metadata") or {}).get("next_cursor") or None
            if not cursor:
                break
        raise AdapterError(
            f"slack adapter: no channel named {ref!r} visible to this token"
        )

    async def _emit_pinned(
        self, query: dict[str, Any], classify: dict[str, Any]
    ) -> list[ContextDoc]:
        channel_id = await self._resolve_channel(str(query.get("channel") or ""))
        data = await self._call("/pins.list", params={"channel": channel_id})
        default_severity = _severity_default(classify)
        docs: list[ContextDoc] = []
        idx = 0
        for item in data.get("items") or []:
            if item.get("type") not in (None, "message"):
                continue
            msg = item.get("message") or {}
            text = (msg.get("text") or "").strip()
            if not text:
                continue
            severity: Severity = default_severity
            m = _SEVERITY_PREFIX_RE.match(text)
            if m and m.group(1).lower() in ("must", "should", "may"):
                severity = m.group(1).lower()  # type: ignore[assignment]
                text = m.group(2).strip()
            ts = msg.get("ts") or ""
            permalink = (
                msg.get("permalink")
                or item.get("permalink")
                or f"slack://{channel_id}/{ts}"
            )
            idx += 1
            docs.append(
                ContextDoc(
                    kind="rule",
                    text=text,
                    source=permalink,
                    severity=severity,
                    id=f"pin-{idx:03d}",
                )
            )
        return docs

    async def _emit_recent(self, query: dict[str, Any]) -> list[ContextDoc]:
        channel_id = await self._resolve_channel(str(query.get("channel") or ""))
        limit = int(query.get("limit") or 50)
        params: dict[str, Any] = {
            "channel": channel_id,
            "limit": min(limit, 200),
        }
        since = query.get("since")
        if since:
            try:
                params["oldest"] = _iso_to_ts(str(since))
            except ValueError as exc:
                raise AdapterError(
                    f"slack adapter: query.since must be ISO 8601 ({since!r}): {exc}"
                ) from exc
        data = await self._call("/conversations.history", params=params)
        docs: list[ContextDoc] = []
        for msg in (data.get("messages") or [])[:limit]:
            text = (msg.get("text") or "").strip()
            if not text:
                continue
            user = (
                msg.get("username")
                or msg.get("user")
                or msg.get("bot_id")
                or "unknown"
            )
            ts = msg.get("ts") or ""
            permalink = msg.get("permalink") or f"slack://{channel_id}/{ts}"
            recency = _ts_to_iso(ts) if ts else None
            docs.append(
                ContextDoc(
                    kind="reasoning",
                    text=f"@{user}: {text}",
                    source=permalink,
                    recency=recency,
                )
            )
        return docs

    async def fetch(
        self, query: dict[str, Any], classify: dict[str, Any]
    ) -> list[ContextDoc]:
        qtype = query.get("type")
        if not qtype:
            raise AdapterError("slack adapter: query.type is required")
        if qtype == "pinned":
            return await self._emit_pinned(query, classify)
        if qtype == "recent":
            return await self._emit_recent(query)
        raise AdapterError(
            f"slack adapter: unknown query.type {qtype!r} (known: pinned, recent)"
        )

    async def health(self) -> dict[str, Any]:
        try:
            data = await self._call("/auth.test")
        except (AdapterError, AuthError) as exc:
            return {"source": self.name, "ok": False, "detail": str(exc)}
        return {
            "source": self.name,
            "ok": True,
            "team": data.get("team"),
            "user": data.get("user"),
            "url": data.get("url"),
        }
