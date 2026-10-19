"""The site's services, declared once (deploy/site/apps.toml) and read by everything that needs them.

A service ("app") is a backend the site sign-in fronts: the account portal, refhandbook, WebDAV, and
whatever comes next. Its entry says where it lives (routes), whom tokens are minted for (audience),
and how it is shown (title, description, links, menu). From that one file:

    nginx      `python -m portal.site render` writes two snippets: the audience map (http level)
               and the locations (inside the server block of deploy/site/www.m00nny.kr.conf)
    landing    the same command writes the landing page's cards (index.html)
    SSO        mints tokens only for the audiences the file declares (with PORTAL_SSO_AUDIENCES)
    portal     links the apps marked `menu` in its header, to the groups that may see them

Adding a service is one [[app]] entry, `render`, and `nginx -t && systemctl reload nginx`.

Rules the renderer enforces, so a new entry cannot weaken the site by omission:
  - a `site` route goes through the sign-in (auth_request) and, if its app has an audience, carries
    a token minted for that audience alone; a `public` route clears X-Auth-Token, so no backend ever
    receives a token it did not ask nginx for
  - every route path is unique, every limit names a declared zone, ids and audiences are plain names
  - raw nginx directives (`nginx = "..."`) are allowed for what the schema does not cover (WebDAV),
    and are copied verbatim: review them like the config they are
"""

from __future__ import annotations

import argparse
import html
import re
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

NAME = re.compile(r"^[a-z][a-z0-9-]{0,31}$")
MATCHES = ("prefix", "exact", "regex", "priority")  # priority = `^~` (a prefix that wins over regexes)
AUTH = ("site", "public")
ZONES = {"login": "m00nny_login", "oauth": "m00nny_oauth"}
ZONE_RATES = {"m00nny_login": "10r/m", "m00nny_oauth": "30r/m"}


class SiteError(ValueError):
    pass


@dataclass(frozen=True)
class Link:
    label: str
    href: str


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
    #                      WWW-Authenticate through (WebDAV clients answer it with Basic)
    nginx: str = ""
    note: str = ""


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
    code: str = ""  # a line shown in a <code> on the landing card (an address to connect to)
    card: bool = True
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


def load(path: str | Path) -> Site:
    data = tomllib.loads(Path(path).read_text())
    apps, seen_ids, seen_paths = [], set(), set()
    for d in data.get("app", []):
        d = dict(d)
        routes = tuple(_route(d.get("id", "?"), r) for r in d.pop("route", []))
        links = tuple(Link(**ln) for ln in d.pop("link", []))
        d["groups"] = tuple(d.get("groups", ()))
        known = set(App.__dataclass_fields__) - {"routes", "links"}
        bad = set(d) - known
        if bad:
            raise SiteError(f"app {d.get('id')}: unknown fields {sorted(bad)}")
        a = App(**d, routes=routes, links=links)
        if not NAME.match(a.id):
            raise SiteError(f"app id {a.id!r}: lowercase letters, digits and -")
        if a.audience and not NAME.match(a.audience):
            raise SiteError(f"app {a.id}: audience {a.audience!r}: lowercase letters, digits and -")
        if a.id in seen_ids:
            raise SiteError(f"app {a.id} is declared twice")
        seen_ids.add(a.id)
        for r in routes:
            key = (r.match, r.path)
            if key in seen_paths:
                raise SiteError(f"route {r.match} {r.path} is declared twice")
            seen_paths.add(key)
            if not (r.upstream or a.upstream) and "alias" not in r.nginx and "return" not in r.nginx:
                raise SiteError(f"app {a.id}: route {r.path} has no upstream (and no alias/return of its own)")
        apps.append(a)
    return Site(tuple(apps))


# ── nginx ────────────────────────────────────────────────────────────────


def _audience_regex(r: Route) -> str:
    """The $request_uri pattern of a route (the request URI carries the query string)."""
    if r.match == "regex":
        return f"~{r.path}"
    if r.match == "exact":
        return f"~^{re.escape(r.path)}(\\?|$)"
    return f"~^{re.escape(r.path.rstrip('/'))}(/|\\?|$)"


def render_map(site: Site) -> str:
    out = ["# Generated by `python -m portal.site render` from apps.toml: do not edit, edit apps.toml.",
           "# http level: which backend a token is minted for. $request_uri, not $uri: the map is read",
           "# inside the auth subrequest, where $uri is /_auth.",
           *[f"limit_req_zone $binary_remote_addr zone={z}:10m rate={rate};" for z, rate in ZONE_RATES.items()],
           "map $request_uri $auth_audience {", '    default "";']
    for a in site.apps:
        if not a.audience:
            continue
        for r in a.routes:
            if r.auth == "site":
                out.append(f"    {_audience_regex(r):40} {a.audience};   # {a.id}")
    out.append("}")
    return "\n".join(out) + "\n"


def _location(a: App, r: Route) -> list[str]:
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
        body.append(f"limit_req zone={ZONES[r.limit]} burst={r.burst} nodelay;")
    upstream = r.upstream or a.upstream
    if upstream and "alias" not in r.nginx and "return" not in r.nginx:
        body.append("include snippets/m00nny-proxy.conf;")
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


def render_locations(site: Site) -> str:
    out = ["# Generated by `python -m portal.site render` from apps.toml: do not edit, edit apps.toml.",
           "# Included inside the server block of www.m00nny.kr.conf."]
    for a in site.apps:
        if not a.routes:
            continue
        out += ["", f"# ── {a.id}: {a.title} " + "─" * max(0, 60 - len(a.id) - len(a.title))]
        for r in a.routes:
            out += _location(a, r)
    return "\n".join(out) + "\n"


# ── the landing page ─────────────────────────────────────────────────────

INDEX_HEAD = Path(__file__).parent / "templates" / "site_index_head.html"


def render_index(site: Site, heading: str = "m00nny", lead: str = "계정 하나(Kerberos)로 아래 서비스를 모두 씁니다.") -> str:
    cards = []
    for a in site.apps:
        if not a.card:
            continue
        e = html.escape
        links = "".join(f'<a href="{e(ln.href)}">{e(ln.label)}</a>' for ln in a.links)
        cards.append(f'    <section class="card">\n      <h2>{e(a.title)}</h2>\n'
                     + (f"      <p>{e(a.description)}</p>\n" if a.description else "")
                     + (f"      <p><code>{e(a.code)}</code></p>\n" if a.code else "")
                     + (f'      <div class="row">{links}</div>\n' if links else "")
                     + "    </section>")
    return (INDEX_HEAD.read_text() + f'<main>\n  <h1>{html.escape(heading)}</h1>\n  <p class="lead">{html.escape(lead)}</p>\n'
            '  <div class="grid">\n' + "\n".join(cards) + "\n  </div>\n</main>\n</body>\n</html>\n")


# ── CLI ──────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m portal.site", description=__doc__.split("\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("render", help="write the nginx snippets and the landing page")
    r.add_argument("apps", help="apps.toml")
    r.add_argument("--nginx-dir", default="/etc/nginx/snippets")
    r.add_argument("--index", default="/var/www/m00nny/index.html")
    c = sub.add_parser("check", help="validate apps.toml and print what it declares")
    c.add_argument("apps")
    args = p.parse_args(argv)
    try:
        site = load(args.apps)
    except (SiteError, tomllib.TOMLDecodeError, TypeError) as e:
        print(f"apps.toml: {e}", file=sys.stderr)
        return 1
    if args.cmd == "check":
        for a in site.apps:
            print(f"{a.id:12} audience={a.audience or '-':12} routes={len(a.routes)} menu={a.menu or '-'}")
        print(f"audiences: {', '.join(site.audiences)}")
        return 0
    d = Path(args.nginx_dir)
    d.mkdir(parents=True, exist_ok=True)
    (d / "m00nny-apps-map.conf").write_text(render_map(site))
    (d / "m00nny-apps.conf").write_text(render_locations(site))
    Path(args.index).parent.mkdir(parents=True, exist_ok=True)
    Path(args.index).write_text(render_index(site))
    print(f"wrote {d / 'm00nny-apps-map.conf'}, {d / 'm00nny-apps.conf'}, {args.index}; now: nginx -t && systemctl reload nginx")
    return 0


if __name__ == "__main__":
    sys.exit(main())
