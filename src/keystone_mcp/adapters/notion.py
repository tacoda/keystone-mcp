"""Notion adapter — Phase 4.

Reads context from Notion via the public REST API.

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

Output kinds:

    page      → classified per `classify` block (rules/reasoning/skills/commands)
                parsed from the page's top-level block children
    database  → reasoning, one per row (title + page id + last_edited_time)

`classify` selector vocabulary matches the markdown/confluence adapters:

    classify:
      rules:    { heading: "Rules", severity: must }
      reasoning: { heading: "Background" }
      skills:   { heading: "Procedures" }
      commands: { heading: "Commands" }

Section split is by `heading_2`; inside skills/commands sections, each
`heading_3` delimits one entry. For commands, the first `code` block in the
entry becomes the invocation; remaining text becomes the description.

Phase 4 walks top-level children only — nested list items are flattened to
their parent's text. Multi-page block listings are paginated.
"""

from __future__ import annotations

import re
from typing import Any

import httpx

from ..errors import AdapterError, AuthError
from ..payload import ContextDoc, Severity


_NOTION_API = "https://api.notion.com/v1"
_DEFAULT_VERSION = "2022-06-28"
_SEVERITY_PREFIX_RE = re.compile(r"^(MUST|SHOULD|MAY)\b[:.\s]*(.+)$", re.IGNORECASE)


def _slugify(text: str) -> str:
    out = re.sub(r"[^a-zA-Z0-9]+", "-", text.strip().lower()).strip("-")
    return out or "section"


def _headings_of(selector: dict[str, Any] | None) -> set[str]:
    if not selector:
        return set()
    h = selector.get("heading")
    if h is None:
        return set()
    if isinstance(h, str):
        return {h.strip().lower()}
    if isinstance(h, list):
        return {str(x).strip().lower() for x in h}
    raise AdapterError(
        f"notion adapter: classify.heading must be string or list, got {type(h).__name__}"
    )


def _severity_default(classify: dict[str, Any]) -> Severity:
    rules = classify.get("rules")
    if isinstance(rules, dict):
        sev = rules.get("severity", "must")
        if sev not in ("must", "should", "may"):
            raise AdapterError(
                f"notion adapter: classify.rules.severity must be must|should|may, got {sev!r}"
            )
        return sev  # type: ignore[return-value]
    return "must"


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
    parts = [t for t in (_block_text(b) for b in blocks) if t]
    return "\n".join(parts)


def _split_by_h2(
    blocks: list[dict[str, Any]],
) -> list[tuple[str, list[dict[str, Any]]]]:
    sections: list[tuple[str, list[dict[str, Any]]]] = []
    current_name: str | None = None
    current: list[dict[str, Any]] = []
    for b in blocks:
        if b.get("type") == "heading_2":
            if current_name is not None:
                sections.append((current_name, current))
            current_name = _rich_text_plain((b.get("heading_2") or {}).get("rich_text"))
            current = []
        else:
            if current_name is not None:
                current.append(b)
    if current_name is not None:
        sections.append((current_name, current))
    return sections


def _split_by_h3(
    blocks: list[dict[str, Any]],
) -> list[tuple[str, list[dict[str, Any]]]]:
    groups: list[tuple[str, list[dict[str, Any]]]] = []
    current_name: str | None = None
    current: list[dict[str, Any]] = []
    for b in blocks:
        if b.get("type") == "heading_3":
            if current_name is not None:
                groups.append((current_name, current))
            current_name = _rich_text_plain((b.get("heading_3") or {}).get("rich_text"))
            current = []
        else:
            if current_name is not None:
                current.append(b)
    if current_name is not None:
        groups.append((current_name, current))
    return groups


def _extract_rules(
    section_blocks: list[dict[str, Any]],
    *,
    source_base: str,
    heading_slug: str,
    default_severity: Severity,
) -> list[ContextDoc]:
    out: list[ContextDoc] = []
    idx = 0
    for b in section_blocks:
        if b.get("type") not in ("bulleted_list_item", "numbered_list_item"):
            continue
        text = _block_text(b).strip()
        if not text:
            continue
        severity: Severity = default_severity
        m = _SEVERITY_PREFIX_RE.match(text)
        if m and m.group(1).lower() in ("must", "should", "may"):
            severity = m.group(1).lower()  # type: ignore[assignment]
            text = m.group(2).strip()
        idx += 1
        out.append(
            ContextDoc(
                kind="rule",
                text=text,
                source=f"{source_base}#{heading_slug}",
                severity=severity,
                id=f"{heading_slug}-{idx:03d}",
            )
        )
    return out


def _extract_reasoning(
    section_blocks: list[dict[str, Any]], *, source_base: str, heading_slug: str
) -> list[ContextDoc]:
    text = _blocks_to_text(section_blocks)
    if not text:
        return []
    return [
        ContextDoc(
            kind="reasoning", text=text, source=f"{source_base}#{heading_slug}"
        )
    ]


def _extract_skills(
    section_blocks: list[dict[str, Any]], *, source_base: str, heading_slug: str
) -> list[ContextDoc]:
    out: list[ContextDoc] = []
    idx = 0
    for name, group in _split_by_h3(section_blocks):
        body = _blocks_to_text(group)
        idx += 1
        sub_slug = _slugify(name)
        out.append(
            ContextDoc(
                kind="skill",
                text=body,
                source=f"{source_base}#{heading_slug}/{sub_slug}",
                name=name,
                id=f"{heading_slug}-{idx:03d}",
            )
        )
    return out


def _extract_commands(
    section_blocks: list[dict[str, Any]], *, source_base: str, heading_slug: str
) -> list[ContextDoc]:
    out: list[ContextDoc] = []
    idx = 0
    for name, group in _split_by_h3(section_blocks):
        invocation = ""
        non_code: list[dict[str, Any]] = []
        for b in group:
            if not invocation and b.get("type") == "code":
                invocation = _block_text(b).strip()
                continue
            non_code.append(b)
        description = _blocks_to_text(non_code)
        idx += 1
        sub_slug = _slugify(name)
        out.append(
            ContextDoc(
                kind="command",
                text=description,
                source=f"{source_base}#{heading_slug}/{sub_slug}",
                name=name,
                invocation=invocation,
                id=f"{heading_slug}-{idx:03d}",
            )
        )
    return out


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

        rule_h = _headings_of(classify.get("rules"))
        reasoning_h = _headings_of(classify.get("reasoning"))
        skill_h = _headings_of(classify.get("skills"))
        command_h = _headings_of(classify.get("commands"))
        reasoning_all = bool(
            isinstance(classify.get("reasoning"), dict)
            and classify["reasoning"].get("all")
        )
        default_severity = _severity_default(classify)

        anything = (
            rule_h or reasoning_h or skill_h or command_h or reasoning_all
        )
        if not anything:
            text = _blocks_to_text(blocks)
            if not text:
                return []
            return [
                ContextDoc(kind="reasoning", text=text, source=source_base)
            ]

        docs: list[ContextDoc] = []
        for heading, section_blocks in _split_by_h2(blocks):
            lower = heading.lower()
            slug = _slugify(heading)
            if lower in rule_h:
                docs.extend(
                    _extract_rules(
                        section_blocks,
                        source_base=source_base,
                        heading_slug=slug,
                        default_severity=default_severity,
                    )
                )
            elif lower in skill_h:
                docs.extend(
                    _extract_skills(
                        section_blocks,
                        source_base=source_base,
                        heading_slug=slug,
                    )
                )
            elif lower in command_h:
                docs.extend(
                    _extract_commands(
                        section_blocks,
                        source_base=source_base,
                        heading_slug=slug,
                    )
                )
            elif lower in reasoning_h or reasoning_all:
                docs.extend(
                    _extract_reasoning(
                        section_blocks,
                        source_base=source_base,
                        heading_slug=slug,
                    )
                )
        return docs

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
