"""One site file and the realm: everything on the host is derived and rendered (portal/deploy.py)."""
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from portal import deploy, facts as facts_mod
from portal.facts import facts, krb5_default_realm

REPO = Path(__file__).parent.parent
SITE = REPO / "deploy" / "site.toml"


@pytest.fixture
def fresh(monkeypatch):
    facts.cache_clear()
    yield monkeypatch
    facts.cache_clear()


def test_the_realm_comes_from_krb5_conf(tmp_path):
    k = tmp_path / "krb5.conf"
    k.write_text("[libdefaults]\n  default_realm = EXAMPLE.ORG  # ours\n[realms]\n  default_realm = NOT.THIS\n")
    assert krb5_default_realm(str(k)) == "EXAMPLE.ORG"
    assert krb5_default_realm(str(tmp_path / "none")) == ""


def test_every_fact_derives_from_the_realm(fresh, tmp_path):
    fresh.setenv("PORTAL_REALM", "LAB.EXAMPLE.ORG")
    s = tmp_path / "site.toml"
    s.write_text("")
    f = facts(str(s))
    assert (f.name, f.domain, f.base_dn, f.users_ou, f.ldap_uri, f.issuer, f.http_service, f.code) == (
        "lab", "www.lab.example.org", "dc=lab,dc=example,dc=org", "ou=Users,dc=lab,dc=example,dc=org",
        "ldaps://ldap.lab.example.org", "https://www.lab.example.org", "HTTP@www.lab.example.org", "/opt/lab-portal")
    assert (f.unit("portal"), f.conf_dir("sso"), f.state_dir("portal")) == ("lab-portal", "/etc/lab-sso",
                                                                             "/var/lib/lab-portal")
    s.write_text('[site]\ndomain = "lab.example.org"\nbase_dn = "o=lab"\n')
    facts.cache_clear()
    f = facts(str(s))
    assert (f.domain, f.base_dn, f.users_ou) == ("lab.example.org", "o=lab", "ou=Users,o=lab")


def test_nothing_rendered_names_a_site_by_hand(fresh, tmp_path):
    """Another realm, the same templates: not one m00nny anywhere."""
    fresh.setenv("PORTAL_REALM", "EXAMPLE.ORG")
    s = tmp_path / "site.toml"
    s.write_text(SITE.read_text().replace('aliases = ["m00nny.kr"]', "aliases = []"))
    files = deploy.rendered(facts(str(s)), s)
    assert set(files) >= {"/etc/systemd/system/example-portal.service", "/etc/systemd/system/example-sso.service",
                          "/etc/systemd/system/example-dav-homes.timer", "/etc/nginx/sites-available/www.example.org.conf",
                          "/etc/nginx/snippets/example-apps.conf", "/var/www/example/index.html",
                          "/etc/example/site.toml"}
    for path, (content, _) in files.items():
        if path.endswith("site.toml"):
            continue  # the input itself, copied (its comments show the m00nny derivations)
        assert "m00nny" not in content.lower(), path
        assert "@@" not in content, path
    unit = files["/etc/systemd/system/example-portal.service"][0]
    assert "User=example-portal" in unit and "ConfigurationDirectory=example-portal" in unit
    assert "EnvironmentFile=-/etc/example-portal/portal.env" in unit and "Environment=PORTAL_SITE=/etc/example/site.toml" in unit


class Recorder:
    def __init__(self):
        self.calls = []

    def __call__(self, cmd):
        self.calls.append(cmd)
        return 0


def test_install_makes_secrets_once_and_moves_an_old_layout(fresh, tmp_path, capsys):
    root = tmp_path / "root"
    old_unit = root / "etc/systemd/system/ldap-portal.service"
    old_unit.parent.mkdir(parents=True)
    old_unit.write_text("[Service]\n")
    (root / "etc/ldap-portal").mkdir(parents=True)
    (root / "etc/ldap-portal/portal.keytab").write_bytes(b"kt")
    (root / "etc/ldap-portal/portal.env").write_text("PORTAL_SESSION_SECRET=keep-me-" + "x" * 40 +
                                                     "\nPORTAL_SERVICE_KEYTAB=/etc/ldap-portal/portal.keytab\n")
    (root / "var/lib/ldap-portal").mkdir(parents=True)
    (root / "var/lib/ldap-portal/requests.db").write_bytes(b"db")
    sh = Recorder()
    assert deploy.install(SITE, root=root, sh=sh) == 0
    assert not old_unit.exists() and ["systemctl", "disable", "--now", "ldap-portal.service"] in sh.calls
    assert (root / "etc/m00nny-portal/portal.keytab").read_bytes() == b"kt"
    assert (root / "var/lib/m00nny-portal/requests.db").read_bytes() == b"db"
    env = root / "etc/m00nny-portal/portal.env"
    assert "PORTAL_SERVICE_KEYTAB=/etc/m00nny-portal/portal.keytab" in env.read_text()  # moved with its file
    secret = re.search(r"PORTAL_SESSION_SECRET=(\S+)", env.read_text()).group(1)
    assert secret.startswith("keep-me-")  # the old secret, not a new one: sessions survive the move
    sso_env = root / "etc/m00nny-sso/sso.env"
    assert len(re.search(r"PORTAL_SSO_SECRET=(\S+)", sso_env.read_text()).group(1)) > 40
    assert (sso_env.stat().st_mode & 0o777) == 0o640
    assert (root / "etc/nginx/sites-enabled/www.m00nny.kr.conf").is_symlink()
    assert (root / "opt/m00nny-portal/portal/deploy.py").exists() and not (root / "opt/m00nny-portal/.git").exists()
    assert ["systemctl", "restart", "m00nny-portal.service", "m00nny-sso.service", "m00nny-dav-homes.timer"] in sh.calls
    out = capsys.readouterr().out
    assert "ktadd -k /etc/m00nny-sso/http.keytab HTTP/www.m00nny.kr@M00NNY.KR" in out  # only what is missing
    assert "/etc/m00nny-portal/portal.keytab" not in out.split("Only an admin")[1]
    assert deploy.install(SITE, root=root, sh=Recorder()) == 0  # again: the secret stays
    assert re.search(r"PORTAL_SESSION_SECRET=(\S+)", env.read_text()).group(1) == secret


@pytest.mark.skipif(shutil.which("nginx") is None, reason="nginx is not installed")
def test_the_rendered_site_passes_nginx_t(tmp_path):
    files = deploy.rendered(facts(str(SITE)), SITE)
    conf_dir = tmp_path / "etc/nginx"
    deploy.write_rendered({k: v for k, v in files.items() if k.startswith("/etc/nginx/")}, tmp_path)
    site_conf = conf_dir / "sites-available/www.m00nny.kr.conf"
    text = site_conf.read_text()
    subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", tmp_path / "k.pem",
                    "-out", tmp_path / "c.pem", "-subj", "/CN=t", "-days", "1"], check=True, capture_output=True)
    text = text.replace("/etc/letsencrypt/live/www.m00nny.kr/fullchain.pem", str(tmp_path / "c.pem"))
    text = text.replace("/etc/letsencrypt/live/www.m00nny.kr/privkey.pem", str(tmp_path / "k.pem"))
    version = subprocess.run(["nginx", "-v"], capture_output=True, text=True).stderr
    if tuple(int(x) for x in re.search(r"(\d+)\.(\d+)", version).groups()) < (1, 25):
        text = text.replace("    http2 on;\n", "")  # `http2 on` is nginx 1.25.1+
    site_conf.write_text(text)
    apps = conf_dir / "snippets/m00nny-apps.conf"
    apps.write_text(apps.read_text().replace("/data/.upload", str(tmp_path / "upload")))
    mods = [f"load_module {m};" for m in Path("/usr/lib/nginx/modules").glob("ngx_http_dav_ext_module.so")]
    if not mods:
        pytest.skip("nginx's dav_ext module is not installed")
    (conf_dir / "nginx.conf").write_text("\n".join(mods) + f"\npid {tmp_path}/nginx.pid;\nerror_log {tmp_path}/e.log;\n"
                                         "events {}\nhttp { include sites-available/www.m00nny.kr.conf; }\n")
    r = subprocess.run(["nginx", "-t", "-p", str(conf_dir), "-c", str(conf_dir / "nginx.conf")],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_the_installer_runs_from_the_shell(tmp_path):
    out = subprocess.run([str(REPO / "deploy/install.sh"), "--check"], capture_output=True, text=True,
                         env={"PATH": "/usr/bin:/bin", "PORTAL_REALM": "M00NNY.KR"})
    assert out.returncode == 0, out.stderr
    assert "m00nny-portal" in out.stdout and "dc=m00nny,dc=kr" in out.stdout


def test_the_directory_side_names_this_sites_admins(fresh, tmp_path, monkeypatch):
    fresh.setenv("PORTAL_REALM", "EXAMPLE.ORG")
    s = tmp_path / "site.toml"
    s.write_text("")
    monkeypatch.setattr(deploy, "_admins", lambda group: ["ann", "bo"])
    files = deploy.rendered(facts(str(s)), s)
    acl = files["/etc/example/directory/kadm5.acl"][0]
    assert "portal/service@EXAMPLE.ORG  ADMCILSP  ann/user@EXAMPLE.ORG" in acl and "  bo@EXAMPLE.ORG" in acl
    ldif = files["/etc/example/directory/slapd-acl.ldif"][0]
    assert 'dn.one="ou=Users,dc=example,dc=org"' in ldif and "@@" not in ldif + acl
