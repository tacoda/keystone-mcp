import json
import os
from pathlib import Path

from fastmcp import FastMCP

from .config import load_config
from .errors import KeystoneError
from .harness_scaffold import Scaffold, options_catalog
from .resolver import Resolver

INSTRUCTIONS = """
This server retrieves company context as four kinds of payload:
  - rules:     constraints to obey (severity must/should/may)
  - reasoning: background facts and intent
  - skills:    procedural how-to knowledge (multi-step playbooks)
  - commands:  canned invocations (shell commands, scripts, named recipes)

Call `list_topics` or read `context://list` to see what's available. Use
`get_context(topic)` for the full envelope, or narrow with `get_rules`,
`get_reasoning`, `get_skills`, or `get_commands`. Rules with severity `must`
are non-negotiable; surface conflicts to the user rather than silently
overriding them.
""".strip()


def _config_path() -> Path:
    return Path(os.environ.get("KEYSTONE_CONFIG", ".keystone/context.yaml"))


def build_server() -> FastMCP:
    config = load_config(_config_path())
    resolver = Resolver(config)
    mcp = FastMCP(name="keystone-mcp", instructions=INSTRUCTIONS)

    @mcp.tool
    async def get_context(topic: str) -> dict:
        """Full envelope (rules + reasoning + skills + commands) for a topic."""
        env = await resolver.get_context(topic)
        return env.to_dict()

    @mcp.tool
    async def get_rules(topic: str) -> dict:
        """Rules only — constraints the agent must obey for this topic."""
        env = await resolver.get_rules(topic)
        return env.to_dict()

    @mcp.tool
    async def get_reasoning(topic: str) -> dict:
        """Reasoning only — background facts and intent for this topic."""
        env = await resolver.get_reasoning(topic)
        return env.to_dict()

    @mcp.tool
    async def get_skills(topic: str) -> dict:
        """Skills only — procedural how-to knowledge for this topic."""
        env = await resolver.get_skills(topic)
        return env.to_dict()

    @mcp.tool
    async def get_commands(topic: str) -> dict:
        """Commands only — canned invocations (e.g. shell commands) for this topic."""
        env = await resolver.get_commands(topic)
        return env.to_dict()

    @mcp.tool
    async def list_topics(tag: str | None = None) -> list[dict]:
        """List all configured topics with descriptions. Pass `tag` to filter."""
        return resolver.list_topics(tag=tag)

    @mcp.tool
    async def source_health(source: str) -> dict:
        """Check whether a configured source is reachable and authenticated."""
        return await resolver.health(source)

    @mcp.resource("context://list")
    async def context_list_resource() -> str:
        return json.dumps(resolver.list_topics(), indent=2)

    @mcp.resource("context://{topic}")
    async def context_resource(topic: str) -> str:
        env = await resolver.get_context(topic)
        return json.dumps(env.to_dict(), indent=2, default=str)

    # Harness scaffold tools (Phase 11b) ----------------------------------

    @mcp.tool
    async def harness_bootstrap(root: str = "harness") -> dict:
        """Create the skeleton directory layout under the harness root.

        Idempotent — existing subdirs are reported in `skipped`. Call this
        once per project before scaffolding individual guides / sensors /
        actions / playbooks.
        """
        return Scaffold(root).bootstrap()

    @mcp.tool
    async def harness_new_guide(
        name: str,
        tier: str = "rules",
        root: str = "harness",
        force: bool = False,
    ) -> dict:
        """Scaffold a new guide markdown file.

        `tier` ∈ iron-law | rules | golden. Tier determines the section
        heading and default severity of bullets inside it.
        """
        return Scaffold(root).new_guide(name, tier=tier, force=force)

    @mcp.tool
    async def harness_new_sensor(
        name: str,
        kind: str = "custom",
        root: str = "harness",
        force: bool = False,
    ) -> dict:
        """Scaffold a new sensor markdown file.

        `kind` ∈ lint | type | test | build | drift | coverage |
        computational | domain | custom. Sensors describe automated checks;
        the actual invocation lives in project state.
        """
        return Scaffold(root).new_sensor(name, kind=kind, force=force)

    @mcp.tool
    async def harness_new_action(
        name: str, root: str = "harness", force: bool = False
    ) -> dict:
        """Scaffold a new action markdown file (single unit of lifecycle work)."""
        return Scaffold(root).new_action(name, force=force)

    @mcp.tool
    async def harness_new_playbook(
        name: str,
        actions: list[str] | None = None,
        root: str = "harness",
        force: bool = False,
    ) -> dict:
        """Scaffold a new playbook markdown file (ordered action chain).

        `actions` is an optional list of action names already present under
        `<root>/actions/`. Each becomes a numbered step in the playbook.
        """
        return Scaffold(root).new_playbook(
            name, actions=actions, force=force
        )

    @mcp.tool
    async def harness_new_adapter(
        agent: str, root: str = "harness", force: bool = False
    ) -> dict:
        """Scaffold a per-agent adapter directory under `<root>/adapters/<agent>/`."""
        return Scaffold(root).new_adapter(agent, force=force)

    @mcp.tool
    async def harness_target_add(
        agent: str,
        project_root: str = ".",
        root: str = "harness",
        force: bool = False,
    ) -> dict:
        """Install the agent's menu file(s) at the project root.

        Menu files (CLAUDE.md, AGENTS.md, etc.) point the agent at the
        harness and at this MCP server. They are thin pointers, not content.
        """
        return Scaffold(root).target_add(
            agent, project_root=project_root, force=force
        )

    @mcp.tool
    async def harness_status(root: str = "harness") -> dict:
        """Audit the harness layout: which subdirs exist and how many files in each."""
        return Scaffold(root).status()

    @mcp.tool
    async def harness_options_catalog() -> dict:
        """List valid arguments for the harness scaffold tools."""
        return options_catalog()

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
