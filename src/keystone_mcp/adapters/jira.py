"""Jira adapter — Phase 5.

Reads context from Jira Cloud via REST API v3.

Auth: basic (email + API token). Token from
https://id.atlassian.com/manage-profile/security/api-tokens.

Query types:

    type: issue
        key: PORT-673
    type: jql
        jql: "assignee = currentUser() AND statusCategory != Done"
        limit: 25                    # default 25 (capped at 100 per Jira)

Output kind: reasoning for both. Issues are facts about in-flight work, not
constraints the agent must obey; the agent should treat them as background.

Each issue produces one reasoning doc with a structured summary line and
(for the `issue` query only) the description body as plain text extracted
from ADF (Atlassian Document Format).
"""

from __future__ import annotations

import base64
from typing import Any

import httpx

from ..errors import AdapterError, AuthError
from ..payload import ContextDoc


_ADF_BLOCK_TYPES = (
    "paragraph",
    "heading",
    "list_item",
    "bulletList",
    "orderedList",
    "codeBlock",
    "blockquote",
    "rule",
)


def _adf_to_text(node: Any) -> str:
    """Walk an Atlassian Document Format tree and emit plain text.

    Phase 5 ignores marks, inline images, mentions, and hard breaks. Block
    boundaries emit a newline so the result is readable line-by-line.
    """
    parts: list[str] = []

    def visit(n: Any) -> None:
        if not isinstance(n, dict):
            return
        for child in n.get("content") or []:
            visit(child)
        t = n.get("type")
        if t == "text":
            parts.append(n.get("text", ""))
        elif t in _ADF_BLOCK_TYPES:
            parts.append("\n")

    visit(node)
    return "\n".join(
        line.strip() for line in "".join(parts).splitlines() if line.strip()
    )


def _summary_line(key: str, fields: dict[str, Any]) -> str:
    summary = fields.get("summary", "")
    status = (fields.get("status") or {}).get("name", "?")
    assignee_obj = fields.get("assignee") or {}
    assignee = assignee_obj.get("displayName") or "unassigned"
    itype = (fields.get("issuetype") or {}).get("name") or "issue"
    return f"{key} [{itype}, {status}] assignee={assignee}: {summary}"


class JiraAdapter:
    name = "jira"

    def __init__(
        self,
        *,
        base_url: str,
        email: str,
        token: str,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if not base_url:
            raise AdapterError("jira adapter: base_url is required")
        if not email:
            raise AuthError("jira adapter: email is required")
        if not token:
            raise AuthError("jira adapter: token is required")
        self._base_url = base_url.rstrip("/")
        self._email = email
        self._token = token
        self._client = client

    def _headers(self) -> dict[str, str]:
        cred = base64.b64encode(f"{self._email}:{self._token}".encode()).decode()
        return {
            "Authorization": f"Basic {cred}",
            "Accept": "application/json",
        }

    async def _get(
        self, path: str, *, params: dict[str, Any] | None = None
    ) -> httpx.Response:
        url = f"{self._base_url}{path}"
        client = self._client or httpx.AsyncClient()
        owns_client = self._client is None
        try:
            resp = await client.get(url, headers=self._headers(), params=params)
        finally:
            if owns_client:
                await client.aclose()
        if resp.status_code == 401:
            raise AuthError(f"jira adapter: 401 unauthorized at {path}")
        if resp.status_code == 403:
            raise AdapterError(
                f"jira adapter: 403 forbidden at {path} ({resp.text[:200]})"
            )
        if resp.status_code == 404:
            raise AdapterError(f"jira adapter: 404 not found at {path}")
        if resp.status_code >= 400:
            raise AdapterError(
                f"jira adapter: {resp.status_code} from {path} ({resp.text[:200]})"
            )
        return resp

    def _issue_source(self, key: str) -> str:
        return f"{self._base_url}/browse/{key}"

    async def _emit_issue(self, query: dict[str, Any]) -> list[ContextDoc]:
        key = query.get("key")
        if not key:
            raise AdapterError("jira adapter: issue query requires 'key'")
        resp = await self._get(
            f"/rest/api/3/issue/{key}",
            params={
                "fields": "summary,status,assignee,issuetype,updated,description"
            },
        )
        data = resp.json()
        fields = data.get("fields") or {}
        line = _summary_line(str(key), fields)
        body = _adf_to_text(fields.get("description"))
        text = f"{line}\n\n{body}" if body else line
        return [
            ContextDoc(
                kind="reasoning",
                text=text,
                source=self._issue_source(str(key)),
                recency=fields.get("updated"),
            )
        ]

    async def _emit_jql(self, query: dict[str, Any]) -> list[ContextDoc]:
        jql = query.get("jql")
        if not jql:
            raise AdapterError("jira adapter: jql query requires 'jql'")
        limit = int(query.get("limit") or 25)
        resp = await self._get(
            "/rest/api/3/search",
            params={
                "jql": jql,
                "maxResults": min(limit, 100),
                "fields": "summary,status,assignee,issuetype,updated",
            },
        )
        data = resp.json()
        docs: list[ContextDoc] = []
        for issue in (data.get("issues") or [])[:limit]:
            key = issue.get("key", "")
            fields = issue.get("fields") or {}
            docs.append(
                ContextDoc(
                    kind="reasoning",
                    text=_summary_line(str(key), fields),
                    source=self._issue_source(str(key)),
                    recency=fields.get("updated"),
                )
            )
        return docs

    async def fetch(
        self, query: dict[str, Any], classify: dict[str, Any]
    ) -> list[ContextDoc]:
        qtype = query.get("type")
        if not qtype:
            raise AdapterError("jira adapter: query.type is required")
        if qtype == "issue":
            return await self._emit_issue(query)
        if qtype == "jql":
            return await self._emit_jql(query)
        raise AdapterError(
            f"jira adapter: unknown query.type {qtype!r} (known: issue, jql)"
        )

    async def health(self) -> dict[str, Any]:
        try:
            resp = await self._get("/rest/api/3/myself")
        except (AdapterError, AuthError) as exc:
            return {"source": self.name, "ok": False, "detail": str(exc)}
        data = resp.json()
        return {
            "source": self.name,
            "ok": True,
            "base_url": self._base_url,
            "account_id": data.get("accountId"),
            "display_name": data.get("displayName"),
        }
