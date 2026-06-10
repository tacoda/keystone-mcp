import httpx
import pytest
import respx

from keystone_mcp.adapters.notion import NotionAdapter
from keystone_mcp.errors import AdapterError, AuthError


_BASE = "https://api.notion.com/v1"


def _adapter() -> NotionAdapter:
    return NotionAdapter(token="t")


def _rich(text: str) -> list[dict]:
    return [{"plain_text": text, "type": "text", "text": {"content": text}}]


def _h2(text: str) -> dict:
    return {"type": "heading_2", "heading_2": {"rich_text": _rich(text)}}


def _h3(text: str) -> dict:
    return {"type": "heading_3", "heading_3": {"rich_text": _rich(text)}}


def _p(text: str) -> dict:
    return {"type": "paragraph", "paragraph": {"rich_text": _rich(text)}}


def _bullet(text: str) -> dict:
    return {
        "type": "bulleted_list_item",
        "bulleted_list_item": {"rich_text": _rich(text)},
    }


def _code(text: str, lang: str = "shell") -> dict:
    return {
        "type": "code",
        "code": {"language": lang, "rich_text": _rich(text)},
    }


_BLOCKS = [
    _h2("Rules"),
    _bullet("MUST pass CI before deploy."),
    _bullet("SHOULD deploy mid-week."),
    _bullet("review the diff."),
    _h2("Background"),
    _p("Adopted after a 2025 incident."),
    _h2("Procedures"),
    _h3("Cut release"),
    _p("Bump version, then tag."),
    _h3("Roll back"),
    _p("Revert and redeploy."),
    _h2("Commands"),
    _h3("deploy"),
    _code("./scripts/deploy.sh prod"),
    _p("Run after CI is green."),
    _h3("rollback"),
    _code("./scripts/rollback.sh"),
]


@respx.mock
async def test_page_by_id_classifies_all_kinds():
    respx.get(f"{_BASE}/blocks/page-123/children").mock(
        return_value=httpx.Response(
            200, json={"results": _BLOCKS, "has_more": False}
        )
    )
    classify = {
        "rules":    {"heading": "Rules", "severity": "must"},
        "reasoning": {"heading": "Background"},
        "skills":   {"heading": "Procedures"},
        "commands": {"heading": "Commands"},
    }
    docs = await _adapter().fetch({"type": "page", "id": "page-123"}, classify)
    by_kind: dict[str, list] = {}
    for d in docs:
        by_kind.setdefault(d.kind, []).append(d)
    assert [r.text for r in by_kind["rule"]] == [
        "pass CI before deploy.",
        "deploy mid-week.",
        "review the diff.",
    ]
    assert [r.severity for r in by_kind["rule"]] == ["must", "should", "must"]
    assert by_kind["rule"][0].source == "notion://page-123#rules"
    assert len(by_kind["reasoning"]) == 1
    assert "2025 incident" in by_kind["reasoning"][0].text
    assert [s.name for s in by_kind["skill"]] == ["Cut release", "Roll back"]
    assert "Bump version" in by_kind["skill"][0].text
    assert [c.name for c in by_kind["command"]] == ["deploy", "rollback"]
    assert by_kind["command"][0].invocation == "./scripts/deploy.sh prod"
    assert "CI is green" in by_kind["command"][0].text


@respx.mock
async def test_page_by_title_resolves_via_search():
    respx.post(f"{_BASE}/search").mock(
        return_value=httpx.Response(
            200,
            json={
                "results": [
                    {
                        "object": "page",
                        "id": "ghost",
                        "properties": {
                            "Name": {"type": "title", "title": _rich("Other")}
                        },
                    },
                    {
                        "object": "page",
                        "id": "page-456",
                        "properties": {
                            "Name": {
                                "type": "title",
                                "title": _rich("Deploy Runbook"),
                            }
                        },
                    },
                ]
            },
        )
    )
    respx.get(f"{_BASE}/blocks/page-456/children").mock(
        return_value=httpx.Response(
            200, json={"results": [_h2("Rules"), _bullet("MUST X.")], "has_more": False}
        )
    )
    docs = await _adapter().fetch(
        {"type": "page", "title": "Deploy Runbook"},
        {"rules": {"heading": "Rules"}},
    )
    assert all(d.source.startswith("notion://page-456") for d in docs)


@respx.mock
async def test_page_title_not_found_raises():
    respx.post(f"{_BASE}/search").mock(
        return_value=httpx.Response(200, json={"results": []})
    )
    with pytest.raises(AdapterError, match="no page titled"):
        await _adapter().fetch(
            {"type": "page", "title": "Ghost"}, {}
        )


@respx.mock
async def test_blocks_pagination():
    respx.get(f"{_BASE}/blocks/page-1/children").mock(
        side_effect=[
            httpx.Response(
                200,
                json={
                    "results": [_h2("Rules"), _bullet("MUST first.")],
                    "has_more": True,
                    "next_cursor": "cur-1",
                },
            ),
            httpx.Response(
                200,
                json={
                    "results": [_bullet("MUST second.")],
                    "has_more": False,
                },
            ),
        ]
    )
    docs = await _adapter().fetch(
        {"type": "page", "id": "page-1"},
        {"rules": {"heading": "Rules"}},
    )
    texts = [d.text for d in docs]
    assert texts == ["first.", "second."]


@respx.mock
async def test_database_returns_reasoning():
    respx.post(f"{_BASE}/databases/db-1/query").mock(
        return_value=httpx.Response(
            200,
            json={
                "results": [
                    {
                        "id": "row-a",
                        "url": "https://www.notion.so/row-a",
                        "last_edited_time": "2026-06-01T00:00:00Z",
                        "properties": {
                            "Name": {"type": "title", "title": _rich("Policy A")}
                        },
                    },
                    {
                        "id": "row-b",
                        "properties": {
                            "Title": {"type": "title", "title": _rich("Policy B")}
                        },
                    },
                ]
            },
        )
    )
    docs = await _adapter().fetch(
        {"type": "database", "id": "db-1", "limit": 5}, {}
    )
    assert [d.kind for d in docs] == ["reasoning", "reasoning"]
    assert docs[0].source == "https://www.notion.so/row-a"
    assert docs[0].recency == "2026-06-01T00:00:00Z"
    assert "Policy A" in docs[0].text
    assert docs[1].source == "notion://row-b"


@respx.mock
async def test_default_classify_returns_whole_page_as_reasoning():
    respx.get(f"{_BASE}/blocks/page-1/children").mock(
        return_value=httpx.Response(
            200,
            json={
                "results": [_p("freeform notes here.")],
                "has_more": False,
            },
        )
    )
    docs = await _adapter().fetch({"type": "page", "id": "page-1"}, {})
    assert len(docs) == 1
    assert docs[0].kind == "reasoning"
    assert "freeform notes here." in docs[0].text


@respx.mock
async def test_unknown_query_type_raises():
    with pytest.raises(AdapterError, match="unknown query.type"):
        await _adapter().fetch({"type": "bogus"}, {})


@respx.mock
async def test_unauthorized_raises_auth_error():
    respx.get(f"{_BASE}/blocks/page-1/children").mock(
        return_value=httpx.Response(401, json={"message": "bad token"})
    )
    with pytest.raises(AuthError, match="401"):
        await _adapter().fetch({"type": "page", "id": "page-1"}, {})


def test_constructor_requires_token():
    with pytest.raises(AuthError, match="token is required"):
        NotionAdapter(token="")


async def test_page_requires_id_or_title():
    a = _adapter()
    with pytest.raises(AdapterError, match="requires either"):
        await a.fetch({"type": "page"}, {})


async def test_database_requires_id():
    a = _adapter()
    with pytest.raises(AdapterError, match="database query requires"):
        await a.fetch({"type": "database"}, {})


@respx.mock
async def test_health_ok_returns_workspace():
    respx.get(f"{_BASE}/users/me").mock(
        return_value=httpx.Response(
            200,
            json={
                "type": "bot",
                "bot": {"workspace_name": "Acme"},
                "name": "Keystone Bot",
            },
        )
    )
    h = await _adapter().health()
    assert h["ok"] is True
    assert h["bot"] == "Acme"
    assert h["type"] == "bot"


@respx.mock
async def test_health_fails_on_auth():
    respx.get(f"{_BASE}/users/me").mock(
        return_value=httpx.Response(401, json={"message": "bad"})
    )
    h = await _adapter().health()
    assert h["ok"] is False
    assert "401" in h["detail"]


@respx.mock
async def test_severity_invalid_rejected():
    respx.get(f"{_BASE}/blocks/page-1/children").mock(
        return_value=httpx.Response(
            200, json={"results": [_h2("Rules"), _bullet("MUST X.")], "has_more": False}
        )
    )
    with pytest.raises(AdapterError, match="severity"):
        await _adapter().fetch(
            {"type": "page", "id": "page-1"},
            {"rules": {"heading": "Rules", "severity": "ghost"}},
        )
