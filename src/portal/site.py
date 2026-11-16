"""The site's services: the [[app]] entries of the site file (deploy/site.toml), and what they render.

A service ("app") is a backend the site sign-in fronts: the account portal, refhandbook, and whatever
comes next. Its entry says where it lives (routes), whom tokens are minted for (audience),
and how it is shown (title, description, links, menu). portal/deploy.py renders the nginx snippets
from it; the SSO shows its cards on the main page and mints tokens for its audiences; the portal's
menu shows its apps.

Rules the renderer enforces, so a new entry cannot weaken the site by omission:
  - a `site` route goes through the sign-in (auth_request) and, if its app has an audience, carries
    a token minted for that audience alone; a `public` route clears X-Auth-Token, so no backend ever
    receives a token it did not ask nginx for
  - every route path is unique, every limit names a declared zone, ids and audiences are plain names
  - raw nginx directives (`nginx = "..."`) are allowed for what the schema does not cover, and are
    copied verbatim: review them like the config they are
  - an app the site hosts (`static`, `storage`) gets its routes generated, and its tokens are minted
    for its id alone, which the storage service checks against the app in the path
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from .i18n import N_, catalog, t

NAME = re.compile(r"^[a-z][a-z0-9-]{0,31}$")
# A widget's cells on the main page's grid, columns x rows (docs/frame.md §4): the one declaration — the
# frame receives it (/auth/api/v1/me `sizes`) and draws, snaps and names sizes from it, nowhere else.
SIZES: dict[str, tuple[int, int]] = {"1x1": (1, 1), "2x1": (2, 1), "1x2": (1, 2), "2x2": (2, 2), "3x1": (3, 1), "3x2": (3, 2), "4x2": (4, 2)}
THEMES = ("auto", "light", "dark")  # the values of a person's theme (docs/frame.md §1)
FRAME = 1  # the version of the frame the sign-in serves (/auth/static/site.js, theme.css, parts.css)
# The catalog's tags (docs/apps-vault-calendar.md §1.1): a fixed vocabulary an app picks from, so the catalog
# can filter by them and every language has their words.
TAGS = (N_("연구"), N_("글쓰기"), N_("AI"), N_("도구"), N_("일정"), N_("자료"))
MATCHES = ("prefix", "exact", "regex", "priority")  # priority = `^~` (a prefix that wins over regexes)
AUTH = ("site", "public")
# limit name → rate; the zone is <site name>_<limit>. api: the pages' own calls (they poll a run, say)
ZONES = {"login": "10r/m", "oauth": "30r/m", "api": "10r/s"}


class SiteError(ValueError):
    pass


# The person's look (docs/frame.md §1.3): what the settings page offers over theme.css's tokens, declared in the
# site file ([look]) and carried to the frame (/auth/api/v1/me `look`). A choice redeclares tokens — a palette
# for the light and the dark theme, the others once — and the first choice of a kind is theme.css's own. The
# frame writes nothing but these tokens; the parts take them (parts.css), as they take every token.
LOOK_KINDS = ("palette", "corner", "type", "heading", "mono", "size")
# the look's fonts (docs/frame.md §1.3): the body's (--sans), the headings' (--serif) and the code's (--mono). A choice
# of these may name the open fonts it needs (ids of web/fonts.json, served at [look] fonts) and the group it is listed under.
FONT_KINDS = ("type", "heading", "mono")
FONT_GROUPS = {"sans": N_("고딕"), "serif": N_("명조"), "hand": N_("손글씨"), "display": N_("제목용"), "mono": N_("고정폭")}
FONTS_AT = re.compile(r"^/(?!/)[A-Za-z0-9._~/-]*/$")  # where the fonts are served: an address of this site, a folder
TOKEN = re.compile(r"^[a-z][a-z0-9-]{0,31}$")
TOKEN_VALUE = re.compile(r"^[^;{}<>\\\n]{1,200}$")  # a value inside a declaration: it cannot close one or open another


def _tokens(where: str, d: object) -> dict[str, str]:
    if not isinstance(d, dict):
        raise SiteError(f"{where}: a table of tokens (name = value)")
    for k, v in d.items():
        if not TOKEN.match(k) or not isinstance(v, str) or not TOKEN_VALUE.match(v):
            raise SiteError(f"{where}: {k} = {v!r}: a token name (lowercase, -) and a value without ; {{ }} < > \\")
    return dict(d)


def _look(data: dict) -> dict:
    """[look] of the site file, checked: {kind: [{id, label, tr, tokens | light+dark, fonts+group}], columns: [..],
    fonts: the address the open fonts are served at}."""
    look = data.get("look") or {}
    bad = set(look) - set(LOOK_KINDS) - {"columns", "fonts"}
    if bad:
        raise SiteError(f"look: unknown kinds {sorted(bad)} (the kinds are {LOOK_KINDS}, columns and fonts)")
    out: dict = {}
    for kind in LOOK_KINDS:
        seen, choices = set(), []
        for c in look.get(kind, []):
            known = {"id", "label", "tr"} | ({"light", "dark"} if kind == "palette" else {"tokens"}) | ({"fonts", "group"} if kind in FONT_KINDS else set())
            if set(c) - known or not NAME.match(str(c.get("id", ""))) or not c.get("label"):
                raise SiteError(f"look.{kind}: a choice has an id (lowercase, -), a label and {sorted(known - {'id', 'label', 'tr'})}")
            if c["id"] in seen:
                raise SiteError(f"look.{kind}: {c['id']} is declared twice")
            seen.add(c["id"])
            choice = {"id": c["id"], "label": c["label"], "tr": dict(c.get("tr") or {})}
            if kind == "palette":
                light, dark = _tokens(f"look.palette.{c['id']}.light", c.get("light", {})), _tokens(f"look.palette.{c['id']}.dark", c.get("dark", {}))
                if set(light) != set(dark):
                    raise SiteError(f"look.palette.{c['id']}: light and dark redeclare the same tokens")
                choice |= {"light": light, "dark": dark}
            else:
                choice["tokens"] = _tokens(f"look.{kind}.{c['id']}.tokens", c.get("tokens", {}))
            if kind in FONT_KINDS:
                if c.get("group") not in FONT_GROUPS:
                    raise SiteError(f"look.{kind}.{c['id']}: group is one of {sorted(FONT_GROUPS)}")
                fonts = c.get("fonts", [])
                if not isinstance(fonts, list) or any(not isinstance(f, str) or not NAME.match(f) for f in fonts):
                    raise SiteError(f"look.{kind}.{c['id']}: fonts are ids of the open fonts (lowercase, -)")
                choice |= {"group": c["group"], "fonts": list(fonts)}
            choices.append(choice)
        out[kind] = choices
    at = look.get("fonts", "")
    if not isinstance(at, str) or (at and not FONTS_AT.match(at)):
        raise SiteError("look.fonts: where the open fonts are served — an address of this site ending in /")
    if not at and any(c["fonts"] for k in FONT_KINDS for c in out[k]):
        raise SiteError("look.fonts: a choice names open fonts — say where they are served")
    out["fonts"] = at
    cols = look.get("columns", [])
    if not isinstance(cols, list) or any(not isinstance(n, int) or n < 0 or n > 12 for n in cols):
        raise SiteError("look.columns: numbers of the main page's columns (0 = as many as fit, up to 12)")
    out["columns"] = list(cols)
    return out


@dataclass(frozen=True)
class Link:
    label: str
    href: str
    groups: tuple[str, ...] = ()  # shown only to members of one of these (the backend still checks)
    tr: dict[str, str] = field(default_factory=dict, compare=False, hash=False)  # the label in other languages

    def shown_to(self, groups: set[str] | frozenset[str]) -> bool:
        return not self.groups or bool(set(self.groups) & set(groups))

    def label_in(self, lang: str) -> str:
        return self.tr.get(lang) or t(self.label)  # a label of ours (N_) has its words in the catalog


@dataclass(frozen=True)
class Address:
    """One way to connect to an app, shown on its page with a copy button: `value` is what the person
    types or pastes (an address, a URI, a command), and may name the person looking as {user};
    `label` says which client it is for."""
    value: str
    label: str = ""
    tr: dict[str, str] = field(default_factory=dict, compare=False, hash=False)  # the label in other languages

    def label_in(self, lang: str) -> str:
        return self.tr.get(lang) or self.label


def _addresses(app_id: str, code) -> tuple[Address, ...]:  # noqa: ANN001 — a string, or a list of tables
    """An app's `code`: one line (a string), or a list of {value, label, tr} — one address per client."""
    if isinstance(code, str):
        return (Address(code),) if code else ()
    if not isinstance(code, list):
        raise SiteError(f"app {app_id}: code is a string or a list of {{value, label, tr}}")
    out = []
    for c in code:
        if not isinstance(c, dict) or "value" not in c or set(c) - {"value", "label", "tr"}:
            raise SiteError(f"app {app_id}: each code is {{value, label, tr}} with a value")
        out.append(Address(str(c["value"]), str(c.get("label", "")), dict(c.get("tr") or {})))
    return tuple(out)


@dataclass(frozen=True)
class Source:
    """Where a setting's choices are read: a path of the site, the list in its answer, an item's value and label."""
    path: str
    list: str
    value: str
    label: str


@dataclass(frozen=True)
class Param:
    """A setting of a widget, kept by a person with each place they give it ([[app.widget.param]],
    docs/frame.md §4): one of `choices` (value, label), or one of the person's own objects read from
    `source` (the file's `from`) with `all`, the word for no filter."""
    id: str
    label: str
    default: str = ""
    choices: tuple[tuple[str, str], ...] = ()
    source: Source | None = None
    all: str = ""
    tr: dict[str, dict] = field(default_factory=dict, compare=False, hash=False)

    def json(self, lang: str) -> dict:
        """As /me carries it, in a language."""
        words = self.tr.get(lang) or {}
        out: dict = {"id": self.id, "label": words.get("label") or self.label, "default": self.default}
        if self.source:
            s = self.source
            out["from"] = {"path": s.path, "list": s.list, "value": s.value, "label": s.label}
            out["all"] = words.get("all") or self.all
        else:
            named = words.get("choices") or {}
            out["choices"] = [{"value": v, "label": named.get(v) or label} for v, label in self.choices]
        return out


@dataclass(frozen=True)
class Widget:
    """A piece an app contributes to the main page (docs/frame.md §4): its ES module draws into a cell
    of the grid for whoever has the app on. `module` is a path under the app's own files (a static
    app) or an absolute path (a service's); `href` is where the frame imports it from."""
    id: str
    title: str
    module: str
    size: str = "1x1"
    description: str = ""  # one line: what the piece shows or does, for the person choosing it (docs/frame.md §4)
    href: str = ""  # filled by load(): the module's absolute path
    params: tuple[Param, ...] = ()  # its settings, kept with each place a person gives it ([[app.widget.param]])
    tr: dict[str, dict[str, str]] = field(default_factory=dict, compare=False, hash=False)

    def text(self, name: str, lang: str) -> str:
        return (self.tr.get(lang) or {}).get(name) or getattr(self, name)


@dataclass(frozen=True)
class Route:
    path: str
    match: str = "prefix"
    auth: str = "site"
    upstream: str = ""
    limit: str = ""
    burst: int = 10
    body: str = ""
    stream: bool = False
    signin: bool = True  # on 401, send a browser to the sign-in page; False passes the 401 and its
    #                      WWW-Authenticate through (for clients that answer it themselves)
    nginx: str = ""
    note: str = ""
    page: bool = False  # one of a pages app's paths (served only once that app is published)


@dataclass(frozen=True)
class App:
    id: str
    title: str
    description: str = ""  # the tagline: one line (what the app gives), on its card and in the catalog
    about: str = ""  # two or three sentences (what it does, what stays), on its page in the catalog
    tags: tuple[str, ...] = ()  # from TAGS
    audience: str = ""
    upstream: str = ""
    groups: tuple[str, ...] = ()
    menu: str = ""  # the menu label; "" = not in the portal's menu
    menu_href: str = ""
    links: tuple[Link, ...] = ()
    code: tuple[Address, ...] = ()  # the ways to connect to it (Address), on its page in the catalog
    card: bool = True
    icon: str = ""  # a short mark for the app (an emoji or a letter or two) on its card and in the app list
    # the app's words in other languages: {lang: {title, description, about, menu}} (Korean is the file's own)
    tr: dict[str, dict[str, str]] = field(default_factory=dict, compare=False, hash=False)
    # An app hosted by the site itself (portal/apps.py): `static` serves its built files at /apps/<id>/
    # (true: from <apps_root>/<id>, or a directory), `storage` gives each user a JSON store at
    # /apps/<id>/api/. Their routes are generated; the app's audience is its id.
    static: bool | str = False
    storage: bool = False
    # A static app that is the site's pages: every path here serves its index.html (a path ending in
    # "/": it and everything below; any other, "/" too: that path exactly); it reads the services' APIs.
    # `public`: its files need no sign-in (the APIs do; `storage` gives it each user's store, too).
    pages: tuple[str, ...] = ()
    public: bool = False
    build: str = ""  # its built files in the code tree (web/dist): the installer publishes them when there
    # Every app is off until a person turns it on (docs/frame.md §2). `optional = false`: it cannot be
    # turned off (the account), and the frame keeps it in the person's own menu rather than the apps'.
    optional: bool = True
    # `default = true`: on for an account that has no settings kept yet (docs/frame.md §2 R13); a kept
    # choice stays as it is. The frame reads it from /auth/api/v1/me — no list of app ids in the code.
    default: bool = False
    widgets: tuple[Widget, ...] = ()  # what it offers the main page ([[app.widget]], docs/frame.md §4)
    routes: tuple[Route, ...] = ()

    def text(self, name: str, lang: str) -> str:
        """`title`, `description`, `about` or `menu`, in `lang` if the file says it there."""
        return (self.tr.get(lang) or {}).get(name) or getattr(self, name)


@dataclass(frozen=True)
class Site:
    apps: tuple[App, ...] = field(default_factory=tuple)
    look: dict = field(default_factory=dict, compare=False, hash=False)  # [look], checked (_look)

    def look_in(self, lang: str) -> dict:
        """The look's choices for the frame, their labels in `lang`; where the fonts are; the fonts' group words."""
        words = catalog(lang)
        return {**{k: ([{**{x: v for x, v in c.items() if x not in ("tr",)}, "label": c["tr"].get(lang) or c["label"]}
                        for c in self.look.get(k, [])] if k != "columns" else list(self.look.get(k, [])))
                   for k in (*LOOK_KINDS, "columns")},
                "fonts": self.look.get("fonts", ""), "groups": {g: words.get(w, w) for g, w in FONT_GROUPS.items()}}

    @property
    def audiences(self) -> tuple[str, ...]:
        return tuple(sorted({a.audience for a in self.apps if a.audience}))

    def menu(self, groups: set[str] | frozenset[str] = frozenset(), lang: str = "ko") -> list[Link]:
        return [Link(a.text("menu", lang), a.menu_href or (a.links[0].href if a.links else "/")) for a in self.apps
                if a.menu and (not a.groups or set(a.groups) & set(groups))]

    def cards(self, groups: set[str] | frozenset[str] = frozenset()) -> list[App]:
        """The main page's cards for someone in `groups`: the apps they may see, each with the links
        they may see."""
        from dataclasses import replace

        return [replace(a, links=tuple(ln for ln in a.links if ln.shown_to(groups))) for a in self.apps
                if a.card and (not a.groups or set(a.groups) & set(groups))]


def _route(app_id: str, d: dict) -> Route:
    known = set(Route.__dataclass_fields__)
    bad = set(d) - known
    if bad:
        raise SiteError(f"app {app_id}: unknown route fields {sorted(bad)}")
    r = Route(**d)
    if not r.path.startswith("/") and r.match != "regex":
        raise SiteError(f"app {app_id}: route path {r.path!r} must start with /")
    if r.match not in MATCHES:
        raise SiteError(f"app {app_id}: route {r.path}: match is one of {MATCHES}")
    if r.auth not in AUTH:
        raise SiteError(f"app {app_id}: route {r.path}: auth is one of {AUTH}")
    if r.limit and r.limit not in ZONES:
        raise SiteError(f"app {app_id}: route {r.path}: limit is one of {sorted(ZONES)}")
    if r.body and not re.fullmatch(r"\d+[kmg]?", r.body):
        raise SiteError(f"app {app_id}: route {r.path}: body is an nginx size (16k, 4m, 0)")
    if any(c in r.path for c in "{};\n"):
        raise SiteError(f"app {app_id}: route {r.path!r}: no braces, semicolons or newlines")
    return r


def _param(app_id: str, widget_id: str, d: dict) -> Param:
    where = f"app {app_id}: widget {widget_id}"
    if not isinstance(d, dict):
        raise SiteError(f"{where}: a parameter is a table")
    bad = set(d) - {"id", "label", "default", "choices", "from", "all", "tr"}
    if bad:
        raise SiteError(f"{where}: unknown parameter fields {sorted(bad)}")
    pid, label, default = d.get("id", ""), d.get("label", ""), d.get("default", "")
    if not isinstance(pid, str) or not NAME.match(pid) or not isinstance(label, str) or not label:
        raise SiteError(f"{where}: a parameter needs an id (lowercase letters, digits and -) and a label")
    where = f"{where}: parameter {pid}"
    choices, source = d.get("choices"), d.get("from")
    if (choices is None) == (source is None):
        raise SiteError(f"{where}: one of choices and from")
    if not isinstance(default, str):
        raise SiteError(f"{where}: default is text")
    tr = d.get("tr") or {}
    for lang, words in tr.items():
        if not isinstance(words, dict) or set(words) - {"label", "all", "choices"} or not isinstance(words.get("choices", {}), dict):
            raise SiteError(f"{where}: tr.{lang} names label, all or choices")
    if choices is not None:
        if (not isinstance(choices, list) or not choices
                or any(not isinstance(c, dict) or set(c) != {"value", "label"} or not all(isinstance(v, str) for v in c.values()) for c in choices)):
            raise SiteError(f"{where}: choices are tables of value and label")
        pairs = tuple((c["value"], c["label"]) for c in choices)
        values = {v for v, _ in pairs}
        if len(values) < len(pairs):
            raise SiteError(f"{where}: a choice's value is given twice")
        if default not in values:
            raise SiteError(f"{where}: default is one of its choices")
        if "all" in d:
            raise SiteError(f"{where}: all goes with from")
        return Param(id=pid, label=label, default=default, choices=pairs, tr=tr)
    if not isinstance(source, dict) or set(source) != {"path", "list", "value", "label"} or not all(isinstance(v, str) and v for v in source.values()):
        raise SiteError(f"{where}: from names path, list, value and label")
    path = source["path"]
    if not path.startswith("/") or path.startswith("//") or ".." in path or any(c in path for c in " \n\\{};?#"):
        raise SiteError(f"{where}: from.path is a path of the site")
    if default:
        raise SiteError(f"{where}: a setting read from the site starts with no filter (no default)")
    word = d.get("all", "")
    if not isinstance(word, str) or not word:
        raise SiteError(f"{where}: all is the word for no filter")
    return Param(id=pid, label=label, source=Source(**source), all=word, tr=tr)


def _widget(app_id: str, d: dict) -> Widget:
    d = dict(d)
    declared = d.pop("param", [])
    known = set(Widget.__dataclass_fields__) - {"href", "params"}
    bad = set(d) - known
    if bad:
        raise SiteError(f"app {app_id}: unknown widget fields {sorted(bad)}")
    for lang, words in (d.get("tr") or {}).items():
        if not isinstance(words, dict) or set(words) - {"title", "description"}:
            raise SiteError(f"app {app_id}: widget tr.{lang} names title or description")
    try:
        w = Widget(**d)
    except TypeError as e:
        raise SiteError(f"app {app_id}: a widget needs id, title and module") from e
    if not NAME.match(w.id):
        raise SiteError(f"app {app_id}: widget id {w.id!r}: lowercase letters, digits and -")
    if w.size not in SIZES:
        raise SiteError(f"app {app_id}: widget {w.id}: size is one of {tuple(SIZES)}")
    if not w.module or any(c in w.module for c in "{};\n "):
        raise SiteError(f"app {app_id}: widget {w.id}: module is a path")
    if len(w.description) > 80:
        raise SiteError(f"app {app_id}: widget {w.id}: description is one line (80 characters)")
    if not isinstance(declared, list):
        raise SiteError(f"app {app_id}: widget {w.id}: param is a list of tables")
    params = tuple(_param(app_id, w.id, p) for p in declared)
    if len({p.id for p in params}) < len(params):
        raise SiteError(f"app {app_id}: widget {w.id}: a parameter id is declared twice")
    return Widget(**d, params=params)


def _filled(value, f):  # noqa: ANN001, ANN202 — every string of the file through the facts' placeholders
    if isinstance(value, str):
        return f.substitute(value)
    if isinstance(value, list):
        return [_filled(v, f) for v in value]
    if isinstance(value, dict):
        return {k: _filled(v, f) for k, v in value.items()}
    return value


def load(path: str | Path, f=None) -> Site:  # noqa: ANN001 — f: portal.facts.Facts (default: the site's own)
    from .facts import FactError, facts

    data = tomllib.loads(Path(path).read_text())
    try:
        f = f or facts(str(path))
        data = _filled(data, f)
    except FactError as e:
        raise SiteError(str(e)) from e
    apps, seen_ids, seen_paths = [], set(), set()
    for d in data.get("app", []):
        d = dict(d)
        routes = tuple(_route(d.get("id", "?"), r) for r in d.pop("route", []))
        links = tuple(Link(**{**ln, "groups": tuple(ln.get("groups", ()))}) for ln in d.pop("link", []))
        code = _addresses(d.get("id", "?"), d.pop("code", ""))
        widgets = tuple(_widget(d.get("id", "?"), w) for w in d.pop("widget", []))
        for lang, words in (d.get("tr") or {}).items():
            if not isinstance(words, dict) or set(words) - {"title", "description", "about", "menu"}:
                raise SiteError(f"app {d.get('id')}: tr.{lang} names title, description, about or menu")
        d["groups"] = tuple(d.get("groups", ()))
        d["pages"] = tuple(d.get("pages", ()))
        d["tags"] = tuple(d.get("tags", ()))
        if set(d["tags"]) - set(TAGS):
            raise SiteError(f"app {d.get('id')}: tags are among {TAGS}, not {sorted(set(d['tags']) - set(TAGS))}")
        known = set(App.__dataclass_fields__) - {"routes", "links", "widgets", "code"}
        bad = set(d) - known
        if bad:
            raise SiteError(f"app {d.get('id')}: unknown fields {sorted(bad)}")
        a = App(**d, routes=routes, links=links, widgets=widgets, code=code)
        if not NAME.match(a.id):
            raise SiteError(f"app id {a.id!r}: lowercase letters, digits and -")
        if a.default and not a.optional:
            raise SiteError(f"app {a.id}: default is for an optional app (one that is not is always on)")
        if a.static or a.storage:
            a = _hosted(a, f)
        if a.widgets:
            from dataclasses import replace

            if len({w.id for w in a.widgets}) < len(a.widgets):
                raise SiteError(f"app {a.id}: a widget id is declared twice")
            resolved = []
            for w in a.widgets:  # a static app's module lives under its own files; a service names its path
                if w.module.startswith("/"):
                    resolved.append(replace(w, href=w.module))
                elif a.static:
                    resolved.append(replace(w, href=f"/apps/{a.id}/{w.module}"))
                else:
                    raise SiteError(f"app {a.id}: widget {w.id}: module {w.module!r} must be an absolute path (the app is not static)")
            a = replace(a, widgets=tuple(resolved))
        if a.audience and not NAME.match(a.audience):
            raise SiteError(f"app {a.id}: audience {a.audience!r}: lowercase letters, digits and -")
        if a.id in seen_ids:
            raise SiteError(f"app {a.id} is declared twice")
        seen_ids.add(a.id)
        for r in a.routes:
            key = (r.match, r.path, r.page)  # a page path stands in for another route once its app is live
            if key in seen_paths:
                raise SiteError(f"route {r.match} {r.path} is declared twice")
            seen_paths.add(key)
            if not (r.upstream or a.upstream) and not any(d in r.nginx for d in ("alias", "return", "rewrite")):
                raise SiteError(f"app {a.id}: route {r.path} has no upstream (and no alias/return/rewrite of its own)")
        apps.append(a)
    return Site(tuple(apps), _look(data))


def _hosted(a: App, f) -> App:  # noqa: ANN001 — f: portal.facts.Facts
    """The routes of an app the site hosts, before any of its own."""
    from dataclasses import replace

    if a.audience and a.audience != a.id:
        raise SiteError(f"app {a.id}: a hosted app's audience is its id ({a.id}), not {a.audience!r}")
    # a public app (the site's pages) reads the services' own APIs: no token is minted for it
    audience = "" if a.public and not a.storage else a.id
    base = f"/apps/{a.id}"
    routes = []
    if a.storage:
        routes.append(Route(path=f"{base}/api/", upstream=f.upstream("apps"), body="1m",
                            signin=False, note="each user's storage (portal/apps.py)"))
    if a.static:
        root = a.static if isinstance(a.static, str) else f"{f.apps_root}/{a.id}"
        if not root.startswith("/") or any(c in root for c in "{};\n "):
            raise SiteError(f"app {a.id}: static is true or an absolute directory, not {root!r}")
        routes += [Route(path=base, match="exact", auth="public", nginx=f"return 301 {base}/$is_args$args;"),
                   Route(path=f"{base}/", auth="public" if a.public else "site",
                         # no-cache: a browser asks again (cheaply, by ETag), so after a new build it never runs an
                         # old index.html that names files the new build no longer has
                         nginx=f"alias {root.rstrip('/')}/;\nindex index.html;\ntry_files $uri {base}/index.html;\n"
                               'add_header Cache-Control "no-cache" always;',
                         note="its built files")]
    for page in a.pages:
        if not a.static or not page.startswith("/") or any(c in page for c in "{};\n "):
            raise SiteError(f"app {a.id}: pages are paths (/, /account/) of a static app")
        # the page's address stays; nginx answers it with the app's index.html, which routes itself
        routes.append(Route(path=page, match="exact" if page == "/" or not page.endswith("/") else "prefix",
                            auth="public", page=True,
                            nginx=f"rewrite ^ {base}/index.html last;", note="the site's pages (an app)"))
    links = a.links or ((Link(N_("열기"), f"{base}/"),) if a.static else ())
    return replace(a, audience=audience, links=links, routes=(*routes, *a.routes))


# ── nginx ────────────────────────────────────────────────────────────────


def _audience_regex(r: Route) -> str:
    """The $request_uri pattern of a route (the request URI carries the query string)."""
    if r.match == "regex":
        return f"~{r.path}"
    if r.match == "exact":
        return f"~^{re.escape(r.path)}(\\?|$)"
    return f"~^{re.escape(r.path.rstrip('/'))}(/|\\?|$)"


def render_map(site: Site, name: str) -> str:
    out = ["# Generated by the installer (portal/deploy.py) from the site file: edit that, not this.",
           "# http level: which backend a token is minted for. $request_uri, not $uri: the map is read",
           "# inside the auth subrequest, where $uri is /_auth.",
           *[f"limit_req_zone $binary_remote_addr zone={name}_{z}:10m rate={rate};" for z, rate in ZONES.items()],
           "map $request_uri $auth_audience {", '    default "";']
    for a in site.apps:
        if not a.audience:
            continue
        for r in a.routes:
            if r.auth == "site":
                out.append(f"    {_audience_regex(r):40} {a.audience};   # {a.id}")
    out.append("}")
    return "\n".join(out) + "\n"


def _location(a: App, r: Route, name: str) -> list[str]:
    head = {"prefix": f"location {r.path}", "exact": f"location = {r.path}", "regex": f"location ~ {r.path}",
            "priority": f"location ^~ {r.path}"}[r.match]
    body = []
    if r.auth == "site":
        body.append("auth_request /_auth;")
        if a.audience:
            body.append("auth_request_set $auth_token $upstream_http_x_auth_token;")
        if r.signin:
            body.append("error_page 401 = @signin;")
    if r.limit:
        body.append(f"limit_req zone={name}_{r.limit} burst={r.burst} nodelay;")
    upstream = r.upstream or a.upstream
    if upstream and "alias" not in r.nginx and "return" not in r.nginx:
        body.append(f"include snippets/{name}-proxy.conf;")
        # a token goes only where nginx minted one for this app; everywhere else it is cleared
        body.append("proxy_set_header X-Auth-Token $auth_token;" if r.auth == "site" and a.audience
                    else 'proxy_set_header X-Auth-Token "";')
        body.append(f"proxy_pass {upstream};")
    if r.body:
        body.append(f"client_max_body_size {r.body};")
    if r.stream:
        body += ["proxy_buffering off;", "proxy_cache off;", "proxy_read_timeout 360s;", "proxy_send_timeout 360s;"]
    body += [ln.strip() for ln in r.nginx.strip().splitlines() if ln.strip()]
    note = f"   # {r.note}" if r.note else ""
    return [f"{head} {{{note}", *[f"    {b}" for b in body], "}"]


def page_paths(site: Site, live: set[str] | None = None) -> set[str]:
    """The paths the site's pages apps answer (of those `live`: published; None: every one)."""
    return {r.path for a in site.apps if live is None or a.id in live for r in a.routes if r.page}


def render_locations(site: Site, name: str, live: set[str] | None = None) -> str:
    """Every app's locations. A pages app's page paths only if it is `live` (its build is published:
    until then those paths stay with whatever served them before). None: every one."""
    out = ["# Generated by the installer (portal/deploy.py) from the site file: edit that, not this.",
           "# Included inside the site's server block."]
    taken = page_paths(site, live)
    for a in site.apps:
        routes = [r for r in a.routes if (not r.page or live is None or a.id in live)
                  and (r.page or (r.match, r.path) not in {("prefix", p) for p in taken})]
        if not routes:
            continue
        out += ["", f"# ── {a.id}: {a.title} " + "─" * max(0, 60 - len(a.id) - len(a.title))]
        for r in routes:
            out += _location(a, r, name)
    return "\n".join(out) + "\n"
