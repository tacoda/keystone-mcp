import json
import os
from pathlib import Path

from fastmcp import FastMCP
from fastmcp.server.providers.skills import SkillsDirectoryProvider

from .config import load_config
from .errors import KeystoneError
from .harness_scaffold import Scaffold, options_catalog
from .patches import apply_patches, pending_patches
from .verify import run_doctor, run_verify
from .prompts import (
    render_audit,
    render_bootstrap,
    render_learn,
    render_task,
)
from .resolver import Resolver

# The harness layout is fixed under `.keystone/harness`. The entire
# `.keystone/` directory is team-shared and version-controlled; no secrets
# live there (use `env:VAR` references in `.keystone/context.yaml`).
HARNESS_ROOT = ".keystone/harness"

INSTRUCTIONS = """
Keystone Harness Manager — the end-to-end harness manager for any project.

This server retrieves company context as four kinds of payload:
  - rules:     constraints to obey (severity must/should/may)
  - reasoning: background facts and intent
  - skills:    procedural how-to knowledge (multi-step playbooks)
  - commands:  canned invocations (shell commands, scripts, named recipes)

Every primitive carries a `keystone` namespace.

Read-only retrieval is exposed as MCP resources, rooted at `keystone://`:
  - keystone://context/list           directory of configured topics
  - keystone://context/{topic}        full envelope for a topic
  - keystone://source/{name}/health   adapter reachability + auth state
  - keystone://harness/status         harness layout audit (always .keystone/harness)
  - keystone://harness/options        valid scaffold-tool arguments
  - skill://<name>/SKILL.md           project-local skill (FastMCP primitive)
  - skill://<name>/_manifest          manifest of supporting files in the skill

Project-local skills live at `.keystone/harness/skills/<name>/SKILL.md`
and are named `keystone-<slug>` when authored by the manager itself.
They are discovered automatically by FastMCP's SkillsDirectoryProvider —
agent runtimes (Claude Code, Cursor, etc.) auto-load them.

Tools (all `keystone_`-prefixed) cover parameterized retrieval and write
operations:
  - keystone_get_context(topic), keystone_list_topics(tag?)
  - keystone_harness_bootstrap / keystone_new_* / keystone_target_add

Prompts (all `keystone_`-prefixed) seed multi-step agent workflows:
  - keystone_bootstrap            one-time codebase analysis + state ledger fill
  - keystone_task(description)    end-to-end task: spec → orient → implement →
                                  check-drift → verify → review
  - keystone_audit                dual-flywheel: learning + pruning
  - keystone_learn(finding)       capture a finding into learning/inbox/

The harness lives at `.keystone/harness` — fixed path, team-shared,
version-controlled. Never put secrets there; use `env:VAR` references in
`.keystone/context.yaml` instead.

Rules with severity `must` are non-negotiable; surface conflicts to the user
rather than silently overriding them.
""".strip()


def _config_path() -> Path:
    return Path(os.environ.get("KEYSTONE_CONFIG", ".keystone/context.yaml"))


def build_server() -> FastMCP:
    config = load_config(_config_path())
    resolver = Resolver(config)
    mcp = FastMCP(name="keystone-mcp", instructions=INSTRUCTIONS)

    # Mount FastMCP's SkillsDirectoryProvider at .keystone/harness/skills/.
    # Each subdirectory containing a SKILL.md becomes a discoverable
    # `skill://<name>/SKILL.md` resource. The directory may or may not
    # exist at server start; FastMCP picks up additions/removals at
    # discovery time.
    skills_dir = Path(HARNESS_ROOT) / "skills"
    skills_dir.mkdir(parents=True, exist_ok=True)
    mcp.add_provider(SkillsDirectoryProvider(roots=skills_dir))

    # Tools: parameterized retrieval + write operations ------------------

    @mcp.tool
    async def keystone_get_context(topic: str) -> dict:
        """Full envelope (rules + reasoning + skills + commands) for a topic."""
        env = await resolver.get_context(topic)
        return env.to_dict()

    @mcp.tool
    async def keystone_list_topics(tag: str | None = None) -> list[dict]:
        """List configured topics. Pass `tag` to filter."""
        return resolver.list_topics(tag=tag)

    # Resources: read-only data ------------------------------------------

    _READ_ONLY = {"readOnlyHint": True, "idempotentHint": True}

    @mcp.resource("keystone://context/list", annotations=_READ_ONLY)
    async def context_list_resource() -> str:
        return json.dumps(resolver.list_topics(), indent=2)

    @mcp.resource("keystone://context/{topic}", annotations=_READ_ONLY)
    async def context_resource(topic: str) -> str:
        env = await resolver.get_context(topic)
        return json.dumps(env.to_dict(), indent=2, default=str)

    @mcp.resource("keystone://source/{name}/health", annotations=_READ_ONLY)
    async def source_health_resource(name: str) -> str:
        return json.dumps(await resolver.health(name), indent=2)

    @mcp.resource("keystone://harness/status", annotations=_READ_ONLY)
    async def harness_status_resource() -> str:
        return json.dumps(Scaffold(HARNESS_ROOT).status(), indent=2)

    @mcp.resource("keystone://harness/options", annotations=_READ_ONLY)
    async def harness_options_resource() -> str:
        return json.dumps(options_catalog(), indent=2)

    @mcp.resource("keystone://harness/verify", annotations=_READ_ONLY)
    async def harness_verify_resource() -> str:
        """Cascade-engine resolution report for the current harness
        (Phase 20). Surfaces unreachable items, canonical violations,
        required gaps, and non-canonical conflicts. Read-only — no
        side effects."""
        return json.dumps(run_verify(HARNESS_ROOT, config), indent=2)

    @mcp.resource("keystone://harness/doctor", annotations=_READ_ONLY)
    async def harness_doctor_resource() -> str:
        """Full audit report — cascade verify + path conformance +
        ambient-load budget proxy. Read-only."""
        return json.dumps(run_doctor(HARNESS_ROOT, config), indent=2)

    @mcp.resource(
        "keystone://harness/patch/pending", annotations=_READ_ONLY
    )
    async def harness_patch_pending_resource() -> str:
        """Pending shipped patches against the current harness (Phase
        21). Lists files that would be written if the consumer ran the
        patch playbook, plus files skipped because the consumer has
        modified them since the previous shipped version."""
        return json.dumps(pending_patches(HARNESS_ROOT), indent=2)

    # Harness scaffold tools (write operations) --------------------------
    #
    # Every tool writes under `.keystone/harness`. The root is fixed; the
    # `.keystone/` directory is team-shared and version-controlled.

    @mcp.tool
    async def keystone_harness_bootstrap(
        materialize_templates: bool = True,
    ) -> dict:
        """Create `.keystone/harness/` and (by default) materialize the
        shipped template tree.

        Idempotent — existing subdirs and files are reported in `skipped`,
        never overwritten. Call this once per project before scaffolding
        individual guides / sensors / actions / playbooks.

        Pass `materialize_templates=False` to get the bare-bones directory
        layout only (no shipped state ledgers, sensors, actions, or
        playbooks). The full tree is the recommended default; opt out
        only for advanced use cases.
        """
        return Scaffold(HARNESS_ROOT).bootstrap(
            materialize_templates=materialize_templates
        )

    @mcp.tool
    async def keystone_new_guide(
        name: str, tier: str = "rules", force: bool = False
    ) -> dict:
        """Scaffold a new guide markdown file under `.keystone/harness/guides/`.

        `tier` ∈ iron-law | golden | rules. Strictness cascade:
        iron-law (can never be violated) > golden (hard rule; deviation
        requires explicit reasoning) > rules (regular rule; golden rules
        can override).
        """
        return Scaffold(HARNESS_ROOT).new_guide(name, tier=tier, force=force)

    @mcp.tool
    async def keystone_new_sensor(
        name: str,
        kind: str = "custom",
        mode: str = "computational",
        force: bool = False,
    ) -> dict:
        """Scaffold a new sensor + its matching implementation.

        Sensors are blocking rules. `mode` selects how the agent runs them:

          - `computational` (default) → stamps `scripts/<name>.sh` (shell).
            Agent runs via Bash; exit 0 = pass, non-zero = fail.
          - `inferential` → stamps `prompts/<name>.md` (markdown).
            Agent reads the prompt and performs the reasoning task it
            describes (e.g. code review, security review). Reports
            PASS / FAIL.

        `kind` ∈ lint | type | test | build | drift | coverage |
        computational | domain | custom — informational category.
        """
        return Scaffold(HARNESS_ROOT).new_sensor(
            name, kind=kind, mode=mode, force=force
        )

    @mcp.tool
    async def keystone_new_script(
        name: str, body: str | None = None, force: bool = False
    ) -> dict:
        """Scaffold a shell script under `.keystone/harness/scripts/<name>.sh`.

        Use this to drop a script body without a sensor wrapper, or to
        refresh an existing script (with `force=True`). New scripts are
        chmod +x. Most projects scaffold sensors via `keystone_new_sensor`
        which stamps the matching script automatically.
        """
        return Scaffold(HARNESS_ROOT).new_script(name, body=body, force=force)

    @mcp.tool
    async def keystone_new_prompt(
        name: str, body: str | None = None, force: bool = False
    ) -> dict:
        """Scaffold a prompt markdown under `.keystone/harness/prompts/<name>.md`.

        Used by inferential sensors — the agent reads the prompt and
        performs the reasoning task it describes. Most projects scaffold
        inferential sensors via `keystone_new_sensor(mode="inferential")`
        which stamps the matching prompt automatically.
        """
        return Scaffold(HARNESS_ROOT).new_prompt(name, body=body, force=force)

    @mcp.tool
    async def keystone_new_skill(
        name: str,
        description: str | None = None,
        force: bool = False,
    ) -> dict:
        """Scaffold `.keystone/harness/skills/<name>/SKILL.md`.

        Skills are the FastMCP-native primitive for agent-discoverable
        procedural how-to. Each subdirectory containing a `SKILL.md` becomes
        a discoverable skill, surfaced as `skill://<name>/SKILL.md` and
        auto-loaded by agent runtimes (Claude Code, Cursor, etc.).

        Manager-authored skills are named `keystone-<slug>`; the scaffolder
        prepends `keystone-` if missing.
        """
        return Scaffold(HARNESS_ROOT).new_skill(
            name, description=description, force=force
        )

    @mcp.tool
    async def keystone_new_action(name: str, force: bool = False) -> dict:
        """Scaffold a new action markdown under `.keystone/harness/actions/<name>.md`.

        Actions are short, focused operations the agent walks during a
        task — `spec`, `orient`, `implement`, `verify`, `review`,
        `learn`, `audit`, `release`. They complement playbooks (which
        orchestrate actions into a flow) and skills (which expose
        procedural how-to via the FastMCP `skill://` scheme).
        """
        return Scaffold(HARNESS_ROOT).new_action(name, force=force)

    @mcp.tool
    async def keystone_new_playbook(name: str, force: bool = False) -> dict:
        """Scaffold a new playbook markdown under `.keystone/harness/playbooks/<name>.md`.

        Playbooks orchestrate multiple actions into a higher-level flow
        with explicit phase gates: `task`, `bootstrap`, `audit`,
        `install`, `verify`, `doctor`, `patch`, `release`.
        """
        return Scaffold(HARNESS_ROOT).new_playbook(name, force=force)

    @mcp.tool
    async def keystone_new_corpus(name: str, force: bool = False) -> dict:
        """Scaffold a new corpus markdown under `.keystone/harness/corpus/<name>.md`.

        Corpus entries are reasoning / background context — domain
        notes, architecture decisions, idioms. Not constraints (those
        go in `guides/`) and not procedures (those go in `actions/`,
        `playbooks/`, `skills/`).
        """
        return Scaffold(HARNESS_ROOT).new_corpus(name, force=force)

    @mcp.tool
    async def keystone_new_adapter(agent: str, force: bool = False) -> dict:
        """Scaffold a per-agent adapter directory under `.keystone/harness/adapters/<agent>/`."""
        return Scaffold(HARNESS_ROOT).new_adapter(agent, force=force)

    @mcp.tool
    async def keystone_target_add(
        agent: str, project_root: str = ".", force: bool = False
    ) -> dict:
        """Install the agent's menu file(s) at the project root.

        Menu files (CLAUDE.md, AGENTS.md, etc.) point the agent at
        `.keystone/harness/` and at this MCP server. They are thin pointers,
        not content — the single source of truth lives in the harness.
        Phase 19 overlay semantics: only the region between
        `<!-- BEGIN KEYSTONE -->` and `<!-- END KEYSTONE -->` is
        rewritten; pre-existing user content is preserved.
        """
        return Scaffold(HARNESS_ROOT).target_add(
            agent, project_root=project_root, force=force
        )

    @mcp.tool
    async def keystone_apply_patches() -> dict:
        """Apply every pending shipped patch to the project harness.

        Patches are forward-only. Files modified by the user since the
        previous shipped version are skipped and reported as
        conflicts; the user resolves them by hand. Today no patches
        ship — the call reports an empty `applied` list. Future
        releases populate `templates/patches/<version>/`.
        """
        return apply_patches(HARNESS_ROOT)

    # Lifecycle prompts (Phase 14b) --------------------------------------

    @mcp.prompt
    def keystone_bootstrap() -> str:
        """Seed the bootstrap workflow: analyze the codebase and fill the
        project's state ledgers under `.keystone/harness/corpus/state/`."""
        return render_bootstrap()

    @mcp.prompt
    def keystone_task(description: str) -> str:
        """Seed the task workflow on a unit of work.

        Walks spec → orient → implement → check-drift → verify → review.
        Pause for explicit user acceptance between phases.
        """
        return render_task(description)

    @mcp.prompt
    def keystone_audit() -> str:
        """Seed the dual-flywheel audit: learning + pruning."""
        return render_audit()

    @mcp.prompt
    def keystone_learn(finding: str) -> str:
        """Seed the learn workflow: capture a finding into learning/inbox/."""
        return render_learn(finding)

    return mcp


def main() -> None:
    try:
        mcp = build_server()
    except KeystoneError as exc:
        # Surface boundary errors loudly — empty responses are worse than
        # a startup crash the operator can see.
        raise SystemExit(f"keystone-mcp: {exc}") from exc
    mcp.run()


if __name__ == "__main__":
    main()
