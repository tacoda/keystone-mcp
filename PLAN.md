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

Keystone CLI commands replaced by MCP tools:

| Keystone CLI | MCP tool |
|---|---|
| `keystone init` | `harness_bootstrap` + `harness_target_add` |
| `keystone new guide` | `harness_new_guide` |
| `keystone new sensor` | `harness_new_sensor` |
| `keystone new action` | `harness_new_action` |
| `keystone new playbook` | `harness_new_playbook` |
| `keystone new adapter` | `harness_new_adapter` |
| `keystone target add` | `harness_target_add` |
| `keystone doctor` (minus plugin checks) | `harness_status` |
| `keystone options` | `harness_options_catalog` |
| `keystone install` / `plugin *` / `patch` / `verify` | **dropped** — MCP serves live context in place of vendored plugins |

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
- **Proactive rule injection** (open Q6). The host could stitch
  `must`-severity rules from a configured "session-prelude" topic into the
  system prompt at session start, so the agent has them before the first
  tool call.
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
6. **Proactive rule injection.** Should the host stitch `must`-severity rules
   into the system prompt at session start, or always rely on the agent calling
   `get_rules`? Phase 1: tool-call only. Re-open after real-world use.
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
