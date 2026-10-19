"""The site's services from one file (portal/site.py, deploy/site/apps.toml)."""
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from portal import site

APPS = Path(__file__).parent.parent / "deploy" / "site" / "apps.toml"


def test_the_shipped_file_declares_the_site():
    s = site.load(APPS)
    assert s.audiences == ("account", "refhandbook")
    assert {a.id for a in s.apps} >= {"account", "dav", "agents", "refhandbook"}


def test_only_the_routes_minted_for_receive_a_token():
    out = site.render_locations(site.load(APPS))
    blocks = dict(re.findall(r"(location [^{]+)\{(.*?)\n\}", out, re.S))

    def block(head):
        return next(v for k, v in blocks.items() if k.strip().split("   #")[0].strip() == head)

    assert "proxy_set_header X-Auth-Token $auth_token;" in block("location /account/")
    assert "proxy_set_header X-Auth-Token $auth_token;" in block("location /agents")
    for public in ("location = /account/request", "location /mcp", "location ^~ /.well-known/oauth-",
                   "location ~ ^/(register|authorize|token|revoke)$"):
        assert 'proxy_set_header X-Auth-Token "";' in block(public) and "auth_request" not in block(public)
    dav = block("location /dav/")
    assert "auth_request /_auth;" in dav and "@signin" not in dav and "X-Auth-Token" not in dav
    assert "proxy_buffering off;" in block("location /mcp")
    m = site.render_map(site.load(APPS))
    assert "~^/agents(/|\\?|$)" in m and "~^/login(\\?|$)" in m and "dav" not in m


def test_the_landing_page_has_a_card_per_app():
    page = site.render_index(site.load(APPS))
    for title in ("계정", "파일 (WebDAV)", "에이전트 · 샌드박스", "핸드북 (Claude MCP)"):
        assert f"<h2>{title}</h2>" in page
    assert "&lt;사용자명&gt;" in page  # escaped


@pytest.mark.parametrize("bad, message", [
    ('[[app]]\nid = "x"\ntitle = "X"\nupstream = "http://a"\n[[app.route]]\npath = "/a"\n[[app.route]]\npath = "/a"\n',
     "declared twice"),
    ('[[app]]\nid = "x"\ntitle = "X"\ncolour = "red"\n', "unknown fields"),
    ('[[app]]\nid = "x"\ntitle = "X"\nupstream = "http://a"\n[[app.route]]\npath = "/a"\nlimit = "huge"\n', "limit"),
    ('[[app]]\nid = "x"\ntitle = "X"\n[[app.route]]\npath = "/a"\n', "no upstream"),
    ('[[app]]\nid = "x"\ntitle = "X"\naudience = "Bad Name"\n', "audience"),
    ('[[app]]\nid = "x"\ntitle = "X"\nupstream = "http://a"\n[[app.route]]\npath = "/a;}"\n', "no braces"),
])
def test_a_bad_entry_is_refused_before_anything_is_written(tmp_path, bad, message):
    f = tmp_path / "apps.toml"
    f.write_text(bad)
    with pytest.raises(site.SiteError, match=message):
        site.load(f)


def test_the_menu_follows_groups():
    s = site.Site((site.App("a", "A", menu="A", menu_href="/a"), site.App("b", "B", menu="B", groups=("admin",))))
    assert [ln.label for ln in s.menu({"user"})] == ["A"]
    assert [ln.label for ln in s.menu({"admin"})] == ["A", "B"]


@pytest.mark.skipif(shutil.which("nginx") is None, reason="nginx is not installed")
def test_the_rendered_site_passes_nginx_t(tmp_path):
    """The whole site config, with the generated snippets, as nginx itself reads it."""
    snippets, sites = tmp_path / "snippets", tmp_path / "sites"
    sites.mkdir()
    assert site.main(["render", str(APPS), "--nginx-dir", str(snippets), "--index", str(tmp_path / "index.html")]) == 0
    shutil.copy(APPS.parent / "m00nny-proxy.conf", snippets)
    (snippets / "m00nny-apps.conf").write_text((snippets / "m00nny-apps.conf").read_text()
                                               .replace("/data/.upload", str(tmp_path / "upload")))
    subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", tmp_path / "k.pem",
                    "-out", tmp_path / "c.pem", "-subj", "/CN=t", "-days", "1"], check=True, capture_output=True)
    conf = (APPS.parent / "www.m00nny.kr.conf").read_text()
    conf = conf.replace("/etc/letsencrypt/live/www.m00nny.kr/fullchain.pem", str(tmp_path / "c.pem"))
    conf = conf.replace("/etc/letsencrypt/live/www.m00nny.kr/privkey.pem", str(tmp_path / "k.pem"))
    version = subprocess.run(["nginx", "-v"], capture_output=True, text=True).stderr
    if tuple(int(x) for x in re.search(r"(\d+)\.(\d+)", version).groups()) < (1, 25):
        conf = conf.replace("    http2 on;\n", "")  # `http2 on` is nginx 1.25.1+
    (sites / "www.conf").write_text(conf)
    mods = [f"load_module {m};" for m in Path("/usr/lib/nginx/modules").glob("ngx_http_dav_ext_module.so")]
    if not mods:
        pytest.skip("nginx's dav_ext module is not installed")
    (tmp_path / "nginx.conf").write_text("\n".join(mods) + f"\npid {tmp_path}/nginx.pid;\nerror_log {tmp_path}/e.log;\n"
                                         "events {}\nhttp { include sites/www.conf; }\n")
    r = subprocess.run(["nginx", "-t", "-p", str(tmp_path), "-c", str(tmp_path / "nginx.conf")],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
