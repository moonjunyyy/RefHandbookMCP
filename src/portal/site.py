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

NAME = re.compile(r"^[a-z][a-z0-9-]{0,31}$")
MATCHES = ("prefix", "exact", "regex", "priority")  # priority = `^~` (a prefix that wins over regexes)
AUTH = ("site", "public")
# limit name → rate; the zone is <site name>_<limit>. api: the pages' own calls (they poll a run, say)
ZONES = {"login": "10r/m", "oauth": "30r/m", "api": "10r/s"}


class SiteError(ValueError):
    pass


@dataclass(frozen=True)
class Link:
    label: str
    href: str
    groups: tuple[str, ...] = ()  # shown only to members of one of these (the backend still checks)

    def shown_to(self, groups: set[str] | frozenset[str]) -> bool:
        return not self.groups or bool(set(self.groups) & set(groups))


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
    description: str = ""
    audience: str = ""
    upstream: str = ""
    groups: tuple[str, ...] = ()
    menu: str = ""  # the menu label; "" = not in the portal's menu
    menu_href: str = ""
    links: tuple[Link, ...] = ()
    code: str = ""  # a line shown in a <code> on its card on the main page (an address to connect to)
    card: bool = True
    # An app hosted by the site itself (portal/apps.py): `static` serves its built files at /apps/<id>/
    # (true: from <apps_root>/<id>, or a directory), `storage` gives each user a JSON store at
    # /apps/<id>/api/. Their routes are generated; the app's audience is its id.
    static: bool | str = False
    storage: bool = False
    # A static app that is the site's pages: every path here (and below, but "/" exactly) serves its
    # index.html; it reads the services' APIs. `public`: its files need no sign-in (the APIs do).
    pages: tuple[str, ...] = ()
    public: bool = False
    build: str = ""  # its built files in the code tree (web/dist): the installer publishes them when there
    routes: tuple[Route, ...] = ()


@dataclass(frozen=True)
class Site:
    apps: tuple[App, ...] = field(default_factory=tuple)

    @property
    def audiences(self) -> tuple[str, ...]:
        return tuple(sorted({a.audience for a in self.apps if a.audience}))

    def menu(self, groups: set[str] | frozenset[str] = frozenset()) -> list[Link]:
        return [Link(a.menu, a.menu_href or (a.links[0].href if a.links else "/")) for a in self.apps
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
        d["groups"] = tuple(d.get("groups", ()))
        d["pages"] = tuple(d.get("pages", ()))
        known = set(App.__dataclass_fields__) - {"routes", "links"}
        bad = set(d) - known
        if bad:
            raise SiteError(f"app {d.get('id')}: unknown fields {sorted(bad)}")
        a = App(**d, routes=routes, links=links)
        if not NAME.match(a.id):
            raise SiteError(f"app id {a.id!r}: lowercase letters, digits and -")
        if a.static or a.storage:
            a = _hosted(a, f)
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
    return Site(tuple(apps))


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
                         nginx=f"alias {root.rstrip('/')}/;\nindex index.html;\ntry_files $uri {base}/index.html;",
                         note="its built files")]
    for page in a.pages:
        if not a.static or not page.startswith("/") or any(c in page for c in "{};\n "):
            raise SiteError(f"app {a.id}: pages are paths (/, /account/) of a static app")
        # the page's address stays; nginx answers it with the app's index.html, which routes itself
        routes.append(Route(path=page, match="exact" if page == "/" else "prefix", auth="public", page=True,
                            nginx=f"rewrite ^ {base}/index.html last;", note="the site's pages (an app)"))
    links = a.links or ((Link("열기", f"{base}/"),) if a.static else ())
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
