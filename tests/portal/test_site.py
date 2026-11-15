"""The site's services from the site file (portal/site.py, deploy/site.toml)."""
import re

import pytest

from .conftest import SITE
from portal import site
from portal.facts import facts



def load():
    return site.load(SITE, facts(str(SITE)))


def test_the_shipped_file_declares_the_site():
    s = load()
    assert s.audiences == ("account", "calendar", "eq-sandbox", "refhandbook", "site", "vault", "wordgen")
    assert {a.id for a in s.apps} >= {"account", "agents", "refhandbook", "site", "projects", "calendar", "vault"}
    pages = next(a for a in s.apps if a.id == "site")
    assert pages.pages == ("/", "/apps", "/app/", "/settings", "/projects", "/projects/", "/account/", "/agents/",
                           "/calendar", "/vault", "/vault/", "/board")
    assert pages.public and not pages.card
    # its files are public; each person's settings are in its store, behind the sign-in, for it alone
    assert pages.audience == "site" and pages.storage
    routes = {(r.match, r.path): r for r in pages.routes}
    assert routes[("exact", "/apps")].page and routes[("exact", "/settings")].page  # /apps/<id>/ stay the apps'
    assert routes[("prefix", "/apps/site/api/")].auth == "site" and routes[("prefix", "/apps/site/")].auth == "public"
    assert all(a.icon for a in s.apps if a.card)
    # the person's look: the kinds the settings page offers, each led by theme.css's own (no tokens redeclared)
    assert [k for k in site.LOOK_KINDS if s.look[k]] == list(site.LOOK_KINDS) and 0 in s.look["columns"]
    assert all(not (c.get("tokens") or c.get("light")) for c in (s.look[k][0] for k in site.LOOK_KINDS))
    assert s.look_in("en")["palette"][1]["label"] == "Forest" and "tr" not in s.look_in("ko")["palette"][1]


def test_the_catalog_speaks_of_each_app_as_a_product():
    """docs/apps-vault-calendar.md §1: a product name (no status in brackets, no middle-dot pairing), a
    tagline of one line, an introduction of a sentence or three, tags from the vocabulary — in both languages."""
    s = load()
    for a in s.apps:
        if not a.card:
            continue
        for lang in ("ko", "en"):
            title, tagline, about = a.text("title", lang), a.text("description", lang), a.text("about", lang)
            assert "(" not in title and "·" not in title and len(title) <= 24, (a.id, lang, title)
            assert 0 < len(tagline) <= 48 and "\n" not in tagline and not tagline.endswith("."), (a.id, lang, tagline)
            assert 1 <= about.count(".") <= 3 and len(about) <= 240, (a.id, lang, about)
        assert set(a.tags) <= set(site.TAGS) and (a.tags or not a.optional), a.id  # every app in the catalog has a tag
    assert [t for t in site.TAGS] == ["연구", "글쓰기", "AI", "도구", "일정", "자료"]


def test_a_service_app_declares_its_widgets_pages_and_routes():
    s = load()
    cal = next(a for a in s.apps if a.id == "calendar")
    assert cal.audience == "calendar" and cal.upstream.endswith(":8120") and cal.menu_href == "/calendar"
    assert [(w.id, w.href, w.size) for w in cal.widgets] == [("today", "/apps/site/widgets/calendar.js", "2x1"),
                                                            ("upcoming", "/apps/site/widgets/calendar.js", "1x1"),
                                                            ("month", "/apps/site/widgets/calendar.js", "2x2"),
                                                            ("tasks", "/apps/site/widgets/calendar.js", "1x1")]
    routes = {r.path: r for r in cal.routes}
    assert not routes["/calendar/api/"].signin and routes["/calendar/feed/"].auth == "public"
    # CalDAV: public (the service answers its own 401 with Basic), a body for an event, and the discovery redirect
    assert routes["/calendar/dav/"].auth == "public" and not routes["/calendar/dav/"].signin and routes["/calendar/dav/"].body
    wk = routes["/.well-known/caldav"]
    assert wk.match == "exact" and wk.auth == "public" and wk.nginx.startswith("return 301 /calendar/dav/")
    assert "location = /.well-known/caldav" in site.render_locations(s, "m00nny")
    assert cal.default and vault.default if (vault := next(a for a in s.apps if a.id == "vault")) else False
    vault = next(a for a in s.apps if a.id == "vault")
    assert vault.audience == "vault" and vault.upstream.endswith(":8110")
    assert [(w.id, w.size) for w in vault.widgets] == [("recent", "1x1"), ("tags", "1x1"), ("home", "2x2")]
    assert {r.path for r in vault.routes} == {"/vault/api/"} and vault.routes[0].body == "5m"
    projects = next(a for a in s.apps if a.id == "projects")
    assert not projects.audience and not projects.routes and projects.widgets[0].href == "/apps/site/widgets/projects.js"
    assert next(a for a in s.apps if a.id == "account").links[0].href == "/account/"  # the projects link became an app
    board = next(a for a in s.apps if a.id == "board")  # the public board: the handbook's API, the pages app's page
    assert board.audience == "refhandbook" and board.upstream.endswith(":8765") and board.menu_href == "/board" and board.default
    assert [(w.id, w.href) for w in board.widgets] == [("news", "/apps/site/widgets/board.js")]
    assert [(r.path, r.signin) for r in board.routes] == [("/board/api/", False)]


def _blocks(out):
    blocks = dict(re.findall(r"(location [^{]+)\{(.*?)\n\}", out, re.S))

    def block(head):
        return next(v for k, v in blocks.items() if k.strip().split("   #")[0].strip() == head)
    return block


def test_the_pages_take_their_paths_only_once_published():
    before = _blocks(site.render_locations(load(), "m00nny", live=set()))  # the pages app not published yet
    assert "proxy_pass http://127.0.0.1:8080;" in before("location /account/")  # the portal's own pages still
    out = site.render_locations(load(), "m00nny", live={"site"})
    after = _blocks(out)
    for page in ("location = /", "location /account/", "location /agents/"):
        assert after(page).strip().endswith("rewrite ^ /apps/site/index.html last;") and "auth_request" not in after(page)
    assert out.count("location /account/ {") == 1  # the portal's /account/ gave way, its API and public pages did not
    assert "proxy_pass http://127.0.0.1:8080;" in after("location /account/api/")
    assert "auth_request" not in after("location /apps/site/")  # the pages' files are public; the APIs are not


def test_only_the_routes_minted_for_receive_a_token():
    out = site.render_locations(load(), "m00nny")
    block = _blocks(out)
    assert "proxy_set_header X-Auth-Token $auth_token;" in block("location /account/api/")
    assert "proxy_pass http://127.0.0.1:8080;" in block("location /account/api/")  # @@upstream:portal@@
    for api in ("location /agents/api/", "location /approvals"):
        assert "proxy_set_header X-Auth-Token $auth_token;" in block(api)
    for public in ("location = /account/request", "location /mcp", "location ^~ /.well-known/oauth-",
                   "location ~ ^/(register|authorize|token|revoke)$"):
        assert 'proxy_set_header X-Auth-Token "";' in block(public) and "auth_request" not in block(public)
    assert "proxy_buffering off;" in block("location /mcp")
    m = site.render_map(load(), "m00nny")
    assert "~^/approvals(/|\\?|$)" in m and "~^/agents/api(/|\\?|$)" in m and "~^/login(\\?|$)" in m
    assert "zone=m00nny_login" in m


def test_the_invitation_sign_up_is_public_and_throttled():
    out = site.render_locations(load(), "m00nny")
    block = re.search(r"location /account/join/ \{.*?\n\}", out, re.S).group(0)
    assert "auth_request" not in block and "zone=m00nny_login" in block and 'X-Auth-Token "";' in block


@pytest.mark.parametrize("bad, message", [
    ('[[app]]\nid = "x"\ntitle = "X"\nupstream = "http://a"\n[[app.route]]\npath = "/a"\n[[app.route]]\npath = "/a"\n',
     "declared twice"),
    ('[[app]]\nid = "x"\ntitle = "X"\ncolour = "red"\n', "unknown fields"),
    ('[[app]]\nid = "x"\ntitle = "X"\nupstream = "http://a"\n[[app.route]]\npath = "/a"\nlimit = "huge"\n', "limit"),
    ('[[app]]\nid = "x"\ntitle = "X"\n[[app.route]]\npath = "/a"\n', "no upstream"),
    ('[[app]]\nid = "x"\ntitle = "X"\naudience = "Bad Name"\n', "audience"),
    ('[[app]]\nid = "x"\ntitle = "X"\nupstream = "http://a"\n[[app.route]]\npath = "/a;}"\n', "no braces"),
    ('[[app]]\nid = "x"\ntitle = "X"\nupstream = "@@upstream:nope@@"\n', "no role"),
    ('[[app]]\nid = "x"\ntitle = "@@nothing@@"\n', "unknown placeholder"),
    ('[[app]]\nid = "x"\ntitle = "X"\ntags = ["연구", "nope"]\n', "tags are among"),
    ('[[app]]\nid = "x"\ntitle = "X"\ntr.en = { tags = ["x"] }\n', "names title, description, about or menu"),
    ('[look]\nshadow = []\n', "unknown kinds"),
    ('[[look.corner]]\nid = "x"\nlabel = "X"\ntokens = { radius = "1px; } body { color: red" }\n', "without"),
    ('[[look.palette]]\nid = "x"\nlabel = "X"\nlight = { accent = "#000" }\ndark = {}\n', "the same tokens"),
    ('[look]\ncolumns = [3, 40]\n', "columns"),
    ('[[app]]\nid = "x"\ntitle = "X"\ncode = 3\n', "a string or a list"),
    ('[[app]]\nid = "x"\ntitle = "X"\ncode = [{ label = "a" }]\n', "with a value"),
    ('[[app]]\nid = "x"\ntitle = "X"\ncode = [{ value = "v", href = "h" }]\n', "with a value"),
])
def test_a_bad_entry_is_refused_before_anything_is_written(tmp_path, bad, message):
    f = tmp_path / "site.toml"
    f.write_text(bad)
    with pytest.raises(site.SiteError, match=message):
        site.load(f, facts(str(SITE)))


def test_an_app_gives_its_ways_to_connect(tmp_path):
    """`code`: one line (a string), or one labelled address per client; {user} is the person looking."""
    smb = next(a for a in load().apps if a.id == "smb")
    assert [c.value for c in smb.code] == ["net use \\\\samba.m00nny.kr\\{user} /TCPPORT:38445",
                                          "\\\\samba.m00nny.kr\\{user}", "smb://samba.m00nny.kr:38445/{user}"]
    assert [c.label_in("en") for c in smb.code] == ["Windows — connect once (Command Prompt)",
                                                    "Windows — Explorer address", "macOS · Linux · others"]
    assert smb.code[0].label_in("ko").startswith("Windows") and smb.text("title", "en") == "SMB Storage"
    f = tmp_path / "site.toml"
    f.write_text('[[app]]\nid = "x"\ntitle = "X"\ncode = "ssh x.example"\n')
    (x,) = site.load(f, facts(str(SITE))).apps
    assert [(c.label, c.value) for c in x.code] == [("", "ssh x.example")]


def test_the_main_pages_cards_follow_groups_down_to_each_link():
    s = site.Site((site.App("acct", "Account", links=(site.Link("Mine", "/a/"), site.Link("Users", "/a/admin", ("admin",)))),
                   site.App("lab", "Lab", groups=("admin",))))
    cards = s.cards({"user"})
    assert [a.id for a in cards] == ["acct"] and [ln.label for ln in cards[0].links] == ["Mine"]
    cards = s.cards({"admin"})
    assert [a.id for a in cards] == ["acct", "lab"] and [ln.label for ln in cards[0].links] == ["Mine", "Users"]


def test_the_site_file_offers_the_admin_pages_to_admins_only():
    acct = next(a for a in site.load(SITE, facts(str(SITE))).apps if a.id == "account")
    admin = {ln.label: ln.groups for ln in acct.links}
    assert admin["내 계정"] == () and "admin" in admin["사용자 관리"] and "helpdesk" in admin["사용자 관리"]


def test_the_menu_follows_groups():
    s = site.Site((site.App("a", "A", menu="A", menu_href="/a"), site.App("b", "B", menu="B", groups=("admin",))))
    assert [ln.label for ln in s.menu({"user"})] == ["A"]
    assert [ln.label for ln in s.menu({"admin"})] == ["A", "B"]


def _luminance(hex_: str) -> float:
    c = [int(hex_.lstrip("#")[i:i + 2], 16) / 255 for i in (0, 2, 4)] if len(hex_) == 7 else [int(x * 2, 16) / 255 for x in hex_.lstrip("#")]
    lin = [x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def _contrast(a: str, b: str) -> float:
    la, lb = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def test_every_palette_of_the_look_reads_in_both_themes():
    """docs/frame.md §1.3: a palette the site file declares redeclares the accent tokens over theme.css; in each theme
    every pairing the parts make of them (a button's text on it and on its hover, a link or a secondary button on the
    page and on a card, a hover on the soft accent) is at least 4.5:1, as theme.css's own palette is."""
    import re as _re
    import tomllib
    from pathlib import Path

    theme = (Path(__file__).resolve().parents[2] / "src/portal/static/theme.css").read_text()
    blocks = {"light": _re.search(r":root \{(.*?)\n\}", theme, _re.S).group(1), "dark": _re.search(r':root\[data-theme="dark"\] \{(.*?)\n\}', theme, _re.S).group(1)}
    base = {}
    for scheme, block in blocks.items():
        tokens = dict(_re.findall(r"--([a-z-]+):\s*(#[0-9a-f]{3,6}\b|var\(--[a-z-]+\))", blocks["light"] + block))
        base[scheme] = {name: tokens.get(value[6:-1], value) if value.startswith("var(") else value
                        for name, value in tokens.items()}
    look = site._look(tomllib.loads(SITE.read_text()))
    pairs = [("accent-text", "accent"), ("accent-text", "accent-hover"), ("accent", "bg"), ("accent", "card"), ("accent-hover", "accent-soft"), ("accent", "accent-soft")]
    low = []
    for p in [{"id": "theme.css", "light": {}, "dark": {}}, *look["palette"]]:
        for scheme in ("light", "dark"):
            t = {**base[scheme], **p[scheme]}
            for fg, bg in pairs:
                r = _contrast(t[fg], t[bg])
                if r < 4.5:
                    low.append(f"{p['id']} {scheme}: {fg} on {bg} {r:.2f}")
    assert not low, "palettes below 4.5:1:\n" + "\n".join(low)
