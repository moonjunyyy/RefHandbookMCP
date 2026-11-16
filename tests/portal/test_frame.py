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
    for p in [STATIC / "parts.css", STATIC / "chrome.css", STATIC / "widgets.css", STATIC / "guide.css", STATIC / "background.css", STATIC / "style.css",
              *sorted((WEB / "src").rglob("*.ts")), *sorted((WEB / "frame").rglob("*.ts")), *sorted((WEB / "widgets").glob("*.ts"))]:
        if not _ours(p):
            continue
        for n, line in enumerate(p.read_text().splitlines(), 1):
            if COLOUR.search(line) and "i18n: data" not in line and "colour: ok" not in line:
                offenders.append(f"{p.relative_to(ROOT)}:{n}: {line.strip()[:90]}")
    assert not offenders, "colours outside theme.css:\n" + "\n".join(offenders)


SPACE = re.compile(r"(?:^|[;{])\s*(?:padding|margin|gap|row-gap|column-gap)(?:-[a-z]+)?\s*:\s*([^;}]+)", re.M)
PX = re.compile(r"\d+(?:\.\d+)?px")
RATCHET_PX = 32  # px literals left in parts.css spacing declarations (hairlines of 1-3px, the page's width): only down from here


def test_space_is_a_token_scale():
    """R14 (docs/frame.md §5): paddings, margins and gaps are the scale theme.css declares (--s1..--s5, --pad, --gap),
    not numbers; what is left is a ratchet."""
    theme = (STATIC / "theme.css").read_text()
    assert all(f"--{k}:" in theme for k in ("s1", "s2", "s3", "s4", "s5", "pad", "gap", "icon", "icon-big", "cell"))
    parts = "".join((STATIC / f).read_text() for f in ("parts.css", "chrome.css", "widgets.css"))  # the header and the widgets' parts moved, the count did not
    n = sum(len(PX.findall(m.group(1))) for m in SPACE.finditer(parts))
    assert n <= RATCHET_PX, f"px literals in spacing declarations grew: {n} > {RATCHET_PX}"
    assert parts.count("var(--s") > 200  # the scale is what the parts use


RADIUS = re.compile(r"border-radius\s*:\s*([^;}]+)")


def test_corners_are_the_tokens_a_look_redeclares():
    """§1.3: the corners a person picks (--radius, --radius-s) reach every part — a corner in parts.css uses a size-limited token, a pill (999px), a circle (50%) or a hairline (≤ 3px), never a number of its own."""
    parts = "".join((STATIC / f).read_text() for f in ("parts.css", "chrome.css", "widgets.css"))
    own = [v.strip() for v in RADIUS.findall(parts)
           if any(not re.fullmatch(r"0|999px|50%|[0-3]px", w) for w in re.sub(r"var\(--(?:panel|control|grid)-radius\)", "", v).split())]
    assert not own, f"corners of their own in parts.css: {own}"


APPS = ROOT / "apps"
SITE_ROUTE = re.compile(r"""href\s*[=:]\s*\{?\s*['"`]/(?:apps|settings)?/?['"`]""")


def _hosted_apps() -> list[tuple[Path, str]]:
    """Each hosted app whose sources are in this repository, with its sources (tests aside) and its page."""
    out = []
    for d in sorted(p for p in APPS.iterdir() if not p.is_symlink() and (p / "src").is_dir()):
        files = [f for f in sorted((d / "src").rglob("*")) if f.suffix in (".ts", ".tsx", ".css") and ".test." not in f.name and _ours(f)]
        out.append((d, "\n".join(f.read_text() for f in files) + (d / "index.html").read_text()))
    return out


def test_every_hosted_app_takes_the_chrome_from_the_frame():
    """docs/frame.md §1: the site's header, menus, help and fonts are the frame's on every page — an app calls
    chrome() and writes no link to the site's pages, no header bar of the site's, no font source."""
    apps = _hosted_apps()
    assert apps, "no hosted app with its sources here"
    for d, text in apps:
        assert "chrome()" in text, f"{d.name} does not take the site's chrome"
        found = SITE_ROUTE.search(text)
        assert not found, f"{d.name} links a page of the site itself: {found and found.group(0)}"
        assert not re.search(r"fonts\.(?:googleapis|gstatic)|@font-face", text), f"{d.name} loads a font of its own"
    assert "chrome.css" in (STATIC / "parts.css").read_text()  # the site's pages draw the same header


def test_the_page_help_has_one_place():
    """A guide's replay is an item of the person's menu in the site header, wherever guide() is called from:
    the frame puts it there, nothing hangs a help button on a page's element."""
    guide = (WEB / "frame" / "guide.ts").read_text()
    header = (WEB / "frame" / "parts.ts").read_text().split("export function header")[1].split("\nlet closing")[0]
    assert "setHelp(open)" in guide and "host.append" not in guide and "t('사용 안내')" not in guide
    assert "t('사용 안내')" in header.split("class: 'me'")[1]
    assert "body > header nav details > div button" in (STATIC / "chrome.css").read_text()


def test_nothing_the_site_file_declares_is_repeated_in_the_code():
    """R13/§4: which apps a new account starts with, and which sizes a cell may have, are the site file's and
    portal/site.py's declarations; the frame and the pages carry no copy of them."""
    s = site.load(SITE, facts(str(SITE)))
    ids = [a.id for a in s.apps if a.optional]
    frame_code = "\n".join(p.read_text() for p in (WEB / "frame").rglob("*.ts") if _ours(p))
    assert not [i for i in ids if f"'{i}'" in frame_code], "an app id is named in the frame code"
    pages = "\n".join(p.read_text() for p in (WEB / "src" / "pages").glob("*.ts") if _ours(p)) + frame_code
    assert not [k for k in site.SIZES if f"'{k}'" in pages.replace("'1x1', cols: 1, rows: 1", "")], "a size id is named in the code"


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
    assert set(me["look"]) == {*site.LOOK_KINDS, "columns", "fonts", "groups"} and me["look"]["palette"][0]["id"]  # what the settings offer
    assert me["look"]["fonts"].startswith("/") and set(me["look"]["groups"]) == set(site.FONT_GROUPS)  # where the open fonts are, their groups' words
    assert all(c["group"] in site.FONT_GROUPS and isinstance(c["fonts"], list) for k in site.FONT_KINDS for c in me["look"][k])
    assert c.get("/auth/api/v1/me", cookies={"theme": "dark"}).json()["theme"] == "dark"
    assert c.get("/auth/api/v1/me", cookies={"theme": "sepia"}).json()["theme"] == "auto"  # not a theme we have
    c, _ = sign_in(app)
    assert c.get("/auth/api/v1/me", cookies={"theme": "light"}).json()["theme"] == "light"


def test_signed_out_the_frame_shows_nothing_of_the_apps(app):
    """Signed out, the sign-in says who is there (no one) and nothing of the apps — no names, abouts or addresses;
    the main page then shows the way in only, and the header only the sign-in."""
    me = TestClient(app).get("/auth/api/v1/me").json()
    assert me["uid"] is None and me["cards"] == [] and me["menu"] == [] and me["title"]
    home = (WEB / "src" / "pages" / "home.ts").read_text()
    assert "widgetsOf(c)[0]))));" not in home.split("if (!frame.uid) {")[1].split("return;")[0]


def test_connection_only_apps_open_their_information_page(app):
    c, _ = sign_in(app)
    cards = c.get('/auth/api/v1/me').json()['cards']
    assert all(c['href'] for c in cards)
    for app_id in ('smb', 'refhandbook'):
        c = next(x for x in cards if x['id'] == app_id)
        assert c['code'] and c['href'] == f'/app/{app_id}'


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
    c, _ = sign_in(app)
    me = c.get("/auth/api/v1/me").json()
    eq = next(x for x in me["cards"] if x["id"] == "eq-sandbox")
    assert eq["optional"] is True and eq["widgets"] == [{"id": "boards", "title": "최근 작업판", "description": "최근에 연 작업판으로 바로",
                                                          "href": "/apps/eq-sandbox/widget.js", "size": "1x1"}]
    assert next(x for x in me["cards"] if x["id"] == "account")["optional"] is False
    assert eq["tags"] == ["연구", "도구"] and eq["about"].startswith("식의 부분을")
    en = c.get("/auth/api/v1/me", headers={"Accept-Language": "en"}).json()
    assert next(x for x in en["cards"] if x["id"] == "eq-sandbox")["tags"] == ["Research", "Tools"]


def test_the_frame_declares_the_sizes_and_the_default_apps(app):
    """R13 and §4: the frame reads which apps a new account starts with, and which sizes a cell may have,
    from the site file through /me — no list in the code."""
    c, _ = sign_in(app)
    me = c.get("/auth/api/v1/me").json()
    assert [c["id"] for c in me["cards"] if c["default"]] == ["projects", "calendar", "vault", "board"]  # the board: the notices reach everyone
    assert all(c["optional"] for c in me["cards"] if c["default"])
    assert me["sizes"] == [{"id": k, "cols": c, "rows": r} for k, (c, r) in site.SIZES.items()]
    assert all(w["size"] in site.SIZES for c in me["cards"] for w in c["widgets"])


def test_every_widget_says_what_it_is():
    """R12 (docs/frame.md §5): the person choosing a widget reads what it shows, in both languages."""
    s = site.load(SITE, facts(str(SITE)))
    for a in s.apps:
        for w in a.widgets:
            assert w.description and len(w.description) <= 80, (a.id, w.id)
            assert w.text("description", "en") != w.description, (a.id, w.id)  # it has its English


WIDGET = '[[app]]\nid = "x"\ntitle = "X"\nstatic = true\n[[app.widget]]\n'


@pytest.mark.parametrize("bad, message", [
    (WIDGET + 'id = "w"\ntitle = "W"\nmodule = "w.js"\n[[app.widget]]\nid = "w"\ntitle = "W2"\nmodule = "w2.js"\n', "declared twice"),
    (WIDGET + 'id = "w"\ntitle = "W"\nmodule = "w.js"\nsize = "3x3"\n', "size is one of"),
    ('[[app]]\nid = "x"\ntitle = "X"\nstatic = true\noptional = false\ndefault = true\n', "default is for an optional app"),
    (WIDGET + 'id = "w"\ntitle = "W"\n', "needs id, title and module"),
    (WIDGET + 'id = "w"\ntitle = "W"\nmodule = "w.js"\ncolour = "red"\n', "unknown widget fields"),
    (WIDGET + 'id = "w"\ntitle = "W"\nmodule = "w.js"\ndescription = "' + "x" * 81 + '"\n', "one line"),
    (WIDGET + 'id = "w"\ntitle = "W"\nmodule = "w.js"\ntr.en = { size = "2x2" }\n', "names title or description"),
    (WIDGET + 'id = "Bad Id"\ntitle = "W"\nmodule = "w.js"\n', "widget id"),
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
RATCHET = {"account.ts": 0, "agents.ts": 0, "flows.ts": 0, "projects.ts": 0, "schedule.ts": 0, "grant.ts": 0,
           "home.ts": 0, "apps.ts": 0, "settings.ts": 0, "tabs.ts": 0, "calendar.ts": 0, "vault.ts": 0, "board.ts": 0}
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


def test_the_main_page_is_never_the_store():
    """The main page shows widgets or the app menu; turning apps on and off is the store's (/apps). With nothing on,
    the page is one action that goes there (docs/frame.md §4.2)."""
    text = (PAGES / "home.ts").read_text()
    assert "from './apps'" not in text and "catalog(" not in text
    assert "primaryLink('/apps'" in text


# ── §1.3: the open fonts ──────────────────────────────────────────────────

FONTS = WEB / "fonts.json"
FAMILY_TOKEN = {"type": "sans", "heading": "serif", "mono": "mono"}


def _look() -> dict:
    import tomllib
    return site._look(tomllib.loads(SITE.read_text()))


def _face(kind: str, c: dict) -> str:
    """The font list a choice sets its role to: its token, theme.css's own for a choice that redeclares nothing,
    a var(--role-default) read as theme.css's value."""
    role = FAMILY_TOKEN[kind]
    value = c["tokens"].get(role) or f"var(--{role}-default)"
    theme = (STATIC / "theme.css").read_text()
    for r in ("sans", "serif", "mono"):
        m = re.search(rf"--{r}-default:\s*([^;]+);", theme)
        value = value.replace(f"var(--{r}-default)", m.group(1) if m else "")
    return value


def test_the_open_fonts_are_declared_once():
    """§1.3: web/fonts.json is what the pages app ships (built from npm packages it depends on); a choice of the look
    names a font by its id and its family; nothing shipped is left unused, nothing named is missing."""
    import json
    catalog = {f["id"]: f for f in json.loads(FONTS.read_text())["fonts"]}
    deps = json.loads((WEB / "package.json").read_text())["devDependencies"]
    assert all(f["package"] in deps for f in catalog.values()), "a font whose package the pages app does not depend on"
    assert all(re.fullmatch(r"\d+\.\d+\.\d+", deps[f["package"]]) for f in catalog.values()), "a font package not pinned"
    assert '"build:fonts"' in (WEB / "package.json").read_text() and "build:fonts" in json.loads((WEB / "package.json").read_text())["scripts"]["build"]
    look = _look()
    used = set()
    for kind in site.FONT_KINDS:
        for c in look[kind]:
            for f in c["fonts"]:
                assert f in catalog, f"look.{kind}.{c['id']} names {f}, which web/fonts.json does not ship"
                assert catalog[f]["family"] in " ".join([_face(kind, c), *c["tokens"].values()]), f"look.{kind}.{c['id']}: its tokens do not name {catalog[f]['family']}"
                used.add(f)
    assert set(catalog) == used, f"shipped and never offered: {sorted(set(catalog) - used)}"
    assert look["fonts"] == "/apps/site/fonts/"  # the pages app publishes its dist at /apps/site/


def test_a_font_choice_keeps_its_fallback_and_the_first_is_the_themes():
    """A font choice redeclares its role's token (--sans, --serif, --mono) with its own family first and the role's
    fallback after (or another role's token); the first choice of each kind is theme.css's own: it redeclares
    nothing and loads the open font theme.css names first (U15: the defaults load what they name, open fonts)."""
    theme = (STATIC / "theme.css").read_text()
    for role in ("sans", "serif", "mono"):
        assert f"--{role}-fallback:" in theme and f"--{role}-default:" in theme and f"--{role}: var(--{role}-default)" in theme
    look = _look()
    for kind in site.FONT_KINDS:
        import json
        catalog = {f["id"]: f for f in json.loads(FONTS.read_text())["fonts"]}
        first, *rest = look[kind]
        assert not first["tokens"], f"look.{kind}: the first choice is theme.css's own"
        lead = _face(kind, first).split(",")[0].strip().strip('"')
        assert [catalog[f]["family"] for f in first["fonts"]] == [lead], f"look.{kind}: the first choice loads {lead}, what theme.css names first"
        for c in rest:
            v = c["tokens"].get(FAMILY_TOKEN[kind], "")
            assert v, f"look.{kind}.{c['id']} does not redeclare --{FAMILY_TOKEN[kind]}"
            assert not c["fonts"] or re.search(r"var\(--(?:sans|serif|mono)-fallback\)$", _face(kind, c)), f"look.{kind}.{c['id']}: an open font keeps the fallback"


@pytest.mark.parametrize("bad,message", [
    ('[[look.type]]\nid = "a"\nlabel = "A"\n[[look.type]]\nid = "b"\nlabel = "B"\ngroup = "fancy"\n', "group is one of"),
    ('[[look.type]]\nid = "a"\nlabel = "A"\ngroup = "sans"\nfonts = ["Bad Id"]\n', "fonts are ids"),
    ('fonts = "https://cdn.example/fonts/"\n[[look.type]]\nid = "a"\nlabel = "A"\ngroup = "sans"\n', "an address of this site"),
    ('[[look.type]]\nid = "a"\nlabel = "A"\ngroup = "sans"\nfonts = ["x"]\n', "say where they are served"),
    ('[[look.palette]]\nid = "a"\nlabel = "A"\nfonts = ["x"]\n', "a choice has an id"),
])
def test_a_bad_font_choice_is_refused(bad, message):
    import tomllib
    with pytest.raises(site.SiteError, match=message):
        site._look(tomllib.loads("[look]\n" + bad))


# ── §4.2: the widgets' parts ──────────────────────────────────────────────

PARTS = ("items", "groupHead", "stats", "meter", "dayStrip", "monthGrid", "bars", "activity", "fit", "ago", "dayKey")


def test_widgets_draw_with_the_frames_parts():
    """§4.2: the parts a widget draws with are the frame's (exported from site.js, styled by widgets.css); the site's
    widgets write no list markup of their own and take how much to show from the cell's size."""
    exported = (STATIC / "site.d" / "index.d.ts").read_text()
    assert all(re.search(rf"\b{p}\b", exported) for p in PARTS), "a part is not exported from site.js"
    assert "--cell-items:" in (STATIC / "theme.css").read_text() and '@import url("widgets.css")' in (STATIC / "parts.css").read_text()
    for p in sorted((WEB / "widgets").glob("*.ts")):
        if not _ours(p):
            continue
        text = p.read_text()
        assert not re.search(r"h\(\s*'(?:ul|ol|li)'", text), f"{p.name} writes list markup of its own"
        assert "from '/auth/static/site.js'" in text and re.search(r"\b(?:items|bars|monthGrid|dayStrip)\b", text), f"{p.name} draws without the frame's parts"
    home = (WEB / "src" / "pages" / "home.ts").read_text()
    assert "mount(el, c, w, size)" in home  # the module learns the cell's size
