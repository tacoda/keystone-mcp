"""Phase 27 — ambient-load budget for the project harness.

Counts the cost of loading the harness into an agent's ambient context
window.

Two tokenizer backends:

  * **`tiktoken`** (preferred). Available when the user installs
    `pip install keystone-mcp[tokens]`. Uses the `cl100k_base` BPE
    encoding shared by GPT-4 and Claude's tokenizer family — the
    counts are exact for that encoding and a close proxy for other
    modern frontier-model tokenizers.
  * **word-count proxy** (default). No external dependency; counts
    whitespace-separated tokens and multiplies by ~1.33 (the
    empirical inverse of 0.75 words/token).

The report's `tokenizer` field reports which backend ran so consumers
can decide how strictly to trust the number.

Output shape:

    {
      "harness_root": "/abs/path",
      "tokenizer": "tiktoken-cl100k-base",  # or "word_count"
      "totals": {
        "files": 42,
        "words": 12345,
        "tokens": 16460,
        "approx_tokens": 16460,  # alias preserved for back-compat
      },
      "per_port": {
        "guides":     {"files": 3, "words": 800,  "tokens": 1066, "approx_tokens": 1066},
        ...
      },
      "hot_files": [                       # top 10 largest by tokens
        {"port": "playbooks", "name": "task.md", "words": 410, "tokens": 547, ...},
        ...
      ],
      "cascade_excluded": {                # files shadowed by canonical locks
        "files": 0,
        "words": 0,
        "tokens": 0,
      }
    }

Cascade-excluded counts answer: "how much would I save if I deleted
the project files an upstream canonical lock has already shadowed?"
The agent never loads them; they still cost git+disk space.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from .cascade import CascadeReport
from .harness_scaffold import BOOTSTRAP_DIRS


# Empirical multiplier for word-count → token-count for English markdown.
# Modern BPE tokenizers average ~0.75 words / token; we round up.
_WORDS_PER_TOKEN = 0.75


def _word_count_tokens(text: str) -> int:
    return int(len(text.split()) / _WORDS_PER_TOKEN)


def _select_tokenizer() -> tuple[str, Callable[[str], int]]:
    """Return `(name, encode_fn)` for the active tokenizer.

    Prefer `tiktoken` if installed; otherwise fall back to the
    word-count proxy. The encode function returns the integer token
    count for a single string.
    """
    try:
        import tiktoken  # type: ignore
    except ImportError:
        return "word_count", _word_count_tokens
    enc = tiktoken.get_encoding("cl100k_base")
    return "tiktoken-cl100k-base", lambda text: len(enc.encode(text))


def _count(
    path: Path, encode: Callable[[str], int]
) -> tuple[int, int, int]:
    """Return `(file_count, word_count, token_count)` for one file."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return 0, 0, 0
    return 1, len(text.split()), encode(text)


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
    tokenizer_name, encode = _select_tokenizer()
    per_port: dict[str, dict[str, int]] = {}
    all_files: list[dict[str, Any]] = []
    total_files = 0
    total_words = 0
    total_tokens = 0

    for sub in BOOTSTRAP_DIRS:
        port_dir = root / sub
        if not port_dir.is_dir():
            continue
        files = 0
        words = 0
        tokens = 0
        for path in port_dir.rglob("*"):
            if not path.is_file():
                continue
            f, w, t = _count(path, encode)
            files += f
            words += w
            tokens += t
            if f:
                all_files.append(
                    {
                        "port": sub,
                        "name": path.relative_to(port_dir).as_posix(),
                        "words": w,
                        "tokens": t,
                        # `approx_tokens` preserved as an alias for
                        # consumers that pinned to the Phase-27 shape.
                        "approx_tokens": t,
                    }
                )
        per_port[sub] = {
            "files": files,
            "words": words,
            "tokens": tokens,
            "approx_tokens": tokens,
        }
        total_files += files
        total_words += words
        total_tokens += tokens

    hot_files = sorted(
        all_files, key=lambda d: d["tokens"], reverse=True
    )[:top_n]

    cascade_excluded = {
        "files": 0,
        "words": 0,
        "tokens": 0,
        "approx_tokens": 0,
    }
    if cascade and cascade.unreachable:
        for skip in cascade.unreachable:
            p = Path(skip.project_layer_path) if skip.project_layer_path else None
            if p and p.exists():
                f, w, t = _count(p, encode)
                cascade_excluded["files"] += f
                cascade_excluded["words"] += w
                cascade_excluded["tokens"] += t
        cascade_excluded["approx_tokens"] = cascade_excluded["tokens"]

    return {
        "harness_root": str(root),
        "tokenizer": tokenizer_name,
        "totals": {
            "files": total_files,
            "words": total_words,
            "tokens": total_tokens,
            "approx_tokens": total_tokens,
        },
        "per_port": per_port,
        "hot_files": hot_files,
        "cascade_excluded": cascade_excluded,
    }
