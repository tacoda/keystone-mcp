# keystone-mcp — Plan

An MCP server that retrieves contextual information from company resources and
surfaces it to coding agents as **rules to obey**, **reasoning to consult**,
**skills to follow**, and **commands to consider running**.

---

## What this is

A context broker. The agent asks for context relevant to its current work; the
server fetches from one or more company resources (wikis, docs, ticket systems,
repo files, etc.) and returns a structured payload with four kinds:

- **`rules`** — constraints the agent must follow (e.g., "all schema changes
  require a migration file", "deploys to prod gated on green CI"). Severity
  `must` / `should` / `may`.
- **`reasoning`** — background facts that inform decisions but don't constrain
  them (e.g., team roster, sprint goal, architectural intent).
- **`skills`** — procedural how-to knowledge: multi-step playbooks the agent
  can follow (e.g., "how to cut a patch release", "how to roll back a deploy").
- **`commands`** — canned invocations the agent can execute, each with a name,
  a literal invocation (typically shell), and a description of when to use it.

The agent treats each kind differently: rules are non-negotiable, reasoning is
input to judgment, skills are procedures to follow, commands are invocations
to consider running.

## What this is not

- **Not a verbatim service wrapper.** Official MCP servers for Atlassian, Notion,
  GitHub already exist for *operating* those systems. This server sits above them
  at the contextual-retrieval layer.
- **Not a static rules file.** Rules in `.claude/rules/` are loaded by the host
  at session start. This server returns rules that depend on **live data** — who
  owns this module, what's in the current sprint, what the latest runbook says.
- **Not a database.** Source systems own their data. This server resolves,
  fetches, normalizes, optionally caches.
- **Not an LLM.** It does not summarize, rank, or reason about retrieved content
  beyond mechanical filtering. The agent reasons; the server retrieves.

---

## Why this exists

Coding agents fail at organizational context. They lack two things:

1. **Knowledge of constraints** that aren't visible in the code (deploy windows,
   review policies, security requirements, domain invariants).
2. **Knowledge of intent** that isn't documented in the diff (why this module
   exists, what the team is currently focused on, who owns what).

Both live in company resources — Confluence pages, Notion wikis, Jira tickets,
runbooks, ADRs, team rosters. Pulling them in *every* session via system prompt
is wasteful; pulling them in *when relevant* via a typed MCP call is targeted.

The broker shape (one server, many sources) keeps the agent's mental model small:
it asks for context by intent (`rules_for("deploy")`,
`reasoning_for("billing-service")`), not by source.

---

## Design principles

1. **Payload kind is a first-class distinction.** Every retrieval returns all
   four lists (`rules`, `reasoning`, `skills`, `commands`), even when some are
   empty. Mixing them collapses the agent's decision-making — a how-to is not a
   constraint, and a constraint is not a fact.
2. **Repo owns the context map.** Which resources back which queries is declared
   in repo-local config, version-controlled with the code.
3. **Adapters are pluggable.** Each resource type is a module implementing a
   common interface. Adding a resource is adding an adapter.
4. **Broker, not store.** Default behavior is passthrough fetch. Caching is
   opt-in per query with a TTL.
5. **Discoverable surface.** The agent sees the catalog of available context
   queries via `resources/list` — names + descriptions only.
6. **Fail loud at boundaries.** Missing credentials, malformed config, or
   unreachable sources surface explicit errors.
7. **Read-only by default.** No adapter writes back to a source unless a future
   phase explicitly opens that door.

---

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│  FastMCP server                                              │
│                                                              │
│   resources                  tools                           │
│   ├── context://list         ├── get_context(topic)          │
│   ├── context://<topic>      ├── get_rules(topic)            │
│   └── source://<n>/health    ├── get_reasoning(topic)        │
│                              ├── get_skills(topic)           │
│                              ├── get_commands(topic)         │
│                              └── list_topics(tag?)           │
│                                                              │
│   ┌──────────────────────────────────────────────────────┐   │
│   │  Resolver                                            │   │
│   │   reads context.yaml → routes topic to adapter(s)    │   │
│   │   normalizes results → {rules[], reasoning[]}        │   │
│   └──────────────────────────────────────────────────────┘   │
│                            │                                 │
│   ┌────────┬────────┬──────┴──────┬─────────┬──────────┐     │
│   ▼        ▼        ▼             ▼         ▼          ▼     │
│ Markdown  Jira  Confluence      Notion    GitHub    (more)   │
│  (P1)    (P2)    (P2)            (P2)     (P2)              │
└──────────────────────────────────────────────────────────────┘
```

### Components

- **FastMCP server** — entrypoint, registers resources and tools.
- **Resolver** — loads config, maps a topic to one or more adapter calls,
  bins results by kind (`rules`/`reasoning`/`skills`/`commands`), applies caching.
- **Adapters** — one per resource type. Implements
  `fetch(query, classify) -> list[ContextDoc]` where each doc carries a
  `kind: rule | reasoning | skill | command` tag.
- **Topic registry** — in-memory representation of the topic map, rebuilt on
  config change.
- **Cache** — keyed by `(topic, source, query-hash)`. In-memory for Phase 1.

---

## Payload shape

Every context retrieval returns the same envelope:

```json
{
  "topic": "deploy-policy",
  "rules": [
    {
      "id": "deploy-001",
      "text": "Production deploys require two approvals on the PR.",
      "source": "confluence://deploy-runbook#approvals",
      "severity": "must"
    }
  ],
  "reasoning": [
    {
      "text": "Team prefers Friday morning deploys to leave weekend for rollback.",
      "source": "notion://eng-wiki/deploy-cadence",
      "recency": "2026-04-12"
    }
  ],
  "skills": [
    {
      "id": "procedures-001",
      "name": "Cut a patch release",
      "body": "1. Confirm main is green ... 5. Watch the release workflow.",
      "source": "markdown://release-playbook.md#procedures/cut-a-patch-release"
    }
  ],
  "commands": [
    {
      "id": "commands-001",
      "name": "tag-release",
      "invocation": "git tag -a vX.Y.Z -m 'release' && git push --tags",
      "description": "Run after the patch-release procedure to tag and push.",
      "source": "markdown://release-playbook.md#commands/tag-release"
    }
  ],
  "fetched_at": "2026-06-10T14:32:00Z",
  "cache_hit": false
}
```

Conventions:
- `rules[].severity` ∈ `{must, should, may}` — maps to RFC-2119-ish strength.
- `rules[].source` is a stable URI back to the originating doc so the agent
  (and humans) can verify.
- `reasoning[]` is unranked; agent decides what's relevant.
- `skills[]` carry a `name` + free-form `body`. The body is the playbook text;
  the agent reads it the same way a human follows a runbook.
- `commands[]` carry a `name`, a literal `invocation` (typically shell), and a
  `description` explaining when to use it. Agents do not execute commands
  automatically — they propose them to the user.
- Adapters classify their own output via config-declared selectors (heading,
  tag, CSS, JQL field). Misclassification is a config bug, not a server bug.

---

## Configuration model

Single YAML file in the consuming repo (`.keystone/context.yaml`).

```yaml
sources:
  docs:
    type: markdown
    root: .keystone/context/

  wiki:
    type: confluence
    base_url: https://acme.atlassian.net/wiki
    space: ENG
    auth: env:CONFLUENCE_TOKEN
    email: env:CONFLUENCE_EMAIL

  tickets:
    type: jira
    base_url: https://acme.atlassian.net
    project: ENG
    auth: env:JIRA_TOKEN
    email: env:JIRA_EMAIL

topics:
  deploy-policy:
    description: |
      Rules and context for production deploys. Read before any change touching
      deploy scripts, CI config, or release tooling.
    sources:
      - source: docs
        query: { file: deploy-policy.md }
        classify:
          rules:    { heading: "Rules" }
          reasoning: { heading: "Background" }
      - source: wiki
        query: { page: "Deploy Runbook" }
        classify:
          rules:    { tag: "must" }
          reasoning: { tag: "context" }
    cache: 15m

  current-sprint:
    description: |
      Active sprint goal and in-flight work. Read when planning, estimating, or
      choosing what to pick up next.
    sources:
      - source: tickets
        query: { type: sprint.active }
        classify:
          reasoning: { all: true }   # tickets are facts, not rules
    cache: 5m

  module-ownership:
    description: |
      Who owns a given module and how to reach them.
    sources:
      - source: docs
        query: { file: owners.md }
        classify:
          rules:    { heading: "Required reviewers" }
          reasoning: { heading: "Contacts" }
```

Notes:
- Secrets resolve from environment variables (`env:NAME`). No secrets in YAML.
- `classify` is how an adapter decides which chunks become rules vs reasoning.
  Selector vocabulary varies per adapter type (heading, tag, CSS, JQL field).
- `description` is shown in `context://list` — should explain *when* to call,
  not *what data comes back*.

---

## MCP surface

### Resources

| URI | Purpose |
|---|---|
| `context://list` | Directory of all configured topics (slugs + descriptions). Cheap. |
| `context://<topic>` | Full payload (rules + reasoning) for one topic. Triggers fetch. |
| `source://<name>/health` | Adapter status, last successful fetch, auth state. |

### Tools

| Tool | Purpose |
|---|---|
| `get_context(topic)` | Full envelope: rules + reasoning + skills + commands. Default call. |
| `get_rules(topic)` | Rules only. Use when the agent is about to act and needs constraints. |
| `get_reasoning(topic)` | Reasoning only. Use when the agent is exploring or explaining. |
| `get_skills(topic)` | Skills only. Use when the agent needs a how-to / playbook. |
| `get_commands(topic)` | Commands only. Use when the agent needs a canned invocation. |
| `list_topics(tag?)` | Filtered topic directory. Tags optional in YAML. |

### Server instructions block

```
This server retrieves company context as four kinds of payload:
  - rules:     constraints to obey (severity must/should/may)
  - reasoning: background facts and intent
  - skills:    procedural how-to knowledge (multi-step playbooks)
  - commands:  canned invocations (shell commands, scripts, named recipes)

Call `list_topics` or read `context://list` to see what's available. Use
`get_context(topic)` for the full envelope, or narrow with `get_rules`,
`get_reasoning`, `get_skills`, or `get_commands`. Rules with severity `must`
are non-negotiable; surface conflicts to the user rather than silently
overriding them.
```

---

## Phase 1 — markdown adapter, end-to-end

**Goal:** prove the four-kind payload (rules, reasoning, skills, commands)
end-to-end against the simplest possible resource. No external auth, no rate
limits, just repo-local files.

In scope:
- FastMCP server skeleton, stdio transport.
- YAML config loader + topic registry (single-source shorthand and multi-source
  list shape both parse, though Phase 1 only exercises single-source).
- `markdown` adapter:
  - reads files under a configured root (path-traversal blocked)
  - splits by H2 headings, classifies each section by config selectors
  - `rules` sections → one `rule` per bullet, severity from `MUST/SHOULD/MAY`
    prefix or per-section default
  - `reasoning` sections → one `reasoning` per section
  - `skills` sections → one `skill` per H3 sub-heading (name + body)
  - `commands` sections → one `command` per H3 (name + fenced-block invocation
    + surrounding description)
- Resolver: per-topic in-memory TTL cache; binds caches across all four kinds.
- Resources: `context://list`, `context://<topic>`.
- Tools: `get_context`, `get_rules`, `get_reasoning`, `get_skills`,
  `get_commands`, `list_topics`, `source_health`.
- Health endpoint for each configured source.

Out of scope (deferred):
- Adapters beyond markdown.
- Cross-source merge semantics (precedence, dedup, conflict resolution).
- Persistent cache.
- Write operations.
- Semantic search across topics.

**Definition of done:**
- Agent configured with this server can call `get_rules("deploy-policy")` and
  receive bullet-classified rule objects with severities from a repo-local
  markdown file.
- `get_reasoning("deploy-policy")` returns the reasoning section.
- `get_skills("release-playbook")` returns each `### …` procedure as a Skill.
- `get_commands("release-playbook")` returns each `### name` + fenced-block
  pair as a Command with `invocation` and `description` fields.
- `get_context(topic)` returns all four lists in one envelope.
- `context://list` shows all configured topics with descriptions.
- Missing file, escape from root, or malformed classifier emits an explicit
  error (no silent empty result).

---

## Phase 2 — GitHub adapter + multi-source merge (shipped)

**Goal:** prove the broker against a real external API and enable cross-source
topics. Closes the open question on rule conflict resolution.

Shipped:
- `github` adapter (`adapters/github.py`) using httpx + PAT auth (`env:GITHUB_TOKEN`).
  Query types:
  - `codeowners` → rules (one rule per CODEOWNERS pattern, severity configurable
    via `classify.rules.severity`)
  - `branch_protection` → rules (review count, code-owner reqs, status checks,
    linear history, force-push policy, admin enforcement). Default branch
    resolved automatically when omitted.
  - `recent_prs` → reasoning (PR number, title, author, state, draft flag,
    `updated_at` as `recency`)
  - `releases` → reasoning (tag, name, published_at, body)
  - Health endpoint reports `core` rate-limit remaining/reset.
- Multi-source topics: resolver fans out across all bindings concurrently via
  `asyncio.gather`. One failed adapter call surfaces as an error rather than
  emitting a partial envelope.
- Rule merge policy: duplicates by normalized text → **highest severity wins**;
  ties at the top severity → all tied rules kept (so both sources stay cited).
  Reasoning, skills, and commands are not deduped — they're additive.
- Tests: 21 new (`tests/adapters/test_github.py`, `tests/test_payload.py`, plus
  multi-source case in `tests/test_resolver.py`). Total: 55 passing.

## Phase 3 — Confluence adapter (shipped)

**Goal:** prove a second external adapter with classified HTML body parsing.

Shipped:
- `confluence` adapter (`adapters/confluence.py`) — Confluence Cloud REST v2,
  basic auth (email + API token). Query types:
  - `page` (by `id` or `title` + `space` key) → classified docs parsed from
    the page's `view` HTML body. Space key resolves to space-id on demand and
    is cached per adapter instance.
  - `space_pages` (list pages in a space) → reasoning (title + page id +
    `createdAt` as `recency`).
  - Health endpoint probes `/wiki/api/v2/spaces` for connectivity + auth.
- HTML body parsed via BeautifulSoup. H2 sections classify the same way as
  markdown (`rules`/`reasoning`/`skills`/`commands`). Inside skills/commands
  sections, H3 sub-headings delimit entries; for commands, the first `<pre>`
  or `<code>` block becomes the invocation.
- Classify vocabulary stays identical to markdown — same `heading` /
  `severity` selectors — so a topic can fan out across markdown +
  Confluence with the same `classify` block on each binding.
- Tests: 13 new (`tests/adapters/test_confluence.py`) via respx. Total: 68.

## Phase 4 — Notion adapter (shipped)

**Goal:** prove block-structured retrieval (Notion's API exposes pages as a
flat list of typed blocks, not HTML).

Shipped:
- `notion` adapter (`adapters/notion.py`) — Notion REST API v1, Bearer
  integration token, `Notion-Version: 2022-06-28`. Query types:
  - `page` (by `id` or `title` resolved via `/search` with case-insensitive
    exact-match) → classified docs parsed from the page's top-level blocks.
  - `database` (entries via `/databases/{id}/query`) → reasoning with title,
    page id, and `last_edited_time` as `recency`.
  - Health endpoint hits `/users/me` and surfaces the workspace name.
- Block-walking classifier: sections split by `heading_2`; skills/commands
  sections sub-split by `heading_3`. For commands, the first `code` block in
  each entry becomes the invocation. Rule items pulled from
  `bulleted_list_item` / `numbered_list_item`. `rich_text` arrays joined via
  their `plain_text` field.
- Pagination of `/blocks/{id}/children` (100 per page) via `start_cursor`.
- Same classify vocabulary as markdown / Confluence — one block portable
  across all three on a multi-source topic.
- Tests: 14 new (`tests/adapters/test_notion.py`) via respx. Total: 82.

## Phase 5 — Jira adapter (shipped)

**Goal:** prove ticket-shaped reasoning retrieval. Issues are facts about
in-flight work, not constraints — Phase 5 emits all output as reasoning.

Shipped:
- `jira` adapter (`adapters/jira.py`) — Jira Cloud REST v3, basic auth
  (email + API token, same shape as Confluence). Query types:
  - `issue` (by `key`) → 1 reasoning doc with a structured summary line
    (`KEY [type, status] assignee=Name: summary`) plus the issue description
    extracted from ADF.
  - `jql` (JQL search, `limit` default 25 / cap 100) → reasoning per matching
    issue; summary line only (no descriptions in list mode).
  - Health endpoint hits `/rest/api/3/myself` and surfaces accountId +
    displayName.
- Atlassian Document Format (ADF) walker: recursive plain-text extraction.
  Block-type boundaries (`paragraph`/`heading`/`list_item`/`codeBlock`/
  `blockquote`/`rule`/`bulletList`/`orderedList`) emit newlines. Marks,
  inline images, and hard breaks ignored.
- Source URIs link directly to `{base_url}/browse/{KEY}` for human
  verification.
- Tests: 15 new (`tests/adapters/test_jira.py`) via respx, including ADF
  walker unit tests. Total: 97.

## Phase 6 — Linear adapter (shipped)

**Goal:** prove a GraphQL-shaped adapter alongside the REST-shaped ones, and
ship the second ticketing surface.

Shipped:
- `linear` adapter (`adapters/linear.py`) — Linear GraphQL API, personal API
  key in raw `Authorization` header (no `Bearer` prefix — Linear quirk).
  Query types:
  - `issue` (by team identifier like `PORT-123` or UUID) → 1 reasoning doc
    with summary line plus the issue description (Linear stores descriptions
    as markdown — no walker needed).
  - `issues` (typed `IssueFilter` dict + `limit` capped at 100) → reasoning
    per matching node. `filter` passes through verbatim as the GraphQL
    `IssueFilter` variable.
  - Health endpoint hits `viewer { id name email }`.
- GraphQL error handling: top-level HTTP 401 → `AuthError`. Body-level
  `errors[]` with `extensions.code` containing `AUTHENTICATION` → `AuthError`;
  other GraphQL errors → `AdapterError` with all messages concatenated.
- Summary line shape:
  `{identifier} [{state}, priority {N}] assignee={name}: {title}`. Priority
  rendered as integer (Linear uses 0–4); missing priority renders as `-`.
- Source URI prefers issue.url from Linear; falls back to `linear://{id}`.
- Tests: 18 new (`tests/adapters/test_linear.py`) via respx. Total: 115.

## Phase 7 — Slack adapter (shipped)

**Goal:** ship the last adapter on the Phase 2+ roadmap. Slack is unique on
this list: it's the only adapter that emits *both* rules (from pinned
messages) and reasoning (from recent discussion), and the only one whose
backend uses HTTP 200 + `{ok: false}` for application errors.

Shipped:
- `slack` adapter (`adapters/slack.py`) — Slack Web API, Bearer token (bot
  or user OAuth, `xoxb-...` / `xoxp-...`). Query types:
  - `pinned` (`channel: <name|id>`) → rules. Each pinned message becomes one
    rule. Severity defaults from `classify.rules.severity` (default `must`);
    `MUST/SHOULD/MAY` prefix in the message text overrides per-item.
  - `recent` (`channel`, `limit` default 50 / cap 200, optional `since` ISO
    timestamp → Slack `oldest` epoch) → reasoning per message. Text is
    `@{user}: {message}`; recency is the Slack `ts` rendered as ISO.
  - Health endpoint hits `/auth.test` and surfaces team + user + URL.
- Channel resolution: accepts ID (regex-matched as `[CDG][A-Z0-9]{6,}`) or
  name (with or without leading `#`). Name → ID resolved via paginated
  `conversations.list` (200 per page, follows `response_metadata.next_cursor`),
  cached per adapter instance.
- Error handling: HTTP 401 → `AuthError`. Body-level `{ok: false}` with auth
  codes (`invalid_auth`, `not_authed`, `token_revoked`, `token_expired`,
  `no_permission`, `missing_scope`, `account_inactive`) → `AuthError`; others
  → `AdapterError`.
- Source URIs prefer Slack-provided `message.permalink`; fall back to
  `slack://{channel_id}/{ts}` so the agent can always cite an origin.
- Tests: 25 new (`tests/adapters/test_slack.py`) via respx — includes ts↔ISO
  unit tests, channel-name caching, paginated channel lookup, and severity
  prefix parsing. Total: 140.

## Phase 8 — shared classifier primitives (shipped)

**Goal:** collapse the H2-section / H3-subblock / severity-prefix classifier
logic that markdown, Confluence, and Notion had each reimplemented.

Shipped:
- `adapters/_classify.py` — new shared module exposing:
  - `Section` (heading + bullets + sub_blocks + body — all three views
    populated up front; classifier picks based on selector binding)
  - `SubBlock` (name + body + first code block as `invocation`)
  - `slugify`, `headings_of`, `severity_default` helpers (with consistent
    `<adapter> adapter: ...` error wording)
  - `classify_sections()` — single dispatch over selectors. Handles
    severity-prefix parsing, id format (`{slug}-{idx:03d}`), source URI
    format (`{base}#{heading_slug}` and `{base}#{heading_slug}/{sub_slug}`),
    and the no-classify fallback that emits the entire body as one
    reasoning doc (source URI = `source_base`, no fragment).
- Markdown / Confluence / Notion now each contain only a native-to-Section
  parser. Markdown: regex over text. Confluence: BS4 walk over HTML.
  Notion: walk over block list. After the parse, all three call
  `classify_sections()` with identical args.
- Behavior preserved exactly — 140 existing tests still pass without
  modification. Confluence's fallback source URI silently dropped the
  `#title-slug` suffix it used to emit (no test asserted on it).
- 19 new unit tests (`tests/adapters/test_classify.py`) lock the shared
  contract independently of any one adapter's parser. Total: 159.

Code volume cut: each of the three heading-based adapters lost ~80 lines of
duplicated extractor/walker logic, replaced by a single
`classify_sections(...)` call.

## Phase 9 — persistent sqlite cache (shipped)

**Goal:** survive process restarts without re-paying external-API
round-trip latency for every topic.

Shipped:
- `SqliteCache` (in `cache.py`) — same `get(key) -> Any | None` /
  `put(key, value, ttl_seconds)` interface as `TTLCache`. Values pickled
  (HIGHEST_PROTOCOL). Schema: `cache(key TEXT PRIMARY KEY, value BLOB,
  expires_at REAL)`. Uses wall-clock (`time.time()`) so entries written by a
  previous process stay valid after restart.
- Opportunistic eviction: expired rows are deleted on `get`. Corrupt /
  schema-mismatched pickle blobs are treated as a miss and dropped, so a
  stale DB doesn't poison a fresh process.
- Parent directory created on first write.
- `CacheConfig` in `config.py`: top-level `cache: { backend, path }` block.
  Defaults to `{ backend: "memory", path: None }` when omitted. `sqlite`
  requires `path`; loader raises on missing path or unknown backend.
- `Resolver(__init__)` falls back to `build_cache(config.cache)` when no
  cache is passed explicitly. Existing tests passing `cache=...` directly
  continue to work.
- 12 new tests: 7 on `SqliteCache` directly (roundtrip, miss, expiry,
  cross-instance persistence, overwrite, parent-dir creation, corrupt-entry
  handling), 4 on cache config loading (default, sqlite happy path, missing
  path, unknown backend), 1 resolver-integration test that proves a second
  `Resolver` reading the same DB sees `cache_hit=True` on the second
  fetch. Total: 171.

Closes open question on caching backend.

## Phase 11a — harness adapter (shipped)

**Goal:** read keystone-style harness directory trees natively so the same
content powers both keystone CLI scaffolding and MCP-served retrieval.

Shipped:
- `harness` adapter (`adapters/harness.py`). Walks a directory laid out as
  `<root>/{guides,corpus,actions,playbooks,sensors}/`. Skips `README.md` at
  any depth.
- Query types:
  - `guides` → rules. H2 section headings drive tiering:
    - `IRON LAW` / `IRON LAWS` → severity `must` (bullets or single prose
      paragraph both supported).
    - `RULES` → severity `must` (bullets).
    - `GOLDEN RULE(S)` → severity `should` (bullets).
    - `Anti-patterns` → reasoning (educational context).
    - Other H2 sections ignored.
    Bullet-level `MUST/SHOULD/MAY` prefix still overrides the tier default,
    matching the shared classifier vocabulary.
  - `corpus` → reasoning, one doc per file (full body).
  - `actions` → skills, one per file (name = filename stem).
  - `playbooks` → skills, same shape.
  - `sensors` → skills, same shape.
  - Health endpoint reports which subdirs are present.
- 17 new tests (`tests/adapters/test_harness.py`). Total: 188.

Plugins / `keystone patch` / `keystone verify` are intentionally dropped —
MCP supplies live cross-project context in their place.

## Phase 11b — harness scaffold MCP tools (shipped)

**Goal:** absorb keystone CLI's write surface (`init`, `new <port>`,
`target add`, `doctor`) into MCP tools so the agent can drive scaffolding.

Shipped:
- `src/keystone_mcp/harness_scaffold.py` — pure-Python `Scaffold` class
  with templates as inline strings. Refuse-to-overwrite by default;
  `force=True` opt-in. Every write returns `{created: [...], skipped: [...]}`.
- 9 new MCP tools wired into the server:
  - `harness_bootstrap(root)` — skeleton dirs (`guides/`, `corpus/`,
    `corpus/state/`, `actions/`, `playbooks/`, `sensors/`, `adapters/`,
    `learning/inbox/`, `archive/`). Idempotent.
  - `harness_new_guide(name, tier)` — tier ∈ iron-law | rules | golden.
  - `harness_new_sensor(name, kind)` — kind ∈ lint | type | test | build |
    drift | coverage | computational | domain | custom. Stamps frontmatter
    that the harness adapter reads at retrieval time.
  - `harness_new_action(name)` — single unit of lifecycle work.
  - `harness_new_playbook(name, actions[])` — ordered chain. References
    each action via a relative markdown link.
  - `harness_new_adapter(agent)` — adapter dir + README under
    `<root>/adapters/<agent>/`.
  - `harness_target_add(agent, project_root)` — agent menu file
    (CLAUDE.md, AGENTS.md, `.cursor/rules/000-harness.mdc`, etc.) at the
    project root. Menu is a thin pointer to the harness + MCP tools, not
    content — single source of truth stays in the harness.
  - `harness_status(root)` — per-subdir file counts.
  - `harness_options_catalog()` — discovery: valid tiers, sensor kinds,
    supported agents, menu file paths per agent.
- Name validation rejects path-traversal / empty / punctuated names.
- 29 new tests (`tests/test_harness_scaffold.py`). 217 total.

Keystone CLI commands replaced by MCP tools / resources:

| Keystone CLI | MCP surface |
|---|---|
| `keystone init` | `harness_bootstrap` + `harness_target_add` (tools) |
| `keystone new guide` | `harness_new_guide` (tool) |
| `keystone new sensor` | `harness_new_sensor` (tool) |
| `keystone new action` | `harness_new_action` (tool) |
| `keystone new playbook` | `harness_new_playbook` (tool) |
| `keystone new adapter` | `harness_new_adapter` (tool) |
| `keystone target add` | `harness_target_add` (tool) |
| `keystone doctor` (minus plugin checks) | `harness://status` (resource, after Phase 12) |
| `keystone options` | `harness://options` (resource, after Phase 12) |
| `keystone install` / `plugin *` / `patch` / `verify` | **dropped** — MCP serves live context in place of vendored plugins |

## Phase 12 — FastMCP-conformance reshape (shipped)

**Goal:** align the MCP surface with FastMCP's three primitives — tools,
resources, prompts. Read-only ops move to resources; writes and
parameterized reads stay as tools.

Shipped:
- Dropped 7 read-only tools: `get_rules`, `get_reasoning`, `get_skills`,
  `get_commands`, `source_health`, `harness_status`,
  `harness_options_catalog`.
- Added 3 resource templates + 3 static resources:
  - `context://list` (static) — topic directory
  - `context://{topic}` (template) — full envelope. The agent reads the
    envelope and extracts the kind it needs; no narrow URL slices needed
    when the resource is fetched directly via MCP.
  - `source://{name}/health` (template) — adapter reachability + auth state
  - `harness://status` (static, default root=harness) — layout audit
  - `harness://{root}/status` (template) — layout audit at a custom root
  - `harness://options` (static) — valid scaffold tool arguments
- All resources annotated `readOnlyHint: true, idempotentHint: true`.
- Kept as tools (parameterized read or write):
  - `get_context(topic)` — canonical entry, parameterized
  - `list_topics(tag?)` — optional filter
  - All `harness_bootstrap` / `harness_new_*` / `harness_target_add` — writes
- INSTRUCTIONS block updated to document the new surface.
- 217 tests still pass (no test churn — server surface had no direct test
  coverage; integration smoke confirms 9 tools + 3 static resources + 3
  resource templates register correctly).

**Deferred to follow-up:** FastMCP's `SkillsDirectoryProvider` exposes
`<dir>/<name>/SKILL.md` directories as `skill://` resources, discoverable
by clients that understand the skill primitive (Claude Code, Cursor, etc.).
Our scaffold writes `actions/<name>.md` / `playbooks/<name>.md`, not the
required directory-per-skill layout. Mounting the provider would either
require changing the scaffold layout or adding a separate
`<harness>/skills/` dir alongside actions/playbooks. Decide direction
before Phase 13.

## Phase 13 — fixed `.keystone/harness` root + secret guard (shipped)

**Goal:** consolidate everything under `.keystone/`, version-controlled
and team-shared. Drop the top-level `harness/` convention; harness lives at
`.keystone/harness/` with a *fixed*, non-overridable path. Add a defensive
guard against scaffolding files with secret-looking names.

Shipped:
- `HARNESS_ROOT = ".keystone/harness"` constant in `server.py`. Every
  harness MCP tool hardcodes this path — `root` arg removed from
  `harness_bootstrap`, `harness_new_*`, `harness_target_add`,
  `harness_status`.
- `_build_harness` in `resolver.py` ignores any `root` declared in the
  config and always builds an adapter against `.keystone/harness`.
  Keeps the team-shared layout canonical.
- `harness://{root}/status` resource template removed; only `harness://status`
  remains (single fixed root → single static resource).
- Secret-name guard in `harness_scaffold.py`: `_check_no_secret_name`
  rejects scaffold attempts whose name contains any of `secret`,
  `secrets`, `token`, `credential`, `credentials`, `password`,
  `passwd`, `apikey`, `api-key`, `api_key`, `private`, `.env`,
  `envfile`. Error message points users at `env:VAR` indirection.
- Agent menu template rewritten to reflect the Phase 12 MCP surface
  (`get_context`, `context://{topic}` resources, no more `get_rules/...`
  references) and to call out the no-secrets rule explicitly.
- `.keystone/context.yaml` example: documented (commented) `hb: type:
  harness` source and a `harness` topic that fans out across
  guides/corpus/actions/playbooks/sensors.
- 18 new tests covering the secret-name guard + updated menu template.
  Total: 235.

Surface count: 9 tools, 3 static resources, 2 resource templates.

## Phase 14a — adopt FastMCP skills primitive (shipped)

**Goal:** collapse `actions/` and `playbooks/` into `skills/<name>/SKILL.md`
directories. Mount FastMCP's `SkillsDirectoryProvider` at
`.keystone/harness/skills/` so each skill becomes a `skill://` resource
discoverable by agent runtimes (Claude Code, Cursor, etc.).

Shipped:
- `BOOTSTRAP_DIRS` updated: dropped `actions`, `playbooks`. Added `skills`.
- `Scaffold.new_skill(name, description=?)` creates
  `<root>/skills/<name>/SKILL.md` (directory-per-skill, FastMCP convention).
  YAML frontmatter declares `description:` so agents can surface a one-line
  summary without parsing body text.
- `harness_new_skill` MCP tool replaces `harness_new_action` +
  `harness_new_playbook`.
- Harness adapter drops `actions` and `playbooks` query types; their
  emission used to be `skill` envelope kind, but project-local skills now
  go through the FastMCP primitive instead. Error message points users at
  `skill://` resources for the new path.
- `server.py` mounts `SkillsDirectoryProvider(roots=.keystone/harness/skills)`.
  Each `<name>/SKILL.md` is auto-exposed as `skill://<name>/SKILL.md`
  + a `skill://<name>/_manifest` listing supporting files.
- `Scaffold.status()` counts skills by subdirectory containing a `SKILL.md`,
  matching how the provider discovers them.
- 235 tests pass (drops for action/playbook tests; new tests for
  `new_skill` + status counting).

**Disambiguation chosen (Option A):** two surfaces share the word "skill":
- **File skills** (FastMCP primitive) — project-local
  `<harness>/skills/<name>/SKILL.md` directories, surfaced as `skill://`
  resources. Agent runtimes auto-load.
- **Inline skills** (envelope `skill` kind) — comes from external adapters
  (Confluence "Procedures" sections, Notion `heading_3` blocks). Different
  population path, same conceptual category. Continues to surface through
  `context://{topic}` envelopes.

## Phase 14b — lifecycle prompts (shipped)

**Goal:** absorb keystone's lifecycle action/playbook content into FastMCP
prompts. Each prompt seeds a multi-step agent conversation. Walking the
phases drives the agent to call scaffold tools (`harness_new_*`) and read
state resources (`harness://status`, `context://...`) along the way.

Shipped:
- New module `src/keystone_mcp/prompts.py` with four `render_*` functions.
- Four `@mcp.prompt` decorators in `server.py`:
  - `bootstrap()` — one-time codebase analysis. Walks the agent through
    scaffold → read existing state → codebase scan → state ledger fills
    (`CODEBASE_STATE.md`, `code-debt.md`, `risk-fingerprints.md`,
    `quality-radar.md`, `traffic-topology.md`) → iron-law guides → skills.
  - `task(description)` — end-to-end unit of work. Phase order: spec →
    orient → load rules → implement → check-drift → verify → review (+
    optional learn). Iron-law list, pacing-mode handling.
  - `audit()` — dual-flywheel: learning (walk `learning/inbox/`, surface
    new rule candidates from commits) + pruning (stale rules, dead idioms,
    placeholders, failing sensors, empty shells, drifted state). Refresh
    risk fingerprint + traffic topology in `corpus/state/`.
  - `learn(finding)` — capture a finding into
    `.keystone/harness/learning/inbox/<slug>.md` with proposed
    classification (iron-law / rule / golden / skill / reasoning / defer).
    No on-the-spot promotion — audit batches decisions.
- Each prompt references MCP tools/resources by name so the agent knows
  what to call. They do NOT inline guide/skill content — that lives in the
  harness and is retrieved on demand at execution time.
- Iron-law lines explicitly enumerated in every prompt:
  - bootstrap → no silent overwrites, no invented facts, no secrets.
  - task → no proceeding without acceptance criteria, no completion claims
    without fresh verification, no commits with failing sensors, no AI
    attribution, no silent overwrites.
  - audit → propose every state-file diff before applying.
  - learn → no invented evidence, no secrets in inbox.
- 13 new tests (`tests/test_prompts.py`). Total: 248.

Surface count: 8 tools, 3 static resources, 2 resource templates, 4
prompts, plus N skill:// resources auto-discovered from
`.keystone/harness/skills/`.

Phases 14c (shipped scripts) and 14d (proactive rule injection) to follow.

## Phase 14c — sensors as commands + shipped scripts + cascade rename (shipped)

**Goal:** make sensors first-class blocking rules. Each sensor markdown is
WHAT to check; the matching shell script under `scripts/` is HOW to check.
Agent runs the script during the verify phase; any non-zero exit halts the
workflow. Also folds in a cascade rename driven by the user.

Two-axis model (Phase 14c scope = computational sensors):

|         | Computational            | Inferential                    |
|---------|--------------------------|--------------------------------|
| Guide   | tool-enforced config     | markdown the agent reads       |
|         | (lives next to harness)  | (rule kind, cascade tier)      |
| Sensor  | shell script, exit=pass  | agent prompt, judges pass      |
|         | (shipped in 14c)         | (deferred to 14e)              |

Strictness cascade (third axis): **non-negotiable > strong > rules**.

Shipped:
- `scripts/` added to `BOOTSTRAP_DIRS`.
- `render_script(name)` template — `#!/usr/bin/env bash`, `set -euo
  pipefail`, exit 1 stub.
- `Scaffold.new_script(name, body=?)` writes
  `<root>/scripts/<name>.sh` (chmod +x). Idempotent; `force=True`
  replaces.
- `Scaffold.new_sensor(name, kind)` now writes BOTH the sensor markdown
  AND the matching `scripts/<name>.sh` stub. Forcing a sensor refresh
  never clobbers an existing script (user's edits are preserved).
- Sensor template gains an explicit
  `**Run** — .keystone/harness/scripts/<name>.sh` bullet. Frontmatter is
  metadata-only (`kind:` category); no `script:` field — mode and
  invocation are inferred from convention.
- Harness adapter:
  - `_strip_frontmatter` skips the leading `---`/`---` block (no parsing
    needed; convention drives behavior).
  - Sensors now emit `command` kind (NOT `skill`). Invocation derived by
    convention: if `<root>/scripts/<sensor-stem>.sh` exists, invocation =
    that path; otherwise empty (descriptive-only sensor).
- `harness_new_script` MCP tool exposed for ad-hoc scripts.
- `task` prompt — verify phase rewritten to enforce **halt on any
  non-zero sensor exit**, with explicit instructions to invoke each
  sensor's `invocation` field via Bash.

Cascade rename (driven by user clarification during 14c):
- Tier names: `iron-law` → `non-negotiable`, `golden` → `strong`,
  `rules` unchanged.
- Severity mapping fix: previously RULES tier mapped to `must` (broke
  the cascade). Now: non-negotiable → `must`, strong → `should`,
  rules → `may`. Bullet-level MUST/SHOULD/MAY prefix still overrides.
- Old keystone headings (`IRON LAW`, `GOLDEN RULES`) still recognized
  by the adapter for backward compat. Tier arguments to
  `harness_new_guide` use the new names only.
- Guide templates updated: `## NON-NEGOTIABLE`, `## STRONG`, `## RULES`.
- `options_catalog()` reflects the new tier names.

23 new/changed tests. 258 total. Surface: 9 tools (added
`harness_new_script`), 3 static resources, 2 resource templates,
4 prompts, plus N skill:// auto-discovered.

Phase 14d (proactive rule injection) and 14e (inferential sensors)
to follow.

## Phase 14d — proactive rule injection (shipped)

**Goal:** stitch non-negotiable + strong rules into the agent's menu file at
project root so they auto-load at session start. Regular rules and reasoning
keep loading on demand via MCP. Closes open Q6.

Rationale (strictness cascade, from Phase 14c):
- **non-negotiable** rules can never be violated → must be present at
  session start, no MCP round-trip permitted.
- **strong** rules are preferred-path; deviation requires explicit
  reasoning → also present at session start so the agent acknowledges
  them before considering deviation.
- **rules** (regular) → load on demand. Avoids bloating the menu and the
  agent's context window.

Shipped:
- `extract_tier_sections(harness_root)` walks
  `<harness_root>/guides/**/*.md`, picks H2 sections matching the
  non-negotiable / strong heading sets (new names + legacy keystone
  names), returns `{tier: [(rel_path, body), ...]}`.
- `_format_inlined_rules(sections)` renders extracted sections into a
  markdown block with explicit source citations
  (`### From \`guides/<path>\``).
- `render_agent_menu(harness_root, sections=?)` appends the inlined rules
  to the base pointer template. With `sections=None` (no rules to inline)
  the menu degrades to the pointer-only shape.
- Menu template documents the strictness cascade up front and tells the
  agent to re-run `harness_target_add(agent, force=True)` after editing
  guides to refresh the inlined rules.
- `Scaffold.target_add` now extracts sections from its own harness root
  and passes them through. Existing tool signature unchanged.
- 12 new tests covering: extraction (empty, nested guides, legacy
  headings, README skip), menu inlining (with sections, without sections,
  cascade documentation), and target_add round-trip (rule edits propagate
  to the menu via `force=True`).

258 → 266 tests.

Phase 14e — inferential sensors — completes the harness side; see below.

## Phase 14e — inferential sensors (shipped)

**Goal:** support the second sensor mode from the two-axis model
(computational × inferential, established Phase 14c). An inferential
sensor is a check the agent performs by reasoning — code review,
security review, risk review — rather than by shelling out. Same
gating semantics: failure halts the workflow.

Convention-by-name (mirrors the script path from 14c):

  * `<root>/scripts/<name>.sh`  exists → computational; agent runs Bash.
  * `<root>/prompts/<name>.md`  exists → inferential; agent reads the
                                         prompt and performs the
                                         reasoning task.
  * neither                     → descriptive only; empty invocation.

If both somehow exist, the script wins — computational checks are
cheaper and more deterministic. The harness adapter resolves at fetch
time and emits `command` kind with the appropriate file path. Agent
distinguishes by extension: `.sh` → Bash; `.md` → Read + reason.

Shipped:
- `prompts/` added to `BOOTSTRAP_DIRS`.
- `SENSOR_MODES = ("computational", "inferential")` declared.
- `render_prompt(name)` template — PASS/FAIL contract, scope / checks /
  pass criteria / fail examples sections.
- `Scaffold.new_prompt(name, body=?)` writes
  `<root>/prompts/<name>.md` idempotently.
- `Scaffold.new_sensor(name, kind=, mode=)`:
  - `mode="computational"` (default, unchanged) → stamps script stub.
  - `mode="inferential"` → stamps prompt stub instead. NO matching
    script created (would defeat the mode signal).
- `render_sensor(name, kind, mode=)` template branches the "Run" bullet
  + the rest of the bullet list to match the mode.
- Harness adapter `_read_sensor_file` probes both `scripts/<name>.sh`
  and `prompts/<name>.md`; the script wins when both exist.
- `harness_new_prompt` MCP tool exposed.
- `harness_new_sensor` MCP tool gains a `mode` parameter.
- `task` prompt verify phase rewritten again — agent picks behavior
  from the invocation extension: `.sh` → Bash; `.md` → Read + reason;
  empty → descriptive-only, skip with a note. Halt on any non-zero
  exit OR any FAIL verdict.
- `Scaffold.status()` includes per-subdir count for `prompts/`.

10 new tests covering inferential rendering, the `mode` switch in
`new_sensor`, `new_prompt`, adapter resolution (script vs prompt
preference), and PASS/FAIL contract.

266 → 276 tests. Surface: **10 tools** (added `harness_new_prompt`),
3 static resources, 2 resource templates, 4 prompts.

Two-axis model now fully implemented:
  - (guide, inferential) → rule kind in envelope (Phase 1–14d)
  - (sensor, computational) → command kind, .sh invocation (Phase 14c)
  - (sensor, inferential) → command kind, .md invocation (Phase 14e)
  - (guide, computational) → out of harness scope (LSP configs in repo)

## Phase 15 — packaging + PyPI release (shipped)

**Goal:** publishable wheel + `uvx keystone-mcp` install path.

Shipped:
- `pyproject.toml`:
  - `[project.scripts] keystone-mcp = "keystone_mcp.server:main"` — wires
    the `keystone-mcp` console entry point.
  - Author, MIT license, keywords, classifiers, project URLs.
  - `build` added as a dev dep for sdist/wheel construction.
- `LICENSE` (MIT, attributed to Ian Johnson).
- `python -m build` produces both wheel and sdist cleanly.
- Wheel smoke-tested: `uv run --with ./dist/...whl python -c "..."`
  imports `keystone_mcp` and resolves `keystone_mcp.server:main` as the
  entry point.
- Published to PyPI at https://pypi.org/project/keystone-mcp/0.1.0/.

Install path:
```
uvx keystone-mcp           # one-shot run
pipx install keystone-mcp  # install + add to PATH
```

`.mcp.json` for a consumer no longer needs `--directory`:
```json
{
  "mcpServers": {
    "keystone": {
      "command": "uvx",
      "args": ["keystone-mcp"],
      "env": { "KEYSTONE_CONFIG": "/path/to/.keystone/context.yaml" }
    }
  }
}
```

## Phase 12+ — remaining open work

- **Packaging.** Publish to PyPI and wire `uvx keystone-mcp` as the
  documented install path so consumers don't need to clone.
- **Real-world smoke test.** Run against live Jira creds (and any others on
  hand) to catch real-API drift from the respx mocks.
- **Action / playbook revisit.** Open question: collapse `actions` and
  `playbooks` into the existing `skills` payload kind entirely, or keep
  the distinction. Decide before adding more action/playbook surface.
- **Secret-store auth** (open Q2). `env:NAME` works but forces secrets into
  shell rc files. Macos Keychain / 1Password CLI integration via a
  `secret:NAME` scheme that calls out at config-load time.
- **`agents` payload kind.** Same shape as rules/reasoning/skills/commands.
  Deferred from Phase 8 question — revisit when a concrete need appears.
- **Classifier strength DSL** (open Q4). Defer until a real
  misclassification incident surfaces; then design from the failure shape.
- **Multi-tenant server** (open Q5). Defer; no concrete demand yet.

---

## Open design questions

Explicit deferrals. Each closes before the relevant phase ships.

1. ~~**Rule conflict resolution.**~~ **Closed in Phase 2.** Duplicates
   (identical normalized text) collapse with highest-severity winning; ties at
   the top severity keep both sources. True semantic contradictions can't be
   detected mechanically and surface as separate rules for the agent to flag.
2. **Auth strategy.** Per-source env vars are simplest. Worth integrating with
   macOS Keychain / 1Password CLI later? Decide before Phase 2.
3. ~~**Caching backend.**~~ **Closed in Phase 9.** Sqlite backend ships
   alongside the in-memory default. Top-level `cache: { backend, path }`
   block in config; pickle-serialized values; wall-clock TTL so entries
   written by a prior process stay valid after restart.
4. **Classifier strength.** Heading/tag selectors are crude. Do we need a richer
   DSL (XPath, frontmatter, structured annotations)? Wait for real misclassification
   pain before adding complexity.
5. **One server per repo, or one server multi-tenant.** Phase 1 assumes one
   process per consuming repo. Multi-tenant adds real complexity; revisit only
   with concrete demand.
6. ~~**Proactive rule injection.**~~ **Closed in Phase 14d.** Menu file
   at project root (CLAUDE.md / AGENTS.md / .cursor/rules/...) inlines
   non-negotiable + strong rules verbatim at write time. Regular rules
   and reasoning continue to load on demand via MCP. Re-run
   `harness_target_add(agent, force=True)` after editing guides to
   refresh the inlined rules.
7. **Write operations.** Should any adapter ever write (comment on a ticket,
   update a page)? Default: no, keep read-only. Re-open only with a clear case.

---

## Project layout

```
keystone-mcp/
├── pyproject.toml
├── PLAN.md
├── README.md
├── .keystone/
│   ├── context.yaml             # repo-owned topic map
│   └── context/                 # markdown source files
├── src/
│   └── keystone_mcp/
│       ├── __init__.py
│       ├── server.py            # FastMCP entrypoint
│       ├── config.py            # YAML loader + topic registry
│       ├── resolver.py          # multi-source dispatch + rule merge
│       ├── payload.py           # Rule/Reasoning/Skill/Command + envelope + merge_rules
│       ├── cache.py             # in-memory TTL cache + sqlite backend
│       ├── errors.py            # typed boundary errors
│       ├── harness_scaffold.py  # write-side harness templates + Scaffold (Phase 11b)
│       └── adapters/
│           ├── __init__.py
│           ├── base.py          # Adapter protocol
│           ├── _classify.py     # shared section / sub-block classifier (Phase 8)
│           ├── markdown.py      # Phase 1
│           ├── github.py        # Phase 2
│           ├── confluence.py    # Phase 3
│           ├── notion.py        # Phase 4
│           ├── jira.py          # Phase 5
│           ├── linear.py        # Phase 6
│           ├── slack.py         # Phase 7
│           └── harness.py       # Phase 11a
└── tests/
    ├── test_config.py
    ├── test_resolver.py
    ├── test_payload.py
    ├── test_cache.py
    ├── test_harness_scaffold.py
    └── adapters/
        ├── test_classify.py
        ├── test_markdown.py
        ├── test_github.py
        ├── test_confluence.py
        ├── test_notion.py
        ├── test_jira.py
        ├── test_linear.py
        ├── test_slack.py
        └── test_harness.py
```
