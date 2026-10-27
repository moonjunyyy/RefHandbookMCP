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
    assert s.audiences == ("account", "refhandbook", "site", "wordgen")
    assert {a.id for a in s.apps} >= {"account", "agents", "refhandbook", "site"}
    pages = next(a for a in s.apps if a.id == "site")
    assert pages.pages == ("/", "/apps", "/settings", "/account/", "/agents/") and pages.public and not pages.card
    # its files are public; each person's settings are in its store, behind the sign-in, for it alone
    assert pages.audience == "site" and pages.storage
    routes = {(r.match, r.path): r for r in pages.routes}
    assert routes[("exact", "/apps")].page and routes[("exact", "/settings")].page  # /apps/<id>/ stay the apps'
    assert routes[("prefix", "/apps/site/api/")].auth == "site" and routes[("prefix", "/apps/site/")].auth == "public"
    assert all(a.icon for a in s.apps if a.card)


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
])
def test_a_bad_entry_is_refused_before_anything_is_written(tmp_path, bad, message):
    f = tmp_path / "site.toml"
    f.write_text(bad)
    with pytest.raises(site.SiteError, match=message):
        site.load(f, facts(str(SITE)))


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
