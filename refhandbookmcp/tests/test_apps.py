"""The apps the site hosts: generated routes (portal/site.py), each user's storage (portal/apps.py),
and publishing their built files (portal/deploy.py)."""
import pytest
from conftest import SITE
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

from portal import deploy, site, tokens
from portal.apps import Store, create_app
from portal.config import Settings
from portal.facts import facts

ISS = "https://www.m00nny.kr"


@pytest.fixture
def key():
    return Ed25519PrivateKey.generate()


@pytest.fixture
def client(tmp_path, key):
    s = Settings(session_secret="x" * 40, audit_log=str(tmp_path / "a.log"), sso_issuer=ISS, site_file=str(SITE),
                 apps_max_keys=3, apps_max_value=1000)
    return TestClient(create_app(s, Store(":memory:", s.apps_max_keys), key.public_key()))


def as_user(key, uid="alice", aud="wordgen"):
    return {"X-Auth-Token": tokens.issue(key, ISS, aud, uid)}


JSON = {"Content-Type": "application/json"}


def test_each_user_has_their_own_values(client, key):
    alice, bob = as_user(key), as_user(key, "bob")
    assert client.get("/apps/wordgen/api/me", headers=alice).json() == {"uid": "alice"}
    assert client.put("/apps/wordgen/api/store/saved-sets", headers={**alice, **JSON},
                      content='[{"title": "첫 세트"}]').status_code == 204
    assert client.get("/apps/wordgen/api/store/saved-sets", headers=alice).json() == [{"title": "첫 세트"}]
    assert client.get("/apps/wordgen/api/store/saved-sets", headers=bob).status_code == 404  # alice's alone
    assert [k["key"] for k in client.get("/apps/wordgen/api/store", headers=alice).json()["keys"]] == ["saved-sets"]
    assert client.delete("/apps/wordgen/api/store/saved-sets", headers=alice).status_code == 204
    assert client.get("/apps/wordgen/api/store/saved-sets", headers=alice).status_code == 404


def test_a_token_opens_only_its_own_app(client, key):
    assert client.get("/apps/wordgen/api/me").status_code == 401
    assert client.get("/apps/wordgen/api/me", headers=as_user(key, aud="account")).status_code == 401
    assert client.get("/apps/agents/api/me", headers=as_user(key, aud="agents")).status_code == 404  # no storage
    forged = {"X-Auth-Token": tokens.issue(Ed25519PrivateKey.generate(), ISS, "wordgen", "alice")}
    assert client.get("/apps/wordgen/api/me", headers=forged).status_code == 401


def test_writes_are_json_small_and_few(client, key):
    alice = as_user(key)
    put = lambda k, body, h=JSON: client.put(f"/apps/wordgen/api/store/{k}", headers={**alice, **h}, content=body)  # noqa: E731
    assert put("a", "{}", {"Content-Type": "text/plain"}).status_code == 415  # what a cross-site form sends
    assert put("a", "not json").status_code == 400
    assert put("a", '"' + "x" * 2000 + '"').status_code == 413
    assert put("Bad Key", "1").status_code == 400
    for k in ("a", "b", "c"):
        assert put(k, "1").status_code == 204
    assert put("d", "1").status_code == 409  # at most 3 keys here
    assert put("a", "2").status_code == 204  # replacing one is fine


def test_a_hosted_app_gets_its_routes(tmp_path):
    f = facts(str(SITE))
    wordgen = next(a for a in site.load(SITE, f).apps if a.id == "wordgen")
    assert wordgen.audience == "wordgen" and wordgen.links[0].href == "/apps/wordgen/"
    out = site.render_locations(site.load(SITE, f), "m00nny")
    assert "alias /var/www/m00nny/apps/wordgen/;" in out and "proxy_pass http://127.0.0.1:8100;" in out
    bad = tmp_path / "site.toml"
    bad.write_text('[[app]]\nid = "x"\ntitle = "X"\nstorage = true\naudience = "account"\n')
    with pytest.raises(site.SiteError, match="audience is its id"):
        site.load(bad, f)
    bad.write_text('[[app]]\nid = "x"\ntitle = "X"\nstatic = "relative/dir"\n')
    with pytest.raises(site.SiteError, match="absolute"):
        site.load(bad, f)


def test_publishing_replaces_the_apps_files(tmp_path):
    f = facts(str(SITE))
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<h1>v1</h1>")
    (dist / "assets" / "old.js").write_text("1")
    root = tmp_path / "root"
    assert deploy.install_app(f, SITE, "wordgen", dist, root) == 0
    target = root / "var/www/m00nny/apps/wordgen"
    assert (target / "index.html").read_text() == "<h1>v1</h1>"
    (dist / "assets" / "old.js").unlink()
    (dist / "index.html").write_text("<h1>v2</h1>")
    assert deploy.install_app(f, SITE, "wordgen", dist, root) == 0
    assert (target / "index.html").read_text() == "<h1>v2</h1>" and not (target / "assets/old.js").exists()
    assert deploy.install_app(f, SITE, "account", dist, root) == 1  # not a hosted app
    assert deploy.install_app(f, SITE, "wordgen", tmp_path, root) == 1  # no build there
