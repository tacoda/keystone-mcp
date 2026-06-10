import httpx
import pytest
import respx

from keystone_mcp.adapters.confluence import ConfluenceAdapter
from keystone_mcp.errors import AdapterError, AuthError


_BASE = "https://acme.atlassian.net"


def _adapter() -> ConfluenceAdapter:
    return ConfluenceAdapter(base_url=_BASE, email="e@x.com", token="t")


_PAGE_HTML = """
<h1>Deploy Runbook</h1>

<h2>Rules</h2>
<ul>
  <li>MUST pass CI before deploy.</li>
  <li>SHOULD deploy mid-week.</li>
  <li>do not skip review.</li>
</ul>

<h2>Background</h2>
<p>The team adopted these rules after a 2025 incident.</p>

<h2>Procedures</h2>
<h3>Cut release</h3>
<p>Bump version, then tag.</p>
<h3>Roll back</h3>
<p>Revert and redeploy.</p>

<h2>Commands</h2>
<h3>deploy</h3>
<pre>./scripts/deploy.sh prod</pre>
<p>Run after CI is green.</p>
<h3>rollback</h3>
<pre>./scripts/rollback.sh</pre>
"""


def _page_response(page_id: str = "12345") -> dict:
    return {
        "id": page_id,
        "title": "Deploy Runbook",
        "body": {"view": {"value": _PAGE_HTML, "representation": "view"}},
    }


@respx.mock
async def test_page_by_id_classifies_all_kinds():
    respx.get(f"{_BASE}/wiki/api/v2/pages/12345").mock(
        return_value=httpx.Response(200, json=_page_response())
    )
    classify = {
        "rules":    {"heading": "Rules", "severity": "must"},
        "reasoning": {"heading": "Background"},
        "skills":   {"heading": "Procedures"},
        "commands": {"heading": "Commands"},
    }
    docs = await _adapter().fetch({"type": "page", "id": "12345"}, classify)
    by_kind: dict[str, list] = {}
    for d in docs:
        by_kind.setdefault(d.kind, []).append(d)
    assert [r.text for r in by_kind["rule"]] == [
        "pass CI before deploy.",
        "deploy mid-week.",
        "do not skip review.",
    ]
    assert [r.severity for r in by_kind["rule"]] == ["must", "should", "must"]
    assert by_kind["rule"][0].source == "confluence://12345#rules"
    assert len(by_kind["reasoning"]) == 1
    assert "2025 incident" in by_kind["reasoning"][0].text
    assert [s.name for s in by_kind["skill"]] == ["Cut release", "Roll back"]
    assert "Bump version" in by_kind["skill"][0].text
    assert [c.name for c in by_kind["command"]] == ["deploy", "rollback"]
    assert by_kind["command"][0].invocation == "./scripts/deploy.sh prod"
    assert "CI is green" in by_kind["command"][0].text


@respx.mock
async def test_page_by_title_resolves_space_id_first():
    respx.get(f"{_BASE}/wiki/api/v2/spaces").mock(
        return_value=httpx.Response(
            200, json={"results": [{"id": "777", "key": "ENG"}]}
        )
    )
    respx.get(f"{_BASE}/wiki/api/v2/pages").mock(
        return_value=httpx.Response(200, json={"results": [_page_response("9999")]})
    )
    docs = await _adapter().fetch(
        {"type": "page", "title": "Deploy Runbook", "space": "ENG"},
        {"rules": {"heading": "Rules"}},
    )
    assert all(d.source.startswith("confluence://9999") for d in docs)


@respx.mock
async def test_page_missing_when_title_not_found():
    respx.get(f"{_BASE}/wiki/api/v2/spaces").mock(
        return_value=httpx.Response(200, json={"results": [{"id": "777"}]})
    )
    respx.get(f"{_BASE}/wiki/api/v2/pages").mock(
        return_value=httpx.Response(200, json={"results": []})
    )
    with pytest.raises(AdapterError, match="no page titled"):
        await _adapter().fetch(
            {"type": "page", "title": "Ghost", "space": "ENG"}, {}
        )


@respx.mock
async def test_space_pages_returns_reasoning():
    respx.get(f"{_BASE}/wiki/api/v2/spaces").mock(
        return_value=httpx.Response(200, json={"results": [{"id": "777"}]})
    )
    respx.get(f"{_BASE}/wiki/api/v2/spaces/777/pages").mock(
        return_value=httpx.Response(
            200,
            json={
                "results": [
                    {
                        "id": "1",
                        "title": "Page A",
                        "version": {"createdAt": "2026-06-01T00:00:00Z"},
                    },
                    {"id": "2", "title": "Page B"},
                ]
            },
        )
    )
    docs = await _adapter().fetch(
        {"type": "space_pages", "space": "ENG", "limit": 10}, {}
    )
    assert [d.kind for d in docs] == ["reasoning", "reasoning"]
    assert docs[0].recency == "2026-06-01T00:00:00Z"
    assert "Page A" in docs[0].text
    assert docs[1].recency is None


@respx.mock
async def test_default_classify_returns_whole_page_as_reasoning():
    respx.get(f"{_BASE}/wiki/api/v2/pages/12345").mock(
        return_value=httpx.Response(200, json=_page_response())
    )
    docs = await _adapter().fetch({"type": "page", "id": "12345"}, {})
    assert len(docs) == 1
    assert docs[0].kind == "reasoning"
    assert "Deploy Runbook" in docs[0].text


@respx.mock
async def test_unknown_query_type_raises():
    with pytest.raises(AdapterError, match="unknown query.type"):
        await _adapter().fetch({"type": "bogus"}, {})


@respx.mock
async def test_unauthorized_raises_auth_error():
    respx.get(f"{_BASE}/wiki/api/v2/pages/12345").mock(
        return_value=httpx.Response(401, json={"message": "bad auth"})
    )
    with pytest.raises(AuthError, match="401"):
        await _adapter().fetch({"type": "page", "id": "12345"}, {})


def test_constructor_requires_email_token_base_url():
    with pytest.raises(AuthError, match="email"):
        ConfluenceAdapter(base_url=_BASE, email="", token="t")
    with pytest.raises(AuthError, match="token"):
        ConfluenceAdapter(base_url=_BASE, email="e@x.com", token="")
    with pytest.raises(AdapterError, match="base_url"):
        ConfluenceAdapter(base_url="", email="e@x.com", token="t")


def test_page_query_requires_id_or_title_plus_space():
    a = _adapter()
    with pytest.raises(AdapterError, match="must include either"):
        # Direct call to internal resolver path via fetch — no respx needed,
        # validation runs before any HTTP request.
        import asyncio

        asyncio.run(a.fetch({"type": "page", "title": "x"}, {}))


@respx.mock
async def test_health_ok():
    respx.get(f"{_BASE}/wiki/api/v2/spaces").mock(
        return_value=httpx.Response(200, json={"results": [{"id": "1"}]})
    )
    h = await _adapter().health()
    assert h["ok"] is True
    assert h["spaces_visible"] == 1


@respx.mock
async def test_health_fails_on_auth():
    respx.get(f"{_BASE}/wiki/api/v2/spaces").mock(
        return_value=httpx.Response(401, json={"message": "bad"})
    )
    h = await _adapter().health()
    assert h["ok"] is False
    assert "401" in h["detail"]


@respx.mock
async def test_invalid_body_format_rejected():
    with pytest.raises(AdapterError, match="query.body must be"):
        await _adapter().fetch(
            {"type": "page", "id": "1", "body": "ghost"}, {}
        )


@respx.mock
async def test_severity_invalid_rejected():
    respx.get(f"{_BASE}/wiki/api/v2/pages/12345").mock(
        return_value=httpx.Response(200, json=_page_response())
    )
    with pytest.raises(AdapterError, match="severity"):
        await _adapter().fetch(
            {"type": "page", "id": "12345"},
            {"rules": {"heading": "Rules", "severity": "ghost"}},
        )
