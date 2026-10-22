# PAGE N4-SOURCE — Source documents: check before relying
KIND: checklist
TAGS: research, normal
TRIGGERS: user file; source document; rely on a user file; check the source; original changed; source edited; hash mismatch; restore the original
OBJECTIVE: Keep the user's originals untouched: check a source document before relying on it, and move any edit into a working copy.

ENTRY — object: a K @N4-SOURCE on a source document (D#) the work is about to
rely on.

1. Call `research_doc(action="check", doc, text)` before relying on a source
   document.
2. If it has changed, report the change, restore the original, and move the
   edit into a working copy (card REF-DOC-ROLES).

**EXITS** (each exit returns objects; `<caller>` = the page of the K that routed here)

- **a**: the source document is unchanged → push `resume <caller move> on D#` @<caller>
- **d**: a source document changed → push `report the edit to the user` @USER
