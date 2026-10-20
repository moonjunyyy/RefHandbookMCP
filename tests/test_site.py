"""The site's services from the site file (portal/site.py, deploy/site.toml)."""
import re
from pathlib import Path

import pytest

from conftest import SITE
from portal import site
from portal.facts import facts



def load():
    return site.load(SITE, facts(str(SITE)))


def test_the_shipped_file_declares_the_site():
    s = load()
    assert s.audiences == ("account", "refhandbook")
    assert {a.id for a in s.apps} >= {"account", "agents", "refhandbook"}


def test_only_the_routes_minted_for_receive_a_token():
    out = site.render_locations(load(), "m00nny")
    blocks = dict(re.findall(r"(location [^{]+)\{(.*?)\n\}", out, re.S))

    def block(head):
        return next(v for k, v in blocks.items() if k.strip().split("   #")[0].strip() == head)

    assert "proxy_set_header X-Auth-Token $auth_token;" in block("location /account/")
    assert "proxy_pass http://127.0.0.1:8080;" in block("location /account/")  # @@upstream:portal@@
    assert "proxy_set_header X-Auth-Token $auth_token;" in block("location /agents")
    for public in ("location = /account/request", "location /mcp", "location ^~ /.well-known/oauth-",
                   "location ~ ^/(register|authorize|token|revoke)$"):
        assert 'proxy_set_header X-Auth-Token "";' in block(public) and "auth_request" not in block(public)
    assert "proxy_buffering off;" in block("location /mcp")
    m = site.render_map(load(), "m00nny")
    assert "~^/agents(/|\\?|$)" in m and "~^/login(\\?|$)" in m and "zone=m00nny_login" in m


def test_the_landing_page_has_a_card_per_app():
    page = site.render_index(load(), "m00nny")
    for title in ("계정", "에이전트 · 샌드박스", "핸드북 (Claude MCP)"):
        assert f"<h2>{title}</h2>" in page
    assert "<code>https://www.m00nny.kr/mcp</code>" in page  # the derived domain


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


def test_the_menu_follows_groups():
    s = site.Site((site.App("a", "A", menu="A", menu_href="/a"), site.App("b", "B", menu="B", groups=("admin",))))
    assert [ln.label for ln in s.menu({"user"})] == ["A"]
    assert [ln.label for ln in s.menu({"admin"})] == ["A", "B"]
