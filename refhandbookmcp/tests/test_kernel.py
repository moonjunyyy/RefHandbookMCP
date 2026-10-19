"""The kernel on its own: graph writes, authority, the rule language, and scope gates."""

import sqlite3

import pytest

from refhandbook.kernel import (Conflict, Forbidden, Graph, KernelError, Program, ScopeRefused, carry, close,
                                detach, evaluate, findings, open_scope, parse, touch)


@pytest.fixture
def g():
    g = Graph(sqlite3.connect(":memory:"))
    with g.tx():
        g.define_type("task", "scope", actor="kernel")
        g.define_type("item", "node", actor="kernel", classes=["row"],
                      states={"todo": ["live"], "done": ["finished"], "dropped": ["finished"]},
                      transitions=[("todo", "done", "any"), ("todo", "dropped", "user")])
        g.define_type("needs", "edge", actor="kernel", inverse="needed_by", classes=["dep"])
    return g


def item(g, i, state="todo", **attrs):
    g.put_node(i, "item", actor="model", state=state, attrs=attrs)


# ── graph ────────────────────────────────────────────────────────────────

def test_compare_and_swap(g):
    item(g, "a")
    v = g.node("a")["version"]
    g.update_node("a", actor="model", expect=v, attrs={"x": 1})
    with pytest.raises(Conflict, match="version 2, not 1"):
        g.update_node("a", actor="model", expect=v, attrs={"x": 2})
    assert g.node("a")["attrs"] == {"x": 1}


def test_attr_merge_removes_only_keys_passed_as_none(g):
    g.put_node("a", "item", actor="kernel", state="todo", attrs={"keep": None, "drop": 1, "x": 0})
    g.update_node("a", actor="model", attrs={"drop": None, "x": 2})
    assert g.node("a")["attrs"] == {"keep": None, "x": 2}


def test_transitions_say_who(g):
    item(g, "a")
    item(g, "b")
    with pytest.raises(Forbidden, match="model may not move"):
        g.update_node("a", actor="model", state="dropped")
    g.update_node("a", actor="user", state="dropped")
    g.update_node("b", actor="model", state="done")
    with pytest.raises(KernelError, match="not a state"):
        g.update_node("b", actor="kernel", state="lost")


def test_model_proposes_and_only_the_user_seals(g):
    g.define_type("note", "node", actor="model")
    assert g.get_type("note")["authority"] == "proposed"
    with pytest.raises(Forbidden, match="only the user approves"):
        g.approve("type", "note", actor="model")
    g.approve("type", "note", actor="user")
    with pytest.raises(Forbidden, match="sealed"):
        g.define_type("note", "node", actor="model", description="changed")
    with pytest.raises(Forbidden, match="kernel"):
        g.define_type("contains", "edge", actor="user")


# ── rules ────────────────────────────────────────────────────────────────

def test_parse_strings_keep_regex_backslashes():
    (c,) = parse(r'p(X) :- attr(X, e, E), match(E, "\brecall"), E != "a \"q\"".')
    builtin = c.body[1].atom
    assert builtin.args[1].value == r"\brecall"
    assert c.body[2].right.value == 'a "q"'


@pytest.mark.parametrize("body, err", [
    ("p(X) :- not node(X, item, _).", "unsafe"),
    ("p(X, Y) :- node(X, _, _).", "head variable Y"),
    ("p(X) :- node(X, _, _), not q(X). q(X) :- node(X, _, _), not p(X).", "not stratified"),
    ("p(X) :- r(X).", "no rule defines"),
    ("p(X) :- node(X, _).", "takes 3"),
    ("node(X) :- p(X).", "built in"),
])
def test_program_checks(body, err):
    with pytest.raises(KernelError, match=err):
        Program(parse(body))


def test_recursion_negation_builtins_and_arithmetic(g):
    with g.tx():
        open_scope(g, "t", "task", actor="kernel")
        for i, n in (("a", 1), ("b", 2), ("c", 3), ("d", 10)):
            item(g, i, n=n, ev="computed" if i != "c" else "recall of a talk")
            g.link("t", "contains", i, actor="kernel")
        g.link("a", "needs", "b", actor="kernel")
        g.link("b", "needs", "c", actor="kernel")
    g.define_rules([
        dict(id="reach", phase="derive", body="reach(X, Y) :- edge(X, T, Y), tclass(T, dep). "
                                              "reach(X, Z) :- reach(X, Y), reach(Y, Z)."),
        dict(id="leaf_dep", phase="check", applies_to="task", severity="warn", message="{X} rests on {Y}",
             body="leaf_dep(X, Y) :- edge(Self, contains, X), reach(X, Y), not reach(Y, _)."),
        dict(id="recall", phase="check", applies_to="task", message="{X}: {E!r}",
             body='recall(X, E) :- edge(Self, contains, X), attr(X, ev, E), match(E, "(?i)\\brecall").'),
        dict(id="gap", phase="check", applies_to="task", severity="info", message="{X} {N}",
             body="gap(X, N) :- edge(Self, contains, X), attr(X, n, K), N = K - 1, N >= 5."),
    ], actor="kernel")
    fs = {f.rule: f.message for f in evaluate(g, "check", "t", "task") if f.rule != "leaf_dep"}
    warn = sorted(f.message for f in evaluate(g, "check", "t", "task") if f.rule == "leaf_dep")
    assert warn == ["a rests on c", "b rests on c"]
    assert fs == {"recall": "c: 'recall of a talk'", "gap": "d 9"}


def test_proposed_rules_never_block(g):
    open_scope(g, "t", "task", actor="kernel")
    item(g, "a")
    g.link("t", "contains", "a", actor="kernel")
    g.define_rule("open_items", "close", "open_items(X) :- edge(Self, contains, X), class(X, live).",
                  actor="model", applies_to="task", message="{X} is still open")
    (f,) = findings(g, "t")
    assert (f.severity, f.proposed) == ("warn", True)
    close(g, "t", actor="model")  # a model's rule is advice, not a gate
    assert g.node("t")["state"] == "closed"


def test_sealed_rule_blocks_and_is_not_the_models_to_change(g):
    open_scope(g, "t", "task", actor="kernel")
    item(g, "a")
    g.link("t", "contains", "a", actor="kernel")
    g.define_rule("open_items", "close", "open_items(X) :- edge(Self, contains, X), class(X, live).",
                  actor="user", applies_to="task", message="{X} is still open")
    with pytest.raises(ScopeRefused, match="a is still open"):
        close(g, "t", actor="model")
    with pytest.raises(Forbidden):
        g.retire_rule("open_items", actor="model")
    with pytest.raises(Forbidden):
        g.define_rule("open_items", "close", "open_items(X) :- edge(Self, contains, X), node(X, item, nope).",
                      actor="model", applies_to="task", message="{X}")
    g.update_node("a", actor="model", state="done")
    close(g, "t", actor="model")


def test_message_fields_must_be_head_variables(g):
    with pytest.raises(KernelError, match=r"\{Y\} is not a head variable"):
        g.define_rule("r", "check", "r(X) :- node(X, _, _).", actor="kernel", message="{Y}")


def test_a_rule_others_use_cannot_be_retired(g):
    g.define_rules([dict(id="base", phase="derive", body="base(X) :- node(X, item, _)."),
                    dict(id="uses", phase="check", message="{X}", body="uses(X) :- base(X).")], actor="kernel")
    with pytest.raises(KernelError, match="used by uses"):
        g.retire_rule("base", actor="kernel")


# ── scopes ───────────────────────────────────────────────────────────────

def test_children_hold_a_scope_open_until_closed_carried_or_detached(g):
    open_scope(g, "goal", "task", actor="kernel")
    open_scope(g, "turn", "task", actor="kernel", parent_id="goal")
    open_scope(g, "job", "task", actor="kernel", parent_id="turn")
    with pytest.raises(ScopeRefused, match="child scope job"):
        close(g, "turn", actor="model")
    detach(g, "job", "goal", actor="model")
    close(g, "turn", actor="model")  # the turn is free; the goal now holds the job
    with pytest.raises(ScopeRefused, match="child scope job"):
        close(g, "goal", actor="model")
    carry(g, "goal", "job", "runs overnight", actor="model")
    close(g, "goal", actor="model")


def test_detach_only_outward(g):
    open_scope(g, "a", "task", actor="kernel")
    open_scope(g, "b", "task", actor="kernel", parent_id="a")
    open_scope(g, "c", "task", actor="kernel", parent_id="b")
    open_scope(g, "x", "task", actor="kernel")
    with pytest.raises(Forbidden, match="outward"):
        detach(g, "c", "x", actor="model")


def test_enclosing_check_errors_block_a_close(g):
    open_scope(g, "goal", "task", actor="kernel")
    open_scope(g, "turn", "task", actor="kernel", parent_id="goal")
    item(g, "a", ev="recall")
    g.link("goal", "contains", "a", actor="kernel")
    g.define_rule("recall", "check", 'recall(X) :- edge(Self, contains, X), attr(X, ev, E), match(E, "recall").',
                  actor="kernel", applies_to="task", message="{X}: recall is not evidence")
    with pytest.raises(ScopeRefused, match="a: recall is not evidence"):
        close(g, "turn", actor="model")


def test_pre_rules_gate_opening_and_roll_back(g):
    g.define_rule("needs_parent", "pre", "needs_parent(Self) :- not edge(_, contains, Self).",
                  actor="kernel", applies_to="task", message="a task opens inside another")
    with pytest.raises(ScopeRefused, match="opens inside another"):
        open_scope(g, "lone", "task", actor="model")
    assert g.get_node("lone") is None


def test_touch_records_an_edge(g):
    open_scope(g, "t", "task", actor="kernel")
    item(g, "a")
    touch(g, "t", "a", actor="model")
    assert [e["dst"] for e in g.edges(src="t", type_="touched")] == ["a"]
