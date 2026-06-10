"""GitHub adapter — Phase 2.

Reads context from a GitHub repository via the REST API.

Query types:

    type: codeowners
        repo: owner/name             # optional, falls back to source default
    type: branch_protection
        repo: owner/name
        branch: main                 # default: repo's default branch
    type: recent_prs
        repo: owner/name
        limit: 10                    # default 10
        state: open                  # open|closed|all (default open)
    type: releases
        repo: owner/name
        limit: 5

Output kinds per query:

    codeowners        -> rules    (one rule per CODEOWNERS pattern)
    branch_protection -> rules
    recent_prs        -> reasoning
    releases          -> reasoning

`classify` overrides:

    classify:
      rules:    { severity: must }   # default severity for rule-emitting queries
"""

from __future__ import annotations

import re
from typing import Any

import httpx

from ..errors import AdapterError, AuthError
from ..payload import ContextDoc, Severity


_GITHUB_API = "https://api.github.com"
_CODEOWNERS_PATHS = (".github/CODEOWNERS", "CODEOWNERS", "docs/CODEOWNERS")
_OWNER_LINE_RE = re.compile(r"^\s*([^\s#]+)\s+(.+?)\s*$")


def _severity_from_classify(classify: dict[str, Any]) -> Severity:
    rules = classify.get("rules")
    if isinstance(rules, dict):
        sev = rules.get("severity", "must")
        if sev not in ("must", "should", "may"):
            raise AdapterError(
                f"github adapter: classify.rules.severity must be must|should|may, got {sev!r}"
            )
        return sev  # type: ignore[return-value]
    return "must"


def _repo(query: dict[str, Any], default_repo: str | None) -> str:
    repo = query.get("repo") or default_repo
    if not repo or "/" not in repo:
        raise AdapterError(
            "github adapter: 'repo' must be set as 'owner/name' on the query or source"
        )
    return repo


class GitHubAdapter:
    name = "github"

    def __init__(
        self,
        *,
        token: str,
        default_repo: str | None = None,
        base_url: str = _GITHUB_API,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if not token:
            raise AuthError("github adapter: token is required")
        self._token = token
        self._default_repo = default_repo
        self._base_url = base_url.rstrip("/")
        self._client = client

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    async def _get(self, path: str, *, params: dict[str, Any] | None = None) -> httpx.Response:
        url = f"{self._base_url}{path}"
        client = self._client or httpx.AsyncClient()
        owns_client = self._client is None
        try:
            resp = await client.get(url, headers=self._headers(), params=params)
        finally:
            if owns_client:
                await client.aclose()
        if resp.status_code == 401:
            raise AuthError(f"github adapter: 401 unauthorized at {path}")
        if resp.status_code == 403:
            # 403 can be auth OR rate-limit; surface as adapter error either way.
            raise AdapterError(f"github adapter: 403 forbidden at {path} ({resp.text[:200]})")
        if resp.status_code == 404:
            raise AdapterError(f"github adapter: 404 not found at {path}")
        if resp.status_code >= 400:
            raise AdapterError(
                f"github adapter: {resp.status_code} from {path} ({resp.text[:200]})"
            )
        return resp

    async def _fetch_codeowners_text(self, repo: str) -> tuple[str, str]:
        last_err: AdapterError | None = None
        for path in _CODEOWNERS_PATHS:
            try:
                resp = await self._get(
                    f"/repos/{repo}/contents/{path}",
                    params={"ref": "HEAD"},
                )
            except AuthError:
                # Don't retry on auth failure — token won't change.
                raise
            except AdapterError as exc:
                last_err = exc
                continue
            data = resp.json()
            content = data.get("content", "")
            encoding = data.get("encoding", "")
            if encoding != "base64":
                raise AdapterError(
                    f"github adapter: unexpected CODEOWNERS encoding {encoding!r}"
                )
            import base64

            text = base64.b64decode(content).decode("utf-8")
            return text, path
        raise AdapterError(
            f"github adapter: no CODEOWNERS file in {repo} "
            f"(tried {list(_CODEOWNERS_PATHS)}; last error: {last_err})"
        )

    async def _emit_codeowners(
        self, repo: str, *, severity: Severity
    ) -> list[ContextDoc]:
        text, used_path = await self._fetch_codeowners_text(repo)
        docs: list[ContextDoc] = []
        idx = 0
        for raw in text.splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            # CODEOWNERS: <pattern> <owner1> <owner2> ...
            parts = line.split()
            if len(parts) < 2:
                continue
            pattern, *owners = parts
            idx += 1
            owners_str = " ".join(owners)
            docs.append(
                ContextDoc(
                    kind="rule",
                    text=f"Changes matching `{pattern}` require review from {owners_str}.",
                    source=f"github://{repo}/{used_path}#L{idx}",
                    severity=severity,
                    id=f"codeowners-{idx:03d}",
                )
            )
        return docs

    async def _emit_branch_protection(
        self, repo: str, branch: str | None, *, severity: Severity
    ) -> list[ContextDoc]:
        if not branch:
            repo_resp = await self._get(f"/repos/{repo}")
            branch = repo_resp.json().get("default_branch", "main")
        resp = await self._get(f"/repos/{repo}/branches/{branch}/protection")
        data = resp.json()
        docs: list[ContextDoc] = []
        idx = 0

        def add(text: str) -> None:
            nonlocal idx
            idx += 1
            docs.append(
                ContextDoc(
                    kind="rule",
                    text=text,
                    source=f"github://{repo}/branches/{branch}/protection",
                    severity=severity,
                    id=f"branch-protection-{idx:03d}",
                )
            )

        reviews = data.get("required_pull_request_reviews") or {}
        if reviews:
            count = reviews.get("required_approving_review_count")
            if count is not None:
                add(
                    f"PRs to `{branch}` require {count} approving review"
                    f"{'s' if count != 1 else ''}."
                )
            if reviews.get("dismiss_stale_reviews"):
                add(f"Stale approvals on `{branch}` PRs are dismissed on new commits.")
            if reviews.get("require_code_owner_reviews"):
                add(f"PRs to `{branch}` require code-owner review.")
        checks = data.get("required_status_checks") or {}
        if checks:
            contexts = checks.get("contexts") or []
            if contexts:
                add(
                    f"PRs to `{branch}` require these checks to pass: "
                    f"{', '.join(contexts)}."
                )
            if checks.get("strict"):
                add(f"PRs to `{branch}` must be up to date with the base branch.")
        if data.get("enforce_admins", {}).get("enabled"):
            add(f"Branch protection on `{branch}` is enforced for admins too.")
        if data.get("required_linear_history", {}).get("enabled"):
            add(f"`{branch}` requires linear history (no merge commits).")
        if data.get("allow_force_pushes", {}).get("enabled") is False:
            add(f"Force pushes to `{branch}` are disallowed.")
        return docs

    async def _emit_recent_prs(
        self, repo: str, limit: int, state: str
    ) -> list[ContextDoc]:
        resp = await self._get(
            f"/repos/{repo}/pulls",
            params={"state": state, "per_page": limit, "sort": "updated", "direction": "desc"},
        )
        docs: list[ContextDoc] = []
        for pr in resp.json()[:limit]:
            num = pr.get("number")
            title = pr.get("title", "(untitled)")
            user = (pr.get("user") or {}).get("login", "?")
            state_now = pr.get("state", "?")
            draft = pr.get("draft", False)
            updated = pr.get("updated_at", "")
            text = (
                f"#{num} ({state_now}{', draft' if draft else ''}) by @{user}: {title}"
            )
            docs.append(
                ContextDoc(
                    kind="reasoning",
                    text=text,
                    source=f"github://{repo}/pull/{num}",
                    recency=updated or None,
                )
            )
        return docs

    async def _emit_releases(self, repo: str, limit: int) -> list[ContextDoc]:
        resp = await self._get(
            f"/repos/{repo}/releases", params={"per_page": limit}
        )
        docs: list[ContextDoc] = []
        for rel in resp.json()[:limit]:
            tag = rel.get("tag_name", "?")
            name = rel.get("name") or tag
            published = rel.get("published_at", "")
            body = (rel.get("body") or "").strip()
            text = f"{name} ({tag})"
            if body:
                text = f"{text}\n\n{body}"
            docs.append(
                ContextDoc(
                    kind="reasoning",
                    text=text,
                    source=f"github://{repo}/releases/tag/{tag}",
                    recency=published or None,
                )
            )
        return docs

    async def fetch(
        self, query: dict[str, Any], classify: dict[str, Any]
    ) -> list[ContextDoc]:
        qtype = query.get("type")
        if not qtype:
            raise AdapterError("github adapter: query.type is required")
        repo = _repo(query, self._default_repo)
        severity = _severity_from_classify(classify)
        if qtype == "codeowners":
            return await self._emit_codeowners(repo, severity=severity)
        if qtype == "branch_protection":
            return await self._emit_branch_protection(
                repo, query.get("branch"), severity=severity
            )
        if qtype == "recent_prs":
            limit = int(query.get("limit") or 10)
            state = str(query.get("state") or "open")
            return await self._emit_recent_prs(repo, limit, state)
        if qtype == "releases":
            limit = int(query.get("limit") or 5)
            return await self._emit_releases(repo, limit)
        raise AdapterError(
            f"github adapter: unknown query.type {qtype!r} "
            f"(known: codeowners, branch_protection, recent_prs, releases)"
        )

    async def health(self) -> dict[str, Any]:
        try:
            resp = await self._get("/rate_limit")
        except (AdapterError, AuthError) as exc:
            return {"source": self.name, "ok": False, "detail": str(exc)}
        core = (resp.json().get("resources") or {}).get("core") or {}
        return {
            "source": self.name,
            "ok": True,
            "rate_limit_remaining": core.get("remaining"),
            "rate_limit_reset": core.get("reset"),
        }
