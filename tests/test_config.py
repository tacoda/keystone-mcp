from pathlib import Path

import pytest

from keystone_mcp.config import load_config
from keystone_mcp.errors import ConfigError


def _write(tmp_path: Path, content: str) -> Path:
    p = tmp_path / "context.yaml"
    p.write_text(content)
    return p


def test_loads_single_source_shorthand(tmp_path):
    cfg = load_config(
        _write(
            tmp_path,
            """
sources:
  docs:
    type: markdown
    root: /tmp/x
topics:
  rollback:
    description: rollback policy
    source: docs
    query: { file: rollback.md }
    classify:
      rules: { heading: Rules }
""",
        )
    )
    assert set(cfg.sources) == {"docs"}
    assert cfg.sources["docs"].type == "markdown"
    topic = cfg.topics["rollback"]
    assert len(topic.bindings) == 1
    b = topic.bindings[0]
    assert b.source == "docs"
    assert b.query == {"file": "rollback.md"}
    assert b.classify == {"rules": {"heading": "Rules"}}
    assert topic.description == "rollback policy"


def test_loads_multi_source_list(tmp_path):
    cfg = load_config(
        _write(
            tmp_path,
            """
sources:
  docs:   { type: markdown, root: /tmp/a }
  notes:  { type: markdown, root: /tmp/b }
topics:
  hybrid:
    description: hybrid topic
    sources:
      - source: docs
        query: { file: a.md }
      - source: notes
        query: { file: b.md }
""",
        )
    )
    assert [b.source for b in cfg.topics["hybrid"].bindings] == ["docs", "notes"]


def test_unknown_source_in_topic_fails(tmp_path):
    with pytest.raises(ConfigError, match="ghost"):
        load_config(
            _write(
                tmp_path,
                """
sources:
  docs: { type: markdown, root: /tmp/x }
topics:
  t:
    source: ghost
    query: { file: x.md }
""",
            )
        )


def test_topic_requires_query_mapping(tmp_path):
    with pytest.raises(ConfigError, match="must be a mapping"):
        load_config(
            _write(
                tmp_path,
                """
sources:
  docs: { type: markdown, root: /tmp/x }
topics:
  t:
    source: docs
    query: "x.md"
""",
            )
        )


def test_env_var_resolution(tmp_path, monkeypatch):
    monkeypatch.setenv("ROOT_DIR", "/from/env")
    cfg = load_config(
        _write(
            tmp_path,
            """
sources:
  docs:
    type: markdown
    root: env:ROOT_DIR
topics: {}
""",
        )
    )
    assert cfg.sources["docs"].settings["root"] == "/from/env"


def test_missing_env_var_fails(tmp_path, monkeypatch):
    monkeypatch.delenv("MISSING_XYZ", raising=False)
    with pytest.raises(ConfigError, match="MISSING_XYZ"):
        load_config(
            _write(
                tmp_path,
                """
sources:
  docs:
    type: markdown
    root: env:MISSING_XYZ
topics: {}
""",
            )
        )


def test_missing_file(tmp_path):
    with pytest.raises(ConfigError, match="not found"):
        load_config(tmp_path / "nope.yaml")


def test_tags_loaded(tmp_path):
    cfg = load_config(
        _write(
            tmp_path,
            """
sources:
  docs: { type: markdown, root: /tmp/x }
topics:
  t:
    source: docs
    query: { file: x.md }
    tags: [a, b]
""",
        )
    )
    assert cfg.topics["t"].tags == ("a", "b")


def test_cache_defaults_to_memory_when_omitted(tmp_path):
    cfg = load_config(
        _write(
            tmp_path,
            """
sources:
  docs: { type: markdown, root: /tmp/x }
topics: {}
""",
        )
    )
    assert cfg.cache.backend == "memory"
    assert cfg.cache.path is None


def test_cache_sqlite_loads_with_path(tmp_path):
    cfg = load_config(
        _write(
            tmp_path,
            """
sources:
  docs: { type: markdown, root: /tmp/x }
topics: {}
cache:
  backend: sqlite
  path: .keystone/cache.db
""",
        )
    )
    assert cfg.cache.backend == "sqlite"
    assert cfg.cache.path == ".keystone/cache.db"


def test_cache_sqlite_requires_path(tmp_path):
    with pytest.raises(ConfigError, match="cache.path is required"):
        load_config(
            _write(
                tmp_path,
                """
sources:
  docs: { type: markdown, root: /tmp/x }
topics: {}
cache:
  backend: sqlite
""",
            )
        )


def test_canonical_and_required_per_source(tmp_path):
    cfg = load_config(
        _write(
            tmp_path,
            """
sources:
  org-standards:
    type: markdown
    root: /tmp/x
    canonical:
      guides: ["documentation", "todos"]
      actions: ["changelog-check"]
    required:
      actions: ["release-notes"]
topics:
  rollback:
    description: rollback policy
    source: org-standards
    query: { file: rollback.md }
""",
        )
    )
    src = cfg.sources["org-standards"]
    assert src.canonical == {
        "guides": ("documentation", "todos"),
        "actions": ("changelog-check",),
    }
    assert src.required == {"actions": ("release-notes",)}
    # canonical / required entries are stripped from settings (not
    # leaked into the adapter).
    assert "canonical" not in src.settings
    assert "required" not in src.settings


def test_canonical_block_rejects_non_mapping(tmp_path):
    with pytest.raises(ConfigError, match="canonical"):
        load_config(
            _write(
                tmp_path,
                """
sources:
  bad:
    type: markdown
    root: /tmp/x
    canonical: ["not-a-mapping"]
topics:
  rollback:
    source: bad
    query: { file: rollback.md }
""",
            )
        )


def test_required_block_rejects_non_list(tmp_path):
    with pytest.raises(ConfigError, match="required"):
        load_config(
            _write(
                tmp_path,
                """
sources:
  bad:
    type: markdown
    root: /tmp/x
    required:
      actions: "not-a-list"
topics:
  rollback:
    source: bad
    query: { file: rollback.md }
""",
            )
        )


def test_cache_rejects_unknown_backend(tmp_path):
    with pytest.raises(ConfigError, match="must be memory"):
        load_config(
            _write(
                tmp_path,
                """
sources:
  docs: { type: markdown, root: /tmp/x }
topics: {}
cache:
  backend: redis
""",
            )
        )
