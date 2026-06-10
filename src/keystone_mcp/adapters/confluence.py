"""Confluence adapter — Phase 3, refactored in Phase 8.

Reads context from Confluence Cloud via REST API v2. The native HTML body is
parsed once into the shared `Section` shape and handed to the shared
classifier in `_classify.py`.

Auth: basic (email + API token). Token from
https://id.atlassian.com/manage-profile/security/api-tokens.

Query types:

    type: page
        id: "12345"                  # OR
        title: "Deploy Runbook"
        space: ENG                   # space key (resolved → space-id)
        body: view                   # view|storage|atlas_doc_format (default view)
    type: space_pages
        space: ENG
        limit: 50                    # default 50
"""

from __future__ import annotations

import base64
from typing import Any

import httpx
from bs4 import BeautifulSoup, NavigableString, Tag

from ..errors import AdapterError, AuthError
from ..payload import ContextDoc
from ._classify import Section, SubBlock, classify_sections


def _between_siblings(start: Tag, stop_tags: tuple[str, ...]) -> list[Any]:
    out: list[Any] = []
    for sib in start.next_siblings:
        if isinstance(sib, Tag) and sib.name in stop_tags:
            break
        out.append(sib)
    return out


def _text_of(nodes: list[Any]) -> str:
    parts: list[str] = []
    for n in nodes:
        if isinstance(n, NavigableString):
            parts.append(str(n))
        elif isinstance(n, Tag):
            parts.append(n.get_text(" ", strip=False))
    return "\n".join(p.strip() for p in "\n".join(parts).splitlines() if p.strip())


def _bullets_in(nodes: list[Any]) -> list[str]:
    out: list[str] = []
    for n in nodes:
        if not isinstance(n, Tag):
            continue
        if n.name in ("ul", "ol"):
            for li in n.find_all("li", recursive=False):
                out.append(li.get_text(" ", strip=True))
    return out


def _sub_blocks_in(nodes: list[Any]) -> list[SubBlock]:
    blocks: list[SubBlock] = []
    current_name: str | None = None
    current: list[Any] = []
    for n in nodes:
        if isinstance(n, Tag) and n.name == "h3":
            if current_name is not None:
                blocks.append(_sub_block(current_name, current))
            current_name = n.get_text(" ", strip=True)
            current = []
        else:
            if current_name is not None:
                current.append(n)
    if current_name is not None:
        blocks.append(_sub_block(current_name, current))
    return blocks


def _sub_block(name: str, nodes: list[Any]) -> SubBlock:
    code = ""
    remaining: list[Any] = []
    for n in nodes:
        if not code and isinstance(n, Tag) and n.name in ("pre", "code"):
            code = n.get_text("\n", strip=True)
            continue
        if not code and isinstance(n, Tag):
            inner = n.find(["pre", "code"])
            if inner is not None:
                code = inner.get_text("\n", strip=True)
                inner.decompose()
        remaining.append(n)
    return SubBlock(name=name, body=_text_of(remaining), code=code)


def _parse_sections(html: str) -> tuple[list[Section], BeautifulSoup]:
    soup = BeautifulSoup(html, "html.parser")
    sections: list[Section] = []
    for h2 in soup.find_all("h2"):
        heading = h2.get_text(" ", strip=True)
        nodes = _between_siblings(h2, stop_tags=("h2",))
        sections.append(
            Section(
                heading=heading,
                bullets=_bullets_in(nodes),
                sub_blocks=_sub_blocks_in(nodes),
                body=_text_of(nodes),
            )
        )
    return sections, soup


class ConfluenceAdapter:
    name = "confluence"

    def __init__(
        self,
        *,
        base_url: str,
        email: str,
        token: str,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if not token:
            raise AuthError("confluence adapter: token is required")
        if not email:
            raise AuthError("confluence adapter: email is required")
        if not base_url:
            raise AdapterError("confluence adapter: base_url is required")
        self._base_url = base_url.rstrip("/")
        self._email = email
        self._token = token
        self._client = client
        self._space_id_cache: dict[str, str] = {}

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
            raise AuthError(f"confluence adapter: 401 unauthorized at {path}")
        if resp.status_code == 403:
            raise AdapterError(
                f"confluence adapter: 403 forbidden at {path} ({resp.text[:200]})"
            )
        if resp.status_code == 404:
            raise AdapterError(f"confluence adapter: 404 not found at {path}")
        if resp.status_code >= 400:
            raise AdapterError(
                f"confluence adapter: {resp.status_code} from {path} ({resp.text[:200]})"
            )
        return resp

    async def _resolve_space_id(self, space_key: str) -> str:
        if space_key in self._space_id_cache:
            return self._space_id_cache[space_key]
        resp = await self._get(
            "/wiki/api/v2/spaces", params={"keys": space_key, "limit": 1}
        )
        results = resp.json().get("results") or []
        if not results:
            raise AdapterError(
                f"confluence adapter: no space found with key {space_key!r}"
            )
        sid = str(results[0].get("id"))
        self._space_id_cache[space_key] = sid
        return sid

    async def _resolve_page(self, query: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        page_id = query.get("id")
        body_format = query.get("body") or "view"
        if body_format not in ("view", "storage", "atlas_doc_format"):
            raise AdapterError(
                f"confluence adapter: query.body must be view|storage|atlas_doc_format, got {body_format!r}"
            )
        if page_id:
            resp = await self._get(
                f"/wiki/api/v2/pages/{page_id}",
                params={"body-format": body_format},
            )
            return str(page_id), resp.json()
        title = query.get("title")
        space_key = query.get("space")
        if not (title and space_key):
            raise AdapterError(
                "confluence adapter: query must include either 'id' or both 'title' and 'space'"
            )
        space_id = await self._resolve_space_id(space_key)
        resp = await self._get(
            "/wiki/api/v2/pages",
            params={
                "title": title,
                "space-id": space_id,
                "body-format": body_format,
                "limit": 1,
            },
        )
        results = resp.json().get("results") or []
        if not results:
            raise AdapterError(
                f"confluence adapter: no page titled {title!r} in space {space_key!r}"
            )
        return str(results[0].get("id")), results[0]

    async def _emit_page(
        self, query: dict[str, Any], classify: dict[str, Any]
    ) -> list[ContextDoc]:
        page_id, page = await self._resolve_page(query)
        body = (page.get("body") or {}).get(query.get("body") or "view") or {}
        html = body.get("value", "")
        source_base = f"confluence://{page_id}"
        if not html:
            return []
        sections, soup = _parse_sections(html)
        fallback = soup.get_text("\n", strip=True)
        return classify_sections(
            sections=sections,
            source_base=source_base,
            classify=classify,
            adapter_name=self.name,
            fallback_reasoning_body=fallback,
        )

    async def _emit_space_pages(
        self, query: dict[str, Any]
    ) -> list[ContextDoc]:
        space_key = query.get("space")
        if not space_key:
            raise AdapterError(
                "confluence adapter: space_pages requires query.space"
            )
        limit = int(query.get("limit") or 50)
        space_id = await self._resolve_space_id(space_key)
        resp = await self._get(
            f"/wiki/api/v2/spaces/{space_id}/pages",
            params={"limit": limit},
        )
        docs: list[ContextDoc] = []
        for page in (resp.json().get("results") or [])[:limit]:
            pid = page.get("id")
            title = page.get("title", "(untitled)")
            version = page.get("version") or {}
            updated = version.get("createdAt") or ""
            text = f"{title} (id {pid})"
            docs.append(
                ContextDoc(
                    kind="reasoning",
                    text=text,
                    source=f"confluence://{pid}",
                    recency=updated or None,
                )
            )
        return docs

    async def fetch(
        self, query: dict[str, Any], classify: dict[str, Any]
    ) -> list[ContextDoc]:
        qtype = query.get("type")
        if not qtype:
            raise AdapterError("confluence adapter: query.type is required")
        if qtype == "page":
            return await self._emit_page(query, classify)
        if qtype == "space_pages":
            return await self._emit_space_pages(query)
        raise AdapterError(
            f"confluence adapter: unknown query.type {qtype!r} (known: page, space_pages)"
        )

    async def health(self) -> dict[str, Any]:
        try:
            resp = await self._get("/wiki/api/v2/spaces", params={"limit": 1})
        except (AdapterError, AuthError) as exc:
            return {"source": self.name, "ok": False, "detail": str(exc)}
        return {
            "source": self.name,
            "ok": True,
            "base_url": self._base_url,
            "spaces_visible": len(resp.json().get("results") or []),
        }
