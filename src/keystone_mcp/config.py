import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .errors import ConfigError


@dataclass(frozen=True)
class SourceConfig:
    name: str
    type: str
    settings: dict[str, Any]


@dataclass(frozen=True)
class TopicSourceBinding:
    """One (source, query, classify) tuple inside a topic."""

    source: str
    query: dict[str, Any]
    classify: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TopicConfig:
    slug: str
    description: str
    bindings: tuple[TopicSourceBinding, ...]
    cache: str | None = None
    tags: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class KeystoneConfig:
    sources: dict[str, SourceConfig]
    topics: dict[str, TopicConfig]


_ENV_PREFIX = "env:"


def _resolve_env(value: Any, *, key_path: str) -> Any:
    if isinstance(value, str) and value.startswith(_ENV_PREFIX):
        env_name = value[len(_ENV_PREFIX):]
        resolved = os.environ.get(env_name)
        if resolved is None or resolved == "":
            raise ConfigError(f"{key_path}: env var {env_name!r} is not set")
        return resolved
    if isinstance(value, dict):
        return {k: _resolve_env(v, key_path=f"{key_path}.{k}") for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve_env(v, key_path=f"{key_path}[{i}]") for i, v in enumerate(value)]
    return value


def _load_sources(raw: dict[str, Any]) -> dict[str, SourceConfig]:
    sources: dict[str, SourceConfig] = {}
    for name, spec in raw.items():
        if not isinstance(spec, dict):
            raise ConfigError(
                f"sources.{name}: expected mapping, got {type(spec).__name__}"
            )
        kind = spec.get("type", name)
        settings = {k: v for k, v in spec.items() if k != "type"}
        resolved = _resolve_env(settings, key_path=f"sources.{name}")
        sources[name] = SourceConfig(name=name, type=kind, settings=resolved)
    return sources


def _load_binding(
    slug: str, idx: int, spec: dict[str, Any], sources: dict[str, SourceConfig]
) -> TopicSourceBinding:
    source = spec.get("source")
    if not source:
        raise ConfigError(f"topics.{slug}.sources[{idx}]: 'source' is required")
    if source not in sources:
        raise ConfigError(
            f"topics.{slug}.sources[{idx}]: source {source!r} is not declared"
        )
    query = spec.get("query")
    if not isinstance(query, dict):
        raise ConfigError(
            f"topics.{slug}.sources[{idx}]: 'query' must be a mapping"
        )
    classify = spec.get("classify") or {}
    if not isinstance(classify, dict):
        raise ConfigError(
            f"topics.{slug}.sources[{idx}]: 'classify' must be a mapping"
        )
    return TopicSourceBinding(source=source, query=query, classify=classify)


def _load_topics(
    raw: dict[str, Any], sources: dict[str, SourceConfig]
) -> dict[str, TopicConfig]:
    topics: dict[str, TopicConfig] = {}
    for slug, spec in raw.items():
        if not isinstance(spec, dict):
            raise ConfigError(f"topics.{slug}: expected mapping")
        # Two shapes accepted: single-source shorthand (source/query/classify at
        # the top level) or explicit list under `sources`.
        if "sources" in spec:
            raw_bindings = spec["sources"]
            if not isinstance(raw_bindings, list) or not raw_bindings:
                raise ConfigError(
                    f"topics.{slug}.sources: must be a non-empty list"
                )
            bindings = tuple(
                _load_binding(slug, i, b, sources) for i, b in enumerate(raw_bindings)
            )
        else:
            bindings = (
                _load_binding(
                    slug,
                    0,
                    {
                        "source": spec.get("source"),
                        "query": spec.get("query"),
                        "classify": spec.get("classify") or {},
                    },
                    sources,
                ),
            )
        tags = tuple(spec.get("tags") or ())
        topics[slug] = TopicConfig(
            slug=slug,
            description=(spec.get("description") or "").strip(),
            bindings=bindings,
            cache=spec.get("cache"),
            tags=tags,
        )
    return topics


def load_config(path: str | Path) -> KeystoneConfig:
    path = Path(path)
    if not path.exists():
        raise ConfigError(f"config file not found: {path}")
    try:
        raw = yaml.safe_load(path.read_text())
    except yaml.YAMLError as exc:
        raise ConfigError(f"config file is not valid YAML: {exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigError("config file must contain a top-level mapping")
    sources_raw = raw.get("sources") or {}
    topics_raw = raw.get("topics") or {}
    if not isinstance(sources_raw, dict):
        raise ConfigError("'sources' must be a mapping")
    if not isinstance(topics_raw, dict):
        raise ConfigError("'topics' must be a mapping")
    sources = _load_sources(sources_raw)
    topics = _load_topics(topics_raw, sources)
    return KeystoneConfig(sources=sources, topics=topics)
