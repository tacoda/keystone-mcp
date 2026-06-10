"""Confluence adapter — Phase 3.

Reads context from Confluence Cloud via REST API v2.

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

Output kinds:

    page         → classified per `classify` block (rules/reasoning/skills/commands)
                   parsed from the page's rendered HTML
    space_pages  → reasoning, one per page (title + URL + updated_at as recency)

`classify` vocabulary is the same as the markdown adapter:

    classify:
      rules:    { heading: "Rules", severity: must }
      reasoning: { heading: "Background" }
      skills:   { heading: "Procedures" }
      commands: { heading: "Commands" }

Sections are delimited by H2 headings. Inside skills/commands sections, each
H3 sub-heading delimits one entry. For commands, the first `<pre>` or `<code>`
block in the entry becomes the invocation; the remaining text becomes the
description.
"""

from __future__ import annotations

import base64
import re
from typing import Any

import httpx
from bs4 import BeautifulSoup, NavigableString, Tag

from ..errors import AdapterError, AuthError
from ..payload import ContextDoc, Severity


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
        f"confluence adapter: classify.heading must be string or list, got {type(h).__name__}"
    )


def _severity_default(classify: dict[str, Any]) -> Severity:
    rules = classify.get("rules")
    if isinstance(rules, dict):
        sev = rules.get("severity", "must")
        if sev not in ("must", "should", "may"):
            raise AdapterError(
                f"confluence adapter: classify.rules.severity must be must|should|may, got {sev!r}"
            )
        return sev  # type: ignore[return-value]
    return "must"


def _between_siblings(start: Tag, stop_tags: tuple[str, ...]) -> list[Any]:
    """Collect siblings after `start` until a tag in `stop_tags` (any level)."""
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


def _h3_groups_in(nodes: list[Any]) -> list[tuple[str, list[Any]]]:
    """Split a section's nodes by H3 headings → [(name, nodes_in_group), ...]."""
    groups: list[tuple[str, list[Any]]] = []
    current_name: str | None = None
    current: list[Any] = []
    for n in nodes:
        if isinstance(n, Tag) and n.name == "h3":
            if current_name is not None:
                groups.append((current_name, current))
            current_name = n.get_text(" ", strip=True)
            current = []
        else:
            if current_name is not None:
                current.append(n)
    if current_name is not None:
        groups.append((current_name, current))
    return groups


def _first_code_block(nodes: list[Any]) -> tuple[str | None, list[Any]]:
    """Return (invocation, nodes_with_code_block_removed). Looks for <pre>/<code>."""
    out: list[Any] = []
    invocation: str | None = None
    for n in nodes:
        if invocation is None and isinstance(n, Tag) and n.name in ("pre", "code"):
            invocation = n.get_text("\n", strip=True)
            continue
        if invocation is None and isinstance(n, Tag):
            inner = n.find(["pre", "code"])
            if inner is not None:
                invocation = inner.get_text("\n", strip=True)
                inner.decompose()
        out.append(n)
    return invocation, out


def _extract_rules(
    section_nodes: list[Any],
    *,
    source_base: str,
    heading_slug: str,
    default_severity: Severity,
) -> list[ContextDoc]:
    out: list[ContextDoc] = []
    idx = 0
    for raw in _bullets_in(section_nodes):
        text = raw.strip()
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
    section_nodes: list[Any], *, source_base: str, heading_slug: str
) -> list[ContextDoc]:
    text = _text_of(section_nodes)
    if not text:
        return []
    return [
        ContextDoc(
            kind="reasoning", text=text, source=f"{source_base}#{heading_slug}"
        )
    ]


def _extract_skills(
    section_nodes: list[Any], *, source_base: str, heading_slug: str
) -> list[ContextDoc]:
    out: list[ContextDoc] = []
    idx = 0
    for name, group in _h3_groups_in(section_nodes):
        body = _text_of(group)
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
    section_nodes: list[Any], *, source_base: str, heading_slug: str
) -> list[ContextDoc]:
    out: list[ContextDoc] = []
    idx = 0
    for name, group in _h3_groups_in(section_nodes):
        invocation, remaining = _first_code_block(group)
        description = _text_of(remaining)
        idx += 1
        sub_slug = _slugify(name)
        out.append(
            ContextDoc(
                kind="command",
                text=description,
                source=f"{source_base}#{heading_slug}/{sub_slug}",
                name=name,
                invocation=invocation or "",
                id=f"{heading_slug}-{idx:03d}",
            )
        )
    return out


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
        title = page.get("title", "")
        source_base = f"confluence://{page_id}"

        rule_headings = _headings_of(classify.get("rules"))
        reasoning_headings = _headings_of(classify.get("reasoning"))
        skill_headings = _headings_of(classify.get("skills"))
        command_headings = _headings_of(classify.get("commands"))
        reasoning_all = bool(
            isinstance(classify.get("reasoning"), dict)
            and classify["reasoning"].get("all")
        )
        default_severity = _severity_default(classify)

        if not html:
            return []

        soup = BeautifulSoup(html, "html.parser")

        anything = (
            rule_headings
            or reasoning_headings
            or skill_headings
            or command_headings
            or reasoning_all
        )
        if not anything:
            text = soup.get_text("\n", strip=True)
            if not text:
                return []
            return [
                ContextDoc(
                    kind="reasoning",
                    text=text,
                    source=f"{source_base}#{_slugify(title)}",
                )
            ]

        docs: list[ContextDoc] = []
        h2s = soup.find_all("h2")
        for h2 in h2s:
            heading = h2.get_text(" ", strip=True)
            lower = heading.lower()
            slug = _slugify(heading)
            section = _between_siblings(h2, stop_tags=("h2",))
            if lower in rule_headings:
                docs.extend(
                    _extract_rules(
                        section,
                        source_base=source_base,
                        heading_slug=slug,
                        default_severity=default_severity,
                    )
                )
            elif lower in skill_headings:
                docs.extend(
                    _extract_skills(
                        section, source_base=source_base, heading_slug=slug
                    )
                )
            elif lower in command_headings:
                docs.extend(
                    _extract_commands(
                        section, source_base=source_base, heading_slug=slug
                    )
                )
            elif lower in reasoning_headings or reasoning_all:
                docs.extend(
                    _extract_reasoning(
                        section, source_base=source_base, heading_slug=slug
                    )
                )
        return docs

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
