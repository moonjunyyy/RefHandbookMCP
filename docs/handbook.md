# refhandbook

A quick reference handbook (QRH) for coding agents, served over MCP. It runs as part of the site
(docs/site.md): Claude connects to `https://<domain>/mcp` as a custom connector, the user signs in
with the site's sign-in and allows the client, and every chat, Cowork and Claude Code session then
reaches that user's own store.

A QRH is the book a flight crew reaches for when something goes wrong: short cards, found by
symptom, each saying how to confirm it applies and what to do, in order. This project keeps that
card discipline and replaces the parts a printed book fixes at press time (tabs, index,
cross-references) with a relational store that changes at runtime.

The same store also carries the **research cards** (`rs-*`) and the **research ledger**: the run
state of a research conversation (directives, premises, claims and their verdicts per
assumption configuration, plan objects, documents). The research cards drive a session loop over
them (one session per message, or per delegated agent run), so each continues from stored state
instead of from the model's memory, and several can work on one ledger side by side.

Status: prototype.

## Try it

The CLI works on one handbook database (`--db`, or `$REFHANDBOOK_DB`, or `~/.refhandbook/handbook.db`),
the same kind of file each user of the server has (`<data>/users/<uid>.db`):

```bash
uv sync
uv run refhandbook seed                        # five example cards
uv run refhandbook lookup "CONFLICT (content): could not apply"
uv run refhandbook show rebase-conflict
uv run refhandbook show rs-n1                  # a research card (loaded automatically)
uv run refhandbook research list               # the research tools, callable with JSON arguments
uv run pytest tests/refhandbook
```

`refhandbook export` and `refhandbook import` move a handbook through JSON, so it can be reviewed and
versioned in git.

## Design

### The card

Card fields come from the UK CAA's guidance on emergency and abnormal checklists, CAP 676.
Paragraph numbers refer to its Chapter 7.

| Card part | Why it is there |
| :- | :- |
| Title | Must fully reflect the failure condition and be unambiguous (2.3) |
| Condition, cues | Repeating the alert and failure state confirms the right card was picked (2.4) |
| Objective | States the expected outcome and is a second confirmation (2.5) |
| Memory items | Done first; kept to six, preferably four or fewer (2.6) |
| Cautions, notes | Placed before the action they concern (2.7, 2.9) |
| Numbered steps | Numbering mitigates skipped steps and losing one's place (1.11) |
| Conditional steps | Set apart from plain actions, because embedded conditionals are error prone (2.10) |
| Deferred items | Grouped at the end, labelled, each with the moment it applies (2.12) |
| End marker | Present at every point the card can finish, including inside branches (3.2) |

**One card, one topic.** A card is a procedure (one situation, one outcome, one sequence of at most
ten steps, branching only to other cards), a set (one list or one table), or an index of its parts.
`store.decomposition()` names the parts a card holds beyond that; the model's writes (`save_entry`,
`cap kind=card`) are refused with those parts, `open_entry` marks such a card SPLIT BEFORE USE
(card `rs-split` says how), and `audit` reports it. The research cards are held to the same rule.

CAP 676's table of checklist errors puts "complete the wrong checklist" beside "provide index,
objective, description of the failure conditions". That is why `lookup` returns the condition
and objective of each candidate and no steps: the reader confirms first, then opens.

### What is dynamic

| Paper QRH | Here |
| :- | :- |
| Tabs and section dividers | `tags` rows; `index` groups by tag, kind, or title on request |
| Alphabetical and alert indexes | `triggers` rows in a full-text index, ranked above title and body |
| "Go to page 4.12" | `items.goto`, a foreign-key-like reference that `audit` checks and the card resolves to a title |
| Fixed "see also" | `relations(src, type, dst)` with types that are themselves rows |
| Reissue of the whole book | Per-entry `revision`; a `supersedes` relation retires a card without deleting it |

Relation types are data. Each has a name and an inverse (`escalates_to` / `escalated_from`), so
an edge is stored once and read correctly from either end. A type whose inverse is its own name
is symmetric. New types are added at runtime with `define_relation_type`.

A step's `goto` and an explicit relation are the same thing to a reader, so the `edges` view
unions them. The card's RELATED block and `traverse` see both.

CAP 676 warns that cross-references are error prone and should be minimised on paper (3.5). The
risk it names is not knowing which step or page is meant and losing one's place. Resolved links
remove the first; the server's instructions tell the agent to reopen and resume for the second.

```
entries ──< items      position, phase (memory|action|deferred), kind (step|caution|note),
        │              text, response, when, goto, ends
        ──< triggers
        ──< tags
relation_types(name, inverse, description)
relations(src, type, dst, note)
edges = relations ∪ items.goto        (view)
search                                (FTS5: title, triggers, condition, body)
```

### Revisions and merging

A card is rewritten whole, so a save made from an older reading would undo what another conversation saved
in between, unseen. A save through the tool therefore works as a push does in version control. It names its
base, the revision its writer read (`open_entry` shows `rev N`); an update without one is refused. On the
current revision it goes in as it is. On an older one it is merged three ways (what was read, what is sent,
what is saved now): one-line fields as a whole, the body line by line, the items item by item, cues and
tags as sets. What does not overlap is merged and saved, and the result says what was merged. Where both
sides changed the same place nothing is written: the save comes back as `CONFLICT` with every field it
sent as it stands on the current revision, the overlapping places between `<<<<<<< yours`, `||||||| rev N`,
`=======` and `>>>>>>> rev M`. Resolving is settling those places and saving again with the current
revision as base; a text that still carries marks is refused.

Each replaced revision is kept (`entry_revisions`, written when the next save replaces it), which is what a
merge starts from; `open_entry(id, rev=N)` reads one. A base older than the first kept revision has nothing
to merge from, and every field that differs is a conflict. The store's own writers (the research cards, a
card capability record, an import) save without a base and replace what is stored, as before.

### MCP tools

| Tool | Purpose |
| :- | :- |
| `lookup` | Symptom to candidate cards, with condition and objective |
| `open_entry` | The card, plus related entries, and the entries that route to it with their ledgers (`ENTRY`: where the work the card describes is entered); `rev=N` shows a kept earlier revision |
| `index` | Contents list grouped by tag, kind, or letter |
| `query` | One read-only SELECT (SQLite syntax) over the graph laid out as tables: `rows` (ledger rows by id, status and node id), `nodes`, `links`, `verdicts`, `cards`. For a question about many nodes at once; it changes nothing and reads no other table of the store |
| `traverse` | Walk relations outward from a card |
| `save_entry` | Create or update a card; an update names the revision it was written against (`base`) and is merged with what was saved since, or refused as a conflict ("Revisions and merging") |
| `delete_entry` | Remove a card and its relations |
| `relate`, `unrelate` | Typed edges between cards |
| `delete_node` | Delete an entry node or a tag of the entry graph (docs/entry-graph.md): refused while it still has links, unless forced; only the caller's own nodes |
| `define_relation_type`, `relation_types` | The relation vocabulary |
| `audit` | CAP 676 assessment checks over the whole handbook |
| `memo` | The model's quick notes, kept the way a cache is: a key, overwritten without asking, expiring, and stale once a node it was read from has changed. Never a basis: what the user said is a ledger row, a procedure a card |
| `research_*` | The research ledger: sessions, rows, plan objects, configurations and verdicts, documents (16 tools; card `rs-ref-ledger`) |
| `cap` | Capability records of every kind (script, policy, layer, alias, rule, card): versioned, owned, reviewed on a TTL, deprecated and retired; a widening grant waits for the user (docs/kernel.md "Capabilities") |
| `run`, `job`, `files` | Run a script in the user's sandbox as a background job, read jobs, and keep files in the workspace. No network of its own: a policy's egress profiles (pypi, npm, crates, github, …) reach out through the egress supervisor, HTTPS only, to those hosts only; the server's layers bring Python, Node and Rust (`refhandbook layers build`) |

A tool that changes something outside a ledger (`save_entry`, `relate`, `run`, a `files` write, a
`cap` change, an entry ref …) ends its result with one line, `LOOP  …`: the sessions the store has
open, most recently used first, or that none is open, and how many changing calls were made since a
chat session was last used. Inside the loop that count starts again with every research call;
outside it only grows, whatever sessions other conversations left open. It stands in for the stop
hook the cards name (a message answered without a session): card `rs-x7`, missed messages. The session loop's state lives in the store,
and this is where a caller that skipped `research_begin` (or lost it with its context) meets it: at
the call that does the work. The line states what the store knows and nothing else; reads and the
research tools do not carry it (`server.CHANGES` names the changing calls of the mixed tools).

Read tools are annotated `readOnlyHint`, and deletes `destructiveHint`, so a client can ask for
confirmation on the right ones. Tools return the rendered card as text, since the reader is a
model. Failures a caller can fix come back as tool errors (`isError`), not protocol errors.

The entity/relation shape follows the MCP reference memory server (directed, active-voice
relations between named nodes). It differs in that a node is a structured card, relation types
are declared with inverses, and search ranks alerting cues above free text.

### Research cards and ledger

**Cards.** `src/refhandbook/research_pages/*.md` is the single source of the research cards. Each
page has a fixed shape:
- header lines: `KIND`, `TAGS`, `TRIGGERS`, `OBJECTIVE`;
- `ENTRY`, the start condition;
- `◆`, a memory item;
- numbered steps;
- `###` notes;
- `**EXITS**`, one line per end condition, each naming the objects it returns.

`research.parse_page` turns a page into a card. The server loads every page at startup, and again
whenever the pages change. The mapping from page to card is:
- memory items become unnumbered, so a page's "step N" is the card's step N;
- every exit ends the card;
- every card an exit returns objects for gets a `pushes_to` relation.

Cards with the `rs-` prefix are managed this way: an edited copy in the store is replaced. Change
the page instead.

**Ledger.** The `rl_*` tables keep one ledger per research question:
- rows in sections U C R S A Z T E H X P K;
- named assumption configurations;
- verdicts per claim × configuration;
- registered documents;
- pending propagation hits;
- a change log.

| Mechanism | What it enforces |
| :- | :- |
| Session protocol: `research_begin` → its token on every call → `research_end` | Sessions (kernel `k_sessions`) run side by side: a write is refused with CONFLICT only when it changes an object another session changed concurrently (still open, or after this one opened) and this one has not read since (`k_writes` / `k_seen`, per object); what a view shows counts as read, nothing else. `research_end` refuses while what the session opened remains (a pending hit it raised, a K it runs, a plan it committed and has not synced) or a check error; a `chat` session also answers for the user's directives and the continuation, an `agent` session does not. A session is resumed only by its token, or by its `label` (the client's conversation id, which the prompt hook passes), never by another participant. |
| Plan objects (K) | Every card exit returns objects. `research_done` refuses an exit that pushed nothing. One K waits for the user across sessions: a push to page USER re-arms it, so a one-word message adds no K. |
| Volume | `research_begin` shows the rows changed in the last 3 sessions and every live row (`view=recent`; `brief` and `full` too), and `research_end` prints only the rows the session changed. `research_show(ids=…)` reads the rest. |
| Configurations | `main` is the set of premises that are on, and only the user switches it. Named configurations switch premises on or off, swap alternatives, or add model premises, and the boundary report shows which single change flips a verdict. Model origin taints: nothing on the main line may rest on it. |
| Propagation | Changing a row opens hits on everything that rests on it, verdict cells included. Switching a premise off reaches only the main line. Superseding or refuting a premise also reaches the exploration cells that contain it. |
| Judge | The kernel's rules (`docs/kernel.md`) decide every check, obligation and end refusal; they are data, versioned with the package, and a user's change to one survives upgrades. |
| Review | Every 7 sessions, or sooner when refusals, UNAFFECTED disposals, carries and drops gather, `research_begin` lists REVIEW (card `rs-rv`). `research_review` records it; rule changes are rule records (`cap kind=rule`), which run as warnings until the user approves them on the server. |
| Documents | Each document has a role. `source` is the user's original: read-only and hash-checked. `deliverable` is for the reader: ids sit in hidden section markers, and a lint keeps ledger artefacts out of the prose. `working` is the model's own. A deliverable changes only through a committed change list: plan, then whole-section rewrites, then sync. Unplanned edits, appended corrections, and citations of replaced rows are refused. |

The research tools are plain functions in `research_api.py`, with no import from `mcp`. The server
registers them, and `scripts/research.py` runs them through the CLI with JSON arguments. A
session with no connection to the server therefore runs the same code on a local database, and
`research_ledgers` export and import move a ledger between the two. The CLI takes the arguments as
JSON, `@FILE` or `-` (stdin), and an import's `data_file` names the export, so a large ledger never
goes through argv. Through the tools, a long text goes once with `research_blob` (in pieces if
needed) and is passed on as `ref`. `export` takes `include_log=false`; `import` takes `to` (another name) and
`dry_run`; `copy` makes a sandbox copy, `rename` renames, and `research_ledger_delete` deletes with
`confirm` set to the ledger id. `lookup` searches the cards a situation leads to: the ordinary cards and
the research cards whose page has an `ENTRY — signal:` line (the session loop and the abnormal cards;
`research.parse_page` tags them `signal`). The cards entered by a routed plan object (stage, domain
and reference cards) are found with `scope="research"`; `"all"` searches every card and `"handbook"`
the ordinary ones only. A user's own cues on a research card (`save_entry(id="rs-…", triggers=…)`)
survive the pages being loaded again, as a rule the user changed survives an upgrade; the rest of the
card is the page's. A Hangul query word is also searched by its first
two syllables (`store.stems`): Korean writes particles and endings onto the word, so only the stem
is a prefix of what a card says.

When porting a hand-kept ledger: `check` also judges the basis of `proposed` rows, and
`[unverified]` propagates only from the first token of the evidence cell.

### Server

`refhandbook serve` serves the tools over Streamable HTTP at `https://<domain>/mcp`. It is its own
OAuth authorization server, which is what Claude expects of a connector, and it checks no passwords:
the site's sign-in does (portal/sso.py).

1. Claude calls `/mcp` without a token and gets `401` with a pointer to
   `/.well-known/oauth-protected-resource/mcp`, which names this server as the authorization server.
2. Claude registers itself at `/register` (dynamic client registration). Only the redirect URIs in
   `RHB_REDIRECT_ALLOW` are accepted, each compared exactly (a loopback entry `http://localhost:*`
   takes any port): by default claude.ai's and claude.com's callbacks, and loopback for Claude Code.
   Setting the variable (in `handbook.env`, then a restart) **replaces** that list, so it names the
   defaults it keeps as well as the new callback. Every authorization response names this server
   (RFC 9207): `iss`, exactly the metadata's `issuer`, on the code and on every error redirect, and
   the metadata says `authorization_response_iss_parameter_supported`. A client that keys its
   callback on that uses one stable callback: ChatGPT sends
   `https://chatgpt.com/connector_platform_oauth_redirect` to such a server, and to one without it a
   callback with a per-connection id (`https://chatgpt.com/connector/oauth/<id>`), which no exact
   entry can allow.
3. The browser opens `/authorize`, which forwards to `/login`. nginx puts `/login` behind the site
   sign-in (`auth_request`); the sign-in vouches for the user with `X-Auth-Token`, an EdDSA JWT for
   this app's audience valid for a minute, which this server checks with the sign-in's public key
   (portal/tokens.py, the same check every backend of the site uses). Someone not signed in is sent
   to the sign-in page. The page names the requesting client and where it returns to, and asks
   "allow it as <uid>?". The account must resolve through NSS (and be in `RHB_REQUIRE_GROUP`, if
   set). A consent POST from another origin is refused.
4. The server issues a one-time code, bound to the PKCE challenge (S256) and to this server as the
   resource, and `/token` exchanges it for an access token (1 h) and a refresh token. Tokens carry the
   uid as their subject; codes and tokens are stored hashed in `<data>/auth.db`.
5. Every tool call opens the signed-in user's own database. The research cards are loaded into each
   store.

**Sessions.** A grant starts a token family. Each refresh rotates the refresh token, and first
re-checks that the account still exists and is still in the group. A rotated token presented again
revokes the whole family. The family ends `RHB_SESSION_TTL` (90 days) after the grant, whatever the
refreshes; revoking any of its tokens ends it at once. Clients that never complete a grant are
deleted after a day; a pending request lasts 10 minutes. Calls to `/mcp` whose `Host` is not the
public host are refused. Rate limits on the sign-in and the OAuth endpoints are the site's (nginx).

**Running it.** The handbook is two roles of the site, installed with everything else by
`deploy/install.sh` (docs/site.md): `<name>-handbook` (this server) and `<name>-runner` (the sandbox
runner, the only unit that creates namespaces; docs/agents.md). Both run as `<name>-handbook` on
`/var/lib/<name>-handbook`. Every setting comes from the site's facts, rendered into the unit: the
site's URL and issuer, the sign-in's key and path, the port, and the audience of the site file's apps
that reach it. `/etc/<name>-handbook/handbook.env` holds local overrides only (`RHB_REQUIRE_GROUP`,
token lifetimes). The server is built on `mcp` 2.x (`MCPServer`); it runs sync tools on worker
threads, so tool calls are serialized, and a refusal is raised as `ToolError` so its text reaches
the model.

**Connect.** In Claude, add `https://<domain>/mcp` as a custom connector and press Connect: the site's
sign-in, then "allow". Claude Code signs in the same way through a loopback redirect. Ledgers kept in
another store move over with `research_ledgers(action="export")` there and `action="import"` here.

## Not built yet

- Run state for ordinary cards: recording which steps of an open card are done, so an interrupted
  run resumes at the right step. CAP 676 lists "fail to complete a step after an interruption" as
  a standing error. The research ledger does this for research cards, through plan objects. A
  general version would attach the same object to any card.
- Scopes: one store per user today (one database per signed-in user). A project-level handbook shared by a group and layered over each personal one is the
  obvious next shape; the directory's groups could define it.
- Typed attributes on entries and relations beyond `kind`, `tags` and `note`.

## References

- UK CAA, [CAP 676: Guidance on the Design, Presentation and Use of Emergency and Abnormal Checklists](https://www.caa.co.uk/our-work/publications/documents/content/cap-676) (Issue 3, 2006). The CAA notes parts are out of date with respect to EASA regulation; the human-factors guidance used here is not regulatory.
- Model Context Protocol, [Tools specification](https://modelcontextprotocol.io/specification/2025-06-18/server/tools).
- Model Context Protocol, [Knowledge Graph Memory Server](https://github.com/modelcontextprotocol/servers/tree/main/src/memory).
- Further reading, not consulted directly for this prototype: Burian, Barshi and Dismukes (NASA Ames), work on emergency and abnormal checklist design; Degani and Wiener (1990), cockpit checklist human factors.

## The structure order

The server's instructions name the structure every ledger is reconstructed to (`entry_api.STRUCTURE`,
now `entry-1`) and give the order to reconstruct a ledger that is not an entry of it, at once and
before anything else is done with it. The order is a command of the instruction set: it does not
depend on a session of the research loop being opened. `research_ledgers` (list) marks the ledgers
it is about, `NOT RECONSTRUCTED (structure entry-1)`: a ledger no entry node routes to with the tag
`structure:entry-1`. Raising the structure is changing that one name; every ledger is then marked
again until its entry carries the new tag.
