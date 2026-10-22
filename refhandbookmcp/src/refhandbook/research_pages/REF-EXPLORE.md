# PAGE REF-EXPLORE — Exploration
KIND: reference
TAGS: research, reference
TRIGGERS: exploration; explore a premise; exploration verdict; named configuration; main line; switch premises; model premise; taint; taint propagates; user row on a model row; adopt a premise
OBJECTIVE: How exploration works next to the main line: whose configurations are whose, how model taint propagates, and how exploration verdicts are reported.

Consulted when exploring premises in named configurations, or when reporting a
verdict from one; return to the step that sent you.

**Exploration.** Every verdict sits in a claim × configuration cell.
- `main` is the user's line: the `A` and `T` rows that are `on`.
- Named configurations are the model's to define freely. They may switch
  premises on or off, swap alternatives, and include model premises.
- Taint propagates. A row built on a model row is itself `model`. A `user` or
  `entailed` row that rests on a model row is an error.
- An exploration verdict is reported with its configuration, and never stands
  in for the main line.
- Only the user adopts a premise into the main line.
