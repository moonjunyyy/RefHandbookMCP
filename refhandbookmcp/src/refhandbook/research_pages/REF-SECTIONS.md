# PAGE REF-SECTIONS — Ledger rows: columns, ids, sections, statuses
KIND: reference
TAGS: research, reference
TRIGGERS: ledger format; row columns; row id; section letter; section letters; status vocabulary; allowed status; which section holds; map M
OBJECTIVE: The columns of a ledger row, how ids are formed, which section letter holds what with which statuses, and the map M.

Consulted when writing or reading a ledger row, its id, its section or its
status; return to the step that sent you.

**Sections.** Each row has the columns `id · content · origin · status ·
evidence · dep`. Ids are the section letter plus a number, assigned by the
device.

| letter | holds | allowed status |
|---|---|---|
| U | directives and questions | active · question · answered · done · blocked · superseded |
| C | judgment criteria | mandatory · free · superseded |
| R | readings of the user's terms | confirmed · proposed · superseded · refuted |
| S | symbols | confirmed · proposed · superseded |
| A | assumptions (`grp` marks alternatives) | on · off · proposed · superseded · stale |
| Z | isolated unknowns | isolated · superseded |
| T | known results | on · proposed · superseded · refuted · stale |
| E | objects and structures | established · open · proposed · superseded · stale · history |
| H | claims (status = main-line verdict) | open · true · false · undecided · supports · contradicts · inconclusive · superseded · refuted · stale · history · proposed |
| X | approximations | on · off · proposed · superseded · stale |
| P | parked byproducts | parked · superseded |
| K | plan objects | queued · running · blocked (user) · done · dropped · superseded · stale |

The map `M` is free text, replaced whole with `research_set(id="M")`.
