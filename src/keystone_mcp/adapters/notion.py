"""Notion adapter — Phase 4, refactored in Phase 8.

Reads context from Notion via the public REST API. The native block-list is
walked once into the shared `Section` shape and handed to the shared
classifier in `_classify.py`.

Auth: integration token (`Authorization: Bearer <token>`). Token from
https://www.notion.so/my-integrations. Pages and databases must be shared
with the integration.

Query types:

    type: page
        id: "<page-id>"              # OR
        title: "Deploy Runbook"      # case-insensitive exact match via /search
    type: database
        id: "<database-id>"
        limit: 50                    # default 50
"""

from __future__ import annotations

from typing import Any

import httpx

from ..errors import AdapterError, AuthError
from ..payload import ContextDoc
from ._classify import Section, SubBlock, classify_sections


_NOTION_API = "https://api.notion.com/v1"
_DEFAULT_VERSION = "2022-06-28"


def _rich_text_plain(rich: list[dict[str, Any]] | None) -> str:
    if not rich:
        return ""
    return "".join(r.get("plain_text", "") for r in rich)


def _block_text(block: dict[str, Any]) -> str:
    btype = block.get("type")
    if not btype:
        return ""
    data = block.get(btype) or {}
    rich = data.get("rich_text")
    if isinstance(rich, list):
        return _rich_text_plain(rich)
    return ""


def _blocks_to_text(blocks: list[dict[str, Any]]) -> str:
    return "\n".join(t for t in (_block_text(b) for b in blocks) if t)


def _bullets_in(blocks: list[dict[str, Any]]) -> list[str]:
    out: list[str] = []
    for b in blocks:
        if b.get("type") in ("bulleted_list_item", "numbered_list_item"):
            t = _block_text(b).strip()
            if t:
                out.append(t)
    return out


def _sub_blocks_in(blocks: list[dict[str, Any]]) -> list[SubBlock]:
    out: list[SubBlock] = []
    current_name: str | None = None
    current: list[dict[str, Any]] = []
    for b in blocks:
        if b.get("type") == "heading_3":
            if current_name is not None:
                out.append(_sub_block(current_name, current))
            current_name = _rich_text_plain(
                (b.get("heading_3") or {}).get("rich_text")
            )
            current = []
        else:
            if current_name is not None:
                current.append(b)
    if current_name is not None:
        out.append(_sub_block(current_name, current))
    return out


def _sub_block(name: str, blocks: list[dict[str, Any]]) -> SubBlock:
    code = ""
    non_code: list[dict[str, Any]] = []
    for b in blocks:
        if not code and b.get("type") == "code":
            code = _block_text(b).strip()
            continue
        non_code.append(b)
    return SubBlock(name=name, body=_blocks_to_text(non_code), code=code)


def _parse_sections(blocks: list[dict[str, Any]]) -> list[Section]:
    sections: list[Section] = []
    current_name: str | None = None
    current: list[dict[str, Any]] = []

    def flush() -> None:
        nonlocal current_name, current
        if current_name is None:
            return
        sections.append(
            Section(
                heading=current_name,
                bullets=_bullets_in(current),
                sub_blocks=_sub_blocks_in(current),
                body=_blocks_to_text(current),
            )
        )

    for b in blocks:
        if b.get("type") == "heading_2":
            flush()
            current_name = _rich_text_plain(
                (b.get("heading_2") or {}).get("rich_text")
            )
            current = []
        else:
            if current_name is not None:
                current.append(b)
    flush()
    return sections


def _title_from_properties(properties: dict[str, Any]) -> str:
    for prop in properties.values():
        if isinstance(prop, dict) and prop.get("type") == "title":
            return _rich_text_plain(prop.get("title"))
    return "(untitled)"


class NotionAdapter:
    name = "notion"

    def __init__(
        self,
        *,
        token: str,
        notion_version: str = _DEFAULT_VERSION,
        base_url: str = _NOTION_API,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if not token:
            raise AuthError("notion adapter: token is required")
        self._token = token
        self._version = notion_version
        self._base_url = base_url.rstrip("/")
        self._client = client

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token}",
            "Notion-Version": self._version,
            "Accept": "application/json",
        }

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> httpx.Response:
        url = f"{self._base_url}{path}"
        client = self._client or httpx.AsyncClient()
        owns_client = self._client is None
        try:
            resp = await client.request(
                method, url, headers=self._headers(), params=params, json=json
            )
        finally:
            if owns_client:
                await client.aclose()
        if resp.status_code == 401:
            raise AuthError(f"notion adapter: 401 unauthorized at {path}")
        if resp.status_code == 403:
            raise AdapterError(
                f"notion adapter: 403 forbidden at {path} ({resp.text[:200]})"
            )
        if resp.status_code == 404:
            raise AdapterError(f"notion adapter: 404 not found at {path}")
        if resp.status_code >= 400:
            raise AdapterError(
                f"notion adapter: {resp.status_code} from {path} ({resp.text[:200]})"
            )
        return resp

    async def _get(
        self, path: str, *, params: dict[str, Any] | None = None
    ) -> httpx.Response:
        return await self._request("GET", path, params=params)

    async def _post(
        self, path: str, *, json: dict[str, Any] | None = None
    ) -> httpx.Response:
        return await self._request("POST", path, json=json)

    async def _resolve_page_id(self, query: dict[str, Any]) -> str:
        pid = query.get("id")
        if pid:
            return str(pid)
        title = query.get("title")
        if not title:
            raise AdapterError(
                "notion adapter: page query requires either 'id' or 'title'"
            )
        resp = await self._post(
            "/search",
            json={
                "query": title,
                "filter": {"value": "page", "property": "object"},
                "page_size": 25,
            },
        )
        results = resp.json().get("results") or []
        target = title.strip().lower()
        for page in results:
            if page.get("object") != "page":
                continue
            ptitle = _title_from_properties(page.get("properties") or {})
            if ptitle.strip().lower() == target:
                return str(page.get("id"))
        raise AdapterError(
            f"notion adapter: no page titled {title!r} accessible to this integration"
        )

    async def _fetch_blocks(self, page_id: str) -> list[dict[str, Any]]:
        blocks: list[dict[str, Any]] = []
        cursor: str | None = None
        while True:
            params: dict[str, Any] = {"page_size": 100}
            if cursor:
                params["start_cursor"] = cursor
            resp = await self._get(
                f"/blocks/{page_id}/children", params=params
            )
            data = resp.json()
            blocks.extend(data.get("results") or [])
            if not data.get("has_more"):
                break
            cursor = data.get("next_cursor")
            if not cursor:
                break
        return blocks

    async def _emit_page(
        self, query: dict[str, Any], classify: dict[str, Any]
    ) -> list[ContextDoc]:
        page_id = await self._resolve_page_id(query)
        blocks = await self._fetch_blocks(page_id)
        source_base = f"notion://{page_id}"
        return classify_sections(
            sections=_parse_sections(blocks),
            source_base=source_base,
            classify=classify,
            adapter_name=self.name,
            fallback_reasoning_body=_blocks_to_text(blocks),
        )

    async def _emit_database(self, query: dict[str, Any]) -> list[ContextDoc]:
        db_id = query.get("id")
        if not db_id:
            raise AdapterError("notion adapter: database query requires 'id'")
        limit = int(query.get("limit") or 50)
        page_size = min(limit, 100)
        resp = await self._post(
            f"/databases/{db_id}/query",
            json={"page_size": page_size},
        )
        docs: list[ContextDoc] = []
        for page in (resp.json().get("results") or [])[:limit]:
            pid = page.get("id")
            title = _title_from_properties(page.get("properties") or {})
            last_edited = page.get("last_edited_time") or None
            url = page.get("url") or f"notion://{pid}"
            docs.append(
                ContextDoc(
                    kind="reasoning",
                    text=f"{title} (id {pid})",
                    source=url,
                    recency=last_edited,
                )
            )
        return docs

    async def fetch(
        self, query: dict[str, Any], classify: dict[str, Any]
    ) -> list[ContextDoc]:
        qtype = query.get("type")
        if not qtype:
            raise AdapterError("notion adapter: query.type is required")
        if qtype == "page":
            return await self._emit_page(query, classify)
        if qtype == "database":
            return await self._emit_database(query)
        raise AdapterError(
            f"notion adapter: unknown query.type {qtype!r} (known: page, database)"
        )

    async def health(self) -> dict[str, Any]:
        try:
            resp = await self._get("/users/me")
        except (AdapterError, AuthError) as exc:
            return {"source": self.name, "ok": False, "detail": str(exc)}
        data = resp.json()
        return {
            "source": self.name,
            "ok": True,
            "bot": (data.get("bot") or {}).get("workspace_name") or data.get("name"),
            "type": data.get("type"),
        }
