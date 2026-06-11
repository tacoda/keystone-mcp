"""Phase 20 — verify + doctor wiring.

Builds cascade-engine inputs from:

  * The configured external sources (their `canonical` and `required`
    declarations on `SourceConfig`).
  * The project's on-disk harness layer under `.keystone/harness/`.

`run_verify(harness_root, config)` produces a `CascadeReport` plus a
small audit summary.

`run_doctor(harness_root, config)` is a superset: cascade report,
path-conformance check (BOOTSTRAP_DIRS present), and a simple
token-budget proxy (file-count + character total per port). A full
tokenizer-backed budget lands in Phase 27.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .cascade import Item, PROJECT_LAYER, resolve
from .config import KeystoneConfig
from .harness_scaffold import BOOTSTRAP_DIRS


# Ports the project layer scanner walks. Each port maps to its
# filesystem representation: either a flat directory of `.md` files
# (most ports) or a directory of subdirs each containing `SKILL.md`
# (skills).
_FLAT_MD_PORTS = (
    "guides",
    "corpus",
    "sensors",
    "actions",
    "playbooks",
    "prompts",
)
_SKILL_PORT = "skills"
_SCRIPT_PORT = "scripts"


def _project_items(
    harness_root: Path,
) -> tuple[list[Item], dict[tuple[str, str], str]]:
    """Walk `<harness_root>/` and emit `Item` declarations + a map of
    project-layer paths keyed by `(port, name)`.
    """
    items: list[Item] = []
    paths: dict[tuple[str, str], str] = {}
    if not harness_root.is_dir():
        return items, paths

    def add(port: str, name: str, path: Path) -> None:
        items.append(
            Item(
                layer=PROJECT_LAYER,
                port=port,
                name=name,
                has_body=True,
                canonical=False,
            )
        )
        paths[(port, name)] = str(path)

    for port in _FLAT_MD_PORTS:
        port_dir = harness_root / port
        if not port_dir.is_dir():
            continue
        for path in sorted(port_dir.rglob("*.md")):
            if not path.is_file() or path.name == "README.md":
                continue
            name = path.stem
            add(port, name, path)

    # Skills: one subdir per skill, each containing SKILL.md.
    skills_dir = harness_root / _SKILL_PORT
    if skills_dir.is_dir():
        for sub in sorted(skills_dir.iterdir()):
            if not sub.is_dir():
                continue
            skill_md = sub / "SKILL.md"
            if skill_md.is_file():
                add(_SKILL_PORT, sub.name, skill_md)

    # Scripts: exec sensors live under scripts/<name>.sh.
    scripts_dir = harness_root / _SCRIPT_PORT
    if scripts_dir.is_dir():
        for path in sorted(scripts_dir.glob("*.sh")):
            add(_SCRIPT_PORT, path.stem, path)

    return items, paths


def _source_items(config: KeystoneConfig) -> list[list[Item]]:
    """Convert each configured source's `canonical` + `required`
    declarations into an ordered list of `Item` layers.
    """
    layers: list[list[Item]] = []
    for name, source in config.sources.items():
        if not source.canonical and not source.required:
            continue
        layer_items: list[Item] = []
        for port, names in source.canonical.items():
            for item_name in names:
                layer_items.append(
                    Item(
                        layer=name,
                        port=port,
                        name=item_name,
                        has_body=True,
                        canonical=True,
                    )
                )
        for port, names in source.required.items():
            for item_name in names:
                layer_items.append(
                    Item(
                        layer=name,
                        port=port,
                        name=item_name,
                        has_body=False,
                        canonical=False,
                    )
                )
        layers.append(layer_items)
    return layers


def run_verify_cascade(
    harness_root: str | Path, config: KeystoneConfig
):
    """Same as `run_verify` but returns the in-memory `CascadeReport`.

    Used by callers (budget reporter, doctor) that want to operate on
    typed cascade entries without re-parsing the dict form.
    """
    root = Path(harness_root).expanduser().resolve()
    project_items, project_paths = _project_items(root)
    layers = _source_items(config)
    layers.append(project_items)
    return resolve(layers, project_paths=project_paths)


def run_verify(
    harness_root: str | Path, config: KeystoneConfig
) -> dict[str, Any]:
    """Cascade-engine resolution for the current harness + config.

    Returns a JSON-serializable dict ready for the
    `keystone://harness/verify` resource.
    """
    root = Path(harness_root).expanduser().resolve()
    report = run_verify_cascade(root, config)
    return {
        "harness_root": str(root),
        "cascade": report.to_dict(),
        "summary": {
            "resolved": len(report.resolved),
            "unreachable": len(report.unreachable),
            "canonical_violations": len(report.canonical_violations),
            "required_gaps": len(report.required_gaps),
            "conflicts": len(report.conflicts),
        },
    }


def _path_conformance(harness_root: Path) -> dict[str, Any]:
    """Check that every BOOTSTRAP_DIR exists under `harness_root`."""
    missing: list[str] = []
    for sub in BOOTSTRAP_DIRS:
        if not (harness_root / sub).is_dir():
            missing.append(sub)
    return {
        "missing_bootstrap_dirs": missing,
        "ok": not missing,
    }


def run_doctor(
    harness_root: str | Path, config: KeystoneConfig
) -> dict[str, Any]:
    """Doctor report: verify + path conformance + ambient-load budget
    + sensor health."""
    from .budget import budget_report

    root = Path(harness_root).expanduser().resolve()
    cascade = run_verify_cascade(root, config)
    verify_payload = {
        "harness_root": str(root),
        "cascade": cascade.to_dict(),
        "summary": {
            "resolved": len(cascade.resolved),
            "unreachable": len(cascade.unreachable),
            "canonical_violations": len(cascade.canonical_violations),
            "required_gaps": len(cascade.required_gaps),
            "conflicts": len(cascade.conflicts),
        },
    }
    return {
        **verify_payload,
        "path_conformance": _path_conformance(root),
        "budget_proxy": _legacy_budget_proxy(root),
        "budget": budget_report(root, cascade=cascade),
        "sensor_health": _sensor_health(root),
    }


def _sensor_health(harness_root: Path) -> dict[str, Any]:
    """Static health check for sensors.

    Each `sensors/<name>.md` must have exactly one matching
    implementation: either `scripts/<name>.sh` (computational) or
    `prompts/<name>.md` (inferential). The doctor surfaces:

      * `missing_implementation` — sensor declared without a matching
        script or prompt.
      * `ambiguous` — both script and prompt present; the runner
        prefers the script, but the user probably didn't intend the
        ambiguity.
      * `orphan_script` / `orphan_prompt` — implementation file without
        a sensor declaration.
    """
    sensors_dir = harness_root / "sensors"
    scripts_dir = harness_root / "scripts"
    prompts_dir = harness_root / "prompts"
    missing: list[str] = []
    ambiguous: list[str] = []
    orphan_scripts: list[str] = []
    orphan_prompts: list[str] = []
    sensor_names: set[str] = set()
    if sensors_dir.is_dir():
        for path in sorted(sensors_dir.glob("*.md")):
            if path.name == "README.md":
                continue
            name = path.stem
            sensor_names.add(name)
            has_script = (scripts_dir / f"{name}.sh").is_file()
            has_prompt = (prompts_dir / f"{name}.md").is_file()
            if not has_script and not has_prompt:
                missing.append(name)
            elif has_script and has_prompt:
                ambiguous.append(name)
    if scripts_dir.is_dir():
        for path in sorted(scripts_dir.glob("*.sh")):
            if path.stem not in sensor_names:
                orphan_scripts.append(path.stem)
    if prompts_dir.is_dir():
        for path in sorted(prompts_dir.glob("*.md")):
            name = path.stem
            if name not in sensor_names:
                orphan_prompts.append(name)
    return {
        "missing_implementation": missing,
        "ambiguous": ambiguous,
        "orphan_scripts": orphan_scripts,
        "orphan_prompts": orphan_prompts,
        "ok": not (missing or ambiguous),
    }


def _legacy_budget_proxy(harness_root: Path) -> dict[str, Any]:
    """Pre-Phase-27 budget proxy. Retained for backward compatibility
    with consumers reading `doctor.budget_proxy`. New consumers should
    read `doctor.budget` (richer shape, supports cascade-excluded)."""
    per_port: dict[str, dict[str, int]] = {}
    if not harness_root.is_dir():
        return {"per_port": per_port, "total_words": 0}
    total = 0
    for sub in BOOTSTRAP_DIRS:
        port_dir = harness_root / sub
        if not port_dir.is_dir():
            continue
        files = 0
        words = 0
        for path in port_dir.rglob("*"):
            if not path.is_file():
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except OSError:
                continue
            files += 1
            words += len(text.split())
        per_port[sub] = {"files": files, "words": words}
        total += words
    return {"per_port": per_port, "total_words": total}
