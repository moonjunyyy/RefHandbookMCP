# PAGE REF-READER — Reader rules for a deliverable
KIND: reference
TAGS: research, reference
TRIGGERS: reader rules; reader lint; deliverable prose; section marker; status in words; ledger artefacts in the text; open problems section
OBJECTIVE: The rules the visible text of a deliverable document follows, including how a status is said in words.

Consulted from a card step; return to that step. Not a procedure: it consumes no K.

- Write for a reader. Use prose in the user's language and LaTeX for
  mathematics. Organize by concept, merging what belongs together; never by
  turn order.
- Follow each `##` heading, on the next line, with a hidden marker
  `<!-- sec:s3 basis: E2 A4 H1 -->`. Ledger ids appear only there.
- The visible text carries no ledger artefacts: no ids in brackets, basis
  tags, tokens, plan objects, card references, or status codes.
- Say status in words:
  - computed → "checked by symbolic computation" (기호 계산으로 확인);
  - measured → "measured numerically over <range>" (수치로 확인);
  - sourced → "from <source>" (출처 확인);
  - followed → "reproduced step by step" (단계 재현);
  - unverified → "not yet verified" (미검증);
  - an exploration verdict → "under the alternative premise …"
    (다른 가정 … 아래에서는).
- Give open problems a section of their own. History stays in the ledger, not
  in the body.
