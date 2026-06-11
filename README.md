# keystone-mcp — Keystone Harness Manager

The **Keystone Harness Manager** is the end-to-end harness manager for any
project. It's a single MCP server (`keystone-mcp` on PyPI) that owns the
full lifecycle of a project harness:

- scaffold + materialize a shipped template tree under
  `.keystone/harness/`
- broker rules, reasoning, skills, and commands from any external source
  (markdown, folder, repo, GitHub, Confluence, Notion, Jira, Linear,
  Slack)
- run computational and inferential sensors as blocking checks
- resolve a cascade across external sources and the project layer
  (canonical locks, required gaps, conflicts, unreachable items)
- apply forward-only shipped-template patches as the manager evolves
- drive Learning + Pruning flywheels via shipped playbooks and skills
- overlay the agent menu file (CLAUDE.md, AGENTS.md, …) without
  clobbering any pre-existing user content

The agent treats each retrieved payload differently:

- **rules** — constraints to obey (`must` / `should` / `may`)
- **reasoning** — background facts and intent
- **skills** — procedural how-to knowledge (multi-step playbooks)
- **commands** — canned invocations (shell commands, scripts, named recipes)

Instead of cramming organizational context into every system prompt, the agent
reads `keystone://context/{topic}` resources or calls `keystone_get_context(topic)` and the
broker fans the request out to the right backing source.

## Status

Pre-1.0; the package name on PyPI stays `keystone-mcp`. Phases 1–24
shipped per [`FEATURE_PARITY_PLAN.md`](./FEATURE_PARITY_PLAN.md) and
[`CHANGELOG.md`](./CHANGELOG.md). Tests pass.

## Adapters

Source types (`type:` in `.keystone/context.yaml`):

| Type | Description |
| --- | --- |
| `markdown` | One local markdown file per query. |
| `folder` | Walk a local directory tree of markdown. Globs (`include` / `exclude`). |
| `repo` | Resolve `owner/repo@version` or a git URL; cache under `~/.cache/keystone-mcp/repos/<sha>/`. Tag/sha refs cache immutably; branch refs honor `ttl`. |
| `github` | Read markdown from a GitHub repo via the API. Requires `auth`. |
| `confluence` | Pages from a Confluence Cloud workspace. Requires `email` + `auth`. |
| `notion` | Pages from Notion. Requires `auth`. |
| `jira` | Issues from a Jira project. Requires `auth`. |
| `linear` | Issues from a Linear team. Requires `auth`. |
| `slack` | Messages from a Slack channel. Requires `auth`. |
| `harness` | The project's own `.keystone/harness/` tree (root is fixed). |

## Adapter overview

| Adapter | Auth | What it emits |
|---|---|---|
| `markdown` | none (repo-local) | rules / reasoning / skills / commands |
| `github` | PAT | CODEOWNERS, branch protection (rules); PRs, releases (reasoning) |
| `confluence` | email + API token | page content (all four kinds) |
| `notion` | integration token | page content (all four kinds), database rows (reasoning) |
| `jira` | email + API token | issues, JQL search (reasoning) |
| `linear` | personal API key | issues, GraphQL filter (reasoning) |
| `slack` | bot OAuth token | pinned messages (rules), recent discussion (reasoning) |

## Install

Published to PyPI as [`keystone-mcp`](https://pypi.org/project/keystone-mcp/).

```bash
pip install keystone-mcp             # core
pip install "keystone-mcp[tokens]"   # + tiktoken-backed budget tokenizer
uvx keystone-mcp                     # one-shot run via uv
pipx install keystone-mcp            # install + add to PATH
```

Without the `tokens` extra, `keystone://harness/budget` falls back to
a deterministic word-count proxy (~0.75 words / token). With the
extra, the budget reports exact `cl100k_base` token counts.

Or from source:

```bash
git clone https://github.com/tacoda/keystone-mcp.git
cd keystone-mcp
uv sync
uv run keystone-mcp        # console entry point
```

Wire into a Claude Code (or any MCP host) project. Add to `.mcp.json`:

```json
{
  "mcpServers": {
    "keystone": {
      "command": "uvx",
      "args": ["keystone-mcp"],
      "env": {
        "KEYSTONE_CONFIG": "/path/to/your/project/.keystone/context.yaml"
      }
    }
  }
}
```

The config path defaults to `.keystone/context.yaml` relative to the working
directory; override with `KEYSTONE_CONFIG`.

## Quickstart

1. Create `.keystone/context.yaml` in your project:

   ```yaml
   sources:
     docs:
       type: markdown
       root: .keystone/context/

   topics:
     deploy-policy:
       description: |
         Rules and context for production deploys.
       sources:
         - source: docs
           query: { file: deploy-policy.md }
           classify:
             rules: { heading: "Rules", severity: must }
             reasoning: { heading: "Background" }
       cache: 15m
   ```

2. Create `.keystone/context/deploy-policy.md`:

   ```markdown
   # Deploy Policy

   ## Rules

   - MUST run full CI green before any production deploy.
   - SHOULD prefer Tuesday/Wednesday morning deploys.

   ## Background

   The team adopted these rules after a 2025 incident.
   ```

3. Start the server. The agent now sees `deploy-policy` in `keystone_list_topics`
   and can read `keystone://context/deploy-policy` to load the envelope.

The repo's own [`.keystone/context.yaml`](./.keystone/context.yaml) is a
working example with topics for deploys, ownership, coding standards, and a
release playbook (plus commented-out examples of every external adapter).

## MCP surface

### Tools

| Tool | Returns |
|---|---|
| `keystone_get_context(topic)` | full envelope (rules + reasoning + skills + commands) |
| `keystone_list_topics(tag?)` | directory of configured topics |
| `keystone_harness_bootstrap()` | scaffold the harness skeleton at `.keystone/harness/` |
| `keystone_new_guide(name, tier?)` | scaffold a new guide; `tier` ∈ `iron-law` / `golden` / `rules` |
| `keystone_new_sensor(name, kind?, mode?)` | scaffold a sensor + matching script (computational) or prompt (inferential) |
| `keystone_new_script(name, body?)` | scaffold a sensor script (or ad-hoc shell script) |
| `keystone_new_prompt(name, body?)` | scaffold a sensor prompt (or ad-hoc prompt for inferential checks) |
| `keystone_new_skill(name, description?)` | scaffold `skills/<name>/SKILL.md` (FastMCP-native; manager-authored skills are auto-prefixed `keystone-`) |
| `keystone_new_action(name)` | scaffold `actions/<name>.md` |
| `keystone_new_playbook(name)` | scaffold `playbooks/<name>.md` |
| `keystone_new_corpus(name)` | scaffold `corpus/<name>.md` |
| `keystone_new_adapter(agent)` | scaffold a per-agent adapter dir |
| `keystone_target_add(agent, project_root?)` | install or refresh agent menu file at project root (overlay; preserves user content) |
| `keystone_apply_patches()` | apply pending shipped patches; skips user-modified files |

### Prompts

Lifecycle workflows that seed multi-step agent conversations. The agent
invokes a prompt, walks the phases, and calls scaffold tools along the way.

| Prompt | Purpose |
|---|---|
| `bootstrap()` | one-time codebase analysis → fill state ledgers under `corpus/state/` |
| `task(description)` | end-to-end work: spec → orient → implement → verify → review |
| `audit()` | dual-flywheel: learning (capture) + pruning (retire stale) |
| `learn(finding)` | capture a finding into `learning/inbox/` for batched promotion |

All harness paths are fixed under `.keystone/harness/` — the `.keystone/`
directory is team-shared and version-controlled. **Never put secrets there.**
Reference them via `env:VAR` in `.keystone/context.yaml` instead. Scaffold
tools refuse to write files whose names look like secrets (`secret`, `token`,
`credential`, `password`, `api_key`, `private`, `envfile`, …).

### Resources

| URI | Purpose |
|---|---|
| `keystone://context/list` | configured topic directory |
| `keystone://context/{topic}` | full envelope for one topic |
| `keystone://source/{name}/health` | adapter reachability + auth state |
| `keystone://harness/status` | harness layout audit (root=harness) |
| `keystone://harness/options` | valid scaffold-tool arguments |
| `keystone://harness/verify` | cascade report (resolved / unreachable / canonical_violations / required_gaps / conflicts) |
| `keystone://harness/doctor` | verify + path conformance + ambient-load budget proxy |
| `keystone://harness/patch/pending` | pending shipped patches and detected conflicts |
| `keystone://harness/budget` | ambient-load budget report (per-port + hot files + approximate tokens) |

### Envelope shape

Every retrieval returns the same envelope. Example:

```json
{
  "topic": "deploy-policy",
  "rules": [
    {
      "id": "rules-001",
      "text": "run full CI green before any production deploy.",
      "source": "markdown://deploy-policy.md#rules",
      "severity": "must"
    }
  ],
  "reasoning": [
    {
      "text": "The team adopted these rules after a 2025 incident.",
      "source": "markdown://deploy-policy.md#background"
    }
  ],
  "skills": [],
  "commands": [],
  "fetched_at": "2026-06-10T14:32:00+00:00",
  "cache_hit": false
}
```

## Configuration

### Topics

Topics are the agent-facing abstraction. Each topic binds one or more
adapter calls and declares how their output classifies into the four kinds:

```yaml
topics:
  repo-policy:
    description: Combined ownership and branch-protection rules.
    sources:
      - source: docs
        query: { file: owners.md }
        classify:
          rules: { heading: "Required reviewers" }
      - source: gh
        query: { type: codeowners }
      - source: gh
        query: { type: branch_protection, branch: main }
    cache: 5m
```

Single-source topics can use the shorthand:

```yaml
topics:
  rollback:
    description: Rollback procedure.
    source: docs
    query: { file: rollback.md }
    classify:
      rules: { heading: "Rules" }
```

### Multi-source merge

When two sources contribute rules whose normalized text matches:
- **Highest severity wins** (`must > should > may`).
- **Ties** at the top severity keep both rules so each source stays cited.

Reasoning, skills, and commands stay additive — no deduplication.

### Classify selectors

`markdown`, `confluence`, and `notion` share the same heading-based
vocabulary. Sections split by H2; skills/commands sub-split by H3.

```yaml
classify:
  rules:
    heading: "Rules"             # single or list, e.g. ["Rules", "Must"]
    severity: must               # default for bullets without MUST/SHOULD/MAY prefix
  reasoning:
    heading: "Background"
    # or
    all: true                    # everything not matched by another kind
  skills:
    heading: "Procedures"        # each H3 → one skill (name + body)
  commands:
    heading: "Commands"          # each H3 → one command (first code block = invocation)
```

For `github`, `jira`, `linear`, `slack` the query `type` determines the kind
(e.g. `codeowners` → rules, `recent_prs` → reasoning).

### Secrets

Reference environment variables with the `env:` prefix:

```yaml
sources:
  gh:
    type: github
    repo: acme/widgets
    auth: env:GITHUB_TOKEN
```

The loader fails fast at startup if a referenced env var is unset.

### Cache

Default is in-memory (lost on restart). Persistent sqlite cache survives
process restarts:

```yaml
cache:
  backend: sqlite
  path: .keystone/cache.db
```

Per-topic TTLs use `5s` / `10m` / `2h` / `1d` syntax.

## Development

```bash
uv sync                     # install deps
uv run pytest -q            # run tests
uv run python -m keystone_mcp.server   # run server
```

The test suite uses `respx` to mock all external APIs — no live credentials
required.

## License

TBD.
