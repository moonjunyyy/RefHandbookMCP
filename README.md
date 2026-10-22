# refhandbook

A quick reference handbook (QRH) for coding agents, packaged as a Claude plugin with an MCP server. The
server runs either on the user's machine, or on a server of their own where every chat, Cowork and
Claude Code session reaches the same store after a sign-in against the LDAP directory.

A QRH is the book a flight crew reaches for when something goes wrong: short cards, found by
symptom, each saying how to confirm it applies and what to do, in order. This project keeps that
card discipline and replaces the parts a printed book fixes at press time (tabs, index,
cross-references) with a relational store that changes at runtime.

The same store also carries the **research cards** (`rs-*`) and the **research ledger**: the run
state of a research conversation (directives, premises, claims and their verdicts per
assumption configuration, plan objects, documents). The `research` skill drives a session loop over
them (one session per message, or per delegated agent run), so each continues from stored state
instead of from the model's memory, and several can work on one ledger side by side.

Status: prototype.

## Try it

```bash
uv sync
uv run refhandbook seed                        # five example cards
uv run refhandbook lookup "CONFLICT (content): could not apply"
uv run refhandbook show rebase-conflict
uv run refhandbook show rs-n1                  # a research card (loaded automatically)
uv run refhandbook research list               # the research tools, callable with JSON arguments
uv run pytest
```

As a plugin, from this directory:

```bash
claude --plugin-dir .
```

Locally, the handbook lives in `~/.refhandbook/handbook.db`; set `REFHANDBOOK_DB` to use another
file. On a remote server, each signed-in user has `RHB_DATA_DIR/users/<uid>.db`.
`refhandbook export` and `refhandbook import` move it through JSON, so it can be reviewed and
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
remove the first; the skill tells the agent to reopen and resume for the second.

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

### MCP tools

| Tool | Purpose |
| :- | :- |
| `lookup` | Symptom to candidate cards, with condition and objective |
| `open_entry` | The card, plus related entries |
| `index` | Contents list grouped by tag, kind, or letter |
| `traverse` | Walk relations outward from a card |
| `save_entry` | Create or update a card |
| `delete_entry` | Remove a card and its relations |
| `relate`, `unrelate` | Typed edges between cards |
| `define_relation_type`, `relation_types` | The relation vocabulary |
| `audit` | CAP 676 assessment checks over the whole handbook |
| `research_*` | The research ledger: sessions, rows, plan objects, configurations and verdicts, documents (16 tools; card `rs-ref-ledger`) |
| `cap` | Capability records of every kind (script, policy, layer, alias, rule, card): versioned, owned, reviewed on a TTL, deprecated and retired; a widening grant waits for the user (docs/kernel.md "Capabilities") |
| `run`, `job`, `files` | Run a script in the user's sandbox as a background job, read jobs, and keep files in the workspace. No network of its own: a policy's egress profiles (pypi, npm, crates, github, …) reach out through the egress supervisor, HTTPS only, to those hosts only; the server's layers bring Python, Node and Rust (`refhandbook layers build`) |

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
the page instead. The research skill's abnormal index is generated from the same pages
(`refhandbook research-index --write skills/research/SKILL.md`), and a test checks that the two
agree.

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
`confirm` set to the ledger id. `lookup` searches the ordinary cards unless `scope="research"` or
`"all"`.

When porting a hand-kept ledger: `check` also judges the basis of `proposed` rows, and
`[unverified]` propagates only from the first token of the evidence cell.

### Plugin

`.claude-plugin/plugin.json` declares the server inline (a root `.mcp.json` would also be read as
this repository's project configuration). It declares it one of two ways, and the way decides
where the plugin works:

| declaration | Chat (web, desktop, mobile) | Cowork | Claude Code |
|---|---|---|---|
| local: a command the app starts | ignored | only when the session runs on the user's computer | loads |
| remote: `{"type": "http", "url": …}` | works after connecting it on the plugin's Connectors tab | loads; connect it on the Connectors tab | loads |

The local declaration runs `uv run --frozen --project ${CLAUDE_PLUGIN_ROOT} refhandbook serve`,
with the virtualenv in `${CLAUDE_PLUGIN_DATA}` so it survives plugin updates; `--frozen` never
writes to the installed plugin. In a cloud session it starts a fresh store each session, so the
ledger does not persist there. The remote declaration points at a server of your own (below):

```bash
uv run refhandbook plugin-json https://hb.example.org/mcp --write .claude-plugin/plugin.json
```

The machine that runs the server needs `uv` on its `PATH`; `uv` fetches Python 3.14 if it is
missing. The server is built on `mcp` 2.x (`MCPServer`). It runs sync tools on worker threads, so
tool calls are serialized, and a refusal is raised as `ToolError` so its text reaches the model.

Two skills ship with the plugin:
- `skills/handbook/SKILL.md` teaches the lookup, confirm, follow discipline and how to write a
  card;
- `skills/research/SKILL.md` runs the research session loop over the `rs-*` cards and the ledger.

Optional Claude Code hooks for the research loop are left unwired, because Cowork rarely uses
hooks. They read a local store, so they only help with the local declaration. To use them, add
these to `.claude/settings.json`:
- `UserPromptSubmit`: `refhandbook research-hook prompt <ledger>`, which counts prompts and names
  the first action of the reply;
- `Stop`: `refhandbook research-hook stop <ledger>`, which exits 2 while this conversation's chat
  session (by the label the prompt hook gave, from the hook payload's `session_id`) is still
  open, or the latest prompt has no session; other conversations' sessions and agents' are not
  the reply's.

### Remote server

`refhandbook serve --http` serves the same tools over Streamable HTTP at `<RHB_PUBLIC_URL>/mcp`.
It is its own OAuth authorization server, which is what Claude expects of a connector:

1. Claude calls `/mcp` without a token and gets `401` with a pointer to
   `/.well-known/oauth-protected-resource/mcp`, which names this server as the authorization
   server.
2. Claude registers itself at `/register` (dynamic client registration). Only the redirect URIs in
   `RHB_REDIRECT_ALLOW` are accepted: by default claude.ai's and claude.com's callbacks, and
   loopback for Claude Code.
3. The browser opens `/authorize`, which forwards to `/login`. The page names the requesting client
   and where it returns to. The user signs in with their POSIX name and password. By default
   (`RHB_AUTH=pam`) the server checks the password through `/etc/pam.d/refhandbook`, which
   includes `common-auth`, exactly as a system login would (Kerberos, nslcd, sssd). Its account
   phase is `pam_permit`, since pam_unix's account check needs root; instead the name must
   resolve through NSS, and `RHB_REQUIRE_GROUP` limits sign-in to one POSIX group. With `RHB_AUTH=ldap` it binds to the
   directory as the user instead (`RHB_LDAP_GROUP_FILTER` for the group). An empty password is
   refused, and so is any non-ASCII name. A password that must be changed first (expired, or an
   admin's one-time password) is refused with a message saying so; the server never changes it.
   Under PAM, the conversation gives the password only to "Password:" prompts and ends the sign-in
   at a "New password:" prompt, which pam_krb5 shows inside authentication; with `defer_pwchange`
   or pam_sss the expiry comes from the account phase, so add `pam_krb5.so`/`pam_sss.so` to the
   `account` lines of `/etc/pam.d/refhandbook`.
4. The server issues a one-time code, bound to the PKCE challenge (S256) and to this server as the
   resource, and `/token` exchanges it for an access token (1 h) and a refresh token. Tokens carry
   the uid as their subject; codes and tokens are stored hashed in `RHB_DATA_DIR/auth.db`.
5. Every tool call opens the signed-in user's own database. The research cards are loaded into
   each store.

**Sessions.** A sign-in starts a token family. Each refresh rotates the refresh token, and first
re-checks that the account still exists and is still in the group (through NSS with PAM, in the
directory with LDAP); if that
cannot answer, the refresh is refused. A rotated token presented again revokes the whole family.
The family ends `RHB_SESSION_TTL` (90 days) after the password was checked, whatever the refreshes;
revoking any of its tokens ends it at once.

**Limits.** Each password attempt is counted before the directory is asked, so concurrent posts
cannot outrun the count. Five failures from one address lock that uid for that address for 15
minutes; fifty from all addresses lock the uid. A sign-in request allows five attempts and lasts 10
minutes. Clients that never complete a sign-in are deleted after a day. The address is read from
`X-Forwarded-For` right to left, past the proxies in `RHB_TRUSTED_PROXIES` (loopback by default; add
a router that terminates TLS in front of the server). `deploy/nginx.conf` also rate-limits `/login`,
`/register`, `/authorize` and `/token`. Calls to `/mcp` whose `Host` is not the public host are
refused, and an `ldap://` directory off this host is refused without StartTLS.

**Install** on a server whose directory already serves POSIX accounts through `nslcd`:

```bash
sudo ./deploy/install.sh   # 1st run: writes /etc/refhandbook/env, LDAP lines taken from /etc/nslcd.conf
sudoedit /etc/refhandbook/env   # set RHB_PUBLIC_URL; optionally RHB_LDAP_GROUP_FILTER
sudo ./deploy/install.sh   # 2nd run: venv, systemd unit, health check
```

The code, its venv and its Python belong to root (`/opt/refhandbook`, `/opt/refhandbook-venv`,
`/opt/refhandbook-python`); the service runs as `refhandbook` and writes only
`/var/lib/refhandbook`. The first run copies nslcd's bind password, if any, into `/etc/refhandbook/ldap-bindpw` (0400);
`refhandbook nslcd-env` prints the translation without it. Then put `deploy/nginx.conf` or
`deploy/Caddyfile` in front for TLS; if a router terminates TLS and forwards plain HTTP to this
server, use `deploy/nginx-behind-router.conf` instead. The proxy must pass server-sent events unbuffered. Check
from outside with `curl https://<domain>/.well-known/oauth-protected-resource/mcp`, and test a
sign-in on the server with
`sudo -u refhandbook /opt/refhandbook-venv/bin/refhandbook --env-file /etc/refhandbook/env check-login <uid>`.

**Site sign-in (`RHB_AUTH=sso`).** Behind the site-wide sign-in of
[ldap-portal](../ldap-portal) (`deploy/site/www.m00nny.kr.conf`), this server checks no passwords.
nginx runs `/login` through `auth_request`; the sign-in service vouches for the user with
`X-Auth-Token`, an EdDSA JWT for audience `refhandbook` valid for a minute, which this server
verifies with `RHB_SSO_PUBLIC_KEY_FILE`. A signed-in user only sees "allow <client> as <uid>?";
someone not signed in is sent to `RHB_LOGIN_URL`. Before the grant, and on every refresh, the
account must still resolve through NSS (and be in `RHB_REQUIRE_GROUP`). A consent POST from another
origin is refused. The OAuth endpoints Claude talks to are unchanged.

**Accounts.** This server creates no accounts. With the account portal
([ldap-portal](../ldap-portal)) served under `/account` on the same host (`PORTAL_ROOT_PATH=/account`;
`deploy/nginx.conf` and `deploy/Caddyfile` carry the proxy block) and `RHB_ACCOUNT_URL=/account`, the
sign-in page links to its account request form (사용 신청, approved by an admin, who gets a one-time
password to pass on) and to its password-change page for one-time and expired passwords.

**Connect.** In Claude, add the plugin (built with `plugin-json`) and press Connect on its
Connectors tab, or add `https://<domain>/mcp` as a custom connector. Claude Code connects through
the same plugin and signs in through a loopback redirect. Ledgers kept in a local store move over
with `research_ledgers(action="export")` there and `action="import"` here.

## Not built yet

- Run state for ordinary cards: recording which steps of an open card are done, so an interrupted
  run resumes at the right step. CAP 676 lists "fail to complete a step after an interruption" as
  a standing error. The research ledger does this for research cards, through plan objects. A
  general version would attach the same object to any card.
- Scopes: one store per user today (a local file, or one database per signed-in user on a remote
  server). A project-level handbook shared by a group and layered over each personal one is the
  obvious next shape; the directory's groups could define it.
- Typed attributes on entries and relations beyond `kind`, `tags` and `note`.
- A marketplace entry for one-line install.

## References

- UK CAA, [CAP 676: Guidance on the Design, Presentation and Use of Emergency and Abnormal Checklists](https://www.caa.co.uk/our-work/publications/documents/content/cap-676) (Issue 3, 2006). The CAA notes parts are out of date with respect to EASA regulation; the human-factors guidance used here is not regulatory.
- Model Context Protocol, [Tools specification](https://modelcontextprotocol.io/specification/2025-06-18/server/tools).
- Model Context Protocol, [Knowledge Graph Memory Server](https://github.com/modelcontextprotocol/servers/tree/main/src/memory).
- Claude Code, [Plugin manifest reference](https://code.claude.com/docs/en/plugins-reference).
- Further reading, not consulted directly for this prototype: Burian, Barshi and Dismukes (NASA Ames), work on emergency and abnormal checklist design; Degani and Wiener (1990), cockpit checklist human factors.
