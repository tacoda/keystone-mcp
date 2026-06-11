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
    "actions",
    "playbooks",
    "adapters",
    "learning/inbox",
    "archive",
)

SENSOR_MODES = ("computational", "inferential")

GUIDE_TIERS = ("iron-law", "golden", "rules")
# Legacy tier names accepted only as inputs (with a deprecation warning) so
# pre-Phase-17 callers don't break in lockstep. New writes always render
# under the new headings.
_LEGACY_GUIDE_TIERS = {
    "non-negotiable": "iron-law",
    "strong": "golden",
}
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
    # Strictness cascade: iron-law > golden > rules.
    # Bullet-level MUST/SHOULD/MAY prefix still overrides the tier default.
    "iron-law": (
        "## IRON LAW\n\n"
        "**<NEVER OR ALWAYS STATEMENT IN ALL CAPS BOLD — this rule can never "
        "be violated>.**\n"
    ),
    "golden": (
        "## GOLDEN RULES\n\n"
        "- <hard rule; deviation requires explicit reasoning>.\n"
        "- <another hard rule>.\n"
    ),
    "rules": (
        "## RULES\n\n"
        "- <regular rule; golden rules and iron laws can override>.\n"
        "- <another regular rule>.\n"
    ),
}


def _titleize(slug: str) -> str:
    cleaned = slug.replace("-", " ").replace("_", " ").strip()
    return cleaned.title() if cleaned else slug


def render_guide(name: str, tier: str) -> str:
    if tier in _LEGACY_GUIDE_TIERS:
        legacy = tier
        new = _LEGACY_GUIDE_TIERS[tier]
        raise ScaffoldError(
            f"guide tier {legacy!r} was renamed to {new!r} in Phase 17 "
            f"(iron-law / golden / rules). Re-run with tier={new!r}."
        )
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
    "  1. **Iron law** — can never be violated.\n"
    "  2. **Golden rule** — preferred path; deviation requires explicit reasoning.\n"
    "  3. **Rules** — regular rules; golden rules and iron laws can override.\n\n"
    "Iron laws and golden rules are inlined below at write time so the\n"
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


# Cascade-section heading names recognized by the menu extractor. Both
# the new (Phase 17) names and the pre-rename legacy names are accepted
# for one transitional release, mirroring the harness adapter.
_IRON_LAW_HEADINGS = {"iron law", "iron laws", "non-negotiable", "non negotiable"}
_GOLDEN_HEADINGS = {"golden rule", "golden rules", "strong"}
# Back-compat aliases for any external code that imported these by name.
_NON_NEGOTIABLE_HEADINGS = _IRON_LAW_HEADINGS
_STRONG_HEADINGS = _GOLDEN_HEADINGS

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

    Returns `{"iron-law": [(rel_path, body), ...], "golden": [...]}`.
    Used by `target_add` to inline iron-law + golden rules into the
    project-root menu file so the agent has them at session start without
    an MCP call.

    Transitional behavior (Phase 17): both new (`## IRON LAW(S)` /
    `## GOLDEN RULES`) and legacy (`## NON-NEGOTIABLE` / `## STRONG`)
    headings are recognized for one release so projects can migrate at
    their own pace.

    `README.md` files are skipped.
    """
    root = Path(harness_root).expanduser().resolve()
    out: dict[str, list[tuple[str, str]]] = {
        "iron-law": [],
        "golden": [],
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
            if lower in _IRON_LAW_HEADINGS and body.strip():
                out["iron-law"].append((rel, body.strip()))
            elif lower in _GOLDEN_HEADINGS and body.strip():
                out["golden"].append((rel, body.strip()))
    return out


def _format_inlined_rules(
    sections: dict[str, list[tuple[str, str]]],
) -> str:
    """Render inlined iron-law and golden-rule sections for the menu file.

    Accepts both the Phase-17 keys (`iron-law` / `golden`) and the legacy
    keys (`non-negotiable` / `strong`) so transitional callers don't break.
    """
    iron_law = sections.get("iron-law") or sections.get("non-negotiable") or []
    golden = sections.get("golden") or sections.get("strong") or []
    parts: list[str] = []
    if iron_law:
        parts.append("\n## Iron laws\n\n")
        parts.append("These rules can never be violated. No mode loosens them.\n\n")
        for source, body in iron_law:
            parts.append(f"### From `{source}`\n\n{body}\n\n")
    if golden:
        parts.append("\n## Golden rules\n\n")
        parts.append(
            "Preferred-path rules. Deviation is allowed only with explicit\n"
            "reasoning surfaced to the user.\n\n"
        )
        for source, body in golden:
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


def render_action(name: str) -> str:
    """Render an `actions/<name>.md` body."""
    return (
        f"# Action: {_titleize(name)}\n\n"
        f"**<One-line summary of what the {name} action does.>**\n\n"
        "## When to use\n\n"
        f"<The point in the task lifecycle at which the agent invokes "
        f"`{name}`.>\n\n"
        "## Inputs\n\n"
        "- <Files, ledgers, or prior phase outputs the action reads.>\n\n"
        "## Activities\n\n"
        "1. <Step one.>\n"
        "2. <Step two.>\n\n"
        "## Output\n\n"
        "<What the action produces (a diff, a verdict, a state update, "
        "a report).>\n\n"
        "## Iron laws\n\n"
        "- <Any constraint this action must never violate.>\n"
    )


def render_playbook(name: str) -> str:
    """Render a `playbooks/<name>.md` body."""
    return (
        f"# Playbook: {_titleize(name)}\n\n"
        f"**<One-line summary of what the {name} playbook orchestrates.>**\n\n"
        "## Goal\n\n"
        "<What this playbook achieves end-to-end.>\n\n"
        "## Phases\n\n"
        "1. **<phase-1>.** <What happens. Which action(s) it invokes. The "
        "gate that must clear before phase 2 starts.>\n"
        "2. **<phase-2>.** <…>\n"
        "3. **<phase-3>.** <…>\n\n"
        "## Iron laws\n\n"
        "- <Any constraint this playbook must never violate (e.g. no "
        "commits with failing sensors).>\n\n"
        "## Output\n\n"
        "<What artifact or state change this playbook leaves behind.>\n"
    )


def render_corpus(name: str) -> str:
    """Render a `corpus/<name>.md` body."""
    return (
        f"# {_titleize(name)}\n\n"
        f"**<One-line summary of the {name} concept.>**\n\n"
        "## Background\n\n"
        "<Why this matters. What problem it addresses or what design "
        "decision it records.>\n\n"
        "## Detail\n\n"
        "<Substantive reasoning, references to code, prior art, "
        "trade-offs considered.>\n\n"
        "## Related\n\n"
        "- <Cross-links to other corpus / guides / actions / playbooks.>\n"
    )


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


# Menu-overlay primitives (Phase 19) --------------------------------------

# Delimited markers that bracket the manager-owned region of the menu
# file. HTML comments render invisibly in every Markdown engine and
# don't collide with frontmatter conventions. The manager owns only the
# region between BEGIN_MARKER and END_MARKER; content above and below is
# preserved verbatim across refreshes.
MENU_BEGIN_MARKER = "<!-- BEGIN KEYSTONE -->"
MENU_END_MARKER = "<!-- END KEYSTONE -->"

_BLOCK_RE = re.compile(
    rf"{re.escape(MENU_BEGIN_MARKER)}.*?{re.escape(MENU_END_MARKER)}",
    re.DOTALL,
)


def _wrap_keystone_block(body: str) -> str:
    """Wrap a Keystone-managed body in BEGIN/END markers."""
    return f"{MENU_BEGIN_MARKER}\n{body.rstrip()}\n{MENU_END_MARKER}\n"


def _menu_overlay(
    path: Path, body: str, *, force: bool
) -> tuple[bool, str]:
    """Install or refresh the Keystone-managed block in a menu file.

    Returns `(wrote_new, str(path))`. `wrote_new` is True if a file was
    created from scratch; False if the file already existed (the
    Keystone block was refreshed in place — the user's surrounding
    content is preserved). Idempotent: re-running with an unchanged
    `body` produces a byte-identical file.

    `force` is honored only when the existing file has no Keystone
    block AND no other content: writing the new block then matches
    `_write` behavior. In every other branch the overlay refreshes
    automatically.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    block = _wrap_keystone_block(body)
    if not path.exists():
        path.write_text(block, encoding="utf-8")
        return True, str(path)
    existing = path.read_text(encoding="utf-8")
    if _BLOCK_RE.search(existing):
        # Refresh the managed block in place.
        refreshed = _BLOCK_RE.sub(block.rstrip("\n"), existing, count=1)
        if not refreshed.endswith("\n"):
            refreshed += "\n"
        path.write_text(refreshed, encoding="utf-8")
        return False, str(path)
    # No markers anywhere — append the block after existing content.
    sep = "" if existing.endswith("\n\n") else "\n" if existing.endswith("\n") else "\n\n"
    path.write_text(existing + sep + block, encoding="utf-8")
    return False, str(path)


# Public scaffold API ------------------------------------------------------


class Scaffold:
    def __init__(self, root: str | Path) -> None:
        self._root = Path(root).expanduser().resolve()

    @property
    def root(self) -> Path:
        return self._root

    # Bootstrap ------------------------------------------------------------

    def bootstrap(
        self, *, materialize_templates: bool = False
    ) -> dict[str, list[str]]:
        """Create the skeleton directory layout under the harness root.

        Phase 18: in addition to mkdir-ing the canonical subdirs, this
        method materializes the shipped template tree from
        `keystone_mcp.templates.harness/` so a fresh harness starts with
        the default state-ledger templates, default sensors (lint, type,
        test, build, drift, coverage, plus inferential reviews), default
        actions / playbooks, and the harness README. Existing files are
        never overwritten — the materialize pass writes only files that
        don't yet exist.

        `materialize_templates=False` restores the pre-Phase-18 behavior:
        directories only, no shipped files.
        """
        result = WriteResult([], [])
        for sub in BOOTSTRAP_DIRS:
            d = self._root / sub
            if d.exists():
                result.skipped.append(str(d))
            else:
                d.mkdir(parents=True, exist_ok=True)
                result.created.append(str(d))
        if materialize_templates:
            from . import templates

            for rel, body in templates.iter_harness_files():
                path = self._root / rel
                if path.exists():
                    result.skipped.append(str(path))
                    continue
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(body, encoding="utf-8")
                if path.suffix == ".sh":
                    path.chmod(0o755)
                result.created.append(str(path))
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

    def new_action(
        self, name: str, *, force: bool = False
    ) -> dict[str, list[str]]:
        """Scaffold `<root>/actions/<name>.md`.

        Actions are short, focused operations the agent walks during a
        task (spec, orient, implement, verify, review, learn, audit,
        release). They complement `playbooks/` (which orchestrate
        actions into a higher-level flow) and `skills/` (which expose
        procedural how-to via the FastMCP `skill://` scheme).
        """
        _validate_name(name, "action")
        path = self._root / "actions" / f"{name}.md"
        created, p = _write(path, render_action(name), force=force)
        return WriteResult(
            created=[p] if created else [], skipped=[] if created else [p]
        ).to_dict()

    def new_playbook(
        self, name: str, *, force: bool = False
    ) -> dict[str, list[str]]:
        """Scaffold `<root>/playbooks/<name>.md`.

        Playbooks orchestrate ordered phases into an end-to-end flow:
        `task`, `bootstrap`, `audit`, `install`, `verify`, `doctor`,
        `patch`, `release`. Each phase has an explicit gate before the
        next runs.
        """
        _validate_name(name, "playbook")
        path = self._root / "playbooks" / f"{name}.md"
        created, p = _write(path, render_playbook(name), force=force)
        return WriteResult(
            created=[p] if created else [], skipped=[] if created else [p]
        ).to_dict()

    def new_corpus(
        self, name: str, *, force: bool = False
    ) -> dict[str, list[str]]:
        """Scaffold `<root>/corpus/<name>.md`.

        Corpus entries are reasoning / background context — domain
        notes, architecture decisions, idioms. Not constraints (those
        live in `guides/`) and not procedures (those live in
        `actions/`, `playbooks/`, `skills/`).
        """
        _validate_name(name, "corpus")
        path = self._root / "corpus" / f"{name}.md"
        created, p = _write(path, render_corpus(name), force=force)
        return WriteResult(
            created=[p] if created else [], skipped=[] if created else [p]
        ).to_dict()

    # Agent menus --------------------------------------------------------

    def target_add(
        self,
        agent: str,
        *,
        project_root: str | Path = ".",
        force: bool = False,
    ) -> dict[str, list[str]]:
        """Install or refresh the agent menu file(s) at the project root.

        Phase 19 overlay semantics: the menu file is the agent's
        pre-existing file (CLAUDE.md, AGENTS.md, etc.). The manager owns
        only the region between `<!-- BEGIN KEYSTONE -->` and
        `<!-- END KEYSTONE -->`. All other content — anything above or
        below those sentinels — is preserved verbatim, even on refresh.

          * File does not exist → write a new file containing only the
            Keystone block, wrapped in BEGIN/END markers.
          * File exists with markers → replace the region between markers
            with the freshly-rendered Keystone block. Content above and
            below the markers is preserved byte-for-byte.
          * File exists with NO markers → append the Keystone block
            (markers + body) after the existing content with a blank
            line of separation. The user's content stays at the top.

        Iron-law and golden-rule sections from `<harness>/guides/` are
        extracted and inlined inside the block so the agent reads them at
        session start without an MCP call.

        `force=True` re-runs the overlay even if the file already
        contains an up-to-date Keystone block. In overlay mode, `force`
        rarely matters — the block always refreshes — but it is
        accepted for symmetry with other scaffold tools.

        `project_root` defaults to "." (CWD).
        """
        files = menu_files_for(agent)
        proj = Path(project_root).expanduser().resolve()
        sections = extract_tier_sections(self._root)
        body = render_agent_menu(self._root.name, sections=sections)
        result = WriteResult([], [])
        for rel in files:
            path = proj / rel
            wrote_new, p = _menu_overlay(path, body, force=force)
            (result.created if wrote_new else result.skipped).append(p)
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
        "sensor_modes": list(SENSOR_MODES),
        "supported_agents": list(SUPPORTED_AGENTS),
        "agent_menu_files": {
            agent: list(files) for agent, files in _AGENT_MENU_FILES.items()
        },
        "bootstrap_dirs": list(BOOTSTRAP_DIRS),
    }
