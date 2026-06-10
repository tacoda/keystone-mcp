from pathlib import Path

import pytest

from keystone_mcp.config import load_config
from keystone_mcp.errors import UnknownTopicError
from keystone_mcp.resolver import Resolver


def _write_config(tmp_path: Path, ctx_root: Path) -> Path:
    cfg = tmp_path / "context.yaml"
    cfg.write_text(
        f"""
sources:
  docs:
    type: markdown
    root: {ctx_root}
topics:
  deploy:
    description: deploy rules
    source: docs
    query: {{ file: deploy.md }}
    classify:
      rules: {{ heading: Rules }}
      reasoning: {{ heading: Background }}
    cache: 60s
  unstructured:
    description: whole-file reasoning
    source: docs
    query: {{ file: notes.md }}
"""
    )
    return cfg


@pytest.fixture
def resolver(tmp_path):
    ctx = tmp_path / "ctx"
    ctx.mkdir()
    (ctx / "deploy.md").write_text(
        """# Deploy

## Rules

- MUST pass CI.
- SHOULD pick a mid-week deploy window.

## Background

History of incidents informs the rules.
"""
    )
    (ctx / "notes.md").write_text("Just some unclassified notes.\n")
    cfg = load_config(_write_config(tmp_path, ctx))
    return Resolver(cfg)


async def test_get_context_returns_rules_and_reasoning(resolver):
    env = await resolver.get_context("deploy")
    assert env.topic == "deploy"
    assert len(env.rules) == 2
    assert env.rules[0].text == "pass CI."
    assert env.rules[0].severity == "must"
    assert env.rules[1].severity == "should"
    assert len(env.reasoning) == 1
    assert "incidents" in env.reasoning[0].text
    assert env.fetched_at != ""


async def test_get_rules_drops_reasoning(resolver):
    env = await resolver.get_rules("deploy")
    assert len(env.rules) == 2
    assert env.reasoning == []


async def test_get_reasoning_drops_rules(resolver):
    env = await resolver.get_reasoning("deploy")
    assert env.rules == []
    assert len(env.reasoning) == 1


async def test_unstructured_file_becomes_reasoning(resolver):
    env = await resolver.get_context("unstructured")
    assert env.rules == []
    assert len(env.reasoning) == 1
    assert "unclassified" in env.reasoning[0].text


async def test_unknown_topic_raises(resolver):
    with pytest.raises(UnknownTopicError, match="missing"):
        await resolver.get_context("missing")


async def test_cache_marks_subsequent_calls_as_hit(resolver):
    first = await resolver.get_context("deploy")
    assert first.cache_hit is False
    second = await resolver.get_context("deploy")
    assert second.cache_hit is True


async def test_list_topics(resolver):
    rows = resolver.list_topics()
    slugs = {r["slug"] for r in rows}
    assert slugs == {"deploy", "unstructured"}


async def test_sqlite_cache_hits_across_resolver_instances(tmp_path):
    ctx = tmp_path / "ctx"
    ctx.mkdir()
    md = ctx / "deploy.md"
    md.write_text(
        """## Rules

- MUST pass CI.
"""
    )
    cfg_path = tmp_path / "context.yaml"
    cfg_path.write_text(
        f"""
sources:
  docs:
    type: markdown
    root: {ctx}
topics:
  deploy:
    description: d
    source: docs
    query: {{ file: deploy.md }}
    classify:
      rules: {{ heading: Rules }}
    cache: 60s
cache:
  backend: sqlite
  path: {tmp_path / 'cache.db'}
"""
    )
    cfg = load_config(cfg_path)
    r1 = Resolver(cfg)
    first = await r1.get_context("deploy")
    assert first.cache_hit is False

    # New Resolver, same on-disk cache.
    r2 = Resolver(load_config(cfg_path))
    second = await r2.get_context("deploy")
    assert second.cache_hit is True
    assert [rule.text for rule in second.rules] == [rule.text for rule in first.rules]


async def test_health_for_markdown(resolver):
    h = await resolver.health("docs")
    assert h["ok"] is True
    assert h["source"] == "markdown"


async def test_multi_source_merges_and_dedupes_rules(tmp_path):
    ctx = tmp_path / "ctx"
    ctx.mkdir()
    (ctx / "a.md").write_text(
        """## Rules

- MUST pass CI.
- SHOULD lint.
"""
    )
    (ctx / "b.md").write_text(
        """## Rules

- SHOULD pass CI.
- MUST review.
"""
    )
    cfg_path = tmp_path / "context.yaml"
    cfg_path.write_text(
        f"""
sources:
  docs:
    type: markdown
    root: {ctx}
topics:
  combined:
    description: combined
    sources:
      - source: docs
        query: {{ file: a.md }}
        classify:
          rules: {{ heading: Rules }}
      - source: docs
        query: {{ file: b.md }}
        classify:
          rules: {{ heading: Rules }}
"""
    )
    cfg = load_config(cfg_path)
    r = Resolver(cfg)
    env = await r.get_context("combined")
    texts = sorted(rule.text for rule in env.rules)
    # "pass CI." appears in both, MUST wins over SHOULD → single entry
    assert texts == ["lint.", "pass CI.", "review."]
    pass_ci = next(rule for rule in env.rules if rule.text == "pass CI.")
    assert pass_ci.severity == "must"
    assert "a.md" in pass_ci.source  # the MUST one came from a.md


async def test_get_skills_and_commands(tmp_path):
    ctx = tmp_path / "ctx"
    ctx.mkdir()
    (ctx / "play.md").write_text(
        """## Procedures

### Cut release

1. Bump.
2. Tag.

## Commands

### tag

```
git tag v1
```

Tag the release.
"""
    )
    cfg_path = tmp_path / "context.yaml"
    cfg_path.write_text(
        f"""
sources:
  docs:
    type: markdown
    root: {ctx}
topics:
  play:
    description: playbook
    source: docs
    query: {{ file: play.md }}
    classify:
      skills:   {{ heading: Procedures }}
      commands: {{ heading: Commands }}
"""
    )
    cfg = load_config(cfg_path)
    r = Resolver(cfg)

    skills_env = await r.get_skills("play")
    assert len(skills_env.skills) == 1
    assert skills_env.skills[0].name == "Cut release"
    assert skills_env.rules == [] and skills_env.commands == []

    cmds_env = await r.get_commands("play")
    assert len(cmds_env.commands) == 1
    assert cmds_env.commands[0].invocation == "git tag v1"
    assert "Tag the release" in cmds_env.commands[0].description
