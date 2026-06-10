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
    "prompts",
    "adapters",
    "learning/inbox",
    "archive",
)

SENSOR_MODES = ("computational", "inferential")

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


def render_sensor(name: str, kind: str, *, mode: str = "computational") -> str:
    """Render a sensor markdown file.

    Sensors are blocking rules — the agent must run them and they must
    pass for the workflow to continue. Mode (computational vs
    inferential) is inferred by convention from which implementation
    file exists:

      * `<root>/scripts/<name>.sh` exists → computational; agent shells
        out to that script.
      * `<root>/prompts/<name>.md` exists → inferential; agent reads the
        prompt and performs the reasoning task it describes.

    Frontmatter carries metadata only (`kind:` category).
    """
    if kind not in SENSOR_KINDS:
        raise ScaffoldError(
            f"sensor kind must be one of {list(SENSOR_KINDS)}, got {kind!r}"
        )
    if mode not in SENSOR_MODES:
        raise ScaffoldError(
            f"sensor mode must be one of {list(SENSOR_MODES)}, got {mode!r}"
        )
    if mode == "computational":
        run_line = f"- **Run** — `.keystone/harness/scripts/{name}.sh` (shell)\n"
        body = (
            "- **Trigger** — when it runs (e.g. verification phase gate).\n"
            "- **Inputs** — what the script reads (files, env vars).\n"
            "- **Exit condition** — pass = exit 0; fail = non-zero.\n"
            "- **Output** — pass/fail; on fail, stdout/stderr surface the cause.\n"
            "- **State writes** — none, or the state files it updates.\n"
        )
    else:
        run_line = (
            f"- **Run** — `.keystone/harness/prompts/{name}.md` "
            "(agent reads + reasons)\n"
        )
        body = (
            "- **Trigger** — when it runs (e.g. review phase gate).\n"
            "- **Inputs** — what the agent inspects (diff, files, conventions).\n"
            "- **Exit condition** — pass = agent reports PASS; fail = agent reports FAIL.\n"
            "- **Output** — PASS or FAIL with cited findings.\n"
            "- **State writes** — none.\n"
        )
    return (
        f"---\nkind: {kind}\n---\n\n"
        f"# Sensor: {name}\n\n"
        "What this sensor checks. This is a **blocking** rule — the agent "
        "must run it and it must pass for the workflow to continue.\n\n"
        + run_line
        + body
    )


def render_script(name: str) -> str:
    """Render an executable shell script body for a (computational) sensor."""
    return (
        "#!/usr/bin/env bash\n"
        f"# Sensor script: {name}\n"
        "# Exit 0 = pass, non-zero = fail. The agent halts the workflow on "
        "any non-zero exit.\n"
        "set -euo pipefail\n\n"
        f"echo '{name}: not yet implemented' >&2\n"
        "exit 1\n"
    )


def render_prompt(name: str) -> str:
    """Render a prompt markdown body for an inferential sensor.

    The agent reads this file, performs the reasoning task it describes,
    and reports PASS/FAIL. Failure halts the workflow, same as a
    non-zero exit from a computational sensor.
    """
    return (
        f"# {name}\n\n"
        f"**Inferential sensor: {name}.**\n\n"
        "Perform the reasoning task described below against the current\n"
        "diff (or the relevant region of the codebase). Report a single\n"
        "verdict at the end: `PASS` or `FAIL: <reason>`. The agent halts\n"
        "the workflow on any `FAIL`.\n\n"
        "## Scope\n\n"
        "<What this sensor inspects — files, modules, behaviors.>\n\n"
        "## Checks\n\n"
        "- <First thing to evaluate.>\n"
        "- <Second thing to evaluate.>\n\n"
        "## PASS criteria\n\n"
        "<What \"good\" looks like — concrete, falsifiable.>\n\n"
        "## FAIL examples\n\n"
        "- <Example of a finding that warrants FAIL.>\n"
        "- <Another.>\n"
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
    "**Strictness cascade** for rules in `{harness_root}/guides/`:\n"
    "  1. **Non-negotiable** — can never be violated.\n"
    "  2. **Strong** — preferred path; deviation requires explicit reasoning.\n"
    "  3. **Rules** — regular rules; strong rules can override.\n\n"
    "Non-negotiable and strong rules are inlined below at write time so the\n"
    "agent sees them at session start. Regular rules and reasoning load on\n"
    "demand via MCP. Re-run `keystone_target_add(agent, force=True)` after\n"
    "editing guides to refresh this file.\n\n"
    "**At session time** — call the MCP server:\n"
    "- `keystone_list_topics()` (tool) — discover configured topics.\n"
    "- `keystone_get_context(topic)` (tool) — full envelope (rules + reasoning + skills + commands).\n"
    "- `keystone://context/{{topic}}` (resource) — same envelope, via resource read.\n"
    "- `keystone://source/{{name}}/health` (resource) — adapter reachability.\n"
    "- `keystone://harness/status` / `keystone://harness/options` (resources) — harness layout audit.\n\n"
    "Scaffold new harness files with the `keystone_new_*` write tools. The\n"
    "default root is `.keystone/harness`. See the keystone-mcp README for\n"
    "adapter and topic configuration.\n"
)


# Cascade-section heading names recognized by the menu extractor. Both the
# new names and the legacy keystone names are accepted, mirroring the
# harness adapter.
_NON_NEGOTIABLE_HEADINGS = {"non-negotiable", "non negotiable", "iron law", "iron laws"}
_STRONG_HEADINGS = {"strong", "golden rule", "golden rules"}

_H2_RE = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)


def _split_h2(body: str) -> list[tuple[str, str]]:
    matches = list(_H2_RE.finditer(body))
    out: list[tuple[str, str]] = []
    for i, m in enumerate(matches):
        heading = m.group(1).strip()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        out.append((heading, body[start:end].strip()))
    return out


def extract_tier_sections(
    harness_root: str | Path,
) -> dict[str, list[tuple[str, str]]]:
    """Walk `<harness_root>/guides/**/*.md` and extract tiered sections.

    Returns `{"non-negotiable": [(rel_path, body), ...], "strong": [...]}`.
    Used by `target_add` to inline non-negotiable + strong rules into the
    project-root menu file so the agent has them at session start without
    an MCP call.

    `README.md` files are skipped.
    """
    root = Path(harness_root).expanduser().resolve()
    out: dict[str, list[tuple[str, str]]] = {
        "non-negotiable": [],
        "strong": [],
    }
    guides_dir = root / "guides"
    if not guides_dir.is_dir():
        return out
    for path in sorted(guides_dir.rglob("*.md")):
        if path.name == "README.md" or not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        rel = str(path.relative_to(root))
        for heading, body in _split_h2(text):
            lower = heading.lower().strip(":.")
            if lower in _NON_NEGOTIABLE_HEADINGS and body.strip():
                out["non-negotiable"].append((rel, body.strip()))
            elif lower in _STRONG_HEADINGS and body.strip():
                out["strong"].append((rel, body.strip()))
    return out


def _format_inlined_rules(
    sections: dict[str, list[tuple[str, str]]],
) -> str:
    parts: list[str] = []
    if sections.get("non-negotiable"):
        parts.append("\n## Non-negotiable rules\n\n")
        parts.append("These rules can never be violated. No mode loosens them.\n\n")
        for source, body in sections["non-negotiable"]:
            parts.append(f"### From `{source}`\n\n{body}\n\n")
    if sections.get("strong"):
        parts.append("\n## Strong rules\n\n")
        parts.append(
            "Preferred-path rules. Deviation is allowed only with explicit\n"
            "reasoning surfaced to the user.\n\n"
        )
        for source, body in sections["strong"]:
            parts.append(f"### From `{source}`\n\n{body}\n\n")
    return "".join(parts)


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


def render_agent_menu(
    harness_root: str,
    *,
    sections: dict[str, list[tuple[str, str]]] | None = None,
) -> str:
    base = _MENU_TEMPLATE.format(harness_root=harness_root)
    if not sections:
        return base
    return base + _format_inlined_rules(sections)


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
        mode: str = "computational",
        force: bool = False,
    ) -> dict[str, list[str]]:
        """Scaffold a sensor markdown file AND its matching implementation.

        Sensors are blocking rules; the matching file is what the agent
        runs. `mode` controls which implementation gets stamped:

          * `computational` (default) → `scripts/<name>.sh` (shell, exec).
            Agent runs via Bash; exit 0 = pass, non-zero = fail.
          * `inferential` → `prompts/<name>.md` (prompt). Agent reads,
            performs the reasoning task, reports PASS / FAIL.

        Existing implementations are preserved — `force=True` overwrites
        the sensor markdown only; the script/prompt body is never
        overwritten by `new_sensor` (use `new_script` / `new_prompt`
        with `force=True` to refresh those).
        """
        _validate_name(name, "sensor")
        if mode not in SENSOR_MODES:
            raise ScaffoldError(
                f"sensor mode must be one of {list(SENSOR_MODES)}, got {mode!r}"
            )
        sensor_path = self._root / "sensors" / f"{name}.md"
        result = WriteResult([], [])

        sensor_created, sp = _write(
            sensor_path, render_sensor(name, kind, mode=mode), force=force
        )
        (result.created if sensor_created else result.skipped).append(sp)

        if mode == "computational":
            script_path = self._root / "scripts" / f"{name}.sh"
            script_created, scp = _write(
                script_path, render_script(name), force=False
            )
            if script_created:
                script_path.chmod(0o755)
                result.created.append(scp)
            else:
                result.skipped.append(scp)
        else:
            prompt_path = self._root / "prompts" / f"{name}.md"
            prompt_created, pp = _write(
                prompt_path, render_prompt(name), force=False
            )
            (result.created if prompt_created else result.skipped).append(pp)

        return result.to_dict()

    def new_prompt(
        self,
        name: str,
        *,
        body: str | None = None,
        force: bool = False,
    ) -> dict[str, list[str]]:
        """Scaffold (or replace) a prompt markdown under `<root>/prompts/<name>.md`.

        Sensors with mode `inferential` invoke prompts. Most projects
        scaffold a sensor with `new_sensor(mode="inferential")` which
        stamps a prompt stub automatically; use this directly to drop a
        prompt without a sensor wrapper or to replace an existing stub.
        """
        _validate_name(name, "prompt")
        path = self._root / "prompts" / f"{name}.md"
        created, p = _write(path, body or render_prompt(name), force=force)
        return WriteResult(
            created=[p] if created else [], skipped=[] if created else [p]
        ).to_dict()

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

        Manager-authored skills carry the `keystone-` prefix so they
        don't collide with project-authored or third-party skills under
        the shared `skill://` resource scheme. If the caller passes a
        bare slug (no `keystone-` prefix), the prefix is prepended.
        """
        if not name.startswith("keystone-"):
            name = f"keystone-{name}"
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

        Non-negotiable and strong rules from `<harness>/guides/` are
        extracted and inlined at write time so the agent reads them at
        session start without an MCP call. Re-run with `force=True` after
        editing guides to refresh the menu.

        `project_root` is the directory that holds (or will hold) the
        agent activation files (e.g. CLAUDE.md). Defaults to "." (CWD).
        """
        files = menu_files_for(agent)
        proj = Path(project_root).expanduser().resolve()
        sections = extract_tier_sections(self._root)
        body = render_agent_menu(self._root.name, sections=sections)
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
        for sub in ("scripts", "prompts"):
            d = self._root / sub
            if not d.is_dir():
                out["subdirs"][sub] = {"present": False, "files": 0}
                continue
            count = sum(
                1
                for p in d.iterdir()
                if p.is_file() and p.name != "README.md"
            )
            out["subdirs"][sub] = {"present": True, "files": count}
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
