import json
import os
from pathlib import Path

from fastmcp import FastMCP
from fastmcp.server.providers.skills import SkillsDirectoryProvider

from .config import load_config
from .errors import KeystoneError
from .harness_scaffold import Scaffold, options_catalog
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
This server retrieves company context as four kinds of payload:
  - rules:     constraints to obey (severity must/should/may)
  - reasoning: background facts and intent
  - skills:    procedural how-to knowledge (multi-step playbooks)
  - commands:  canned invocations (shell commands, scripts, named recipes)

Read-only retrieval is exposed as MCP resources:
  - context://list                  directory of configured topics
  - context://{topic}               full envelope for a topic
  - source://{name}/health          adapter reachability + auth state
  - harness://status                harness layout audit (always .keystone/harness)
  - harness://options               valid scaffold-tool arguments
  - skill://<name>/SKILL.md         project-local skill (FastMCP primitive)
  - skill://<name>/_manifest        manifest of supporting files in the skill

Project-local skills live at `.keystone/harness/skills/<name>/SKILL.md`.
They are discovered automatically by FastMCP's SkillsDirectoryProvider —
agent runtimes (Claude Code, Cursor, etc.) auto-load them.

Tools cover parameterized retrieval and write operations:
  - get_context(topic), list_topics(tag?)
  - harness_bootstrap / harness_new_* / harness_target_add

Prompts seed multi-step agent workflows:
  - bootstrap     one-time codebase analysis + state ledger fill
  - task(description)   end-to-end task: spec → orient → implement →
                        check-drift → verify → review
  - audit         dual-flywheel: learning + pruning
  - learn(finding)      capture a finding into learning/inbox/

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
    async def get_context(topic: str) -> dict:
        """Full envelope (rules + reasoning + skills + commands) for a topic."""
        env = await resolver.get_context(topic)
        return env.to_dict()

    @mcp.tool
    async def list_topics(tag: str | None = None) -> list[dict]:
        """List configured topics. Pass `tag` to filter."""
        return resolver.list_topics(tag=tag)

    # Resources: read-only data ------------------------------------------

    _READ_ONLY = {"readOnlyHint": True, "idempotentHint": True}

    @mcp.resource("context://list", annotations=_READ_ONLY)
    async def context_list_resource() -> str:
        return json.dumps(resolver.list_topics(), indent=2)

    @mcp.resource("context://{topic}", annotations=_READ_ONLY)
    async def context_resource(topic: str) -> str:
        env = await resolver.get_context(topic)
        return json.dumps(env.to_dict(), indent=2, default=str)

    @mcp.resource("source://{name}/health", annotations=_READ_ONLY)
    async def source_health_resource(name: str) -> str:
        return json.dumps(await resolver.health(name), indent=2)

    @mcp.resource("harness://status", annotations=_READ_ONLY)
    async def harness_status_resource() -> str:
        return json.dumps(Scaffold(HARNESS_ROOT).status(), indent=2)

    @mcp.resource("harness://options", annotations=_READ_ONLY)
    async def harness_options_resource() -> str:
        return json.dumps(options_catalog(), indent=2)

    # Harness scaffold tools (write operations) --------------------------
    #
    # Every tool writes under `.keystone/harness`. The root is fixed; the
    # `.keystone/` directory is team-shared and version-controlled.

    @mcp.tool
    async def harness_bootstrap() -> dict:
        """Create the skeleton directory layout under `.keystone/harness`.

        Idempotent — existing subdirs are reported in `skipped`. Call this
        once per project before scaffolding individual guides / sensors /
        actions / playbooks.
        """
        return Scaffold(HARNESS_ROOT).bootstrap()

    @mcp.tool
    async def harness_new_guide(
        name: str, tier: str = "rules", force: bool = False
    ) -> dict:
        """Scaffold a new guide markdown file under `.keystone/harness/guides/`.

        `tier` ∈ non-negotiable | strong | rules. Strictness cascade:
        non-negotiable (can never be violated) > strong (hard rule;
        deviation requires explicit reasoning) > rules (regular rule;
        strong rules can override).
        """
        return Scaffold(HARNESS_ROOT).new_guide(name, tier=tier, force=force)

    @mcp.tool
    async def harness_new_sensor(
        name: str, kind: str = "custom", force: bool = False
    ) -> dict:
        """Scaffold a new sensor + its matching shell script.

        Sensors are blocking rules — the agent must run them and they must
        pass for the workflow to continue. Writes:
          - `.keystone/harness/sensors/<name>.md` (description + metadata)
          - `.keystone/harness/scripts/<name>.sh` (executable stub)

        `kind` ∈ lint | type | test | build | drift | coverage |
        computational | domain | custom. The script is chmod +x and exits
        non-zero until the body is filled in.
        """
        return Scaffold(HARNESS_ROOT).new_sensor(name, kind=kind, force=force)

    @mcp.tool
    async def harness_new_script(
        name: str, body: str | None = None, force: bool = False
    ) -> dict:
        """Scaffold a shell script under `.keystone/harness/scripts/<name>.sh`.

        Use this to drop a script body without a sensor wrapper, or to
        refresh an existing script (with `force=True`). New scripts are
        chmod +x. Most projects scaffold sensors via `harness_new_sensor`
        which stamps the matching script automatically.
        """
        return Scaffold(HARNESS_ROOT).new_script(name, body=body, force=force)

    @mcp.tool
    async def harness_new_skill(
        name: str,
        description: str | None = None,
        force: bool = False,
    ) -> dict:
        """Scaffold `<.keystone/harness/skills/<name>/SKILL.md`.

        Skills are the FastMCP-native primitive for agent-discoverable
        procedural how-to. Each subdirectory containing a `SKILL.md` becomes
        a discoverable skill, surfaced as `skill://<name>/SKILL.md` and
        auto-loaded by agent runtimes (Claude Code, Cursor, etc.).

        Replaces the older `actions/` and `playbooks/` directories from
        Phase 11b — both concepts collapse into skills.
        """
        return Scaffold(HARNESS_ROOT).new_skill(
            name, description=description, force=force
        )

    @mcp.tool
    async def harness_new_adapter(agent: str, force: bool = False) -> dict:
        """Scaffold a per-agent adapter directory under `.keystone/harness/adapters/<agent>/`."""
        return Scaffold(HARNESS_ROOT).new_adapter(agent, force=force)

    @mcp.tool
    async def harness_target_add(
        agent: str, project_root: str = ".", force: bool = False
    ) -> dict:
        """Install the agent's menu file(s) at the project root.

        Menu files (CLAUDE.md, AGENTS.md, etc.) point the agent at
        `.keystone/harness/` and at this MCP server. They are thin pointers,
        not content — the single source of truth lives in the harness.
        """
        return Scaffold(HARNESS_ROOT).target_add(
            agent, project_root=project_root, force=force
        )

    # Lifecycle prompts (Phase 14b) --------------------------------------

    @mcp.prompt
    def bootstrap() -> str:
        """Seed the bootstrap workflow: analyze the codebase and fill the
        project's state ledgers under `.keystone/harness/corpus/state/`."""
        return render_bootstrap()

    @mcp.prompt
    def task(description: str) -> str:
        """Seed the task workflow on a unit of work.

        Walks spec → orient → implement → check-drift → verify → review.
        Pause for explicit user acceptance between phases.
        """
        return render_task(description)

    @mcp.prompt
    def audit() -> str:
        """Seed the dual-flywheel audit: learning + pruning."""
        return render_audit()

    @mcp.prompt
    def learn(finding: str) -> str:
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
