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
    "skills",
    "sensors",
    "scripts",
    "adapters",
    "learning/inbox",
    "archive",
)

GUIDE_TIERS = ("non-negotiable", "strong", "rules")
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
    # Strictness cascade: non-negotiable > strong > rules.
    # Bullet-level MUST/SHOULD/MAY prefix still overrides the tier default.
    "non-negotiable": (
        "## NON-NEGOTIABLE\n\n"
        "**<NEVER OR ALWAYS STATEMENT IN ALL CAPS BOLD — this rule can never "
        "be violated>.**\n"
    ),
    "strong": (
        "## STRONG\n\n"
        "- <hard rule; deviation requires explicit reasoning>.\n"
        "- <another hard rule>.\n"
    ),
    "rules": (
        "## RULES\n\n"
        "- <regular rule; strong rules and non-negotiables can override>.\n"
        "- <another regular rule>.\n"
    ),
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


def render_sensor(name: str, kind: str, script: str | None = None) -> str:
    """Render a sensor markdown file.

    Sensors are computational, blocking rules — the agent must run them
    and they must pass before the workflow can continue. Each sensor
    points at a shell script under `scripts/` that does the actual check.
    """
    if kind not in SENSOR_KINDS:
        raise ScaffoldError(
            f"sensor kind must be one of {list(SENSOR_KINDS)}, got {kind!r}"
        )
    script_name = script or f"{name}.sh"
    return (
        f"---\nkind: {kind}\nscript: {script_name}\n---\n\n"
        f"# Sensor: {name}\n\n"
        "What this sensor checks. This is a **blocking** rule — the agent "
        "must run it and it must pass for the workflow to continue.\n\n"
        f"- **Run** — `.keystone/harness/scripts/{script_name}`\n"
        "- **Trigger** — when it runs (e.g. verification phase gate).\n"
        "- **Inputs** — what the script reads (files, env vars).\n"
        "- **Exit condition** — pass = exit 0; fail = non-zero.\n"
        "- **Output** — pass/fail; on fail, stdout/stderr surface the cause.\n"
        "- **State writes** — none, or the state files it updates.\n"
    )


def render_script(name: str) -> str:
    """Render an executable shell script body for a sensor."""
    return (
        "#!/usr/bin/env bash\n"
        f"# Sensor script: {name}\n"
        "# Exit 0 = pass, non-zero = fail. The agent halts the workflow on "
        "any non-zero exit.\n"
        "set -euo pipefail\n\n"
        f"echo '{name}: not yet implemented' >&2\n"
        "exit 1\n"
    )


def render_skill(name: str, description: str | None = None) -> str:
    """Render a SKILL.md file body.

    YAML frontmatter declares `description` so FastMCP's
    `SkillsDirectoryProvider` and agent runtimes (Claude Code, Cursor) can
    surface a one-line summary without parsing body text.
    """
    desc = description or f"<one-line description of the {name} skill>"
    return (
        "---\n"
        f"description: {desc}\n"
        "---\n\n"
        f"# {name}\n\n"
        "**<One-line summary of what this skill does.>**\n\n"
        "## When to use\n\n"
        "<Conditions under which the agent should invoke this skill.>\n\n"
        "## Activities\n\n"
        "1. Step one.\n"
        "2. Step two.\n\n"
        "## Output\n\n"
        "<What this skill produces (a file diff, a report, a state update).>\n"
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
    "by the `keystone-mcp` server. The entire `.keystone/` directory is\n"
    "version-controlled and shared with the team. **Never put secrets\n"
    "there** — reference env vars via `env:VAR` in `.keystone/context.yaml`.\n\n"
    "**At session start** — load these files directly:\n"
    "- `{harness_root}/guides/**.md` — rules (IRON LAW / RULES / GOLDEN RULES).\n"
    "- `{harness_root}/corpus/**.md` — long-form reasoning, on demand.\n\n"
    "**At session time** — call the MCP server:\n"
    "- `list_topics()` (tool) — discover configured topics.\n"
    "- `get_context(topic)` (tool) — full envelope (rules + reasoning + skills + commands).\n"
    "- `context://{{topic}}` (resource) — same envelope, via resource read.\n"
    "- `source://{{name}}/health` (resource) — adapter reachability.\n"
    "- `harness://status` / `harness://options` (resources) — harness layout audit.\n\n"
    "Scaffold new harness files with the `harness_new_*` write tools. The\n"
    "default root is `.keystone/harness`. See the keystone-mcp README for\n"
    "adapter and topic configuration.\n"
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

# The .keystone/ directory is version-controlled and shared across the team.
# Scaffold tools refuse to write any file whose name looks like a secret.
# Real secrets belong in env vars, referenced from context.yaml via `env:NAME`.
_SECRET_NAME_PATTERNS = (
    "secret",
    "secrets",
    "token",
    "credential",
    "credentials",
    "password",
    "passwd",
    "apikey",
    "api-key",
    "api_key",
    "private",
    ".env",
    "envfile",
)


def _check_no_secret_name(name: str, kind: str) -> None:
    lower = name.lower()
    for pat in _SECRET_NAME_PATTERNS:
        if pat in lower:
            raise ScaffoldError(
                f"{kind} name {name!r} looks like a secret. The .keystone/ "
                f"directory is version-controlled and shared with the team — "
                f"never put secrets there. Use `env:VAR` references in "
                f"context.yaml to pull secrets from the environment instead."
            )


def _validate_name(name: str, kind: str) -> None:
    if not _NAME_RE.match(name or ""):
        raise ScaffoldError(
            f"{kind} name must match [a-zA-Z0-9][a-zA-Z0-9_-]*, got {name!r}"
        )
    _check_no_secret_name(name, kind)


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
        self,
        name: str,
        *,
        kind: str = "custom",
        force: bool = False,
    ) -> dict[str, list[str]]:
        """Scaffold a sensor markdown file AND its matching script stub.

        Sensors are blocking rules; the script is what the agent actually
        executes. Both files are created idempotently — `force` overwrites
        an existing sensor markdown but the script is still skipped if
        present (use `new_script` with `force=True` to refresh a script).
        """
        _validate_name(name, "sensor")
        script_name = f"{name}.sh"
        sensor_path = self._root / "sensors" / f"{name}.md"
        script_path = self._root / "scripts" / script_name

        result = WriteResult([], [])
        sensor_created, sp = _write(
            sensor_path, render_sensor(name, kind, script=script_name), force=force
        )
        (result.created if sensor_created else result.skipped).append(sp)

        # Stamp the matching script stub. Always non-forced — even when the
        # caller forces the sensor refresh, don't blow away script content.
        script_created, scp = _write(
            script_path, render_script(name), force=False
        )
        if script_created:
            script_path.chmod(0o755)
            result.created.append(scp)
        else:
            result.skipped.append(scp)

        return result.to_dict()

    def new_script(
        self,
        name: str,
        *,
        body: str | None = None,
        force: bool = False,
    ) -> dict[str, list[str]]:
        """Scaffold (or replace) a shell script under `<root>/scripts/<name>.sh`.

        Sensors call into scripts. Most projects scaffold a sensor with
        `new_sensor`, which stamps a script stub automatically; use this
        directly to drop a script body without a sensor wrapper or to
        replace an existing stub.
        """
        _validate_name(name, "script")
        path = self._root / "scripts" / f"{name}.sh"
        created, p = _write(path, body or render_script(name), force=force)
        if created:
            path.chmod(0o755)
        return WriteResult(
            created=[p] if created else [], skipped=[] if created else [p]
        ).to_dict()

    def new_skill(
        self,
        name: str,
        *,
        description: str | None = None,
        force: bool = False,
    ) -> dict[str, list[str]]:
        """Scaffold `<root>/skills/<name>/SKILL.md`.

        FastMCP's `SkillsDirectoryProvider` discovers one skill per
        subdirectory containing a `SKILL.md`. The agent runtime (Claude
        Code, Cursor, etc.) auto-loads these as skill resources.
        """
        _validate_name(name, "skill")
        path = self._root / "skills" / name / "SKILL.md"
        created, p = _write(
            path, render_skill(name, description=description), force=force
        )
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
        """Count items per harness subdir + report which are missing.

        For most subdirs, "items" = `.md` files (excluding README.md).
        For `skills/`, "items" = subdirectories containing a SKILL.md, since
        skills are directory-shaped per the FastMCP convention.
        """
        out: dict[str, Any] = {
            "root": str(self._root),
            "root_exists": self._root.exists() and self._root.is_dir(),
            "subdirs": {},
        }
        if not out["root_exists"]:
            return out
        for sub in ("guides", "corpus", "sensors", "adapters"):
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
        scripts_dir = self._root / "scripts"
        if not scripts_dir.is_dir():
            out["subdirs"]["scripts"] = {"present": False, "files": 0}
        else:
            count = sum(
                1
                for p in scripts_dir.iterdir()
                if p.is_file() and p.name != "README.md"
            )
            out["subdirs"]["scripts"] = {"present": True, "files": count}
        skills_dir = self._root / "skills"
        if not skills_dir.is_dir():
            out["subdirs"]["skills"] = {"present": False, "files": 0}
        else:
            count = sum(
                1
                for d in skills_dir.iterdir()
                if d.is_dir() and (d / "SKILL.md").is_file()
            )
            out["subdirs"]["skills"] = {"present": True, "files": count}
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
