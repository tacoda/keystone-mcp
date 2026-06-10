import base64

import httpx
import pytest
import respx

from keystone_mcp.adapters.github import GitHubAdapter
from keystone_mcp.errors import AdapterError, AuthError


_BASE = "https://api.github.com"


def _adapter(**kwargs) -> GitHubAdapter:
    return GitHubAdapter(token="t", default_repo="acme/widgets", **kwargs)


@respx.mock
async def test_codeowners_emits_one_rule_per_pattern():
    body = """# header line ignored

*       @core-team
src/api/* @api-team @secondary
docs/    @docs-team
"""
    encoded = base64.b64encode(body.encode()).decode()
    respx.get(f"{_BASE}/repos/acme/widgets/contents/.github/CODEOWNERS").mock(
        return_value=httpx.Response(
            200, json={"content": encoded, "encoding": "base64"}
        )
    )
    docs = await _adapter().fetch({"type": "codeowners"}, {})
    assert [d.kind for d in docs] == ["rule", "rule", "rule"]
    assert "@core-team" in docs[0].text
    assert "@api-team @secondary" in docs[1].text
    assert docs[0].severity == "must"
    assert docs[0].source.startswith("github://acme/widgets/.github/CODEOWNERS")


@respx.mock
async def test_codeowners_falls_back_to_root_path():
    respx.get(f"{_BASE}/repos/acme/widgets/contents/.github/CODEOWNERS").mock(
        return_value=httpx.Response(404, json={"message": "Not Found"})
    )
    body = base64.b64encode(b"* @core-team\n").decode()
    respx.get(f"{_BASE}/repos/acme/widgets/contents/CODEOWNERS").mock(
        return_value=httpx.Response(200, json={"content": body, "encoding": "base64"})
    )
    docs = await _adapter().fetch({"type": "codeowners"}, {})
    assert len(docs) == 1
    assert "/CODEOWNERS" in docs[0].source


@respx.mock
async def test_codeowners_missing_in_all_paths_raises():
    for p in (".github/CODEOWNERS", "CODEOWNERS", "docs/CODEOWNERS"):
        respx.get(f"{_BASE}/repos/acme/widgets/contents/{p}").mock(
            return_value=httpx.Response(404, json={"message": "Not Found"})
        )
    with pytest.raises(AdapterError, match="no CODEOWNERS"):
        await _adapter().fetch({"type": "codeowners"}, {})


@respx.mock
async def test_codeowners_severity_override():
    encoded = base64.b64encode(b"* @core-team\n").decode()
    respx.get(f"{_BASE}/repos/acme/widgets/contents/.github/CODEOWNERS").mock(
        return_value=httpx.Response(
            200, json={"content": encoded, "encoding": "base64"}
        )
    )
    docs = await _adapter().fetch(
        {"type": "codeowners"}, {"rules": {"severity": "should"}}
    )
    assert docs[0].severity == "should"


@respx.mock
async def test_branch_protection_emits_rules():
    respx.get(f"{_BASE}/repos/acme/widgets/branches/main/protection").mock(
        return_value=httpx.Response(
            200,
            json={
                "required_pull_request_reviews": {
                    "required_approving_review_count": 2,
                    "dismiss_stale_reviews": True,
                    "require_code_owner_reviews": True,
                },
                "required_status_checks": {
                    "strict": True,
                    "contexts": ["ci/test", "ci/lint"],
                },
                "enforce_admins": {"enabled": True},
                "required_linear_history": {"enabled": True},
                "allow_force_pushes": {"enabled": False},
            },
        )
    )
    docs = await _adapter().fetch(
        {"type": "branch_protection", "branch": "main"}, {}
    )
    texts = [d.text for d in docs]
    assert any("2 approving" in t for t in texts)
    assert any("dismissed" in t for t in texts)
    assert any("code-owner" in t for t in texts)
    assert any("ci/test, ci/lint" in t for t in texts)
    assert any("up to date" in t for t in texts)
    assert any("admins" in t for t in texts)
    assert any("linear history" in t for t in texts)
    assert any("Force pushes" in t for t in texts)
    assert all(d.kind == "rule" for d in docs)


@respx.mock
async def test_branch_protection_resolves_default_branch_when_omitted():
    respx.get(f"{_BASE}/repos/acme/widgets").mock(
        return_value=httpx.Response(200, json={"default_branch": "trunk"})
    )
    respx.get(f"{_BASE}/repos/acme/widgets/branches/trunk/protection").mock(
        return_value=httpx.Response(
            200,
            json={
                "required_pull_request_reviews": {
                    "required_approving_review_count": 1
                }
            },
        )
    )
    docs = await _adapter().fetch({"type": "branch_protection"}, {})
    assert any("trunk" in d.text for d in docs)


@respx.mock
async def test_recent_prs_emits_reasoning():
    respx.get(f"{_BASE}/repos/acme/widgets/pulls").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "number": 42,
                    "title": "Fix bug",
                    "user": {"login": "alice"},
                    "state": "open",
                    "draft": False,
                    "updated_at": "2026-06-01T10:00:00Z",
                },
                {
                    "number": 43,
                    "title": "WIP refactor",
                    "user": {"login": "bob"},
                    "state": "open",
                    "draft": True,
                    "updated_at": "2026-06-02T10:00:00Z",
                },
            ],
        )
    )
    docs = await _adapter().fetch({"type": "recent_prs", "limit": 2}, {})
    assert all(d.kind == "reasoning" for d in docs)
    assert "#42" in docs[0].text and "Fix bug" in docs[0].text
    assert "draft" in docs[1].text
    assert docs[0].recency == "2026-06-01T10:00:00Z"


@respx.mock
async def test_releases_emits_reasoning():
    respx.get(f"{_BASE}/repos/acme/widgets/releases").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "tag_name": "v1.2.0",
                    "name": "v1.2.0",
                    "published_at": "2026-05-01T00:00:00Z",
                    "body": "Notes here.",
                }
            ],
        )
    )
    docs = await _adapter().fetch({"type": "releases", "limit": 5}, {})
    assert len(docs) == 1
    assert "v1.2.0" in docs[0].text
    assert "Notes here." in docs[0].text
    assert docs[0].recency == "2026-05-01T00:00:00Z"


@respx.mock
async def test_unknown_query_type_raises():
    with pytest.raises(AdapterError, match="unknown query.type"):
        await _adapter().fetch({"type": "ghosts"}, {})


@respx.mock
async def test_unauthorized_raises_auth_error():
    respx.get(f"{_BASE}/repos/acme/widgets/contents/.github/CODEOWNERS").mock(
        return_value=httpx.Response(401, json={"message": "Bad credentials"})
    )
    with pytest.raises(AuthError, match="401"):
        await _adapter().fetch({"type": "codeowners"}, {})


def test_constructor_requires_token():
    with pytest.raises(AuthError, match="token is required"):
        GitHubAdapter(token="")


@respx.mock
async def test_health_ok_returns_rate_limit():
    respx.get(f"{_BASE}/rate_limit").mock(
        return_value=httpx.Response(
            200, json={"resources": {"core": {"remaining": 4999, "reset": 1700000000}}}
        )
    )
    h = await _adapter().health()
    assert h["ok"] is True
    assert h["rate_limit_remaining"] == 4999


@respx.mock
async def test_health_fails_on_auth_error():
    respx.get(f"{_BASE}/rate_limit").mock(
        return_value=httpx.Response(401, json={"message": "Bad credentials"})
    )
    h = await _adapter().health()
    assert h["ok"] is False
    assert "401" in h["detail"]


@respx.mock
async def test_repo_resolution_falls_back_to_query():
    a = GitHubAdapter(token="t")  # no default repo
    encoded = base64.b64encode(b"* @x\n").decode()
    respx.get(f"{_BASE}/repos/other/proj/contents/.github/CODEOWNERS").mock(
        return_value=httpx.Response(200, json={"content": encoded, "encoding": "base64"})
    )
    docs = await a.fetch({"type": "codeowners", "repo": "other/proj"}, {})
    assert len(docs) == 1


async def test_repo_required_when_neither_query_nor_default():
    a = GitHubAdapter(token="t")
    with pytest.raises(AdapterError, match="'repo' must be set"):
        await a.fetch({"type": "codeowners"}, {})
