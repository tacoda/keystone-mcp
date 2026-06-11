"""Phase 27 — ambient-load budget for the project harness.

Counts the cost of loading the harness into an agent's ambient context
window. Today the counter is a deterministic word-count proxy with no
external dependency. A tokenizer-backed counter (e.g. `tiktoken`)
lands behind an extras install in a future release; the proxy is
stable enough for most "is this getting too big?" questions.

Output shape:

    {
      "harness_root": "/abs/path",
      "tokenizer": "word_count",          # or "tiktoken-cl100k-base" later
      "totals": {
        "files": 42,
        "words": 12345,
        "approx_tokens": 16460,           # words * 4/3 heuristic
      },
      "per_port": {
        "guides":     {"files": 3, "words": 800,  "approx_tokens": 1066},
        "sensors":    {"files": 10, "words": 1200, "approx_tokens": 1600},
        ...
      },
      "hot_files": [                       # top 10 largest by words
        {"port": "playbooks", "name": "task.md", "words": 410, ...},
        ...
      ],
      "cascade_excluded": {                # files shadowed by canonical locks
        "files": 0,
        "words": 0,
      }
    }

Cascade-excluded counts answer: "how much would I save if I deleted
the project files an upstream canonical lock has already shadowed?"
The agent never loads them; today they still cost git+disk space.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .cascade import CascadeReport
from .harness_scaffold import BOOTSTRAP_DIRS


# Empirical multiplier for word-count → token-count for English markdown.
# OpenAI BPE tokenizers average ~0.75 words / token; we round up.
_WORDS_PER_TOKEN = 0.75


def _approx_tokens(words: int) -> int:
    return int(words / _WORDS_PER_TOKEN)


def _count(path: Path) -> tuple[int, int]:
    """Return `(file_count, word_count)` for one file."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return 0, 0
    return 1, len(text.split())


def budget_report(
    harness_root: str | Path,
    *,
    cascade: CascadeReport | None = None,
    top_n: int = 10,
) -> dict[str, Any]:
    """Compute the ambient-load budget report for a harness root.

    `cascade` (if provided) supplies the `unreachable` set so the
    report can also count what the project ships but the agent never
    loads.
    """
    root = Path(harness_root).expanduser().resolve()
    per_port: dict[str, dict[str, int]] = {}
    all_files: list[dict[str, Any]] = []
    total_files = 0
    total_words = 0

    for sub in BOOTSTRAP_DIRS:
        port_dir = root / sub
        if not port_dir.is_dir():
            continue
        files = 0
        words = 0
        for path in port_dir.rglob("*"):
            if not path.is_file():
                continue
            f, w = _count(path)
            files += f
            words += w
            if f:
                all_files.append(
                    {
                        "port": sub,
                        "name": path.relative_to(port_dir).as_posix(),
                        "words": w,
                        "approx_tokens": _approx_tokens(w),
                    }
                )
        per_port[sub] = {
            "files": files,
            "words": words,
            "approx_tokens": _approx_tokens(words),
        }
        total_files += files
        total_words += words

    hot_files = sorted(
        all_files, key=lambda d: d["words"], reverse=True
    )[:top_n]

    cascade_excluded = {"files": 0, "words": 0, "approx_tokens": 0}
    if cascade and cascade.unreachable:
        for skip in cascade.unreachable:
            p = Path(skip.project_layer_path) if skip.project_layer_path else None
            if p and p.exists():
                f, w = _count(p)
                cascade_excluded["files"] += f
                cascade_excluded["words"] += w
        cascade_excluded["approx_tokens"] = _approx_tokens(
            cascade_excluded["words"]
        )

    return {
        "harness_root": str(root),
        "tokenizer": "word_count",
        "totals": {
            "files": total_files,
            "words": total_words,
            "approx_tokens": _approx_tokens(total_words),
        },
        "per_port": per_port,
        "hot_files": hot_files,
        "cascade_excluded": cascade_excluded,
    }
