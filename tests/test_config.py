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
