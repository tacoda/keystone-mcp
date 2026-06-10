import json
import os
from pathlib import Path

from fastmcp import FastMCP

from .config import load_config
from .errors import KeystoneError
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
