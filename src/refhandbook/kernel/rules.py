"""The rule language: a Datalog fragment over the kernel graph, evaluated in SQLite.

    rests_on_bad(R, D, S) :- basis_row(X, R), dep(X, _, D0), class(D0, not_basis),
                             attr(D0, rid, D), attr(D0, status, S).

Terms
    Variables are capitalised (X, Rid). `_` is anonymous. `Self` is the scope being evaluated.
    Constants are lowercase identifiers (on, deliverable), "quoted strings", numbers, or null.
    In a string, \\" and \\\\ are escapes; any other backslash is kept, so regexes read as written.

Body literals
    graph atoms   node(Id, Type, State)   class(Id, Class)    tclass(Type, Class)
                  edge(Src, Type, Dst)    attr(Id, Key, Value) origin(Id, Origin)
                  content(Id, Text)       state_decl(Type, State)
    derived atoms any predicate another clause defines
    negation      not <atom>  ·  not match(...)  ·  not prefix(...)
    builtins      match(E, "regex")  (Python re.search; false on null)   prefix(E, E2)  (false on null)
    functions     len(E)   lower(E)  (Python str.lower)
    comparisons   = and != are null-safe equality (null = null holds). < <= > >= hold only between
                  two numbers (a text value is never ordered against a number). + and - on numbers.
                  `V = expr` with V not yet bound binds V.
    authorship    author(Id, A): who actually wrote the node (kernel | user | model), set by the
                  kernel; origin(Id, O) is the provenance the row claims.
    classes       class/tclass see only the classes of types that are not proposed: a model's new
                  vocabulary cannot change what a sealed rule quantifies over.

Safety and evaluation
    Every head variable, and every variable in a negation, builtin or comparison, must be bound by a
    positive atom (or by a binding comparison). Negation must be stratified: no predicate depends
    negatively on itself through a cycle. Each stratum is evaluated to its fixpoint, in SQL.
"""

from __future__ import annotations

import hashlib
import itertools
import math
import re
import string
from dataclasses import dataclass, field
from typing import Any

from .graph import KernelError

# ── syntax ───────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Var:
    name: str


@dataclass(frozen=True)
class Const:
    value: Any


@dataclass(frozen=True)
class SelfRef:
    pass


@dataclass(frozen=True)
class Anon:
    pass


@dataclass(frozen=True)
class Arith:
    op: str
    left: Any
    right: Any


@dataclass(frozen=True)
class Func:
    name: str
    arg: Any


@dataclass(frozen=True)
class Atom:
    pred: str
    args: tuple[Any, ...]


@dataclass(frozen=True)
class Literal:
    kind: str  # pos | neg | builtin | cmp
    atom: Atom | None = None
    negated: bool = False
    op: str = ""
    left: Any = None
    right: Any = None


@dataclass
class Clause:
    head: Atom
    body: list[Literal] = field(default_factory=list)
    text: str = ""


EDB_ARITY = {"node": 3, "class": 2, "tclass": 2, "edge": 3, "attr": 3, "origin": 2, "author": 2, "content": 2,
             "state_decl": 2}
BUILTINS = {"match": 2, "prefix": 2}
FUNCS = {"len", "lower"}
INT_LIMIT = 2 ** 63
RESERVED = set(EDB_ARITY) | set(BUILTINS) | FUNCS | {"not", "null", "Self"}

TOKEN = re.compile(r"""
    (?P<ws>\s+|%[^\n]*)
  | (?P<str>"(?:[^"\\]|\\.)*")
  | (?P<num>\d+(?:\.\d+)?(?![A-Za-z_]))
  | (?P<op>:-|!=|<=|>=|=|<|>|\(|\)|,|\.|\+|-)
  | (?P<id>[A-Za-z_][A-Za-z0-9_]*)
""", re.X)


def _tokens(text: str) -> list[tuple[str, str, int]]:
    out, pos = [], 0
    while pos < len(text):
        m = TOKEN.match(text, pos)
        if not m:
            raise KernelError(f"rule syntax: unexpected {text[pos:pos + 20]!r} at offset {pos}")
        kind = m.lastgroup
        if kind != "ws":
            out.append((kind, m.group(), pos))  # type: ignore[arg-type]
        pos = m.end()
    return out


def _unquote(s: str) -> str:
    body = re.sub(r'\\(["\\])', r"\1", s[1:-1])
    if "\x00" in body:
        raise KernelError("rule syntax: a string may not contain a NUL character")
    return body


class _Parser:
    def __init__(self, text: str):
        self.text = text
        self.toks = _tokens(text)
        self.i = 0

    def peek(self, k: int = 0) -> tuple[str, str, int] | None:
        j = self.i + k
        return self.toks[j] if j < len(self.toks) else None

    def take(self, value: str | None = None, kind: str | None = None) -> tuple[str, str, int]:
        t = self.peek()
        if t is None:
            raise KernelError(f"rule syntax: unexpected end; expected {value or kind}")
        if (value is not None and t[1] != value) or (kind is not None and t[0] != kind):
            raise KernelError(f"rule syntax: expected {value or kind} at offset {t[2]}, found {t[1]!r}")
        self.i += 1
        return t

    def program(self) -> list[Clause]:
        out = []
        while self.peek() is not None:
            start = self.peek()[2]  # type: ignore[index]
            out.append(self.clause())
            end = self.toks[self.i - 1][2] + 1
            out[-1].text = self.text[start:end].strip()
        if not out:
            raise KernelError("rule syntax: no clauses")
        return out

    def clause(self) -> Clause:
        head = self.atom(head=True)
        body: list[Literal] = []
        if self.peek() and self.peek()[1] == ":-":  # type: ignore[index]
            self.take(":-")
            body.append(self.literal())
            while self.peek() and self.peek()[1] == ",":  # type: ignore[index]
                self.take(",")
                body.append(self.literal())
        self.take(".")
        return Clause(head, body)

    def atom(self, head: bool = False) -> Atom:
        name = self.take(kind="id")[1]
        if not re.match(r"^[a-z_][a-z0-9_]*$", name):
            raise KernelError(f"rule syntax: predicate {name!r} must be lowercase")
        if head and name in RESERVED:
            raise KernelError(f"rule syntax: {name!r} is built in and cannot be defined")
        self.take("(")
        args = [self.term()]
        while self.peek() and self.peek()[1] == ",":  # type: ignore[index]
            self.take(",")
            args.append(self.term())
        self.take(")")
        return Atom(name, tuple(args))

    def term(self) -> Any:
        t = self.peek()
        if t is None:
            raise KernelError("rule syntax: unexpected end in a term")
        kind, val, _ = t
        if kind == "str":
            self.i += 1
            return Const(_unquote(val))
        if kind == "num":
            self.i += 1
            v = float(val) if "." in val else int(val)
            if (isinstance(v, float) and not math.isfinite(v)) or (isinstance(v, int) and abs(v) >= INT_LIMIT):
                raise KernelError(f"rule syntax: number {val} is out of range")
            return Const(v)
        if kind == "id":
            self.i += 1
            if val == "_":
                return Anon()
            if val == "Self":
                return SelfRef()
            if val == "null":
                return Const(None)
            if val[0].isupper() or val[0] == "_":
                return Var(val)
            return Const(val)
        raise KernelError(f"rule syntax: expected a term at offset {t[2]}, found {val!r}")

    def expr(self) -> Any:
        left = self.operand()
        while self.peek() and self.peek()[1] in ("+", "-"):  # type: ignore[index]
            op = self.take()[1]
            left = Arith(op, left, self.operand())
        return left

    def operand(self) -> Any:
        t = self.peek()
        if t and t[0] == "id" and t[1] in FUNCS and self.peek(1) and self.peek(1)[1] == "(":  # type: ignore[index]
            name = self.take()[1]
            self.take("(")
            arg = self.expr()
            self.take(")")
            return Func(name, arg)
        if t and t[1] == "(":
            self.take("(")
            e = self.expr()
            self.take(")")
            return e
        return self.term()

    def literal(self) -> Literal:
        negated = False
        if self.peek() and self.peek()[1] == "not":  # type: ignore[index]
            self.take("not")
            negated = True
        t, n = self.peek(), self.peek(1)
        if t and t[0] == "id" and t[1] in BUILTINS and n and n[1] == "(":
            name = self.take()[1]
            self.take("(")
            args = [self.expr()]
            while self.peek() and self.peek()[1] == ",":  # type: ignore[index]
                self.take(",")
                args.append(self.expr())
            self.take(")")
            if len(args) != BUILTINS[name]:
                raise KernelError(f"{name} takes {BUILTINS[name]} arguments")
            if name == "match":
                pat = args[1]
                if not (isinstance(pat, Const) and isinstance(pat.value, str)):
                    raise KernelError("match: the pattern must be a string constant")
                try:
                    re.compile(pat.value)
                except re.error as e:
                    raise KernelError(f"match: bad pattern {pat.value!r}: {e}") from e
            return Literal("builtin", atom=Atom(name, tuple(args)), negated=negated)
        if t and t[0] == "id" and n and n[1] == "(" and t[1] not in FUNCS:
            a = self.atom()
            return Literal("neg" if negated else "pos", atom=a, negated=negated)
        if negated:
            raise KernelError("rule syntax: `not` applies to an atom or a builtin, not a comparison; "
                              "use the opposite comparison")
        left = self.expr()
        op = self.take(kind="op")[1]
        if op not in ("=", "!=", "<", "<=", ">", ">="):
            raise KernelError(f"rule syntax: expected a comparison, found {op!r}")
        return Literal("cmp", op=op, left=left, right=self.expr())


def parse(text: str) -> list[Clause]:
    return _Parser(text).program()


def head_names(clauses: list[Clause]) -> list[str | None]:
    """The names a message may use: the head's variable at each position. Every clause of a rule
    must use the same name at a position that any clause names."""
    arity = {len(c.head.args) for c in clauses}
    if len(arity) != 1:
        raise KernelError(f"clauses of {clauses[0].head.pred!r} disagree on arity")
    names: list[str | None] = [None] * arity.pop()
    for c in clauses:
        for i, a in enumerate(c.head.args):
            if isinstance(a, Var):
                if names[i] not in (None, a.name):
                    raise KernelError(f"{c.head.pred}: position {i + 1} is {names[i]} in one clause and "
                                      f"{a.name} in another; use one name")
                names[i] = a.name
    return names


def check_message(message: str, names: list[str | None]) -> None:
    """A message may name head variables, optionally with !r or !s, and nothing else: a format
    spec ({X:d}) could fail on a value of another type at evaluation time."""
    if not message:
        raise KernelError("a gate rule needs a message: it is what the reader sees")
    known = {n for n in names if n}
    try:
        parts = list(string.Formatter().parse(message))
    except ValueError as e:
        raise KernelError(f"message: {e}") from e
    for _, fname, spec, conv in parts:
        if fname is None:
            continue
        if fname not in known:
            raise KernelError(f"message field {{{fname}}} is not a head variable; known: {sorted(known)}")
        if spec or conv not in (None, "r", "s"):
            raise KernelError(f"message field {{{fname}}}: only !r or !s may follow a name")


# ── compilation ──────────────────────────────────────────────────────────


def _q(v: Any) -> str:
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return "1" if v else "0"
    if isinstance(v, (int, float)):
        return repr(v)
    return "'" + str(v).replace("'", "''") + "'"


def _edb(pred: str, a: str) -> tuple[list[str], list[str], list[str]]:
    """(FROM items, join conditions, column expressions) for a graph atom with alias `a`."""
    if pred == "node":
        return [f"k_nodes AS {a}"], [], [f"{a}.id", f"{a}.type", f"{a}.state"]
    if pred == "class":
        return ([f"k_nodes AS {a}", f"k_state_class AS {a}c", f"k_types AS {a}t"],
                [f"{a}c.type = {a}.type", f"{a}c.state = {a}.state", f"{a}t.name = {a}.type",
                 f"{a}t.authority <> 'proposed'"], [f"{a}.id", f"{a}c.class"])
    if pred == "tclass":
        return ([f"k_type_class AS {a}", f"k_types AS {a}t"], [f"{a}t.name = {a}.type", f"{a}t.authority <> 'proposed'"],
                [f"{a}.type", f"{a}.class"])
    if pred == "edge":
        return [f"k_edges AS {a}"], [], [f"{a}.src", f"{a}.type", f"{a}.dst"]
    if pred == "attr":
        return [f"k_nodes AS {a}", f"json_each({a}.attrs) AS {a}j"], [], [f"{a}.id", f"{a}j.key", f"{a}j.value"]
    if pred == "origin":
        return [f"k_nodes AS {a}"], [], [f"{a}.id", f"{a}.origin"]
    if pred == "author":
        return [f"k_nodes AS {a}"], [], [f"{a}.id", f"{a}.author"]
    if pred == "content":
        return [f"k_nodes AS {a}"], [], [f"{a}.id", f"{a}.content"]
    if pred == "state_decl":
        return [f"k_states AS {a}"], [], [f"{a}.type", f"{a}.state"]
    raise KernelError(f"unknown graph atom {pred!r}")  # pragma: no cover


def _vars(t: Any) -> set[str]:
    if isinstance(t, Var):
        return {t.name}
    if isinstance(t, Arith):
        return _vars(t.left) | _vars(t.right)
    if isinstance(t, Func):
        return _vars(t.arg)
    return set()


class _Compiler:
    def __init__(self, tables: dict[str, str]):
        self.tables = tables  # derived predicate -> temp table
        self.n = itertools.count()

    def source(self, pred: str) -> tuple[list[str], list[str], list[str], str]:
        a = f"t{next(self.n)}"
        if pred in EDB_ARITY:
            f, c, cols = _edb(pred, a)
        else:
            f, c = [f"{self.tables[pred]} AS {a}"], []
            cols = [f"{a}.c{i}" for i in range(self.arity[pred])]
        return f, c, cols, a

    def expr(self, t: Any, binds: dict[str, str]) -> str:
        if isinstance(t, Var):
            return binds[t.name]
        if isinstance(t, Const):
            return _q(t.value)
        if isinstance(t, SelfRef):
            return ":self"
        if isinstance(t, Arith):
            return f"({self.expr(t.left, binds)} {t.op} {self.expr(t.right, binds)})"
        if isinstance(t, Func):
            fn = {"len": "length", "lower": "rhb_lower"}[t.name]
            return f"{fn}({self.expr(t.arg, binds)})"
        raise KernelError("`_` cannot be used here")

    def cond(self, col: str, t: Any, binds: dict[str, str]) -> str | None:
        if isinstance(t, Anon):
            return None
        return f"{col} IS {self.expr(t, binds)}"  # null-safe: a null value matches a null

    def clause(self, c: Clause) -> str:
        froms: list[str] = []
        conds: list[str] = []
        binds: dict[str, str] = {}
        for lit in c.body:
            if lit.kind != "pos":
                continue
            a = lit.atom
            f, jc, cols, _ = self.source(a.pred)  # type: ignore[union-attr]
            froms += f
            conds += jc
            for t, col in zip(a.args, cols):  # type: ignore[union-attr]
                if isinstance(t, (Arith, Func)):
                    raise KernelError(f"{c.head.pred}: arithmetic belongs in a comparison, not in an atom")
                if isinstance(t, Var) and t.name not in binds:
                    binds[t.name] = col
                    continue
                x = self.cond(col, t, binds)
                if x:
                    conds.append(x)
        rest = [lit for lit in c.body if lit.kind != "pos"]
        progress = True
        while rest and progress:
            progress = False
            for lit in list(rest):
                need = self.needs(lit)
                if lit.kind == "cmp" and lit.op == "=":
                    lv, rv = _vars(lit.left), _vars(lit.right)
                    if isinstance(lit.left, Var) and lit.left.name not in binds and rv <= binds.keys():
                        binds[lit.left.name] = self.expr(lit.right, binds)
                        rest.remove(lit)
                        progress = True
                        continue
                    if isinstance(lit.right, Var) and lit.right.name not in binds and lv <= binds.keys():
                        binds[lit.right.name] = self.expr(lit.left, binds)
                        rest.remove(lit)
                        progress = True
                        continue
                if need <= binds.keys():
                    conds.append(self.literal(lit, binds))
                    rest.remove(lit)
                    progress = True
        if rest:
            unbound = sorted(set().union(*(self.needs(lit) for lit in rest)) - binds.keys())
            raise KernelError(f"{c.head.pred}: unsafe — variable(s) {', '.join(unbound)} are not bound by a "
                              "positive atom")
        head = []
        for t in c.head.args:
            if isinstance(t, Var) and t.name not in binds:
                raise KernelError(f"{c.head.pred}: head variable {t.name} is not bound by the body")
            if isinstance(t, Anon):
                raise KernelError(f"{c.head.pred}: `_` cannot appear in a head")
            head.append(self.expr(t, binds))
        sql = "SELECT DISTINCT " + ", ".join(f"{h} AS c{i}" for i, h in enumerate(head))
        if froms:
            sql += " FROM " + ", ".join(froms)
        if conds:
            sql += " WHERE " + " AND ".join(conds)
        return sql

    @staticmethod
    def needs(lit: Literal) -> set[str]:
        if lit.kind == "cmp":
            return _vars(lit.left) | _vars(lit.right)
        return set().union(*(_vars(t) for t in lit.atom.args))  # type: ignore[union-attr]

    def literal(self, lit: Literal, binds: dict[str, str]) -> str:
        if lit.kind == "cmp":
            x, y = self.expr(lit.left, binds), self.expr(lit.right, binds)
            if lit.op == "=":
                return f"({x} IS {y})"
            if lit.op == "!=":
                return f"({x} IS NOT {y})"
            num = "IN ('integer', 'real')"
            return f"(typeof({x}) {num} AND typeof({y}) {num} AND {x} {lit.op} {y})"
        a = lit.atom
        assert a is not None
        if lit.kind == "builtin":
            x, y = (self.expr(t, binds) for t in a.args)
            if a.pred == "match":
                s = f"rhb_regexp({y}, {x})"
            else:  # null on either side: false, so `not prefix(null, …)` holds, as for match
                s = f"coalesce(substr({x}, 1, length({y})) = {y}, 0)"
            return f"NOT {s}" if lit.negated else s
        f, jc, cols, _ = self.source(a.pred)
        conds = list(jc)
        for t, col in zip(a.args, cols):
            x = self.cond(col, t, binds)
            if x:
                conds.append(x)
        return f"NOT EXISTS (SELECT 1 FROM {', '.join(f)}" + (f" WHERE {' AND '.join(conds)})" if conds else ")")


# ── programs ─────────────────────────────────────────────────────────────


class Program:
    """A set of clauses, checked for arity, safety and stratification."""

    def __init__(self, clauses: list[Clause]):
        self.clauses = clauses
        self.by_pred: dict[str, list[Clause]] = {}
        for c in clauses:
            self.by_pred.setdefault(c.head.pred, []).append(c)
        self.arity: dict[str, int] = {}
        for c in clauses:
            self._arity(c.head)
        for c in clauses:
            for lit in c.body:
                if lit.atom is None or lit.kind == "builtin":
                    continue
                a = lit.atom
                if a.pred in EDB_ARITY:
                    if len(a.args) != EDB_ARITY[a.pred]:
                        raise KernelError(f"{c.head.pred}: {a.pred} takes {EDB_ARITY[a.pred]} arguments")
                elif a.pred not in self.by_pred:
                    raise KernelError(f"{c.head.pred}: uses {a.pred!r}, which no rule defines")
                else:
                    self._arity(a)
        self.deps: dict[str, set[tuple[str, bool]]] = {
            p: {(lit.atom.pred, lit.kind == "neg") for c in cs for lit in c.body  # type: ignore[union-attr]
                if lit.kind in ("pos", "neg") and lit.atom.pred in self.by_pred}  # type: ignore[union-attr]
            for p, cs in self.by_pred.items()}
        self.sccs = self._sccs()
        for scc in self.sccs:
            for p in scc:
                for q, neg in self.deps[p]:
                    if neg and q in scc:
                        raise KernelError(f"{p} depends negatively on {q} inside a cycle: the rules are not "
                                          "stratified (break the cycle, or remove the `not`)")
        comp = _Compiler({})
        comp.arity = self.arity  # type: ignore[attr-defined]
        comp.tables = {p: f"idb_{p}" for p in self.by_pred}
        for c in clauses:
            comp.clause(c)  # safety is checked by compiling

    @classmethod
    def from_rules(cls, rules: list[dict[str, Any]]) -> "Program":
        clauses: list[Clause] = []
        for r in rules:
            clauses += parse(r["body"])
        return cls(clauses)

    def _arity(self, a: Atom) -> None:
        n = self.arity.setdefault(a.pred, len(a.args))
        if n != len(a.args):
            raise KernelError(f"{a.pred} is used with {len(a.args)} and {n} arguments")

    def _sccs(self) -> list[list[str]]:
        """Tarjan: strongly connected components, dependencies before dependents."""
        index: dict[str, int] = {}
        low: dict[str, int] = {}
        on: set[str] = set()
        stack: list[str] = []
        out: list[list[str]] = []
        counter = itertools.count()

        def visit(v: str) -> None:
            index[v] = low[v] = next(counter)
            stack.append(v)
            on.add(v)
            for w, _ in sorted(self.deps[v]):
                if w not in index:
                    visit(w)
                    low[v] = min(low[v], low[w])
                elif w in on:
                    low[v] = min(low[v], index[w])
            if low[v] == index[v]:
                comp = []
                while True:
                    w = stack.pop()
                    on.discard(w)
                    comp.append(w)
                    if w == v:
                        break
                out.append(sorted(comp))

        for v in sorted(self.by_pred):
            if v not in index:
                visit(v)
        return out

    def needed(self, targets: set[str]) -> set[str]:
        seen, todo = set(), list(targets)
        while todo:
            p = todo.pop()
            if p in seen or p not in self.by_pred:
                continue
            seen.add(p)
            todo += [q for q, _ in self.deps[p]]
        return seen

    _runs = itertools.count(1)

    def evaluate(self, db: Any, self_id: str, targets: set[str], max_rounds: int = 1000) -> dict[str, list[tuple]]:
        """Evaluate what the targets need, with Self bound, and return each target's tuples."""
        need = self.needed(targets)
        run = next(self._runs)
        tables = {p: f"temp.idb{run}_{p}" for p in need}
        comp = _Compiler(tables)
        comp.arity = self.arity  # type: ignore[attr-defined]
        made: list[str] = []
        try:
            for p in need:
                cols = ", ".join(f"c{i}" for i in range(self.arity[p]))
                db.execute(f"CREATE TEMP TABLE idb{run}_{p} ({cols})")
                made.append(tables[p])
            for scc in self.sccs:
                live = [p for p in scc if p in need]
                if not live:
                    continue
                sqls = [(p, comp.clause(c)) for p in live for c in self.by_pred[p]]
                recursive = any(q in live for p in live for q, _ in self.deps[p])
                for rnd in itertools.count():
                    added = 0
                    for p, sql in sqls:
                        cur = db.execute(f"INSERT INTO {tables[p]} SELECT * FROM ({sql}) EXCEPT SELECT * FROM {tables[p]}",
                                         {"self": self_id})
                        added += max(cur.rowcount, 0)
                    if not recursive or added == 0:
                        break
                    if rnd >= max_rounds:
                        raise KernelError(f"rules {', '.join(live)} did not reach a fixpoint in {max_rounds} rounds "
                                          "(arithmetic in a recursive rule?)")
            return {p: [tuple(r) for r in db.execute(f"SELECT * FROM {tables[p]}")] for p in targets if p in tables}
        finally:
            for t in made:
                db.execute(f"DROP TABLE IF EXISTS {t}")


# ── findings ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Finding:
    rule: str
    severity: str
    message: str
    values: tuple
    proposed: bool = False


def _format(message: str, names: list[str | None], values: tuple) -> str:
    env = {n: v for n, v in zip(names, values) if n}
    return string.Formatter().vformat(message, (), env)


def _program(graph: Any, rows: list[dict[str, Any]]) -> Program:
    """The compiled program for exactly these rules. Keyed by content, not a counter: a rolled-back
    definition must not leave its program behind."""
    key = hashlib.sha256(json_key(rows).encode()).hexdigest()
    if graph._program_cache and graph._program_cache[0] == key:
        return graph._program_cache[1]
    program = Program.from_rules(rows)
    graph._program_cache = (key, program)
    return program


def json_key(rows: list[dict[str, Any]]) -> str:
    return "\x1e".join(f"{r['id']}\x1f{r['body']}" for r in sorted(rows, key=lambda r: r["id"]))


def _findings(graph: Any, program: Program, targets: list[dict[str, Any]], self_id: str) -> list[Finding]:
    with graph.scratch():  # temp tables and all: nothing of the evaluation survives it
        results = program.evaluate(graph.db, self_id, {r["id"] for r in targets})
    out = []
    for r in targets:
        names = head_names(program.by_pred[r["id"]])
        proposed = r["authority"] == "proposed"
        sev = "warn" if proposed and r["severity"] == "block" else r["severity"]
        for values in sorted(results.get(r["id"], []), key=repr):
            out.append(Finding(r["id"], sev, _format(r["message"], names, values) if r["message"] else "", values,
                               proposed))
    return out


def evaluate(graph: Any, phase: str, self_id: str, scope_type: str) -> list[Finding]:
    """The findings of every active rule of this phase that applies to scope_type, with Self bound.

    Sealed and kernel rules are evaluated first, on their own: they cannot rest on a proposed rule
    (define_rules refuses it), so nothing the model wrote can change or break them. Proposed rules
    are evaluated after, and a proposed rule that fails is reported as a warning about itself: the
    model's advice never blocks the user's work, not even by crashing."""
    rows = graph.active_rules()
    targets = [r for r in rows if r["phase"] == phase and r["applies_to"] in ("*", scope_type)]
    if not targets:
        return []
    firm = [r for r in targets if r["authority"] != "proposed"]
    soft = [r for r in targets if r["authority"] == "proposed"]
    out = _findings(graph, _program(graph, rows), firm, self_id) if firm else []
    for r in soft:
        try:
            out += _findings(graph, _program(graph, rows), [r], self_id)
        except Exception as e:  # noqa: BLE001 — a proposal's failure is information, not an outage
            out.append(Finding(r["id"], "warn", f"proposed rule {r['id']} failed to evaluate: {e}", (), True))
    return out
