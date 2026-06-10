# Keystone Harness Manager — End-to-End Plan

**Repo:** `keystone-mcp` (Python, FastMCP).
**Predecessor:** `keystone` (Go CLI, v1.0.4 at `~/tacoda/keystone`, site `https://www.tacoda.dev/keystone/`).
**Status of this plan:** supersedes the prior "feature parity" framing. The CLI is no longer a partner in the architecture. `keystone-mcp` is being rebranded as the **Keystone Harness Manager** — the sole tool that owns the full end-to-end lifecycle of a project harness.

The CLI's capabilities and the site's documentation are preserved in full. The framing shifts from *binary + MCP* to *one harness manager*.

---

## 0. Re-brand and scope

**Name:** Keystone Harness Manager (working title; final name TBD).
**Surface:** one Python package distributed via PyPI as `keystone-mcp`. Entry points:
- `keystone-mcp` console script (FastMCP server, stdio transport).
- Shipped markdown library inside the package (skills, commands, playbooks, default guides, default sensors, default adapters, state-ledger templates, patch index).

**Single source of truth:** markdown files inside `.keystone/harness/`. Every other surface (MCP tools, MCP resources, prompts, skills, commands) reads from or writes to those files. Git tracks them. Humans edit them in their IDE. Agents edit them through MCP tools or via shipped skills. All three paths converge on byte-identical files.

**Predecessor capabilities preserved in full:**
- Six-phase lifecycle: spec → planning → implementation → verification → review → release.
- Two flywheels: Learning (additive) and Pruning (subtractive, asymmetric).
- Layered policy via external sources (replaces the CLI's "vendored read-only plugins"), with canonical (strict) and required (declared-but-not-shipped) semantics.
- Per-agent adapter bundles.
- State ledgers under `corpus/state/` (`CODEBASE_STATE.md`, `risk-fingerprints.md`, `quality-radar.md`, `traffic-topology.md`, `code-debt.md`).
- Patch system: forward-only versioned content updates as the manager evolves.
- Doctor / verify / install / init lifecycle commands — re-implemented as shipped skills + playbooks calling thin MCP write tools.

---

## 1. Implementation principle — three rings, write-cost ordering

The manager is built in three concentric rings. Every capability lives in the **outermost** ring that can implement it. Code is the last resort.

**Ring 1 — Markdown (canonical).** `.keystone/harness/{guides,corpus,sensors,actions,playbooks,adapters,skills,scripts,prompts,learning,archive,plugins}/`. Hand-editable in any editor. Git-tracked. The agent reads these as ambient context (guides, skills) or on-demand (corpus, sensors-on-call). When markdown alone can satisfy a need (a rule, a procedure, a checklist, a sensor body), nothing else gets built.

**Ring 2 — Shipped skills, commands, playbooks (markdown, packaged).** Inside `src/keystone_mcp/templates/`, the package ships a full library of skills (`SKILL.md` files), commands, and playbooks that drive the harness lifecycle. These are not generated — they are committed in the repo and copied into `.keystone/harness/` on init. The agent walks them when it needs to bootstrap, run a task, audit, learn, install an external source, verify drift, apply a patch, or scaffold a new file. Behavior lives here whenever a skill can express it.

**Ring 3 — Python code in MCP server.** Only when ring 2 cannot work alone:
- External-service adapters (network I/O, auth) — github, notion, jira, confluence, linear, slack, folder, repo, markdown file.
- Cascade evaluation engine — resolves precedence, surfaces severity, enforces canonical locks.
- File-system scaffolding writes — atomic, deterministic, integrity-checked.
- `.keystone/context.yaml` loader + `env:NAME` secret resolution.
- Cache + TTL.
- Token-budget computation.
- Read-only audit resources (`keystone://harness/status`, `keystone://harness/verify`, `keystone://harness/doctor`).
- Hash-based drift detection against external-source lockfiles.

**Rule of construction:** before adding code to ring 3, ask "can a skill or command in ring 2 do this instead?" If yes, ship markdown. Reserve Python for adapters, cascade math, and the file-write primitives skills call into.

---

## 2. Layering and override model

The harness **overlays on top of** the agent's existing configuration. It never replaces what's there.

### 2.1 Layers, broad to specific

1. **Agent's pre-existing configuration** — whatever the user already has in `CLAUDE.md`, `AGENTS.md`, `.cursor/rules/`, etc. The manager does not touch this content. The manager appends a delimited Keystone block to the menu file; the user's content above and below the block is preserved verbatim.
2. **External sources** declared in `.keystone/context.yaml`, in declaration order — broad to specific. A standards repo, a team's Notion page, a compliance database, etc.
3. **Project harness layer** — files directly under `.keystone/harness/<port>/`. The team's own rules, sensors, skills.

### 2.2 Precedence rules

- **Within a single layer:** rule severity (`must` > `should` > `may`) determines weight. Two `must`s on the same item across the layer surface as a cascade conflict — the agent surfaces it rather than picking silently.
- **Across layers, default behavior:** project layer overrides external sources. Specific beats broad.
- **Canonical exception:** an external source can declare an item `canonical: true` (formerly "strict" in the CLI plugin model). A canonical item is locked at the layer that declared it. No project file and no deeper external source can override it. The cascade engine refuses to load a project file that shadows a canonical item and surfaces the conflict.
- **Required items:** an external source can declare an item `required` — meaning the source references it but does not ship it. The cascade engine surfaces the gap; the project layer (or a deeper external source) must supply the body. Bootstrap, audit, and verify all report unfulfilled `required` items.

### 2.3 Best-case unreachability

The cascade engine prefers **not loading** an item over **loading-and-losing-a-conflict**. If a project's candidate file is shadowed by a canonical declaration upstream, the project file is never loaded into the agent's ambient context, never costs tokens, and never produces conflicting guidance. The audit log records the skip so the user can decide to delete the dead file or move it under a non-canonical namespace.

### 2.4 Severity surfacing for items that do load

When an item legitimately loads:

- `must` → constraint the agent obeys absolutely; deviation surfaces to the user before action.
- `should` → strong preference; deviation requires explicit reasoning recorded in the change record.
- `may` → option; the agent picks based on context with no special handling.

The agent treats severities as written; the cascade engine does not promote or demote.

---

## 3. Concept map — which ring owns each piece

| Concept | Ring 1 (markdown) | Ring 2 (shipped skills/playbooks) | Ring 3 (Python) |
| --- | --- | --- | --- |
| `guides/` rules | the rules | `SKILL.md` references that surface relevant rules | none |
| `corpus/` reasoning | the prose | corpus index skill for on-demand reads | none |
| `corpus/state/` ledgers | the ledgers themselves | bootstrap playbook fills them | filesystem write primitive |
| `sensors/` (computational) | sensor definition + `scripts/<name>.sh` | sensor-runner skill orchestrates Bash | none |
| `sensors/` (inferential) | sensor definition + `prompts/<name>.md` | reviewer skills walk the prompt | none |
| `actions/` and `playbooks/` | the action/playbook bodies | shipped lifecycle playbooks (bootstrap, task, audit, learn, install, verify, doctor, patch, release) | none |
| `adapters/<agent>/` | per-agent bindings | adapter-author skill walks user through new agent | none |
| `skills/<name>/SKILL.md` | the skill | FastMCP `SkillsDirectoryProvider` exposes them | discovery only |
| `learning/inbox/` (Learning flywheel) | findings as markdown | `keystone_learn` command + skill | filesystem write primitive |
| `archive/` (Pruning flywheel) | retired content | `keystone_audit` playbook + archive skill | filesystem move primitive |
| External sources (`context.yaml`) | the YAML | install + verify playbooks | source adapters, env resolution, cache, cascade engine |
| Canonical lock enforcement | declaration in source manifest or `context.yaml` | cascade-conflict skill (explains to user) | cascade engine |
| Required-item declaration | declaration in source manifest | gap-report skill | cascade engine |
| Init / bootstrap | initial templates copied from package | bootstrap playbook drives the agent through codebase analysis | template copy + atomic write |
| Verify (drift, cascade) | findings rendered as markdown | verify command surfaces findings | drift hash + cascade evaluation |
| Doctor (paths, plugins, budget) | findings as markdown | doctor command | path scanner, budget computer |
| Patch (forward-only updates) | shipped patches in package | patch playbook | patch loader + applier |
| Menu file (`CLAUDE.md` etc.) | composed at install + refresh time | menu-author skill | delimited-block insert/refresh primitive |
| Token budget for ambient load | reported as markdown summary | budget skill | token counter |

---

## 4. What ships inside the Python package as markdown

A first-class deliverable. The package source tree gains `src/keystone_mcp/templates/`:

```
src/keystone_mcp/templates/
├── harness/
│   ├── guides/
│   │   ├── iron-law/                # IRON LAW rules: non-overridable defaults
│   │   ├── golden/                  # GOLDEN RULES: strong defaults, project may override
│   │   └── rules/                   # RULES: ordinary defaults
│   ├── corpus/
│   │   ├── idioms/                  # stack-specific reasoning (filled by bootstrap)
│   │   ├── domain/                  # project-specific reasoning (filled by bootstrap)
│   │   └── state/                   # ledger templates with placeholders
│   ├── sensors/                     # default computational sensors (lint, type, test, build, drift, coverage)
│   ├── scripts/                     # shell bodies for the default sensors
│   ├── prompts/                     # inferential-sensor prompt bodies (security review, code review, accessibility review, performance review)
│   ├── actions/                     # spec, orient, implement, verify, review, learn, audit, release
│   ├── playbooks/
│   │   ├── task.md                  # six-phase lifecycle
│   │   ├── bootstrap.md             # one-time codebase analysis
│   │   ├── audit.md                 # Pruning flywheel
│   │   ├── install.md               # add an external source
│   │   ├── verify.md                # drift + cascade check
│   │   ├── doctor.md                # full audit
│   │   ├── patch.md                 # forward-only updates
│   │   ├── release.md               # release phase
│   │   └── new-<port>.md            # scaffold a new file in <port>
│   ├── adapters/                    # full bundles for claude-code, codex, pi, cursor, aider, github-copilot, continue, cline, goose, _generic
│   ├── skills/                      # SkillsDirectoryProvider auto-loads these
│   │   ├── keystone-learn/SKILL.md
│   │   ├── keystone-cascade-conflict/SKILL.md
│   │   ├── keystone-reload-notice/SKILL.md
│   │   ├── keystone-menu-author/SKILL.md
│   │   ├── keystone-adapter-author/SKILL.md
│   │   ├── keystone-source-installer/SKILL.md
│   │   ├── keystone-sensor-runner/SKILL.md
│   │   └── keystone-budget-reporter/SKILL.md
│   └── README.md                    # the harness's own README
├── menu/
│   ├── claude-code.md               # menu body for CLAUDE.md
│   ├── codex.md
│   ├── cursor.md
│   ├── pi.md
│   ├── aider.md
│   ├── github-copilot.md
│   ├── continue.md
│   ├── cline.md
│   ├── goose.md
│   └── _generic.md
├── context.yaml.tpl                 # starter `.keystone/context.yaml`
├── gitignore.snippet                # `.keystone/cache/`, `.keystone/secrets/`, etc.
└── patches/                         # forward-only patch tree, keyed by version
    └── v0.2.0/
        └── …
```

Every file is markdown or YAML. The Python code reads them via `importlib.resources` and writes them atomically. No inline string templates remain in `harness_scaffold.py` after the migration — the current inline strings move into this tree.

---

## 5. Two flywheels — preserved verbatim

### 5.1 Learning flywheel (additive)

Triggered by `keystone_learn(finding)` (MCP prompt) or `/keystone-learn` (skill command, depending on agent).

1. Agent captures the finding into `.keystone/harness/learning/inbox/<slug>.md` with proposed classification: iron-law / golden / rules / skill / reasoning / defer.
2. No on-the-spot promotion — audit batches decisions.
3. Reload notice emitted because guides are ambient and the current session's context is stale.

Owned by ring 2 (skill + playbook). Ring 3 supplies only the atomic-write primitive.

### 5.2 Pruning flywheel (subtractive, asymmetric)

Triggered by `keystone_audit()` (MCP prompt) or `/keystone-audit` (skill command).

1. Regular sweep of `guides/` against the codebase. Stale rule (names a removed API, contradicts a newer rule, no longer followed) → candidate for archive.
2. Rare sweep of `corpus/`. Only when the team's design or strategy has moved on.
3. Content moves to `archive/<port>/<name>.md` with reasoning recorded — never deleted.
4. Reload notice if `guides/` was touched.
5. Audit report includes: unfulfilled `required` items from external sources, dead guides shadowed by canonical locks, sensors that have been failing for N days, empty shells (skills/playbooks with no body), drifted state ledgers.

Owned by ring 2 (playbook + skills). Ring 3 supplies file-move primitive and `keystone://harness/audit-report` resource.

### 5.3 Wishlist

`.keystone/harness/learning/wishlist.md` — team-curated file of known gaps. Items here become real `learning/inbox/` candidates only when a real situation triggers them. Owned by ring 1.

---

## 6. External sources — any kind, cascade-respecting

### 6.1 Source declaration

`.keystone/context.yaml` ships a single source-and-topic schema (existing today). Every adapter is read-only and may emit any payload kind (`rules`, `reasoning`, `skills`, `commands`).

Adapters today: `markdown`, `github`, `confluence`, `notion`, `jira`, `linear`, `slack`, `harness` (repo-local). Plan adds: `folder`, `repo`.

### 6.2 Per-source cascade declaration

A source can declare canonical and required items in its own manifest (when sourced from a content repo) or inline in `context.yaml`:

```yaml
sources:
  org-standards:
    type: repo
    source: tacoda/tacoda-org
    version: v1.1.2
    canonical:
      guides: ["documentation", "todos"]
      actions: ["changelog-check", "static-analysis"]
    required:
      actions: ["release-notes"]
```

`canonical` = locked at this layer. No project file and no deeper source overrides.
`required` = declared but not shipped. Surfaced as a gap; project or deeper source must supply the body.

### 6.3 Topic binding

Topics in `context.yaml` continue to map (source × query × classify) → payload. Multiple bindings per topic merge through the cascade engine.

### 6.4 What changes vs. today

- Add `canonical` and `required` keys to source-level config and to source manifests (for `repo` sources that ship `keystone-source.yaml`).
- Cascade engine evaluates them before any payload reaches the agent.
- Verify / doctor surface canonical conflicts and required gaps.

---

## 7. Edit-path triad

Same markdown file is reachable through three paths. All three converge.

1. **Direct edit** — open `.keystone/harness/guides/process/release.md` in any editor. Git tracks the change.
2. **MCP tool** — `keystone_new_guide("process/release", tier="rules")` or `keystone_write_file(path, body)` for surgical edits. Atomic, refuses to overwrite by default (pass `force=True`).
3. **Skill / command** — `/keystone-new-guide` (or whatever the user's agent surfaces). The skill walks the user through tier choice, then calls the MCP tool internally.

Tests assert byte-identical output across all three paths for the same logical operation.

---

## 8. Gaps vs. current `keystone-mcp` (Phase 15) state

Inventory of what's missing or misaligned today, given the new direction.

### 8.1 Surface gaps

| Gap | Ring | Severity |
| --- | --- | --- |
| Namespace prefix `keystone` across tools / prompts / resources / skills | 3 + 2 | high |
| Tier vocabulary alignment (`iron-law` / `golden` / `rules`) | 3 + 2 | high |
| `actions/` and `playbooks/` ports absent (collapsed into `skills/` in Phase 11b/14b) | 2 | high |
| Shipped template library under `src/keystone_mcp/templates/` (markdown, not inline strings) | 2 | high |
| Bootstrap playbook (not just the `keystone_bootstrap` prompt — a full markdown playbook that drives the agent) | 2 | high |
| Cascade engine: precedence, severity surfacing, canonical lock, required gap | 3 | high |
| Canonical + required declarations in `context.yaml` and source manifests | 3 + 1 | high |
| Menu file as overlay (delimited Keystone block; preserves user's pre-existing content) | 3 + 2 | high |
| Source installer playbook (interactive `context.yaml` editing) | 2 | medium |
| Verify command + `keystone://harness/verify` resource | 3 + 2 | medium |
| Doctor command + `keystone://harness/doctor` resource | 3 + 2 | medium |
| Patch system: shipped patch tree + patch playbook | 1 + 2 + 3 | medium |
| `folder` and `repo` source types | 3 | medium |
| Inferential sensor library: shipped prompts for security review, code review, accessibility review, performance review | 1 | medium |
| Default sensor library: shipped lint, type, test, build, drift, coverage | 1 | medium |
| State-ledger templates with placeholders | 1 | medium |
| `new_corpus` write tool | 3 | low |
| Skills directory in `BOOTSTRAP_DIRS` | 3 | low |
| Token budget computation | 3 | low |
| Reload-notice skill | 2 | low |

### 8.2 Behavioral gaps

| Gap | Rationale |
| --- | --- |
| `harness_bootstrap` tool writes mkdir-only; no defaults | Should write shipped templates from the package. |
| Menu file written by `harness_target_add` replaces the file | Should overlay: preserve user content above/below the delimited Keystone block. |
| `new_skill` does not enforce `keystone-` prefix | Required for namespace; FastMCP `skill://` scheme is shared. |
| No `--mode inferential` documentation | Already implemented in code, not surfaced in `INSTRUCTIONS` or `harness://options`. |
| No archival flow | Pruning flywheel must move to `archive/`, not delete. |
| No cache for external sources beyond per-process memory | Repo source needs disk cache; others benefit from TTL. |

---

## 9. Phased plan

Phases renumbered from where `PLAN.md` left off (Phase 15 = packaging + PyPI). Each phase produces a shippable release. Breaking changes group into 0.2.0 (Phases 16–18) and 0.3.0 (Phase 20).

### Phase 16 — Namespace `keystone` across every primitive

**Goal:** every MCP primitive carries a `keystone` namespace.

- Tools: `keystone_get_context`, `keystone_list_topics`, `keystone_harness_bootstrap`, `keystone_new_guide`, `keystone_new_sensor`, `keystone_new_script`, `keystone_new_prompt`, `keystone_new_skill`, `keystone_new_adapter`, `keystone_target_add`.
- Prompts: `keystone_bootstrap`, `keystone_task`, `keystone_audit`, `keystone_learn`.
- Resources rooted at `keystone://`:
  - `keystone://context/list`, `keystone://context/{topic}`
  - `keystone://source/{name}/health`
  - `keystone://harness/status`, `keystone://harness/options`
- Skills authored by the manager are named `keystone-<slug>`. `Scaffold.new_skill` prepends `keystone-` if missing.
- Update `INSTRUCTIONS` block, `README.md`, `PLAN.md`.
- Tests assert the four namespace invariants.

**DoD:** every registered primitive matches the namespace pattern; tests pass; `CHANGELOG.md` documents the rename.

### Phase 17 — Tier vocabulary alignment

**Goal:** rename `non-negotiable` / `strong` / `rules` → `iron-law` / `golden` / `rules`.

- `GUIDE_TIERS = ("iron-law", "golden", "rules")`.
- `render_guide` stamps `## IRON LAW(S)`, `## GOLDEN RULES`, `## RULES`.
- `extract_tier_sections` reads both old and new headers for one release (transitional read), writes only new.
- `keystone://harness/options` returns the new vocabulary.

**DoD:** `keystone_new_guide("foo", tier="iron-law")` succeeds; legacy tier returns a deprecation error with migration hint.

### Phase 18 — Shipped template library

**Goal:** move all inline-string templates into `src/keystone_mcp/templates/`. Restore `actions/` and `playbooks/` as ports.

- Create `src/keystone_mcp/templates/` per §4 layout.
- Port every inline string in `harness_scaffold.py` to a file under `templates/harness/`.
- Read templates via `importlib.resources.files("keystone_mcp.templates")`.
- Add `Scaffold.new_action`, `Scaffold.new_playbook`. Bootstrap dirs include `actions/`, `playbooks/`, `skills/`.
- Add `keystone_new_corpus` tool and `keystone_new_action`, `keystone_new_playbook`.
- Replace `harness_bootstrap` tool body: when the user opts in, materialize the entire shipped tree under `.keystone/harness/`. When tree already exists, write missing files only.
- Ship the default sensor library (lint, type, test, build, drift, coverage) and the default inferential sensor library (security review, code review, accessibility review, performance review).

**DoD:** `keystone_harness_bootstrap()` against an empty repo produces a full-featured `.keystone/harness/` populated from shipped templates. Scaffold tests assert byte-identical output between inline-string (legacy) and template-read paths during the migration window.

### Phase 19 — Bootstrap playbook + menu overlay

**Goal:** init becomes a shipped playbook. Menu file overlays the user's existing content.

- Ship `templates/harness/playbooks/bootstrap.md` — the playbook that walks the agent through codebase analysis, state-ledger fill, default-content acceptance, agent-menu install.
- Reframe `keystone_bootstrap` prompt to seed the playbook walk, not run the work inline.
- Replace `Scaffold.target_add` body: parse the existing menu file, locate the delimited Keystone block (`<!-- BEGIN KEYSTONE -->` … `<!-- END KEYSTONE -->`), insert or refresh the block, preserve all other content. Idempotent.
- Ship a per-agent menu body under `templates/menu/<agent>.md`. Each is a thin pointer to the harness and a list of agent-applicable Keystone primitives.

**DoD:** running the bootstrap playbook against a repo with a hand-written `CLAUDE.md` preserves the human content above and below the Keystone block. Re-running refreshes the block in place without touching user content.

### Phase 20 — Cascade engine + canonical / required semantics

**Goal:** Python implementation of the precedence, severity, canonical, required model from §2.

- New module `src/keystone_mcp/cascade.py`:
  - Inputs: layers (agent base, ordered external sources, project layer) as lists of `(layer, port, name, body, severity, canonical, required-flag)` tuples.
  - Outputs: resolved layer per item, list of conflicts, list of canonical violations, list of required gaps, list of unreachable items.
- `context.yaml` schema additions: `canonical:` and `required:` blocks per source.
- External-source manifest schema additions: `keystone-source.yaml` at the root of a `repo` source declaring its own canonical and required items.
- Add `keystone://harness/verify` resource — read-only, returns the cascade report (no resets, no writes).
- Add `keystone://harness/doctor` resource — supersets verify with path-conformance, budget, ledger-freshness checks.
- Ship `templates/harness/playbooks/verify.md` and `doctor.md`.
- Audit playbook integrates the cascade report — unfulfilled required items and canonical violations become audit candidates.

**DoD:** declaring a canonical guide in an external source blocks a same-named project file from loading. The agent never sees the project body. `keystone://harness/verify` reports the block. The user can remove the project file or rename it under a non-canonical namespace.

### Phase 21 — Source installer + patch system

**Goal:** add an external source through a skill-driven flow; ship a patch tree for forward-only updates.

- Ship `templates/harness/skills/keystone-source-installer/SKILL.md` — walks the user through declaring a source: type, identifier, version, auth, classify selectors, canonical/required.
- Ship `templates/harness/playbooks/install.md` — the higher-level flow that invokes the installer skill, then runs verify.
- For `repo` sources: fetch into `~/.cache/keystone-mcp/repos/<sha>/` (see Phase 23 — folder + repo). Verify against `keystone-source.yaml` declared canonical/required.
- Ship `templates/patches/<version>/` with per-version patch sets. A patch is an ordered list of diffs against the previous version's shipped tree.
- Add `keystone_apply_patches()` tool (atomic, refuses to overwrite user-modified files).
- Ship `templates/harness/playbooks/patch.md` — the user-facing flow.
- Add `keystone://harness/patch/pending` resource.

**DoD:** running install from an empty `context.yaml` produces a working source binding. Running patch against an older shipped tree updates to current; conflicts are reported, not silently applied.

### Phase 22 — Two flywheels as full playbooks

**Goal:** Learning and Pruning are first-class shipped flows.

- Ship `templates/harness/playbooks/audit.md` — Pruning playbook. Walks guide staleness, corpus moves-on, archive moves with reasoning, reload notice.
- Ship `templates/harness/playbooks/learn.md` — Learning playbook. Captures finding into `learning/inbox/`, proposes classification, reload-on-promotion.
- Ship `templates/harness/skills/keystone-reload-notice/SKILL.md` — the skill that emits the reload prompt across agents.
- Ship `templates/harness/skills/keystone-archive/SKILL.md` — moves files to `archive/<port>/<name>.md` with reasoning frontmatter.
- Ship `templates/harness/learning/wishlist.md` template.

**DoD:** the Learning and Pruning loops on the site are walkable, step-by-step, against any harness installed by the manager. The agent never deletes guide content — only archives it.

### Phase 23 — Folder and repo source types

**Goal:** point a topic at a directory of markdown, or at a remote git repository.

- New adapter `src/keystone_mcp/adapters/folder.py`. Walks a directory tree, delegates per-file to `markdown.py`. Globs (`include`, `exclude`). Path-traversal blocked.
- New adapter `src/keystone_mcp/adapters/repo.py`. Resolves `owner/repo@version` to a git URL + ref. Fetches into `~/.cache/keystone-mcp/repos/<sha>/`. Delegates to `folder` against the materialised tree. TTL for branch refs; immutable cache for tag/sha refs.
- Both adapters honour the cascade declarations (§2): a `repo` source's `keystone-source.yaml` can mark its own items canonical.
- Wire in `resolver.py`; add tests with local bare-repo fixtures.

**DoD:** declaring a `folder` source against `../shared/policies/` returns merged docs. Declaring a `repo` source against `tacoda/tacoda-org@v1.1.2` materialises, caches, and merges. Both pass through the cascade engine.

### Phase 24 — Inferential sensors first-class

**Goal:** document `mode: computational | inferential` and ship the default inferential library.

- `keystone://harness/options` lists `sensor_modes`.
- Default inferential sensors ship under `templates/harness/sensors/` (declaration) + `templates/harness/prompts/` (bodies): `security-review`, `code-review`, `accessibility-review`, `performance-review`.
- Adapter bundles indicate sensor mode capability per agent (`adapters/<agent>/sensors.md`).

**DoD:** running an inferential sensor against a change set surfaces a PASS/FAIL with reasoning from the matching prompt.

### Phase 25 — Re-brand to "Keystone Harness Manager"

**Goal:** every doc + the PyPI listing + the server-level `INSTRUCTIONS` reflect the new name.

- Update `README.md` top: "Keystone Harness Manager — the end-to-end harness manager for any project."
- Update `INSTRUCTIONS` block in `server.py`.
- Update `pyproject.toml` description.
- Add `CHANGELOG.md` entry.
- Optional: rename the package to `keystone-harness` on PyPI with a `keystone-mcp` redirect package for one release. (Open question — could defer.)

**DoD:** every user-facing surface refers to the harness manager. PyPI listing matches.

### Phase 26 — Edit-path test suite

**Goal:** prove the triad (§7) — same operation through three paths produces byte-identical files.

- New test module `tests/test_edit_path_triad.py`. Per scaffolded artifact (guide, corpus, sensor, action, playbook, adapter, skill, script, prompt):
  - write via MCP tool,
  - write via shipped skill (simulate by reading the skill, executing its steps programmatically),
  - write via direct filesystem (manual placement of the canonical body).
- Assert byte-identical files across all three.

**DoD:** every supported port survives the triad test. Failures point at template drift before users see it.

### Phase 27 — Token budget + observability

**Goal:** the user knows the ambient-load cost of their harness.

- `src/keystone_mcp/budget.py` — token count via `tiktoken` (or a deterministic word-count fallback if `tiktoken` isn't desired as a dep).
- `keystone://harness/budget` resource — totals per port, hot files, cascade-resolved totals (excludes items blocked by canonical locks).
- Ship `templates/harness/skills/keystone-budget-reporter/SKILL.md`.
- Doctor playbook surfaces budget findings.

**DoD:** the user sees how many tokens their guides load, sorted by file.

### Phase 28 — Sensor runner skill

**Goal:** sensors run consistently across agents.

- Ship `templates/harness/skills/keystone-sensor-runner/SKILL.md`. Computational sensors → Bash invocation when the adapter supports execution. Inferential sensors → load the matching prompt and run the reasoning step.
- Doctor + verify report sensor health.

**DoD:** a single command invocation walks every applicable sensor and produces a unified report.

### Phase 29 — Migration from CLI installs (optional)

**Goal:** users who already have a CLI-installed harness can adopt the manager without losing content.

- Ship a `keystone_migrate_from_cli` tool that:
  - reads `keystone.json`,
  - converts plugin declarations into `context.yaml` source declarations,
  - leaves project markdown intact,
  - removes `keystone.lock.json` (no longer used),
  - writes a delimited Keystone block into the existing menu file (preserving any user additions).
- Ship `templates/harness/playbooks/migrate.md` to drive the flow.

**DoD:** a CLI-installed repo runs the migrate playbook and ends with a fully-functional manager-owned harness.

---

## 10. Sequencing

```
16 namespace ──► 17 tiers ──► 18 templates+actions+playbooks ──► 19 bootstrap+menu overlay
                                                          │
                                                          └─► 20 cascade engine ──► 21 source installer + patch
                                                                                              │
                                                                                              └─► 22 flywheel playbooks
                                                                                                            │
                                                                                                            └─► 23 folder + repo
                                                                                                                       │
                                                                                                                       └─► 24 inferential sensors first-class
                                                                                                                                  │
                                                                                                                                  └─► 25 re-brand
                                                                                                                                            │
                                                                                                                                            └─► 26 edit-path triad tests
                                                                                                                                                       │
                                                                                                                                                       └─► 27 budget + observability
                                                                                                                                                                  │
                                                                                                                                                                  └─► 28 sensor runner skill
                                                                                                                                                                            │
                                                                                                                                                                            └─► 29 migrate from CLI [optional]
```

Phases 16, 17, 18 ship as 0.2.0 (breaking). Phase 19, 20 ship as 0.3.0 (breaking — new cascade semantics affect any consumer relying on the prior naive overlay). Phases 21–29 ship as 0.3.x minors.

---

## 11. Risk register

| Risk | Mitigation |
| --- | --- |
| Template tree drift between in-repo and installed-in-user-project | Phase 26 edit-path triad tests, plus per-template SHA index shipped in the package; doctor compares user files to the index. |
| Cascade engine produces surprising "unreachable" skips | Audit report always lists skipped files with the canonical declaration that caused them. Reversible: rename or relocate the project file. |
| Menu overlay loses user content during refresh | Delimited block is the only mutable region. Tests assert preservation of N variations of pre/post-block content. |
| Patch application overwrites a user-modified shipped file | Patch applier diffs against the per-version template index; user-modified files surface as conflicts requiring explicit resolution. |
| External-source adapter network failures | Existing health endpoint per adapter; verify and doctor report. The agent surfaces, never silently degrades. |
| `actions`/`playbooks` collapse / restore back-and-forth between Phase 11b → 14b → 18 confuses early adopters | Phase 18 ships with a clear changelog entry. The "skills also exist" point is documented as the complementary primitive. |
| Bootstrap writes a large default tree the user doesn't want | Bootstrap playbook offers per-port acceptance; the agent asks before writing. Defaults are opinionated but skippable. |
| Re-brand to "Harness Manager" confuses users who searched for "keystone-mcp" | Phase 25 retains the PyPI package name; only the user-facing branding shifts. Optional rename later behind a redirect. |
| Cascade engine over-fires "required gap" warnings | The audit report aggregates them; verify exits zero on gap-only findings (gaps are work, not errors). |

---

## 12. Out of scope (this plan)

- Multi-tenant manager (one repo's harness, one process).
- Secret-store auth (`secret:NAME` scheme). Stays open — defer until requested.
- Classifier-strength DSL. Defer until misclassification surfaces.
- Cross-language manager (Python is the implementation; markdown is the data).
- A native UI for the harness manager. The MCP surface plus an editor is the UI.
- Backwards compatibility with the Go CLI at the binary level. Migration from CLI installs is Phase 29 (optional one-shot).

---

## 13. Namespace summary (consumer-facing)

> The Keystone Harness Manager (`keystone-mcp` on PyPI) exposes every primitive under a `keystone` namespace. Tools and prompts are prefixed `keystone_` (`keystone_get_context`, `keystone_new_guide`, `keystone_task`, `keystone_audit`, …). Resources are rooted at `keystone://` (`keystone://context/list`, `keystone://harness/status`, `keystone://harness/verify`, …). Manager-authored skills are named `keystone-<slug>` so they remain compatible with the FastMCP-native `skill://` resource scheme. The harness itself lives at `.keystone/harness/` — plain markdown, hand-editable, git-tracked.

---

## 14. Open questions

1. **PyPI rename.** Stay on `keystone-mcp` for the package name, or rename to `keystone-harness`? Recommendation: stay on `keystone-mcp` for one or two releases, then optionally publish a redirect package.
2. **Patch index format.** YAML manifest per version with file-level diffs? Or full templated trees per version with the applier computing diffs at runtime? Recommendation: shipped trees + runtime diff — simpler invariants, larger artifact.
3. **Token counter dependency.** `tiktoken` is heavy. Use a deterministic word-count proxy by default; gate `tiktoken` behind an extras install (`pip install keystone-mcp[tokens]`)?
4. **Migration from CLI.** Bundle the migrate tool with the core package (Phase 29) or ship as a one-shot script? Recommendation: bundle — the cost is small, the discoverability is large.
5. **Pre-existing menu content delimiters.** Standardise on `<!-- BEGIN KEYSTONE -->` / `<!-- END KEYSTONE -->`, or use an HTML comment block + a frontmatter sentinel? Recommendation: HTML comments — work in every markdown renderer; no frontmatter conflicts.
6. **External-source `canonical` granularity.** Per-file (`canonical: { guides: ["documentation"] }`) or per-rule within a file? Recommendation: per-file for v0.2; per-rule deferred until a real conflict surfaces.

---

*Owner: Ian Johnson · drafted 2026-06-10 · supersedes the prior "feature parity" plan; reframes `keystone-mcp` as the Keystone Harness Manager.*
