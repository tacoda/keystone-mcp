"""Harness scaffold — Phase 11b.

Write-side counterpart to the `harness` adapter. The agent invokes these
functions through MCP tools to:

  - bootstrap a fresh harness skeleton
  - drop new guides / sensors / actions / playbooks / adapters at the
    conventional paths
  - install per-agent activation files (CLAUDE.md, AGENTS.md, etc.) that
    point at the harness and at this MCP server

Refuse-to-overwrite is the default. Passing `force=True` overwrites an
existing file. All write functions return a dict of `created` and `skipped`
paths so the caller knows what landed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .errors import KeystoneError


class ScaffoldError(KeystoneError):
    pass


BOOTSTRAP_DIRS = (
    "guides",
    "corpus",
    "corpus/state",
    "actions",
    "playbooks",
    "sensors",
    "adapters",
    "learning/inbox",
    "archive",
)

GUIDE_TIERS = ("iron-law", "rules", "golden")
SENSOR_KINDS = (
    "lint",
    "type",
    "test",
    "build",
    "drift",
    "coverage",
    "computational",
    "domain",
    "custom",
)
SUPPORTED_AGENTS = (
    "claude-code",
    "codex",
    "cursor",
    "aider",
    "github-copilot",
    "continue",
    "goose",
    "pi",
    "cline",
)


# Templates ----------------------------------------------------------------


_GUIDE_SECTIONS: dict[str, str] = {
    "iron-law": "## IRON LAW\n\n**<NEVER OR ALWAYS STATEMENT IN ALL CAPS BOLD>.**\n",
    "rules": "## RULES\n\n- MUST <rule one>.\n- SHOULD <rule two>.\n- <granular rule with no explicit severity>.\n",
    "golden": "## GOLDEN RULES\n\n- Aim to <aspirational rule>.\n- Aim to <another aspiration>.\n",
}


def _titleize(slug: str) -> str:
    cleaned = slug.replace("-", " ").replace("_", " ").strip()
    return cleaned.title() if cleaned else slug


def render_guide(name: str, tier: str) -> str:
    if tier not in _GUIDE_SECTIONS:
        raise ScaffoldError(
            f"guide tier must be one of {list(_GUIDE_SECTIONS)}, got {tier!r}"
        )
    return (
        f"# {_titleize(name)}\n\n"
        f"Brief description of {name}.\n\n"
        f"{_GUIDE_SECTIONS[tier]}"
    )


def render_sensor(name: str, kind: str) -> str:
    if kind not in SENSOR_KINDS:
        raise ScaffoldError(
            f"sensor kind must be one of {list(SENSOR_KINDS)}, got {kind!r}"
        )
    return (
        f"---\nkind: {kind}\n---\n\n"
        f"# Sensor: {name}\n\n"
        "What this sensor checks.\n\n"
        "- **Trigger** — when it runs (e.g. verification phase gate).\n"
        "- **Inputs** — what data it reads from `corpus/state/`.\n"
        "- **Exit condition** — pass/fail criterion.\n"
        "- **Output** — pass/fail.\n"
        "- **State writes** — none, or the state files it updates.\n"
    )


def render_action(name: str) -> str:
    return (
        f"# {name}\n\n"
        "**<One-line summary of what this action does.>**\n\n"
        "## Activities\n\n"
        "1. Step one.\n"
        "2. Step two.\n\n"
        "## Output\n\n"
        "What this action produces (a file diff, a report, a state update).\n"
    )


def render_playbook(name: str, actions: list[str]) -> str:
    arrow = " → ".join(actions) if actions else "<list actions here>"
    if actions:
        steps = "\n".join(
            f"{i + 1}. **{a}** — read [`{a}.md`](../actions/{a}.md)."
            for i, a in enumerate(actions)
        )
    else:
        steps = (
            "1. **<first action>** — read [`<first>.md`](../actions/<first>.md).\n"
            "2. **<next action>** — ..."
        )
    return (
        f"# {name}\n\n"
        f"**Orchestrates {arrow}.**\n\n"
        "## Activities\n\n"
        f"{steps}\n"
    )


def render_adapter_readme(agent: str) -> str:
    return (
        f"# {agent}\n\n"
        f"Per-agent activation and lifecycle bindings for `{agent}`.\n\n"
        "## Activation\n\n"
        f"How `{agent}` loads the harness at session start. Reference the\n"
        "menu file installed in the project root.\n\n"
        "## Lifecycle hooks\n\n"
        f"Which actions and sensors this agent supports natively (e.g. via\n"
        "subagents, slash commands, hooks). Leave blank for the generic\n"
        "tool-call path.\n"
    )


# Agent menu templates: thin pointers, NOT content. Content lives in the
# harness. The menu tells the agent how to reach it.

_MENU_TEMPLATE = (
    "# Harness pointer\n\n"
    "Project context lives in `{harness_root}/` and is also served at runtime\n"
    "by the `keystone-mcp` server. Two ways to read it:\n\n"
    "**At session start** — load these files directly:\n"
    "- `{harness_root}/guides/**.md` — rules (IRON LAW / RULES / GOLDEN RULES).\n"
    "- `{harness_root}/corpus/**.md` — long-form reasoning, on demand.\n\n"
    "**At session time** — call the MCP server:\n"
    "- `get_rules(topic)` for must-follow constraints.\n"
    "- `get_reasoning(topic)` for background.\n"
    "- `get_skills(topic)` for procedural how-to (actions, playbooks).\n"
    "- `get_commands(topic)` for canned invocations.\n"
    "- `list_topics()` to discover what is configured.\n\n"
    "Configure topics in `.keystone/context.yaml`. See the keystone-mcp README\n"
    "for adapter options.\n"
)


_AGENT_MENU_FILES: dict[str, tuple[str, ...]] = {
    "claude-code": ("CLAUDE.md",),
    "codex": ("AGENTS.md",),
    "cursor": (".cursor/rules/000-harness.mdc",),
    "aider": ("CONVENTIONS.md",),
    "github-copilot": (".github/copilot-instructions.md",),
    "continue": (".continue/rules.md",),
    "goose": (".goosehints",),
    "pi": ("AGENTS.md",),
    "cline": (".clinerules",),
}


def menu_files_for(agent: str) -> tuple[str, ...]:
    if agent not in _AGENT_MENU_FILES:
        raise ScaffoldError(
            f"agent must be one of {list(_AGENT_MENU_FILES)}, got {agent!r}"
        )
    return _AGENT_MENU_FILES[agent]


def render_agent_menu(harness_root: str) -> str:
    return _MENU_TEMPLATE.format(harness_root=harness_root)


# Write primitives ---------------------------------------------------------


@dataclass
class WriteResult:
    created: list[str]
    skipped: list[str]

    def to_dict(self) -> dict[str, list[str]]:
        return {"created": self.created, "skipped": self.skipped}


_NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_\-]*$")


def _validate_name(name: str, kind: str) -> None:
    if not _NAME_RE.match(name or ""):
        raise ScaffoldError(
            f"{kind} name must match [a-zA-Z0-9][a-zA-Z0-9_-]*, got {name!r}"
        )


def _write(path: Path, body: str, *, force: bool) -> tuple[bool, str]:
    """Return (created, rel_str). created=True if written, False if skipped."""
    if path.exists() and not force:
        return False, str(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return True, str(path)


# Public scaffold API ------------------------------------------------------


class Scaffold:
    def __init__(self, root: str | Path) -> None:
        self._root = Path(root).expanduser().resolve()

    @property
    def root(self) -> Path:
        return self._root

    # Bootstrap ------------------------------------------------------------

    def bootstrap(self) -> dict[str, list[str]]:
        """Create the skeleton directory layout under the harness root."""
        result = WriteResult([], [])
        for sub in BOOTSTRAP_DIRS:
            d = self._root / sub
            if d.exists():
                result.skipped.append(str(d))
            else:
                d.mkdir(parents=True, exist_ok=True)
                result.created.append(str(d))
        return result.to_dict()

    # Guides / sensors / actions / playbooks ------------------------------

    def new_guide(
        self, name: str, *, tier: str = "rules", force: bool = False
    ) -> dict[str, list[str]]:
        _validate_name(name, "guide")
        path = self._root / "guides" / f"{name}.md"
        created, p = _write(path, render_guide(name, tier), force=force)
        return WriteResult(
            created=[p] if created else [], skipped=[] if created else [p]
        ).to_dict()

    def new_sensor(
        self, name: str, *, kind: str = "custom", force: bool = False
    ) -> dict[str, list[str]]:
        _validate_name(name, "sensor")
        path = self._root / "sensors" / f"{name}.md"
        created, p = _write(path, render_sensor(name, kind), force=force)
        return WriteResult(
            created=[p] if created else [], skipped=[] if created else [p]
        ).to_dict()

    def new_action(
        self, name: str, *, force: bool = False
    ) -> dict[str, list[str]]:
        _validate_name(name, "action")
        path = self._root / "actions" / f"{name}.md"
        created, p = _write(path, render_action(name), force=force)
        return WriteResult(
            created=[p] if created else [], skipped=[] if created else [p]
        ).to_dict()

    def new_playbook(
        self,
        name: str,
        *,
        actions: list[str] | None = None,
        force: bool = False,
    ) -> dict[str, list[str]]:
        _validate_name(name, "playbook")
        action_list = list(actions or [])
        for a in action_list:
            _validate_name(a, "referenced action")
        path = self._root / "playbooks" / f"{name}.md"
        created, p = _write(path, render_playbook(name, action_list), force=force)
        return WriteResult(
            created=[p] if created else [], skipped=[] if created else [p]
        ).to_dict()

    # Adapters / agent menus ---------------------------------------------

    def new_adapter(
        self, agent: str, *, force: bool = False
    ) -> dict[str, list[str]]:
        _validate_name(agent, "agent")
        path = self._root / "adapters" / agent / "README.md"
        created, p = _write(path, render_adapter_readme(agent), force=force)
        return WriteResult(
            created=[p] if created else [], skipped=[] if created else [p]
        ).to_dict()

    def target_add(
        self,
        agent: str,
        *,
        project_root: str | Path = ".",
        force: bool = False,
    ) -> dict[str, list[str]]:
        """Install the agent menu file(s) at the project root.

        `project_root` is the directory that holds (or will hold) the agent
        activation files (e.g. CLAUDE.md). It defaults to "." and is resolved
        relative to the process CWD.
        """
        files = menu_files_for(agent)
        proj = Path(project_root).expanduser().resolve()
        body = render_agent_menu(self._root.name)
        result = WriteResult([], [])
        for rel in files:
            path = proj / rel
            created, p = _write(path, body, force=force)
            (result.created if created else result.skipped).append(p)
        return result.to_dict()

    # Audit ----------------------------------------------------------------

    def status(self) -> dict[str, Any]:
        """Count files per harness subdir + report which are missing."""
        out: dict[str, Any] = {
            "root": str(self._root),
            "root_exists": self._root.exists() and self._root.is_dir(),
            "subdirs": {},
        }
        if not out["root_exists"]:
            return out
        for sub in ("guides", "corpus", "actions", "playbooks", "sensors", "adapters"):
            d = self._root / sub
            if not d.is_dir():
                out["subdirs"][sub] = {"present": False, "files": 0}
                continue
            count = sum(
                1
                for p in d.rglob("*.md")
                if p.is_file() and p.name != "README.md"
            )
            out["subdirs"][sub] = {"present": True, "files": count}
        return out


# Options catalog ----------------------------------------------------------


def options_catalog() -> dict[str, Any]:
    """Static catalog of valid choices for scaffold tool arguments."""
    return {
        "guide_tiers": list(GUIDE_TIERS),
        "sensor_kinds": list(SENSOR_KINDS),
        "supported_agents": list(SUPPORTED_AGENTS),
        "agent_menu_files": {
            agent: list(files) for agent, files in _AGENT_MENU_FILES.items()
        },
        "bootstrap_dirs": list(BOOTSTRAP_DIRS),
    }
