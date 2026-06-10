# keystone-mcp

An MCP server that retrieves contextual information from company resources and
surfaces it to coding agents as **rules**, **reasoning**, **skills**, and
**commands**.

The agent treats each kind differently:
- **rules** — constraints to obey (`must` / `should` / `may`)
- **reasoning** — background facts and intent
- **skills** — procedural how-to knowledge (multi-step playbooks)
- **commands** — canned invocations (shell commands, scripts, named recipes)

Instead of cramming organizational context into every system prompt, the agent
asks for context by intent (`get_rules("deploy")`, `get_reasoning("billing-service")`)
and the broker fans the request out to the right backing source.

## Status

Phases 1–9 shipped. Seven adapters live, plus a shared classifier, multi-source
merge with conflict resolution, and a persistent sqlite cache. 171 tests pass.

See [`PLAN.md`](./PLAN.md) for the full design and remaining open work.

## Adapters

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

Until the package is published (Phase 11), clone and run from source:

```bash
git clone tacoda_github:tacoda/keystone-mcp.git
cd keystone-mcp
uv sync
```

Run the server:

```bash
uv run python -m keystone_mcp.server
```

Or wire it into a Claude Code project as an MCP server. Add to `.mcp.json`:

```json
{
  "mcpServers": {
    "keystone": {
      "command": "uv",
      "args": [
        "--directory", "/path/to/keystone-mcp",
        "run", "python", "-m", "keystone_mcp.server"
      ],
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

3. Start the server. The agent now sees `deploy-policy` in `list_topics` and
   can call `get_rules("deploy-policy")` to load the two rules.

The repo's own [`.keystone/context.yaml`](./.keystone/context.yaml) is a
working example with topics for deploys, ownership, coding standards, and a
release playbook (plus commented-out examples of every external adapter).

## MCP surface

### Tools

| Tool | Returns |
|---|---|
| `get_context(topic)` | full envelope (rules + reasoning + skills + commands) |
| `get_rules(topic)` | rules only |
| `get_reasoning(topic)` | reasoning only |
| `get_skills(topic)` | skills only |
| `get_commands(topic)` | commands only |
| `list_topics(tag?)` | directory of configured topics |
| `source_health(source)` | adapter reachability + auth state |

### Resources

| URI | Purpose |
|---|---|
| `context://list` | configured topic directory |
| `context://<topic>` | full envelope for one topic |

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
