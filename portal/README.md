<<<<<<< HEAD
# ldap-portal

Self-service and admin web portal for a Kerberos realm: OpenLDAP (`ldaps://ldap.<realm>`)
with MIT Kerberos 1.22 storing principals in LDAP (kldap).

- **Every user**: sign in with their Kerberos password, edit display name, email and login shell,
  change their password, and set a new one when it has expired.
- **Helpdesk** (`cn=helpdesk` group): search users, reset passwords (one-time password that must be
  changed at next sign-in), unlock after failed logins. Never on admins or protected groups.
- **Admin** (`cn=admin` group): all of the above, plus create users, disable/enable, manage groups,
  approve or reject account requests, and make invitation links.
- **The site's other services**: the menu links every app of the site file
  (`deploy/site.toml`) that has a menu label and that the user's groups may see, such as
  refhandbook's approval page `/agents` (rule proposals, sandbox policies, jobs).
- **Anyone** (no account yet): ask for one at `/request` ("사용 신청"): a username, what it is for,
  and optionally a name and email, with a consent notice for the personal data. The request waits
  for an admin; nothing is created until then.
- **Anyone with an invitation link**: open it, choose a username and a password, and the account
  exists at once (`/join/<token>`).

Creating a user follows the existing layout: `uid=<u>,ou=Users` (inetOrgPerson, posixAccount,
shadowAccount), a private group `cn=<u>,ou=Groups` with gid = uid number, membership in `cn=user`,
then `kadmin addprinc -x dn=<entry> <u>/user` plus the alias `<u>@<REALM>`. If Kerberos fails, the
LDAP entries are rolled back. Name and email are optional; without a name, `cn`/`sn` (required by
inetOrgPerson) hold the username. The name is not copied into `gecos`, which every host shows to
every user through NSS (`PORTAL_WRITE_GECOS=1` brings that back for ASCII names).

## Security model

Each permission is enforced in three places, so a bug or a compromise in the web app is contained:

| Layer | Enforces | File |
|---|---|---|
| Portal (app) | who sees which page/button; helpdesk vs admin; no self-lockout | `portal/rbac.py` |
| kadmind | which principals the portal's service identity may add/reset/modify | `deploy/kadm5.acl` |
| slapd | which entries/attributes the portal may write; key material hidden | `deploy/slapd-acl.ldif` |

Other protections:
- Passwords live only in Kerberos. The portal never stores, logs, or writes password hashes, and
  never passes a password on a command line (kadmin/kpasswd are driven through a pty).
- Login verification gets a ticket for `HTTP/<domain>` and decrypts it with the portal's
  keytab, which blocks KDC-spoofing attacks against password checks.
- Admins never pick passwords: resets and new accounts get a random one-time password with
  `+needchange`.
- The portal service principal is `portal/service`, deliberately not `*/admin`, since the default
  `kadm5.acl` gives `*/admin` every privilege.
- LDAPS with certificate validation; HTTPS-only `SameSite=Strict` session cookies; CSRF tokens on
  every form; strict input validation before anything reaches a DN or a kadmin query; login
  throttling (plus Kerberos lockout policy); CSP and other security headers; `Cache-Control: no-store`.
- Roles and the disabled flag are re-read from LDAP on every request: disabling a user or removing
  them from `admin` takes effect immediately, not when their session expires.
- Every login and change goes to a JSON-lines audit log (who, what, target, IP).

### Permission matrix

| Action | user | helpdesk | admin |
|---|---|---|---|
| Edit own profile (name, mail, shell), change own password | ✓ | ✓ | ✓ |
| List/search users | | ✓ | ✓ |
| Reset password / unlock (non-admin targets) | | ✓ | ✓ |
| Reset password / unlock an admin | | | ✓ |
| Create user, disable/enable, add/remove groups | | | ✓ |
| Approve/reject account requests | | | ✓ |
| Reset, disable, or change groups of your own account | ✗ | ✗ | ✗ |

To change who can do what: add or remove people from `cn=admin` / `cn=helpdesk` in LDAP (or from the
portal's Groups card). To change what a role can do, edit `PERMISSIONS` in `portal/rbac.py`, and
loosen the matching `kadm5.acl`/olcAccess lines if needed.

## Setup

One command installs or updates everything, and is rerun after any change (code, `deploy/site.toml`,
templates). Nothing on the host is named by hand: every name and path derives from the Kerberos
realm (krb5.conf's `default_realm`) and `deploy/site.toml` (`portal/facts.py`).

```sh
sudo deploy/install.sh --check     # what it derives, before touching anything
sudo deploy/install.sh             # install or update
```

| derived | from the realm `EXAMPLE.ORG` | override in `[site]` |
|---|---|---|
| site name | `example` | `name` |
| domain | `www.example.org` | `domain` |
| LDAP | `ldaps://ldap.example.org`, `dc=example,dc=org`, `ou=Users,…`, `ou=Groups,…` | `ldap_uri`, `base_dn`, `users_ou`, `groups_ou` |
| services | `example-portal` (:8080), `example-sso` (:8090) | `ports` |
| TLS | nginx, with `/etc/letsencrypt/live/<domain>` | `router` (and `listen`), below |
| each service's | system user, `/etc/<unit>`, `/var/lib/<unit>`, `/var/log/<unit>` | |
| code | `/opt/example-portal` (with its `.venv`) | `code` |

What the installer does: creates the two service users; copies the code and builds its virtualenv;
installs `deploy/site.toml` as `/etc/<name>/site.toml`; renders the systemd units, the nginx site and
snippets, and the directory's side (below) from `deploy/templates/`; makes each
service's env file once with a fresh secret (`/etc/<unit>/{portal,sso}.env`: secrets and local
overrides only, never overwritten) and the SSO's token key pair; then `nginx -t`, enables and
restarts the units. A host on the old layout (unit `ldap-portal`) is moved: the old unit is removed
and its `/etc`, `/var/lib`, `/var/log` carried over to the derived names. The WebDAV directory timer
(`dav-homes`, `<site>-dav-homes`) of earlier versions is stopped and removed; `/data` is left as it is.

### TLS at a router

With a TLS-terminating proxy in front (a router holding a DNS-challenged certificate, say), name it
in `[site]`: `router = "192.168.0.1"` (an address or CIDR, or a list: the router's address as
this host sees it, so its inside interface). Keep it out of the repository by putting it in
`deploy/site.local.toml` (git-ignored; its `[site]` keys win over `site.toml`'s, and it is installed
beside it). nginx then serves plain HTTP
on `listen` (80) and:
- answers only the router (and localhost); anyone else reaching the port directly gets 403;
- takes the client from the router's `X-Forwarded-For` (`set_real_ip_from`), so the sign-in rate
  limits and the audit log see clients, not the router;
- still redirects the aliases to `https://<domain>`, and still sends HSTS.

The apps need nothing else: cookies stay `Secure` (the browser sees https) and the backends are
told `X-Forwarded-Proto: https`. The installer renders the router's side into
`/etc/<name>/router/<domain>.conf`: `Host` and `X-Forwarded-For` passed on, the site's 4m body
limit, and no buffering with long timeouts for `/mcp`'s streamed answers.

It ends with what only an admin can do, as exact commands for this site: the keytabs it could not
find, and where the rendered directory files are.

### The directory's side (once, on the KDC and the LDAP server)

The installer renders both files into `/etc/<name>/directory/` with this realm's names, DNs and the
current members of the admin group; re-render (rerun the installer) after adding an admin.

- `kadm5.acl`: merge into `/etc/krb5kdc/kadm5.acl` above any broader rule, then restart
  `krb5-admin-server`. It denies the portal every principal it must never touch, including each
  admin's everyday principals.
- `slapd-acl.ldif`: merge with the current `olcAccess` (instructions inside). Rule `{0}` keeps
  Kerberos key material away from users: before it, an ordinary GSSAPI bind could read
  `krbPrincipalKey` on its own entry, and a `(krbPrincipalKey=*)` search matched `krbtgt/<REALM>`.
  Check from an ordinary account afterwards that `ldapsearch -Y GSSAPI … krbPrincipalKey` on the
  krbtgt entry prints nothing.
- The portal's policy and principals: `kadmin -q 'addpol -minlength 12 -minclasses 3 -history 5
  -maxfailure 5 -failurecountinterval 15m -lockoutduration 15m users'`, and `addprinc -randkey
  portal/service` and `addprinc -randkey HTTP/<domain>` (the installer prints the `ktadd` lines).
- `slapo-unique` on `uidNumber` and `gidNumber` (the portal's ID allocation lock is per-process);
  optionally the `accesslog` overlay; a `helpdesk` group.
- `PORTAL_SASL_USERPASSWORD=1` (in the portal's env file) gives new users `userPassword:
  {SASL}<uid>/user@<REALM>`, so LDAP simple binds go through saslauthd to Kerberos; only with
  saslauthd running `-a kerberos5`.

Run the portal on a host only admins can log in to: anyone with root there holds its kadmin keytab.

### Tests

```sh
uv pip install --python .venv/bin/python -e '.[dev]' && .venv/bin/python -m pytest -q
```

The tests run the real app (routes, permissions, CSRF, throttling, rollback, first-login password
change) against in-memory fakes of LDAP and Kerberos.

### Account requests ("사용 신청")

`/request` is public. A request is stored in `PORTAL_REQUESTS_DB` (SQLite, mode 0600 under
`/var/lib/<site>-portal`), not in LDAP, so the portal needs no new directory rights for it. Admins see
the queue under **Requests** and approve (the normal create-user path; the one-time password is
shown once, to be passed on over a separate channel) or reject. Either way the request row is deleted
at once; unanswered ones go after `PORTAL_REQUEST_TTL_DAYS` (30). The audit log records the username
and the decision, not the name or email.

Abuse limits: 5 submissions per address per hour, at most `PORTAL_REQUEST_MAX_PENDING` (100) waiting,
and the page answers the same whether or not a username is taken, so it cannot be used to list
accounts. Set `PORTAL_REQUESTS=0` to turn it off.

### Invitations (가입 링크)

An admin makes a one-time link under **Invite** (with a note of whom it is for) and sends it. Whoever
opens it chooses a username and a password and has an account at once: the normal create-user path,
but with the password they chose and no forced change, so there is no one-time password to pass
on. The link works once (it is claimed before the account is made, and put back if making it fails)
and expires after `PORTAL_INVITE_TTL_HOURS` (168); admins can revoke open ones. Only the token's
hash is stored (`PORTAL_INVITES_DB`, mode 0600 under `/var/lib/<site>-portal`), so the database alone
cannot be used to sign up. The page tells the link's holder whether a username is taken (it has to);
without a valid link it says nothing. Failed sign-ups are limited to 10 per address per hour, on top
of nginx's `login` rate. The link points at `PORTAL_PUBLIC_URL` (`https://<domain>`). Set
`PORTAL_INVITES=0` to turn it off.

### Personal data (개인정보)

Name and email are personal data. What the portal does about it:
- Collects only username and purpose as required; name and email are optional and say what they are for.
- Shows a consent notice (items, purpose, retention, the right to refuse) and requires agreement
  before a request is accepted. Set `PORTAL_PRIVACY_CONTACT` to name who answers questions about it.
- Deletes request data as soon as it is decided, or after the TTL.
- Keeps names out of `gecos`, and rule `{4}` in `deploy/slapd-acl.ldif` makes `cn`, `sn`,
  `givenName`, `displayName`, `mail`, `gecos` (and the other contact attributes) readable only by
  the user and the portal. Before that rule, every signed-in account could read every user's name
  and email with `ldapsearch`, and `getent passwd` showed the gecos name on every host.

Existing entries still carry `gecos` copied from the name. Once the ACL is in place, remove it
(check the LDIF before applying it):

```sh
kinit <you>/admin
ldapsearch -Q -LLL -o ldif-wrap=no -Y GSSAPI -H ldaps://ldap.<realm> -b ou=Users,<base_dn> '(gecos=*)' dn \
  | awk '/^dn:/{print; print "changetype: modify"; print "delete: gecos"; print ""}' > strip-gecos.ldif
ldapmodify -Q -Y GSSAPI -H ldaps://ldap.<realm> -f strip-gecos.ldif
```

Check from an ordinary account afterwards: `ldapsearch -Y GSSAPI ... -b ou=Users,<base_dn> mail cn`
should list only your own values, and `getent passwd <someone-else>` should have an empty fifth field.

### Serving under a sub-path

Set `PORTAL_ROOT_PATH=/account` and proxy `/account/` to the portal (the second half of
`deploy/nginx.conf`). Links, redirects and the session cookie's `Path` all carry the prefix, and the
app accepts requests whether or not nginx strips it.

## One sign-in for the site

The site runs behind one nginx server with one Kerberos sign-in:

| Path | What | Who checks |
|---|---|---|
| `/` | main page, `portal/sso.py`: sign-in or a greeting, and a card per app of the site file | public |
| `/auth/` | site sign-in, `portal/sso.py` on :8090 | public (rate-limited) |
| `/account/` | this portal on :8080 with `PORTAL_AUTH=sso`; `/account/request` and `/account/join/` stay public | `auth_request` + token |
| `/agents` | refhandbook's approval page | `auth_request` + token |
| `/mcp`, `/authorize`, `/token`, `/register`, `/revoke`, `/login`, `/.well-known/oauth-*` | refhandbook with `RHB_AUTH=sso` | its own OAuth; `/login` via `auth_request` + token |

**Services are declared, not hand-wired.** `deploy/site.toml` lists every service once: its
routes, the audience its tokens are minted for, its card on the main page and its menu entry
(`portal/site.py`). The installer renders from it the nginx snippets (the audience map and the
locations, included by the site's nginx config, which keeps only TLS, the main page and the
sign-in); the SSO shows its cards on the main page and mints tokens for the audiences the file
declares, and the portal's menu shows its apps. The renderer refuses duplicate routes, unknown fields and limits, and
routes with nowhere to go; a `site` route goes through the sign-in and carries a token only for its
own app, and a `public` route clears any token header. Adding a service: one `[[app]]` in
`deploy/site.toml`, then `sudo deploy/install.sh`.

**Apps the site hosts.** A browser app (a built `dist/`, such as 글타래) needs no server of its
own: an `[[app]]` with `static = true` is served at `/apps/<id>/` behind the sign-in, and with
`storage = true` each user gets a JSON store next to it, `/apps/<id>/api/store/<key>`
(`portal/apps.py`, the `<site>-apps` unit), so what they save follows their account. Tokens for it
are minted for the app's id alone, and the store checks the app in the path against them: one app's
token does not open another's data. Publish a build with `sudo deploy/install.sh --app <id> <dist>`.
An app built with relative paths (Vite `base: './'`) finds its store at `api/` next to its page.

How it fits together:
- nginx asks the SSO (`/auth/check`) before every protected request. A browser is known by the
  site cookie (`<site>_sso`, `Path=/`, `SameSite=Lax`, 8 h from sign-in); without one, nginx sends
  it to `/auth/login?next=...`. One-time and expired passwords are changed at `/auth/expired`.
- Backends never trust a user header. For `/account/`, `/agents` and `/login`, nginx names the backend
  (`map $request_uri $auth_audience`) and the SSO answers with `X-Auth-Token`: an EdDSA JWT for
  that backend only, valid one minute (`portal/tokens.py`). Backends hold the public key alone, so a
  local user who reaches :8080 or :8765 directly cannot forge one, and a token for one backend is
  refused by the other.
- refhandbook keeps its OAuth (Claude needs the metadata, registration, PKCE and `/token`); only
  its sign-in step is replaced: signed in to the site, `/login` just asks "allow Claude as <uid>?".
- The SSO runs as its own user with only the `HTTP/<domain>` keytab and the signing key; the
  portal's kadmin keytab never meets the most exposed process.

It is all installed by `sudo deploy/install.sh` (Setup, above).

Check: `/account/` while signed out redirects to `/auth/login`.

## Not included (on purpose)

- **Deleting users.** Disable instead. Deleting frees the uidNumber, which could later be reused
  and inherit the old user's files. Delete by hand: `kadmin delprinc`, then `ldapdelete`.
- **Open self-registration.** Anyone on the network could create accounts. Sign-up takes an admin's
  invitation link, or a request an admin approves.
- **Sending email.** The portal never mails one-time passwords; the admin passes them on.
- **File sharing.** WebDAV was here once; files are shared over SMB instead, outside this site.
- **2FA for admin actions.** Recommended: put the portal behind an SSO with MFA, or require
  Kerberos OTP/PKINIT for members of `admin`.
=======
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
assumption configuration, plan objects, documents). The `research` skill drives a turn loop over
them, so a turn continues from stored state instead of from the model's memory, and so does the
next session.

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
| `research_*` | The research ledger: turns, rows, plan objects, configurations and verdicts, documents (16 tools; card `rs-ref-ledger`) |

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
| Turn protocol: `research_begin` → token on every write → `research_end` | A write proves the caller read the current state. `research_end` refuses while any of these remain: a pending hit, a running plan object, no continuation, an unaddressed directive, an unsynced document plan, or a check error. |
| Plan objects (K) | Every card exit returns objects. `research_done` refuses an exit that pushed nothing. One K waits for the user across turns: a push to page USER re-arms it, so a one-word turn adds no K. |
| Volume | `research_begin` shows the rows changed in the last 3 turns and every live row (`view=recent`; `brief` and `full` too), and `research_end` prints only the rows the turn changed. `research_show(ids=…)` reads the rest. |
| Configurations | `main` is the set of premises that are on, and only the user switches it. Named configurations switch premises on or off, swap alternatives, or add model premises, and the boundary report shows which single change flips a verdict. Model origin taints: nothing on the main line may rest on it. |
| Propagation | Changing a row opens hits on everything that rests on it, verdict cells included. Switching a premise off reaches only the main line. Superseding or refuting a premise also reaches the exploration cells that contain it. |
| Documents | Each document has a role. `source` is the user's original: read-only and hash-checked. `deliverable` is for the reader: ids sit in hidden section markers, and a lint keeps ledger artefacts out of the prose. `working` is the model's own. A deliverable changes only through a committed change list: plan, then whole-section rewrites, then sync. Unplanned edits, appended corrections, and citations of replaced rows are refused. |

The research tools are plain functions in `research_api.py`, with no import from `mcp`. The server
registers them, and `scripts/research.py` runs them through the CLI with JSON arguments. A
session with no connection to the server therefore runs the same code on a local database, and
`research_ledgers` export and import move a ledger between the two. The CLI takes the arguments as
JSON, `@FILE` or `-` (stdin), and an import's `data_file` names the export, so a large ledger never
goes through argv. `export` takes `include_log=false`; `import` takes `to` (another name) and
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
- `skills/research/SKILL.md` runs the research turn loop over the `rs-*` cards and the ledger.

Optional Claude Code hooks for the research loop are left unwired, because Cowork rarely uses
hooks. They read a local store, so they only help with the local declaration. To use them, add
these to `.claude/settings.json`:
- `UserPromptSubmit`: `refhandbook research-hook prompt <ledger>`, which counts prompts and names
  the first action of the turn;
- `Stop`: `refhandbook research-hook stop <ledger>`, which exits 2 while a turn is open, or while
  the latest prompt has no closed turn.

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
   refused, and so is any non-ASCII name.
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
>>>>>>> 23bd3a0 (v0.5.0 First commit for alpha version)
