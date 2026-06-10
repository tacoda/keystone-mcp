import httpx
import pytest
import respx

from keystone_mcp.adapters.jira import JiraAdapter, _adf_to_text
from keystone_mcp.errors import AdapterError, AuthError


_BASE = "https://acme.atlassian.net"


def _adapter() -> JiraAdapter:
    return JiraAdapter(base_url=_BASE, email="e@x.com", token="t")


def _adf(*paragraphs: str) -> dict:
    return {
        "type": "doc",
        "version": 1,
        "content": [
            {
                "type": "paragraph",
                "content": [{"type": "text", "text": p}],
            }
            for p in paragraphs
        ],
    }


def _issue(
    key: str,
    *,
    summary: str = "Do thing",
    status: str = "In Progress",
    assignee: str | None = "Ian Johnson",
    itype: str = "Task",
    updated: str = "2026-06-01T12:00:00.000+0000",
    description: dict | None = None,
) -> dict:
    return {
        "key": key,
        "fields": {
            "summary": summary,
            "status": {"name": status},
            "assignee": {"displayName": assignee} if assignee else None,
            "issuetype": {"name": itype},
            "updated": updated,
            "description": description,
        },
    }


def test_adf_walker_extracts_paragraph_text():
    doc = _adf("first paragraph.", "second paragraph.")
    assert _adf_to_text(doc) == "first paragraph.\nsecond paragraph."


def test_adf_walker_handles_nested_lists_and_code_blocks():
    doc = {
        "type": "doc",
        "content": [
            {"type": "heading", "content": [{"type": "text", "text": "Notes"}]},
            {
                "type": "bulletList",
                "content": [
                    {
                        "type": "list_item",
                        "content": [
                            {
                                "type": "paragraph",
                                "content": [{"type": "text", "text": "one"}],
                            }
                        ],
                    },
                    {
                        "type": "list_item",
                        "content": [
                            {
                                "type": "paragraph",
                                "content": [{"type": "text", "text": "two"}],
                            }
                        ],
                    },
                ],
            },
            {
                "type": "codeBlock",
                "content": [{"type": "text", "text": "echo hi"}],
            },
        ],
    }
    text = _adf_to_text(doc)
    assert "Notes" in text
    assert "one" in text and "two" in text
    assert "echo hi" in text


def test_adf_walker_returns_empty_for_none():
    assert _adf_to_text(None) == ""


@respx.mock
async def test_issue_returns_single_reasoning_doc_with_summary_and_body():
    respx.get(f"{_BASE}/rest/api/3/issue/PORT-1").mock(
        return_value=httpx.Response(
            200,
            json=_issue(
                "PORT-1",
                summary="Add auth",
                description=_adf("Spec lives in the wiki.", "Block on review."),
            ),
        )
    )
    docs = await _adapter().fetch({"type": "issue", "key": "PORT-1"}, {})
    assert len(docs) == 1
    d = docs[0]
    assert d.kind == "reasoning"
    assert "PORT-1 [Task, In Progress]" in d.text
    assert "assignee=Ian Johnson" in d.text
    assert "Add auth" in d.text
    assert "Spec lives in the wiki." in d.text
    assert d.source == f"{_BASE}/browse/PORT-1"
    assert d.recency == "2026-06-01T12:00:00.000+0000"


@respx.mock
async def test_issue_unassigned_renders_as_unassigned():
    respx.get(f"{_BASE}/rest/api/3/issue/PORT-2").mock(
        return_value=httpx.Response(
            200, json=_issue("PORT-2", assignee=None, description=None)
        )
    )
    docs = await _adapter().fetch({"type": "issue", "key": "PORT-2"}, {})
    assert "assignee=unassigned" in docs[0].text


async def test_issue_requires_key():
    with pytest.raises(AdapterError, match="requires 'key'"):
        await _adapter().fetch({"type": "issue"}, {})


@respx.mock
async def test_jql_returns_one_reasoning_per_issue():
    respx.get(f"{_BASE}/rest/api/3/search").mock(
        return_value=httpx.Response(
            200,
            json={
                "issues": [
                    _issue("PORT-10", summary="A"),
                    _issue("PORT-11", summary="B", status="Done"),
                ]
            },
        )
    )
    docs = await _adapter().fetch(
        {"type": "jql", "jql": "project = PORT", "limit": 10}, {}
    )
    assert [d.kind for d in docs] == ["reasoning", "reasoning"]
    assert "PORT-10" in docs[0].text and "A" in docs[0].text
    assert "PORT-11" in docs[1].text and "Done" in docs[1].text
    assert docs[0].source == f"{_BASE}/browse/PORT-10"


@respx.mock
async def test_jql_respects_limit_below_returned_count():
    respx.get(f"{_BASE}/rest/api/3/search").mock(
        return_value=httpx.Response(
            200,
            json={
                "issues": [
                    _issue("A-1"),
                    _issue("A-2"),
                    _issue("A-3"),
                ]
            },
        )
    )
    docs = await _adapter().fetch(
        {"type": "jql", "jql": "x", "limit": 2}, {}
    )
    assert [d.text.split(" ")[0] for d in docs] == ["A-1", "A-2"]


async def test_jql_requires_jql():
    with pytest.raises(AdapterError, match="requires 'jql'"):
        await _adapter().fetch({"type": "jql"}, {})


@respx.mock
async def test_unknown_query_type_raises():
    with pytest.raises(AdapterError, match="unknown query.type"):
        await _adapter().fetch({"type": "ghost"}, {})


@respx.mock
async def test_unauthorized_raises_auth_error():
    respx.get(f"{_BASE}/rest/api/3/issue/PORT-1").mock(
        return_value=httpx.Response(401, json={"message": "bad"})
    )
    with pytest.raises(AuthError, match="401"):
        await _adapter().fetch({"type": "issue", "key": "PORT-1"}, {})


def test_constructor_validates_required_args():
    with pytest.raises(AdapterError, match="base_url"):
        JiraAdapter(base_url="", email="e@x.com", token="t")
    with pytest.raises(AuthError, match="email"):
        JiraAdapter(base_url=_BASE, email="", token="t")
    with pytest.raises(AuthError, match="token"):
        JiraAdapter(base_url=_BASE, email="e@x.com", token="")


@respx.mock
async def test_health_ok_returns_account_info():
    respx.get(f"{_BASE}/rest/api/3/myself").mock(
        return_value=httpx.Response(
            200,
            json={
                "accountId": "abc-123",
                "displayName": "Ian Johnson",
            },
        )
    )
    h = await _adapter().health()
    assert h["ok"] is True
    assert h["account_id"] == "abc-123"
    assert h["display_name"] == "Ian Johnson"


@respx.mock
async def test_health_fails_on_auth_error():
    respx.get(f"{_BASE}/rest/api/3/myself").mock(
        return_value=httpx.Response(401, json={"message": "bad"})
    )
    h = await _adapter().health()
    assert h["ok"] is False
    assert "401" in h["detail"]


@respx.mock
async def test_issue_404_surfaces_adapter_error():
    respx.get(f"{_BASE}/rest/api/3/issue/MISSING-1").mock(
        return_value=httpx.Response(404, json={"errorMessages": ["not found"]})
    )
    with pytest.raises(AdapterError, match="404"):
        await _adapter().fetch({"type": "issue", "key": "MISSING-1"}, {})
