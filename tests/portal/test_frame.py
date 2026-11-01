"""The site frame (docs/frame.md): what the sign-in serves to every page and app, what the site file
may declare for the main page, and the rules the pages' code is held to.

C1 the parts and the pages name no colour outside the tokens; C2 the person's theme reaches the
frame's answer; C5 widgets are validated and resolved; C6 the pages have no page-head explanations,
no explanatory paragraphs on the pages this bundle rewrote (and no more than before on the others),
and no links dressed as buttons there."""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

from portal import site
from portal.config import Settings
from portal.facts import facts
from portal.sso import create_app
from .conftest import SITE
from .test_app import FakeKerberos
from .test_sso import ISS, sign_in

ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / "src" / "portal" / "static"
WEB = ROOT / "web"
COLOUR = re.compile(r"#[0-9a-fA-F]{3,8}\b|\b(?:rgba?|hsla?)\(")


def _ours(p: Path) -> bool:
    return not p.name.startswith("._")


# ── C1: colour lives in the tokens only ───────────────────────────────────

def test_the_tokens_are_the_only_place_a_colour_is_named():
    """theme.css declares the colours; parts.css, the frame and the pages refer to them by name."""
    assert COLOUR.search((STATIC / "theme.css").read_text()), "theme.css holds the colours"
    offenders = []
    for p in [STATIC / "parts.css", STATIC / "style.css", *sorted((WEB / "src").rglob("*.ts")), *sorted((WEB / "frame").rglob("*.ts"))]:
        if not _ours(p):
            continue
        for n, line in enumerate(p.read_text().splitlines(), 1):
            if COLOUR.search(line) and "i18n: data" not in line and "colour: ok" not in line:
                offenders.append(f"{p.relative_to(ROOT)}:{n}: {line.strip()[:90]}")
    assert not offenders, "colours outside theme.css:\n" + "\n".join(offenders)


def test_the_stylesheet_is_the_two_parts():
    """style.css (the name every page links) is the tokens and the parts, nothing of its own."""
    text = (STATIC / "style.css").read_text()
    assert '@import url("theme.css")' in text and '@import url("parts.css")' in text
    assert not re.search(r"^\s*[.#\w:\[][^{]*\{", text, re.M), "style.css declares no rule of its own"
    tokens = (STATIC / "theme.css").read_text()
    for name in ("--bg", "--card", "--soft", "--text", "--muted", "--line", "--accent", "--accent-hover", "--accent-text",
                 "--accent-soft", "--ok", "--bad", "--warn", "--shadow", "--serif", "--sans", "--mono", "--radius", "--radius-s"):
        assert f"{name}:" in tokens, name
    assert '[data-theme="dark"]' in tokens and ':root:not([data-theme="light"])' in tokens  # chosen, and the OS's


# ── C2: the theme reaches every page ──────────────────────────────────────

@pytest.fixture
def key():
    return Ed25519PrivateKey.generate()


@pytest.fixture
def app(tmp_path, key):
    s = Settings(session_secret="x" * 40, sso_secret="y" * 40, cookie_secure=False,
                 audit_log=str(tmp_path / "a.log"), sso_issuer=ISS, site_file=str(SITE))
    return create_app(s, FakeKerberos(), key)


def test_the_frame_tells_the_persons_theme_and_its_version(app):
    c = TestClient(app)
    me = c.get("/auth/api/v1/me").json()
    assert me["theme"] == "auto" and me["frame"] == site.FRAME
    assert c.get("/auth/api/v1/me", cookies={"theme": "dark"}).json()["theme"] == "dark"
    assert c.get("/auth/api/v1/me", cookies={"theme": "sepia"}).json()["theme"] == "auto"  # not a theme we have
    c, _ = sign_in(app)
    assert c.get("/auth/api/v1/me", cookies={"theme": "light"}).json()["theme"] == "light"


def test_the_sign_in_serves_the_frame(app):
    c = TestClient(app)
    for name, must in (("theme.js", "data-theme"), ("theme.css", "--bg:"), ("parts.css", ".card"), ("style.css", "@import"),
                       ("site.js", "export")):
        r = c.get(f"/auth/static/{name}")
        assert r.status_code == 200 and must in r.text, name
    for page in ("/auth/login", "/"):
        assert 'src="/auth/static/theme.js"' in c.get(page).text  # before the stylesheet: no flash of the wrong theme


# ── C4, C5: optional apps and widgets ─────────────────────────────────────

def test_the_shipped_file_keeps_the_account_on_and_offers_a_widget():
    s = site.load(SITE, facts(str(SITE)))
    account = next(a for a in s.apps if a.id == "account")
    assert not account.optional and all(a.optional for a in s.apps if a.id != "account")
    eq = next(a for a in s.apps if a.id == "eq-sandbox")
    assert [(w.id, w.href, w.size) for w in eq.widgets] == [("boards", "/apps/eq-sandbox/widget.js", "1x1")]
    assert eq.widgets[0].text("title", "en") == "Recent boards" and eq.widgets[0].text("title", "ko") == "최근 작업판"


def test_the_frame_lists_each_apps_widgets(app):
    me = TestClient(app).get("/auth/api/v1/me").json()
    eq = next(x for x in me["cards"] if x["id"] == "eq-sandbox")
    assert eq["optional"] is True and eq["widgets"] == [{"id": "boards", "title": "최근 작업판", "href": "/apps/eq-sandbox/widget.js", "size": "1x1"}]
    assert next(x for x in me["cards"] if x["id"] == "account")["optional"] is False
    assert eq["tags"] == ["연구", "도구"] and eq["about"].startswith("방정식의 항을")
    en = TestClient(app).get("/auth/api/v1/me", headers={"Accept-Language": "en"}).json()
    assert next(x for x in en["cards"] if x["id"] == "eq-sandbox")["tags"] == ["Research", "Tools"]


WIDGET = '[[app]]\nid = "x"\ntitle = "X"\nstatic = true\n[[app.widget]]\n'


@pytest.mark.parametrize("bad, message", [
    (WIDGET + 'id = "w"\ntitle = "W"\nmodule = "w.js"\n[[app.widget]]\nid = "w"\ntitle = "W2"\nmodule = "w2.js"\n', "declared twice"),
    (WIDGET + 'id = "w"\ntitle = "W"\nmodule = "w.js"\nsize = "3x3"\n', "size is one of"),
    (WIDGET + 'id = "w"\ntitle = "W"\n', "needs id, title and module"),
    (WIDGET + 'id = "w"\ntitle = "W"\nmodule = "w.js"\ncolour = "red"\n', "unknown widget fields"),
    (WIDGET + 'id = "Bad Id"\ntitle = "W"\nmodule = "w.js"\n', "widget id"),
    (WIDGET + 'id = "w"\ntitle = "W"\nmodule = "w.js"\ntr.en = { description = "x" }\n', "names title"),
    ('[[app]]\nid = "x"\ntitle = "X"\nupstream = "http://a"\n[[app.widget]]\nid = "w"\ntitle = "W"\nmodule = "w.js"\n',
     "absolute path"),
])
def test_a_bad_widget_is_refused(tmp_path, bad, message):
    f = tmp_path / "site.toml"
    f.write_text(bad)
    with pytest.raises(site.SiteError, match=message):
        site.load(f, facts(str(SITE)))


def test_a_services_widget_names_its_own_path(tmp_path):
    f = tmp_path / "site.toml"
    f.write_text('[[app]]\nid = "x"\ntitle = "X"\nupstream = "http://a"\n[[app.widget]]\nid = "w"\ntitle = "W"\nmodule = "/x/widget.js"\nsize = "2x1"\n')
    s = site.load(f, facts(str(SITE)))
    assert s.apps[0].widgets[0].href == "/x/widget.js" and s.apps[0].widgets[0].size == "2x1"


# ── C6: the pages are held to the rules ───────────────────────────────────

PAGES = WEB / "src" / "pages"
# explanatory paragraphs the pages still carry (docs/frame.md §5): the rewritten pages have none, and the
# others may only lose them. Raise a number here only with a reason in the same commit.
RATCHET = {"account.ts": 4, "agents.ts": 10, "flows.ts": 10, "projects.ts": 5, "schedule.ts": 0, "grant.ts": 0,
           "home.ts": 0, "apps.ts": 0, "settings.ts": 0, "tabs.ts": 0, "calendar.ts": 0, "vault.ts": 0}
EXPLANATION = re.compile(r"h\('p',\s*\{\s*class:\s*'(?:muted small|muted)'")


def test_a_page_head_carries_no_explanation():
    """pageHead(heading, tabs?) — the signature has no place for one; this is the grep behind it."""
    for p in filter(_ours, PAGES.glob("*.ts")):
        for m in re.finditer(r"pageHead\(([^;]*?)\)\s*[,;)]", p.read_text(), re.S):
            args = m.group(1)
            assert not re.search(r"\bt\('[^']{40,}'", args), f"{p.name}: pageHead carries a sentence: {args[:80]}"


def test_explanations_only_go_down():
    counts = {p.name: len(EXPLANATION.findall(p.read_text())) for p in filter(_ours, PAGES.glob("*.ts"))}
    assert set(counts) == set(RATCHET), f"a page is missing from the ratchet: {sorted(set(counts) ^ set(RATCHET))}"
    over = {k: (v, RATCHET[k]) for k, v in counts.items() if v > RATCHET[k]}
    assert not over, f"explanatory paragraphs grew (page: now, allowed): {over}"


def test_no_link_is_dressed_as_a_button_on_the_rewritten_pages():
    for name in ("home.ts", "apps.ts", "settings.ts", "calendar.ts", "vault.ts"):
        text = (PAGES / name).read_text()
        assert "class: 'button" not in text and "buttonLink(" not in text, f"{name}: a link dressed as a button"
