import asyncio
from typing import Any

from .adapters.base import Adapter
from .adapters.github import GitHubAdapter
from .adapters.markdown import MarkdownAdapter
from .cache import TTLCache, make_key, parse_ttl
from .config import KeystoneConfig, SourceConfig, TopicConfig
from .errors import ConfigError, UnknownSourceError, UnknownTopicError
from .payload import ContextDoc, ContextEnvelope, docs_to_envelope, merge_rules


def _build_markdown(source: SourceConfig) -> MarkdownAdapter:
    s = source.settings
    root = s.get("root")
    if not root:
        raise ConfigError(f"source {source.name!r}: markdown adapter requires 'root'")
    return MarkdownAdapter(root=root)


def _build_github(source: SourceConfig) -> GitHubAdapter:
    s = source.settings
    token = s.get("auth")
    if not token:
        raise ConfigError(
            f"source {source.name!r}: github adapter requires 'auth' (token)"
        )
    return GitHubAdapter(
        token=token,
        default_repo=s.get("repo"),
        base_url=s.get("base_url", "https://api.github.com"),
    )


_BUILDERS = {
    "markdown": _build_markdown,
    "github": _build_github,
}


def build_adapter(source: SourceConfig) -> Adapter:
    builder = _BUILDERS.get(source.type)
    if builder is None:
        raise ConfigError(
            f"source {source.name!r}: unknown adapter type {source.type!r} "
            f"(known: {sorted(_BUILDERS)})"
        )
    return builder(source)


class Resolver:
    def __init__(self, config: KeystoneConfig, cache: TTLCache | None = None) -> None:
        self._config = config
        self._cache = cache or TTLCache()
        self._adapters: dict[str, Adapter] = {}

    def _adapter_for(self, source_name: str) -> Adapter:
        if source_name in self._adapters:
            return self._adapters[source_name]
        source = self._config.sources.get(source_name)
        if source is None:
            raise UnknownSourceError(f"source {source_name!r} is not declared")
        adapter = build_adapter(source)
        self._adapters[source_name] = adapter
        return adapter

    def list_topics(self, tag: str | None = None) -> list[dict[str, Any]]:
        rows = []
        for slug, t in self._config.topics.items():
            if tag is not None and tag not in t.tags:
                continue
            rows.append(
                {
                    "slug": slug,
                    "description": t.description,
                    "sources": [b.source for b in t.bindings],
                    "tags": list(t.tags),
                }
            )
        return rows

    def _topic(self, slug: str) -> TopicConfig:
        topic = self._config.topics.get(slug)
        if topic is None:
            known = sorted(self._config.topics)
            raise UnknownTopicError(
                f"topic {slug!r} not found. known: {known}"
            )
        return topic

    async def get_context(self, slug: str) -> ContextEnvelope:
        topic = self._topic(slug)
        ttl = parse_ttl(topic.cache)
        cache_key = make_key(slug, {"bindings": [b.query for b in topic.bindings]})
        if ttl is not None:
            cached = self._cache.get(cache_key)
            if cached is not None:
                cached.cache_hit = True
                return cached
        # Fan out across bindings in parallel. Any adapter failure surfaces
        # rather than silently producing a partial envelope.
        async def _one(binding) -> list[ContextDoc]:
            adapter = self._adapter_for(binding.source)
            return await adapter.fetch(binding.query, binding.classify)

        results = await asyncio.gather(*(_one(b) for b in topic.bindings))
        docs: list[ContextDoc] = [d for chunk in results for d in chunk]
        envelope = docs_to_envelope(slug, docs)
        # Dedup rules across sources: highest severity wins; ties keep all.
        envelope.rules = merge_rules(envelope.rules)
        if ttl is not None:
            self._cache.put(cache_key, envelope, ttl)
        return envelope

    async def get_rules(self, slug: str) -> ContextEnvelope:
        env = await self.get_context(slug)
        return ContextEnvelope(
            topic=env.topic,
            rules=list(env.rules),
            reasoning=[],
            skills=[],
            commands=[],
            fetched_at=env.fetched_at,
            cache_hit=env.cache_hit,
        )

    async def get_reasoning(self, slug: str) -> ContextEnvelope:
        env = await self.get_context(slug)
        return ContextEnvelope(
            topic=env.topic,
            rules=[],
            reasoning=list(env.reasoning),
            skills=[],
            commands=[],
            fetched_at=env.fetched_at,
            cache_hit=env.cache_hit,
        )

    async def get_skills(self, slug: str) -> ContextEnvelope:
        env = await self.get_context(slug)
        return ContextEnvelope(
            topic=env.topic,
            rules=[],
            reasoning=[],
            skills=list(env.skills),
            commands=[],
            fetched_at=env.fetched_at,
            cache_hit=env.cache_hit,
        )

    async def get_commands(self, slug: str) -> ContextEnvelope:
        env = await self.get_context(slug)
        return ContextEnvelope(
            topic=env.topic,
            rules=[],
            reasoning=[],
            skills=[],
            commands=list(env.commands),
            fetched_at=env.fetched_at,
            cache_hit=env.cache_hit,
        )

    async def health(self, source_name: str) -> dict[str, Any]:
        adapter = self._adapter_for(source_name)
        return await adapter.health()
