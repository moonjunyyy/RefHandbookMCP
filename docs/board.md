# The public board

The board is the one place where the site's people meet what others made: the administrators'
notices, the agents' presets and the sandbox layers people share, and the projects one has not
joined yet. It is an app of the catalog (`[[app]] id = "board"`, on by default so the notices reach
everyone), a page of the pages app (`/board`, `web/src/pages/board.ts`), a widget for the main page
(`news`, `web/widgets/board.ts`), and an API of the handbook's (`/board/api/v1`,
`src/refhandbook/board_api.py`) over one file of the server's (`<data>/board.db`,
`src/refhandbook/board.py`).

## What is here

**A share** is a copy of something of one person's that others may take:

- *a preset* — the agents' flow: its blocks with their commands and models, its arrows, the run's
  limits and its input. Each block's key is reduced to its provider (`anthropic/main` travels as
  `anthropic`): a person's keys never leave their store.
- *a layer* — the sandbox's: its build script, the shared layers it stands on, its env and what it
  is for. Only a layer that stands on the server's shared layers (`sys:`) travels; one built on a
  person's own layers names them and stays home (the share dialog shows why).

A share is a snapshot taken when it is shared. What the author changes afterwards reaches the board
when they share it again: the same share, its version up by one. Taking a share (*import*) copies it
into the taker's own store under a name they choose:

- a preset's blocks are put on the taker's own key of the same provider (the first one they
  registered); a taker with no key of a provider is told which to register first. Its sandbox
  policy is theirs when they hold one of that name, otherwise their default.
- a layer is recorded as the taker's and built again in their sandbox, under their default policy;
  a build that needs more waits for them as any widening does.

The board counts how many times a share was taken.

**A notice** is the administrators' word to everyone: a title and a body in Markdown (rendered
without HTML), pinned or not. Pinned notices come first, then the newest.

**The projects** are the account service's (`/account/api/v1/projects`): the board lists the ones
the viewer is not in and that are not archived, each linking to its page, where one joins.

## Who does what

| | reads | shares, shares again, takes down | hides, shows | writes notices |
|---|---|---|---|---|
| anyone signed in | every share not hidden, every notice | their own | — | — |
| an administrator | every share | any (takes down) | any, with the reason | yes |

An administrator is a member of the site's administrators' group (the site file's `admin_group`,
given to the handbook as `RHB_ADMIN_GROUP` by its unit; membership is read from the system's
accounts). A hidden share disappears for everyone but its author and the administrators; its author
sees the reason. Taking down removes the share from the board; the copies people already took stay
theirs.

## What is not here

No comment, no reply, no post of one's own besides a share of one's own preset or layer, no
messages between people. The board is not a bulletin board: those features wait for a review of the
law that would govern them (telecommunications and e-commerce). Adding one is a decision, not an
extension.

## The limits

Declared once, in `board.py`, and read by the page through `GET /` (`limits`):

| | |
|---|---|
| `KINDS` | what may be shared: `preset`, `layer` |
| `TITLE_MAX` | a share's or a notice's title: 80 characters |
| `ABOUT_MAX` | a share's line, and the reason for hiding one: 240 |
| `NOTICE_MAX` | a notice's body: 4000 |
| `PAYLOAD_MAX` | the copy a share carries: 256 KB |
| `SHARES_PER_AUTHOR` | 100 |

## The API

Behind the site sign-in like the agents' API (nginx asks the sign-in for a token for the audience
`refhandbook`; a 401 is answered as JSON). A write needs the pages' header (`X-Requested-With`) and
the site's origin. Errors are `{error: {code, message}}`, the message in the request's language.

| | |
|---|---|
| `GET /` | `{me: {uid, admin}, kinds, limits, shares, notices}` — what the viewer sees |
| `GET /mine` | what the viewer could share: `{preset: [...], layer: [...]}`, each `{name, title, why}` (`why`: why it cannot travel, or empty) |
| `GET /shares/{id}` | one share with its copy (`payload`) |
| `POST /shares` | `{kind, name, title?, about?}`: share one's own (again: a new version) |
| `DELETE /shares/{id}` | its author, or an administrator |
| `POST /shares/{id}/import` | `{as}`: take it into one's own store under that name (409: the name is taken, or a key is missing) |
| `POST /shares/{id}/hide` | `{why}`: an administrator |
| `POST /shares/{id}/show` | an administrator |
| `POST /notices` | `{title, body, pinned?}`: an administrator |
| `PATCH /notices/{id}` | `{title?, body?, pinned?}`: an administrator |
| `DELETE /notices/{id}` | an administrator |

## The page

`/board`: a search and the actions (share; write a notice, for an administrator) on one row, then
chips — all, notices, each kind the board names, projects — that narrow the page to one view; the
view and the search stay in the address (`?view=preset&q=…`). A share's card says its kind, author,
version, how often it was taken and when; its title opens what it carries (a preset's blocks drawn
as the presets page draws them, each block's command, the limits; a layer's base, env and script),
and *take* asks for the name. The author's menu shares again or takes down; an administrator's
hides (with the reason), shows, takes down; a notice's menu, for an administrator, edits, pins and
deletes.

The widget (`news`) shows how many notices and shares there are, the notices (pinned first) and the
shares made last, each opening the board in its view.

## Tests

`tests/refhandbook/test_board.py` (the API through the handbook's server: keys never travel, a
taker's own keys, a layer's parents, versions, hiding, notices, the limits) and the board's steps of
`web/e2e/e2e.js` (section m: the page, the dialogs, the menus, the widget, against the mock in
`web/e2e/mock.js`).
