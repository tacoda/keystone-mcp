import httpx
import pytest
import respx

from keystone_mcp.adapters.slack import SlackAdapter, _iso_to_ts, _ts_to_iso
from keystone_mcp.errors import AdapterError, AuthError


_BASE = "https://slack.com/api"


def _adapter() -> SlackAdapter:
    return SlackAdapter(token="xoxb-abc")


def _msg(text: str, *, user: str = "U1", ts: str = "1700000000.000001",
         permalink: str | None = None) -> dict:
    out: dict = {"text": text, "user": user, "ts": ts, "type": "message"}
    if permalink is not None:
        out["permalink"] = permalink
    return out


def test_ts_to_iso_roundtrip():
    iso = _ts_to_iso("1700000000.000001")
    assert iso is not None
    assert iso.startswith("2023-11-14T") or iso.startswith("2023-11-15T")


def test_ts_to_iso_invalid_returns_none():
    assert _ts_to_iso("junk") is None
    assert _ts_to_iso("") is None


def test_iso_to_ts_handles_z_suffix():
    assert _iso_to_ts("1970-01-01T00:00:00Z") == "0.000000"


@respx.mock
async def test_pinned_emits_rules_with_severity_prefix_parsing():
    respx.get(f"{_BASE}/pins.list").mock(
        return_value=httpx.Response(
            200,
            json={
                "ok": True,
                "items": [
                    {"type": "message", "message": _msg("MUST pass CI before deploy.")},
                    {"type": "message", "message": _msg("SHOULD deploy mid-week.")},
                    {"type": "message", "message": _msg("Review the diff.")},
                ],
            },
        )
    )
    docs = await _adapter().fetch(
        {"type": "pinned", "channel": "C0123ABCDE"}, {}
    )
    assert [d.kind for d in docs] == ["rule", "rule", "rule"]
    assert [d.text for d in docs] == [
        "pass CI before deploy.",
        "deploy mid-week.",
        "Review the diff.",
    ]
    assert [d.severity for d in docs] == ["must", "should", "must"]
    assert docs[0].id == "pin-001"


@respx.mock
async def test_pinned_default_severity_override():
    respx.get(f"{_BASE}/pins.list").mock(
        return_value=httpx.Response(
            200,
            json={
                "ok": True,
                "items": [{"type": "message", "message": _msg("Read the runbook.")}],
            },
        )
    )
    docs = await _adapter().fetch(
        {"type": "pinned", "channel": "C0123ABCDE"},
        {"rules": {"severity": "should"}},
    )
    assert docs[0].severity == "should"


@respx.mock
async def test_pinned_uses_message_permalink_when_present():
    respx.get(f"{_BASE}/pins.list").mock(
        return_value=httpx.Response(
            200,
            json={
                "ok": True,
                "items": [
                    {
                        "type": "message",
                        "message": _msg(
                            "MUST tag releases.",
                            permalink="https://acme.slack.com/archives/C0/p1700000000000001",
                        ),
                    }
                ],
            },
        )
    )
    docs = await _adapter().fetch(
        {"type": "pinned", "channel": "C0123ABCDE"}, {}
    )
    assert docs[0].source == "https://acme.slack.com/archives/C0/p1700000000000001"


@respx.mock
async def test_pinned_falls_back_to_synthetic_source_uri():
    respx.get(f"{_BASE}/pins.list").mock(
        return_value=httpx.Response(
            200,
            json={
                "ok": True,
                "items": [{"type": "message", "message": _msg("MUST X.")}],
            },
        )
    )
    docs = await _adapter().fetch(
        {"type": "pinned", "channel": "C0123ABCDE"}, {}
    )
    assert docs[0].source == "slack://C0123ABCDE/1700000000.000001"


@respx.mock
async def test_pinned_skips_empty_messages():
    respx.get(f"{_BASE}/pins.list").mock(
        return_value=httpx.Response(
            200,
            json={
                "ok": True,
                "items": [
                    {"type": "message", "message": _msg("")},
                    {"type": "file", "file": {"name": "spec.pdf"}},  # non-message
                    {"type": "message", "message": _msg("MUST X.")},
                ],
            },
        )
    )
    docs = await _adapter().fetch(
        {"type": "pinned", "channel": "C0123ABCDE"}, {}
    )
    assert [d.text for d in docs] == ["X."]


@respx.mock
async def test_recent_emits_reasoning_with_recency():
    respx.get(f"{_BASE}/conversations.history").mock(
        return_value=httpx.Response(
            200,
            json={
                "ok": True,
                "messages": [
                    _msg("Deploy went out.", user="U-alice", ts="1700000000.111111"),
                    _msg("Rolled back.", user="U-bob", ts="1700000050.222222"),
                ],
            },
        )
    )
    docs = await _adapter().fetch(
        {"type": "recent", "channel": "C0123ABCDE", "limit": 10}, {}
    )
    assert [d.kind for d in docs] == ["reasoning", "reasoning"]
    assert docs[0].text == "@U-alice: Deploy went out."
    assert docs[0].recency is not None
    assert docs[0].source == "slack://C0123ABCDE/1700000000.111111"


@respx.mock
async def test_recent_passes_oldest_when_since_is_iso():
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["params"] = dict(request.url.params)
        return httpx.Response(200, json={"ok": True, "messages": []})

    respx.get(f"{_BASE}/conversations.history").mock(side_effect=handler)
    await _adapter().fetch(
        {
            "type": "recent",
            "channel": "C0123ABCDE",
            "since": "1970-01-01T00:00:00Z",
        },
        {},
    )
    assert captured["params"]["oldest"] == "0.000000"


@respx.mock
async def test_recent_invalid_since_raises():
    respx.get(f"{_BASE}/conversations.history").mock(
        return_value=httpx.Response(200, json={"ok": True, "messages": []})
    )
    with pytest.raises(AdapterError, match="since must be ISO"):
        await _adapter().fetch(
            {"type": "recent", "channel": "C0123ABCDE", "since": "ghost"},
            {},
        )


@respx.mock
async def test_recent_respects_limit_below_returned_count():
    respx.get(f"{_BASE}/conversations.history").mock(
        return_value=httpx.Response(
            200,
            json={
                "ok": True,
                "messages": [
                    _msg("one"),
                    _msg("two"),
                    _msg("three"),
                ],
            },
        )
    )
    docs = await _adapter().fetch(
        {"type": "recent", "channel": "C0123ABCDE", "limit": 2}, {}
    )
    assert [d.text.split(": ")[1] for d in docs] == ["one", "two"]


@respx.mock
async def test_channel_resolution_by_name_uses_conversations_list():
    respx.get(f"{_BASE}/conversations.list").mock(
        return_value=httpx.Response(
            200,
            json={
                "ok": True,
                "channels": [
                    {"id": "C00OTHER1", "name": "general"},
                    {"id": "C00DEPL01", "name": "deploys"},
                ],
            },
        )
    )
    respx.get(f"{_BASE}/pins.list").mock(
        return_value=httpx.Response(
            200,
            json={
                "ok": True,
                "items": [{"type": "message", "message": _msg("MUST tag.")}],
            },
        )
    )
    docs = await _adapter().fetch({"type": "pinned", "channel": "deploys"}, {})
    assert docs[0].source.startswith("slack://C00DEPL01/")


@respx.mock
async def test_channel_resolution_strips_leading_hash_and_caches():
    list_route = respx.get(f"{_BASE}/conversations.list").mock(
        return_value=httpx.Response(
            200,
            json={
                "ok": True,
                "channels": [{"id": "C00DEPL01", "name": "deploys"}],
            },
        )
    )
    respx.get(f"{_BASE}/pins.list").mock(
        return_value=httpx.Response(
            200,
            json={
                "ok": True,
                "items": [{"type": "message", "message": _msg("MUST X.")}],
            },
        )
    )
    a = _adapter()
    await a.fetch({"type": "pinned", "channel": "#deploys"}, {})
    await a.fetch({"type": "pinned", "channel": "#deploys"}, {})
    assert list_route.call_count == 1  # cached after first lookup


@respx.mock
async def test_channel_resolution_paginates_until_match():
    respx.get(f"{_BASE}/conversations.list").mock(
        side_effect=[
            httpx.Response(
                200,
                json={
                    "ok": True,
                    "channels": [{"id": "C00X", "name": "general"}],
                    "response_metadata": {"next_cursor": "cur-1"},
                },
            ),
            httpx.Response(
                200,
                json={
                    "ok": True,
                    "channels": [{"id": "C00DEPL01", "name": "deploys"}],
                },
            ),
        ]
    )
    respx.get(f"{_BASE}/pins.list").mock(
        return_value=httpx.Response(
            200,
            json={
                "ok": True,
                "items": [{"type": "message", "message": _msg("MUST X.")}],
            },
        )
    )
    docs = await _adapter().fetch({"type": "pinned", "channel": "deploys"}, {})
    assert docs[0].source.startswith("slack://C00DEPL01/")


@respx.mock
async def test_channel_resolution_not_found_raises():
    respx.get(f"{_BASE}/conversations.list").mock(
        return_value=httpx.Response(
            200,
            json={
                "ok": True,
                "channels": [{"id": "C00OTHER1", "name": "general"}],
            },
        )
    )
    with pytest.raises(AdapterError, match="no channel named"):
        await _adapter().fetch({"type": "pinned", "channel": "ghost"}, {})


@respx.mock
async def test_slack_invalid_auth_raises_auth_error():
    respx.get(f"{_BASE}/pins.list").mock(
        return_value=httpx.Response(200, json={"ok": False, "error": "invalid_auth"})
    )
    with pytest.raises(AuthError, match="invalid_auth"):
        await _adapter().fetch({"type": "pinned", "channel": "C0123ABCDE"}, {})


@respx.mock
async def test_slack_non_auth_error_raises_adapter_error():
    respx.get(f"{_BASE}/pins.list").mock(
        return_value=httpx.Response(
            200, json={"ok": False, "error": "channel_not_found"}
        )
    )
    with pytest.raises(AdapterError, match="channel_not_found"):
        await _adapter().fetch({"type": "pinned", "channel": "C0123ABCDE"}, {})


@respx.mock
async def test_http_401_raises_auth_error():
    respx.get(f"{_BASE}/pins.list").mock(
        return_value=httpx.Response(401, text="unauthorized")
    )
    with pytest.raises(AuthError, match="401"):
        await _adapter().fetch({"type": "pinned", "channel": "C0123ABCDE"}, {})


@respx.mock
async def test_unknown_query_type_raises():
    with pytest.raises(AdapterError, match="unknown query.type"):
        await _adapter().fetch({"type": "bogus"}, {})


async def test_channel_required():
    with pytest.raises(AdapterError, match="channel is required"):
        await _adapter().fetch({"type": "pinned"}, {})


def test_constructor_requires_token():
    with pytest.raises(AuthError, match="token is required"):
        SlackAdapter(token="")


@respx.mock
async def test_health_ok_returns_team_and_user():
    respx.get(f"{_BASE}/auth.test").mock(
        return_value=httpx.Response(
            200,
            json={
                "ok": True,
                "team": "Acme",
                "user": "keystone-bot",
                "url": "https://acme.slack.com/",
            },
        )
    )
    h = await _adapter().health()
    assert h["ok"] is True
    assert h["team"] == "Acme"
    assert h["user"] == "keystone-bot"


@respx.mock
async def test_health_fails_on_invalid_auth():
    respx.get(f"{_BASE}/auth.test").mock(
        return_value=httpx.Response(200, json={"ok": False, "error": "invalid_auth"})
    )
    h = await _adapter().health()
    assert h["ok"] is False
    assert "invalid_auth" in h["detail"]


@respx.mock
async def test_severity_invalid_rejected():
    respx.get(f"{_BASE}/pins.list").mock(
        return_value=httpx.Response(
            200,
            json={
                "ok": True,
                "items": [{"type": "message", "message": _msg("MUST X.")}],
            },
        )
    )
    with pytest.raises(AdapterError, match="severity"):
        await _adapter().fetch(
            {"type": "pinned", "channel": "C0123ABCDE"},
            {"rules": {"severity": "ghost"}},
        )
