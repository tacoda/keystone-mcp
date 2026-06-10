import httpx
import pytest
import respx

from keystone_mcp.adapters.linear import LinearAdapter
from keystone_mcp.errors import AdapterError, AuthError


_URL = "https://api.linear.app/graphql"


def _adapter() -> LinearAdapter:
    return LinearAdapter(api_key="k")


def _issue(
    identifier: str = "PORT-1",
    *,
    title: str = "Add auth",
    state: str = "In Progress",
    priority: int | None = 2,
    assignee: str | None = "Ian Johnson",
    updated: str = "2026-06-01T12:00:00.000Z",
    description: str | None = None,
    url: str | None = None,
) -> dict:
    return {
        "identifier": identifier,
        "title": title,
        "description": description,
        "priority": priority,
        "updatedAt": updated,
        "url": url or f"https://linear.app/acme/issue/{identifier}",
        "state": {"name": state, "type": "started"},
        "assignee": {"name": assignee} if assignee else None,
        "team": {"key": identifier.split("-")[0]},
    }


@respx.mock
async def test_issue_returns_summary_line_with_description():
    respx.post(_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "data": {
                    "issue": _issue(
                        description="Spec lives in the wiki.\nReview blocked."
                    )
                }
            },
        )
    )
    docs = await _adapter().fetch({"type": "issue", "id": "PORT-1"}, {})
    assert len(docs) == 1
    d = docs[0]
    assert d.kind == "reasoning"
    assert "PORT-1 [In Progress, priority 2]" in d.text
    assert "assignee=Ian Johnson" in d.text
    assert "Add auth" in d.text
    assert "Spec lives in the wiki." in d.text
    assert d.source == "https://linear.app/acme/issue/PORT-1"
    assert d.recency == "2026-06-01T12:00:00.000Z"


@respx.mock
async def test_issue_unassigned_renders_as_unassigned():
    respx.post(_URL).mock(
        return_value=httpx.Response(
            200, json={"data": {"issue": _issue(assignee=None)}}
        )
    )
    docs = await _adapter().fetch({"type": "issue", "id": "PORT-1"}, {})
    assert "assignee=unassigned" in docs[0].text


@respx.mock
async def test_issue_missing_priority_renders_dash():
    respx.post(_URL).mock(
        return_value=httpx.Response(
            200, json={"data": {"issue": _issue(priority=None)}}
        )
    )
    docs = await _adapter().fetch({"type": "issue", "id": "PORT-1"}, {})
    assert "priority -" in docs[0].text


@respx.mock
async def test_issue_url_fallback_when_missing():
    issue = _issue()
    del issue["url"]
    respx.post(_URL).mock(
        return_value=httpx.Response(200, json={"data": {"issue": issue}})
    )
    docs = await _adapter().fetch({"type": "issue", "id": "PORT-1"}, {})
    assert docs[0].source == "linear://PORT-1"


@respx.mock
async def test_issue_not_found_raises():
    respx.post(_URL).mock(
        return_value=httpx.Response(200, json={"data": {"issue": None}})
    )
    with pytest.raises(AdapterError, match="no issue"):
        await _adapter().fetch({"type": "issue", "id": "PORT-99"}, {})


async def test_issue_requires_id():
    with pytest.raises(AdapterError, match="requires 'id'"):
        await _adapter().fetch({"type": "issue"}, {})


@respx.mock
async def test_issues_returns_one_per_node():
    respx.post(_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "data": {
                    "issues": {
                        "nodes": [
                            _issue("PORT-10", title="A"),
                            _issue("PORT-11", title="B", state="Done"),
                        ]
                    }
                }
            },
        )
    )
    docs = await _adapter().fetch(
        {"type": "issues", "filter": {"team": {"key": {"eq": "PORT"}}}, "limit": 10},
        {},
    )
    assert [d.kind for d in docs] == ["reasoning", "reasoning"]
    assert "PORT-10" in docs[0].text and "A" in docs[0].text
    assert "PORT-11" in docs[1].text and "Done" in docs[1].text


@respx.mock
async def test_issues_respects_limit_below_returned_count():
    respx.post(_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "data": {
                    "issues": {
                        "nodes": [_issue("A-1"), _issue("A-2"), _issue("A-3")]
                    }
                }
            },
        )
    )
    docs = await _adapter().fetch({"type": "issues", "limit": 2}, {})
    assert [d.text.split(" ")[0] for d in docs] == ["A-1", "A-2"]


async def test_issues_rejects_non_mapping_filter():
    with pytest.raises(AdapterError, match="filter must be a mapping"):
        await _adapter().fetch(
            {"type": "issues", "filter": "junk"}, {}
        )


@respx.mock
async def test_issues_forwards_filter_and_first_to_graphql():
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = request.read()
        return httpx.Response(200, json={"data": {"issues": {"nodes": []}}})

    respx.post(_URL).mock(side_effect=handler)
    await _adapter().fetch(
        {
            "type": "issues",
            "filter": {"assignee": {"isMe": {"eq": True}}},
            "limit": 7,
        },
        {},
    )
    import json

    body = json.loads(captured["body"])
    assert body["variables"]["first"] == 7
    assert body["variables"]["filter"] == {"assignee": {"isMe": {"eq": True}}}
    assert "issues" in body["query"]


@respx.mock
async def test_unknown_query_type_raises():
    with pytest.raises(AdapterError, match="unknown query.type"):
        await _adapter().fetch({"type": "bogus"}, {})


@respx.mock
async def test_http_401_raises_auth_error():
    respx.post(_URL).mock(
        return_value=httpx.Response(401, json={"errors": [{"message": "bad"}]})
    )
    with pytest.raises(AuthError, match="401"):
        await _adapter().fetch({"type": "issue", "id": "PORT-1"}, {})


@respx.mock
async def test_graphql_auth_error_in_payload_raises_auth_error():
    respx.post(_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "errors": [
                    {
                        "message": "Not authenticated",
                        "extensions": {"code": "AUTHENTICATION_ERROR"},
                    }
                ]
            },
        )
    )
    with pytest.raises(AuthError, match="Not authenticated"):
        await _adapter().fetch({"type": "issue", "id": "PORT-1"}, {})


@respx.mock
async def test_graphql_non_auth_error_raises_adapter_error():
    respx.post(_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "errors": [
                    {
                        "message": "Bad filter",
                        "extensions": {"code": "VALIDATION_ERROR"},
                    }
                ]
            },
        )
    )
    with pytest.raises(AdapterError, match="GraphQL error"):
        await _adapter().fetch({"type": "issues"}, {})


def test_constructor_requires_api_key():
    with pytest.raises(AuthError, match="api_key is required"):
        LinearAdapter(api_key="")


@respx.mock
async def test_health_ok_returns_viewer():
    respx.post(_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "data": {
                    "viewer": {
                        "id": "u-1",
                        "name": "Ian Johnson",
                        "email": "ian@parentoleave.com",
                    }
                }
            },
        )
    )
    h = await _adapter().health()
    assert h["ok"] is True
    assert h["viewer_id"] == "u-1"
    assert h["viewer_name"] == "Ian Johnson"


@respx.mock
async def test_health_fails_on_auth_error():
    respx.post(_URL).mock(
        return_value=httpx.Response(401, json={"errors": [{"message": "bad"}]})
    )
    h = await _adapter().health()
    assert h["ok"] is False
    assert "401" in h["detail"]


@respx.mock
async def test_auth_header_is_raw_key_no_bearer_prefix():
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json={"data": {"viewer": {"id": "u"}}})

    respx.post(_URL).mock(side_effect=handler)
    await _adapter().health()
    assert captured["auth"] == "k"
