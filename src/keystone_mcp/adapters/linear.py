"""Linear adapter — Phase 6.

Reads context from Linear via the GraphQL API.

Auth: personal API key. Token from Settings → API → Personal API keys. Linear
expects the raw key in the `Authorization` header — *not* `Bearer <key>`.

Query types:

    type: issue
        id: PORT-123                  # team identifier or UUID
    type: issues
        filter: { ... }               # IssueFilter input passed through verbatim
        limit: 25                     # default 25

`filter` is forwarded as the GraphQL `IssueFilter` variable. Common shapes:

    filter:
      assignee: { isMe: { eq: true } }
      state: { type: { neq: completed } }
    filter:
      team: { key: { eq: PORT } }
      priority: { in: [1, 2] }

Output kind: reasoning for both. Issues are facts about in-flight work, not
constraints the agent must obey.

Each issue produces one reasoning doc with a structured summary line:
`{identifier} [{state}, priority {N}] assignee={name}: {title}`. For the
`issue` query the description is appended below as markdown text; for `issues`
the result is the summary line only.
"""

from __future__ import annotations

from typing import Any

import httpx

from ..errors import AdapterError, AuthError
from ..payload import ContextDoc


_DEFAULT_URL = "https://api.linear.app/graphql"

_ISSUE_QUERY = """
query Issue($id: String!) {
  issue(id: $id) {
    identifier
    title
    description
    priority
    updatedAt
    url
    state { name type }
    assignee { name }
    team { key }
  }
}
""".strip()

_ISSUES_QUERY = """
query Issues($filter: IssueFilter, $first: Int) {
  issues(filter: $filter, first: $first) {
    nodes {
      identifier
      title
      priority
      updatedAt
      url
      state { name type }
      assignee { name }
      team { key }
    }
  }
}
""".strip()

_VIEWER_QUERY = "query { viewer { id name email } }"


def _summary_line(issue: dict[str, Any]) -> str:
    ident = issue.get("identifier") or "?"
    title = issue.get("title") or ""
    state = (issue.get("state") or {}).get("name") or "?"
    priority = issue.get("priority")
    priority_str = f"priority {priority}" if priority is not None else "priority -"
    assignee = (issue.get("assignee") or {}).get("name") or "unassigned"
    return f"{ident} [{state}, {priority_str}] assignee={assignee}: {title}"


def _source_for(issue: dict[str, Any]) -> str:
    return issue.get("url") or f"linear://{issue.get('identifier') or 'unknown'}"


class LinearAdapter:
    name = "linear"

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = _DEFAULT_URL,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if not api_key:
            raise AuthError("linear adapter: api_key is required")
        self._api_key = api_key
        self._base_url = base_url
        self._client = client

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": self._api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    async def _graphql(
        self, query: str, variables: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        client = self._client or httpx.AsyncClient()
        owns_client = self._client is None
        payload = {"query": query, "variables": variables or {}}
        try:
            resp = await client.post(
                self._base_url, headers=self._headers(), json=payload
            )
        finally:
            if owns_client:
                await client.aclose()
        if resp.status_code == 401:
            raise AuthError("linear adapter: 401 unauthorized")
        if resp.status_code >= 400:
            raise AdapterError(
                f"linear adapter: HTTP {resp.status_code} ({resp.text[:200]})"
            )
        body = resp.json()
        errs = body.get("errors") or []
        if errs:
            msg = "; ".join(e.get("message", "") for e in errs)
            auth_like = any(
                "AUTHENTICATION"
                in ((e.get("extensions") or {}).get("code") or "").upper()
                for e in errs
            )
            if auth_like:
                raise AuthError(f"linear adapter: {msg}")
            raise AdapterError(f"linear adapter: GraphQL error: {msg}")
        return body.get("data") or {}

    async def _emit_issue(self, query: dict[str, Any]) -> list[ContextDoc]:
        ident = query.get("id")
        if not ident:
            raise AdapterError("linear adapter: issue query requires 'id'")
        data = await self._graphql(_ISSUE_QUERY, {"id": str(ident)})
        issue = data.get("issue")
        if not issue:
            raise AdapterError(f"linear adapter: no issue with id {ident!r}")
        line = _summary_line(issue)
        body = (issue.get("description") or "").strip()
        text = f"{line}\n\n{body}" if body else line
        return [
            ContextDoc(
                kind="reasoning",
                text=text,
                source=_source_for(issue),
                recency=issue.get("updatedAt"),
            )
        ]

    async def _emit_issues(self, query: dict[str, Any]) -> list[ContextDoc]:
        filter_ = query.get("filter")
        if filter_ is not None and not isinstance(filter_, dict):
            raise AdapterError(
                "linear adapter: issues.filter must be a mapping"
            )
        limit = int(query.get("limit") or 25)
        data = await self._graphql(
            _ISSUES_QUERY,
            {"filter": filter_ or None, "first": min(limit, 100)},
        )
        nodes = ((data.get("issues") or {}).get("nodes") or [])[:limit]
        docs: list[ContextDoc] = []
        for issue in nodes:
            docs.append(
                ContextDoc(
                    kind="reasoning",
                    text=_summary_line(issue),
                    source=_source_for(issue),
                    recency=issue.get("updatedAt"),
                )
            )
        return docs

    async def fetch(
        self, query: dict[str, Any], classify: dict[str, Any]
    ) -> list[ContextDoc]:
        qtype = query.get("type")
        if not qtype:
            raise AdapterError("linear adapter: query.type is required")
        if qtype == "issue":
            return await self._emit_issue(query)
        if qtype == "issues":
            return await self._emit_issues(query)
        raise AdapterError(
            f"linear adapter: unknown query.type {qtype!r} (known: issue, issues)"
        )

    async def health(self) -> dict[str, Any]:
        try:
            data = await self._graphql(_VIEWER_QUERY)
        except (AdapterError, AuthError) as exc:
            return {"source": self.name, "ok": False, "detail": str(exc)}
        viewer = data.get("viewer") or {}
        return {
            "source": self.name,
            "ok": True,
            "viewer_id": viewer.get("id"),
            "viewer_name": viewer.get("name"),
        }
