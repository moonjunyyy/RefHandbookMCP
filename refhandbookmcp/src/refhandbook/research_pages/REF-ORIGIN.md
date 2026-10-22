# PAGE REF-ORIGIN — The origin of an item
KIND: reference
TAGS: research, reference
TRIGGERS: origin; origin of an item; user origin; entailed; entailed(<step>); model origin; minimal reading; adopt a model item; adoption; user(adopted); content cell; notes in the evidence cell
OBJECTIVE: The three origins an item can have, what happens to a model item until and on its adoption, and what a content cell may hold.

Consulted when assigning or checking an item's origin, or when the user adopts a
model item; return to the step that sent you.

**Origin** of an item:

- **user**: the user's words, or the same content restated in symbols with
  no structure added (the minimal reading);
- **entailed(<step>)**: follows from user items by a cited step, including
  premises presupposed by a definition the user gave;
- **model**: everything else, such as a larger reading, an added premise, a
  frame, an intermediate object, or a special case.

A model item stays out of the main line until the user adopts it. It may be
used inside named exploration configurations meanwhile, and anything built on
it is `model` too. On adoption, `set` its origin to `user(adopted, session N)`.
Content cells hold only the user's words for user items; notes go in the
evidence cell.
