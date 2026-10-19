"""The research ledger as a kernel package: its vocabulary as types and state classes, and its
obligations, turn-end blockers and integrity checks as rules.

Nothing here is Python logic about ledgers: the sections are node types, the status sets of
research.py are state classes, and every check is a Datalog rule. tests/conftest.py runs the legacy
test-suite with a differential harness that requires these rules to reproduce the legacy results
exactly (obligations, end blockers, check() messages) after every ledger write.

Node ids inside a ledger L: rows `L:<rid>`, verdict cells `L:<claim>@<config>`, configurations
`L:cfg:<name>`, documents `L:<D#>`, turns `L:turn:<n>`. Every node a rule names carries the attr
`rid` (its legacy id), so messages read exactly as before.
"""

from __future__ import annotations

from ... import research as legacy
from ..graph import Graph, encode_type

PKG = "research"

SEC_TYPE = {
    "U": "directive", "C": "criterion", "R": "reading", "S": "symbol", "A": "assumption", "Z": "unknown",
    "T": "result", "E": "object", "H": "claim", "X": "approximation", "P": "parked", "K": "plan",
}
TYPE_SEC = {t: s for s, t in SEC_TYPE.items()}
DEP_RELS = sorted(legacy.RELS)

# state classes: each is a set of status keys. The legacy sets are taken from research.py so the
# two cannot drift apart; the rest name sets research.py writes inline.
CLASSES: dict[str, set[str]] = {
    "live": set(legacy.NONTERMINAL),
    "invalidating": set(legacy.INVALIDATING),
    "finished": set(legacy.FINISHED),
    "not_basis": set(legacy.NOT_A_BASIS),
    "not_citable": set(legacy.NOT_CITABLE),
    "withdrawn": {"superseded", "refuted", "stale"},          # what a model-origin row may not rest on
    "verdict_exempt": {"superseded", "refuted", "history", "stale"},  # a main verdict need not match these
    "rejudge": {"stale", "proposed", "open"},
    "k_live": {"queued", "running", "blocked"},
    "u_open": {"active", "question"},
    "continuation": {"queued", "blocked"},
}
ALL_STATES = sorted(set().union(*legacy.ALLOWED.values(), *CLASSES.values(), legacy.VERDICTS))


def _row_states(sec: str) -> dict[str, list[str]]:
    return {s: sorted([c for c, members in CLASSES.items() if s in members]
                      + (["allowed"] if s in legacy.ALLOWED[sec] else []))
            for s in ALL_STATES}


def install(g: Graph, actor: str = "kernel") -> None:
    """Define the research vocabulary and rules (idempotent)."""
    with g.tx():
        g.define_type("ledger", "scope", actor=actor, pkg=PKG, binding="manual",
                      description="One research question: its rows, configurations, verdicts and documents.")
        g.define_type("turn", "scope", actor=actor, pkg=PKG, binding="tick",
                      description="One exchange with the user; opened by the user's message.")
        for sec, t in SEC_TYPE.items():
            g.define_type(t, "node", actor=actor, pkg=PKG, states=_row_states(sec),
                          classes=["row"] + (["premise"] if sec in "AT" else []),
                          description=f"{sec} — {legacy.SECTIONS[sec]}")
        g.define_type("verdict", "node", actor=actor, pkg=PKG,
                      states={v: sorted(c for c, m in CLASSES.items() if v in m) for v in legacy.VERDICTS},
                      description="The verdict of one claim under one configuration.")
        g.define_type("config", "node", actor=actor, pkg=PKG, description="A set of premises a claim is judged under.")
        g.define_type("document", "node", actor=actor, pkg=PKG, description="A registered document (source, deliverable, working).")
        for rel in DEP_RELS:  # in the dep namespace: dep_req, dep_sup, dep_int, dep_con, …
            g.define_type(encode_type("dep", rel), "edge", actor=actor, pkg=PKG, classes=["dep"],
                          description=f"a row rests on another ({rel})")
        for name, inverse, desc in (
            ("on", "worked_on_by", "A plan object works on these rows (where it works, not what it rests on)."),
            ("member", "member_of", "A configuration contains this premise."),
            ("of", "has_verdict", "A verdict cell judges this claim."),
            ("under", "judges", "A verdict cell is judged under this configuration."),
            ("pending_hit", "pending_from", "A change to the source still awaits a disposition of the target."),
        ):
            g.define_type(name, "edge", actor=actor, pkg=PKG, inverse=inverse, description=desc)
        g.define_rules(RULES, actor=actor)


def key(*words: str) -> str:
    """A regex for research.key(text) in words: after optional whitespace, the first run of ASCII
    letters, compared case-insensitively. Spelled with ASCII classes because `(?i)` would also fold
    Unicode letters (ſ matches s) where key() does not."""
    alts = "|".join("".join(f"[{c.upper()}{c.lower()}]" for c in w) for w in words)
    return rf"^\s*(?:{alts})(?![A-Za-z])"


def _r(id: str, phase: str, body: str, message: str = "", applies_to: str = "*", severity: str = "block") -> dict:
    return dict(id=id, phase=phase, body=body, message=message, applies_to=applies_to, severity=severity, pkg=PKG)


RULES = [
    # ── shared vocabulary ────────────────────────────────────────────────
    _r("rs_row", "derive",
       "rs_row(L, X, R, Sec) :- edge(L, contains, X), node(X, T, _), tclass(T, row), attr(X, rid, R), attr(X, sec, Sec)."),
    _r("rs_model", "derive", 'rs_model(X) :- origin(X, O), prefix(lower(O), "model").'),
    _r("rs_dep", "derive", "rs_dep(X, Rel, D) :- edge(X, Rel, D), tclass(Rel, dep)."),
    _r("rs_basis_row", "derive",
       'rs_basis_row(L, X, R) :- rs_row(L, X, R, Sec), Sec != "K", not class(X, finished), not node(X, _, stale).'),
    _r("rs_verdict", "derive",
       "rs_verdict(V, H, C, HC, CN) :- edge(L, contains, V), node(V, verdict, _), edge(V, of, H), edge(V, under, C),"
       " attr(V, claim, HC), attr(V, config, CN)."),
    _r("rs_v_ok", "derive",
       "rs_v_ok(V, H, C, HC, CN) :- rs_verdict(V, H, C, HC, CN), not node(H, missing, _), not node(C, missing, _)."),
    _r("rs_v_true", "derive", "rs_v_true(V, H, C, HC, CN) :- rs_v_ok(V, H, C, HC, CN), node(V, _, true)."),
    _r("rs_has_dep", "derive", "rs_has_dep(H) :- rs_dep(H, _, _)."),
    _r("rs_has_nonsup", "derive", "rs_has_nonsup(H) :- rs_dep(H, Rel, _), Rel != dep_sup."),
    _r("rs_member", "derive", """
        rs_member(C, M) :- edge(C, member, M).
        rs_member(C, M) :- node(C, config, _), attr(C, synthetic, 1), edge(L, contains, C), rs_row(L, M, _, "A"), node(M, _, on).
        rs_member(C, M) :- node(C, config, _), attr(C, synthetic, 1), edge(L, contains, C), rs_row(L, M, _, "T"), node(M, _, on).
    """),
    _r("rs_doc", "derive",
       "rs_doc(L, Dn, D, Role) :- edge(L, contains, Dn), node(Dn, document, _), attr(Dn, rid, D), attr(Dn, role, Role)."),
    _r("rs_doc_planned", "derive", 'rs_doc_planned(Dn) :- attr(Dn, plan, P), P != null, P != "".'),
    _r("rs_turn_ledger", "derive", "rs_turn_ledger(T, L) :- edge(L, contains, T), node(T, turn, _), node(L, ledger, _)."),
    _r("rs_has_k", "derive", 'rs_has_k(L) :- rs_row(L, _, _, "K").'),
    _r("rs_has_cont", "derive", 'rs_has_cont(L) :- rs_row(L, X, _, "K"), class(X, continuation).'),
    _r("rs_touched_u", "derive", 'rs_touched_u(T) :- edge(T, touched, X), attr(X, rid, R), prefix(R, "U").'),
    _r("rs_idle", "derive", 'rs_idle(T) :- attr(T, idle, I), I != null, I != "".'),

    # ── integrity (check): applies to the ledger; an error blocks the end of a turn inside it ──
    _r("rs_c_status", "check", "rs_c_status(R, St, Sec) :- rs_row(Self, X, R, Sec), not class(X, allowed), attr(X, status, St).",
       "{R}: status {St!r} not allowed in {Sec}", "ledger"),
    _r("rs_c_model_on", "check", 'rs_c_model_on(R) :- rs_row(Self, X, R, "A"), node(X, _, on), rs_model(X).',
       "{R}: a model premise is on the main line; only the user adopts it (then set origin to 'user(adopted, turn N)'); "
       "explore it in a named configuration instead", "ledger"),
    _r("rs_c_sourced", "check",
       f'rs_c_sourced(R) :- rs_row(Self, X, R, _), attr(X, evidence, E), match(E, "{key("sourced")}"),'
       ' not match(lower(E), "chat:|file:|https?://").',
       "{R}: 'sourced' without a locator (chat:<uuid>, file:<path>, or a URL)", "ledger"),
    _r("rs_c_recall", "check",
       r'rs_c_recall(R) :- rs_row(Self, X, R, _), attr(X, evidence, E), match(lower(E), "\brecall"),'
       r' not match(lower(E), "\[unverified\]").',
       "{R}: recall is not evidence — retrieve it (RF) or mark [unverified]", "ledger"),
    _r("rs_c_not_found", "check",
       r'rs_c_not_found(R) :- rs_row(Self, X, R, _), attr(X, evidence, E), match(lower(E), "not found:\s*($|[·;])").',
       "{R}: 'not found:' must name the calls that were made", "ledger"),
    _r("rs_c_closure", "check",
       'rs_c_closure(R) :- rs_row(Self, X, R, Sec), Sec != "K", node(X, _, proposed), rs_model(X),'
       ' attr(X, evidence, E), not match(lower(E), "closure:").',
       "{R}: model-origin proposed without 'closure: <what the user givens were checked against>'", "ledger"),
    _r("rs_w_accreting", "check", """
        rs_w_accreting(R) :- rs_row(Self, X, R, _), attr(X, evidence, E), len(E) > 240.
        rs_w_accreting(R) :- rs_row(Self, X, R, _), attr(X, evidence, E), match(E, "(?s);.*;.*;").
    """, "{R}: evidence cell is accreting; replace it with the current state (history is in the log)", "ledger", "warn"),
    _r("rs_c_missing", "check",
       "rs_c_missing(R, D) :- rs_basis_row(Self, X, R), rs_dep(X, _, Dn), node(Dn, missing, _), attr(Dn, rid, D).",
       "{R}: cites missing {D}", "ledger"),
    _r("rs_c_model_basis", "check",
       "rs_c_model_basis(R, D, O) :- rs_basis_row(Self, X, R), rs_dep(X, _, Dn), not node(Dn, missing, _),"
       " rs_model(Dn), not rs_model(X), origin(X, O), attr(Dn, rid, D).",
       "{R}: rests on model-origin {D}; a {O} row cannot (mark {R} model, or have the user adopt the premise)", "ledger"),
    _r("rs_c_bad_basis", "check", """
        rs_c_bad_basis(R, D, S) :- rs_basis_row(Self, X, R), not rs_model(X), rs_dep(X, _, Dn),
            not node(Dn, missing, _), class(Dn, not_basis), attr(Dn, rid, D), attr(Dn, status, S).
        rs_c_bad_basis(R, D, S) :- rs_basis_row(Self, X, R), rs_model(X), rs_dep(X, _, Dn),
            not node(Dn, missing, _), class(Dn, withdrawn), attr(Dn, rid, D), attr(Dn, status, S).
    """, "{R}: rests on {D} with status {S!r} — mark {R} stale or re-derive", "ledger"),
    _r("rs_c_pointer", "check",
       r'rs_c_pointer(R, D) :- rs_basis_row(Self, X, R), rs_dep(X, _, Dn), not node(Dn, missing, _),'
       f' attr(Dn, evidence, DE), match(DE, "{key("pointer")}"), attr(Dn, rid, D).',
       "{R}: rests on {D}, which is only a pointer — retrieve the original (RF)", "ledger"),
    _r("rs_w_unknown", "check",
       'rs_w_unknown(R, D) :- rs_basis_row(Self, X, R), rs_dep(X, _, Dn), not node(Dn, missing, _),'
       ' attr(Dn, rid, D), prefix(D, "Z").',
       "{R}: uses isolated unknown {D} — confirm it appears only as a symbol or gauge", "ledger", "warn"),
    _r("rs_w_int", "check",
       'rs_w_int(R, D) :- rs_basis_row(Self, X, R), edge(X, dep_int, Dn), not node(Dn, missing, _),'
       ' attr(X, evidence, E), not match(lower(E), "map"), attr(Dn, rid, D).',
       "{R}: 'int' edge to {D} without an explicit map in evidence", "ledger", "warn"),
    _r("rs_w_unverified", "check",
       r'rs_w_unverified(R, E, D) :- rs_basis_row(Self, X, R), rs_dep(X, _, Dn), not node(Dn, missing, _),'
       r' attr(Dn, evidence, DE), match(DE, "(?i)^\s*\[?unverified\b"), attr(X, evidence, E),'
       f' match(E, "{key("computed", "followed", "sourced")}"), attr(Dn, rid, D).',
       "{R}: evidence {E!r} rests on [unverified] {D}; the conclusion is at most [unverified]", "ledger", "warn"),
    _r("rs_w_open", "check",
       'rs_w_open(R, N) :- rs_row(Self, X, R, "H"), node(X, _, open), attr(Self, turn, LT), attr(X, turn_created, TC),'
       ' N = LT - TC, N >= 3, attr(X, evidence, E), not match(lower(E), "tried:|not found:").',
       "{R}: open for {N} turns with no recorded attempt", "ledger", "warn"),
    _r("rs_c_v_unknown", "check", """
        rs_c_v_unknown(HC, CN) :- rs_verdict(V, H, C, HC, CN), edge(Self, contains, V), node(H, missing, _).
        rs_c_v_unknown(HC, CN) :- rs_verdict(V, H, C, HC, CN), edge(Self, contains, V), node(C, missing, _).
    """, "verdict {HC}@{CN}: unknown claim or configuration", "ledger"),
    _r("rs_c_sup_only", "check",
       "rs_c_sup_only(HC, CN) :- rs_v_true(V, H, C, HC, CN), edge(Self, contains, V), rs_has_dep(H), not rs_has_nonsup(H).",
       "{HC}@{CN}: true on 'sup' edges only — supports is evidence, not proof", "ledger"),
    _r("rs_c_external", "check",
       'rs_c_external(HC, CN, D) :- rs_v_true(V, H, C, HC, CN), edge(Self, contains, V), rs_dep(H, _, Dn),'
       ' attr(Dn, rid, D), prefix(D, "T"), not rs_member(C, Dn).',
       "{HC}@{CN}: true, but rests on external result {D}, which is not in configuration {CN!r}", "ledger"),
    _r("rs_c_contradicts", "check",
       "rs_c_contradicts(HC, D, CN) :- rs_v_true(V, H, C, HC, CN), edge(Self, contains, V), edge(H, dep_con, Dn),"
       " not node(Dn, missing, _), attr(Dn, rid, D), edge(W, of, Dn), edge(W, under, C), node(W, verdict, true).",
       "{HC} contradicts {D}, both true under {CN!r}", "ledger"),
    _r("rs_c_main_status", "check",
       'rs_c_main_status(HC, S, VV) :- rs_v_ok(V, H, C, HC, "main"), edge(Self, contains, V), node(V, _, VV),'
       " node(H, _, HK), HK != VV, not class(H, verdict_exempt), attr(H, status, S).",
       "{HC}: status {S!r} disagrees with its main verdict {VV!r}", "ledger"),
    _r("rs_c_cfg_missing", "check",
       "rs_c_cfg_missing(CN, M) :- edge(Self, contains, C), node(C, config, _), attr(C, name, CN),"
       " edge(C, member, Mn), node(Mn, missing, _), attr(Mn, rid, M).",
       "configuration {CN}: member {M} missing", "ledger"),

    # ── obligations: what a turn starts from (research_begin's OBLIGATIONS) ──
    _r("rs_o_pending", "obligation",
       "rs_o_pending(Hit, Src) :- edge(Self, contains, S), edge(S, pending_hit, Hn), attr(S, rid, Src), attr(Hn, rid, Hit).",
       "PENDING {Hit} (from {Src}): dispose", "ledger", "info"),
    _r("rs_o_k", "obligation", 'rs_o_k(R) :- rs_row(Self, X, R, "K"), class(X, k_live).',
       "K {R} is queued, running or awaiting the user", "ledger", "info"),
    _r("rs_o_directive", "obligation", 'rs_o_directive(R) :- rs_row(Self, X, R, "U"), class(X, u_open).',
       "DIRECTIVE {R}: address it, or carry with a reason", "ledger", "info"),
    _r("rs_o_rejudge", "obligation",
       'rs_o_rejudge(R) :- rs_row(Self, X, R, Sec), Sec != "K", Sec != "U", class(X, rejudge).',
       "{R}: re-judge", "ledger", "info"),
    _r("rs_o_stale_verdict", "obligation",
       "rs_o_stale_verdict(R) :- edge(Self, contains, V), node(V, verdict, stale), attr(V, rid, R).",
       "STALE {R}: recheck the verdict", "ledger", "info"),
    _r("rs_o_doc_plan", "obligation", 'rs_o_doc_plan(D) :- rs_doc(Self, Dn, D, "deliverable"), rs_doc_planned(Dn).',
       "DOC-PLAN {D}: planned changes not synced", "ledger", "info"),
    _r("rs_o_doc_behind", "obligation", """
        rs_o_doc_behind(D) :- rs_doc(Self, Dn, D, "deliverable"), not rs_doc_planned(Dn), attr(Dn, sync_clock, C),
            C != 0, rs_row(Self, X, _, Sec), Sec != "K", attr(X, clock, K), K > C.
        rs_o_doc_behind(D) :- rs_doc(Self, Dn, D, "deliverable"), not rs_doc_planned(Dn), attr(Dn, sync_clock, C),
            C != 0, edge(Self, contains, V), node(V, verdict, _), attr(V, clock, K), K > C.
    """, "DOC {D}: the ledger changed since its sync — plan before the next edit", "ledger", "info"),

    # ── the end of a turn (research_end); check errors of the ledger block it too ──
    _r("rs_b_pending", "close",
       "rs_b_pending(Hit, Src) :- rs_turn_ledger(Self, L), edge(L, contains, S), edge(S, pending_hit, Hn),"
       " attr(S, rid, Src), attr(Hn, rid, Hit).",
       "PENDING {Hit} (from {Src})", "turn"),
    _r("rs_b_running", "close", 'rs_b_running(R) :- rs_turn_ledger(Self, L), rs_row(L, X, R, "K"), node(X, _, running).',
       "K {R} is still running: finish its card with research_done", "turn"),
    _r("rs_b_no_continuation", "close",
       "rs_b_no_continuation(L) :- rs_turn_ledger(Self, L), rs_has_k(L), not rs_has_cont(L).",
       "NO CONTINUATION: push the next K (a queued step, or @USER awaiting the user) before ending", "turn"),
    _r("rs_b_directive", "close",
       'rs_b_directive(R) :- rs_turn_ledger(Self, L), rs_row(L, X, R, "U"), class(X, u_open),'
       " not edge(Self, touched, X), not edge(Self, carry, X).",
       "DIRECTIVE {R} neither addressed (set) nor carried", "turn"),
    _r("rs_b_no_directive", "close", "rs_b_no_directive(Self) :- not rs_touched_u(Self), not rs_idle(Self).",
       'NO DIRECTIVE this turn: register or update the user\'s message as U, or end with idle="<why nothing was asked>"',
       "turn"),
    _r("rs_b_doc_plan", "close",
       "rs_b_doc_plan(D) :- rs_turn_ledger(Self, L), rs_doc(L, Dn, D, _), attr(Dn, plan, P), P != null.",
       "DOC-PLAN {D} committed but not synced", "turn"),
]
