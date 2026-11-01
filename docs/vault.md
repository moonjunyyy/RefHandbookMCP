# The notes: a person's markdown vaults, in the browser (src/portal/vault.py)

A vault is a directory of markdown notes — the thing Obsidian opens — in a person's storage. The
notes app reads and writes it from the browser: the first thing on the page is the note (Home when
there is one), beside it the tree with a search above and "새 노트" as its last row; the view/edit
switch edits in place; wikilinks go to notes, `$…$` is set as mathematics, backlinks are one line
under the head. The files stay what they are — the same directory, the same `.md`, Obsidian over
SMB and the browser on one vault at once — so nothing is imported and nothing is exported. The
service is `<name>-vault` (port 8110, `facts.ROLES`), behind the site sign-in; the pages app draws
it (`/vault`, `/vault/<vault>/<path>`, `web/src/pages/vault.ts`, markdown and mathematics in
`web/src/lib/markdown.ts`) and its widgets (`web/widgets/vault.ts`: the notes last changed; Home).

## Whose files, and how the service reaches them

The service runs as its own user and **cannot see a person's files by itself**. What it sees is
what root stages for it: `<name>-vault-mounts` (`deploy/templates/vault-mounts.{service,path,timer}`)
is the handbook's sandbox-mounts reconciler (`refhandbook/agents/mounts.py`, run as
`refhandbook mounts --picks vault --roots-env PORTAL_VAULT_ROOTS`) reading the vault registry
instead of the sandbox policies: for each registered directory it makes an **idmapped bind** under
`/run/<name>-vault-mounts/<uid>/…`, through which the files read and write as the service's user and
stay the person's (owner, mode, quota). It runs when a vault is registered (the `.path` unit watches
the request file the service touches) and every minute (`.timer`); the service's unit starts after
it and may write only there (`ReadWritePaths=-/run/<name>-vault-mounts`). A vault just registered is
`pending` until the stage is there, which the page says in one line.

Where a vault may be is `PORTAL_VAULT_ROOTS` (`/etc/<name>-vault/vault.env`; the syntax of
`RHB_SANDBOX_MOUNTS`, `FROM[=NAME][:ro]`, `{user}` and `{uid}` for the person; unset:
`/data/{user}=storage`): a registered path must lie under one of the offered roots, resolved for
that person, which is also the list the page shows beside "볼트 추가". Up to 20 vaults a person.

Without a stage root (`PORTAL_VAULT_STAGE` unset: a local run, the tests) the real path is used.

## The API (`/vault/api/v1`)

| | |
|---|---|
| `GET /vaults` | `{vaults: [{id, name, path, status, created}], roots: [...]}` — `status` is `ok`, `pending`, or why not |
| `POST /vaults` `{path, name}` | register a directory of their storage (name empty: the directory's) → 201 |
| `DELETE /vaults/<id>` | forget it; the files stay |
| `GET /vaults/<id>/tree` | folders and notes (`type`: `dir`, `note`, `text`, `file`; `.obsidian`, `.git`, `.trash` hidden), at most 20000 entries |
| `GET /vaults/<id>/file?path=` | `{path, text, sha256, mtime, size}` of a text file (`.md .txt .json .canvas .csv`, up to 4 MB) |
| `PUT /vaults/<id>/file?path=` `{text}` with `If-Match: <sha256>` | the save; `409` when the note exists and no hash was given, `412` when it changed meanwhile |
| `GET /vaults/<id>/raw?path=` | an attachment a note shows (an image; `svg`, `html`, `xml` are sent as downloads, not rendered) |
| `POST /vaults/<id>/move` `{from, to}` · `DELETE /vaults/<id>/file?path=` | rename; move to `.trash/` (Obsidian's own trash folder) |
| `GET /vaults/<id>/search?q=` | full text (SQLite FTS5, unicode61) with snippets |
| `GET /vaults/<id>/links?path=` | `{links: [{path, text}], backlinks: [path]}`; `GET /vaults/<id>/tags` |
| `GET /vaults/<id>/recent?n=` | the notes last changed |

A path is relative to the vault, cleaned (`clean()`: no `.` or `..` segments, no empty ones, each
segment ≤ 255 bytes); anything else is `400`. A write must say `Content-Type: application/json`.
Errors are `{error}` with the status.

**A save never overwrites a change made elsewhere.** The page reads a note with its `sha256` and
sends it back as `If-Match`; the service compares it with the file as it is now (Obsidian may have
written it over SMB meanwhile) and refuses with `412` — the page shows one line and keeps the
person's text in the editor. A new note is a `PUT` without `If-Match`; one over an existing path
without a hash is `409`.

## The index

Search, links and tags come from the service's own SQLite per vault
(`PORTAL_VAULT_DATA/index/<uid>-<id>.db`: `notes`, `fts`, `links`, `tags`), refreshed from the
files' mtimes when a request needs it (a walk at most every 2 s, only the changed notes re-read).
Wikilinks are Obsidian's (`[[note]]`, `[[note#heading]]`, `[[note|alias]]`, `![[image.png]]`),
resolved as Obsidian does: the path as written, then with `.md`, then any note of that name
anywhere in the vault; tags are `#word`. The index is a cache: deleting it costs one walk.

## Units, settings

| | |
|---|---|
| `PORTAL_VAULT_DB` | the registry, `/var/lib/<name>-vault/vault.db` (0600) |
| `PORTAL_VAULT_DATA` | the index files, `/var/lib/<name>-vault/` |
| `PORTAL_VAULT_ROOTS` | where a vault may be registered from (above) |
| `PORTAL_VAULT_STAGE` | the stage root, `/run/<name>-vault-mounts` (set in the unit) |

`deploy/templates/vault.service` (`uvicorn portal.vault:create_app --factory --fd 3`, no keytab, no
secret: the SSO's token for the audience `vault`), `vault.env` (made once, never overwritten),
`vault-mounts.service/.path/.timer`; `portal/deploy.py` installs and enables them with the rest.
The site file declares the app (`[[app]] id = "vault"`, title `노트`, `audience = "vault"`, route
`/vault/api/` with a 5 MB body, pages `/vault` and `/vault/`, widgets `recent` and `home` 2x2).
`tests/portal/test_vault.py` covers the paths, the tree, If-Match, trash, search, links and
backlinks, and the staged-path rule.

## What comes next

A project's vault (a directory of the project's storage): the registry gains `kind = group` and the
reconciler stages for the group's members, once the provisioner (docs/projects.md) makes the
project's storage root. Git history of a vault, and the handbook's `files` reaching a vault through
the policy mounts, are named there too. The Home widget renders markdown without the page's
mathematics (that module is heavier than a widget should be): a formula shows as written there.
