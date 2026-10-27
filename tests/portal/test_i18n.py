"""The site in more than one language (portal/i18n.py, web/src/lib/i18n.ts): every text a person reads
goes through t(), and every one has its English. Korean left outside t() is a text no other language
gets; a t() with no English shows Korean to an English reader. A line may say `i18n: data` where its
Korean is data (a language's own name), not a text to translate. A table built before the language is
known marks its texts N_() (n_() in the pages) and shows t(TABLE[x])."""

from __future__ import annotations

import io
import re
import tokenize
from pathlib import Path

import pytest

from portal import i18n
from portal.locale.en import LANG as EN

ROOT = Path(__file__).resolve().parents[2]
HANGUL = re.compile(r"[가-힣ㄱ-ㆎ]")
EXEMPT = "i18n: data"

# ── the pages app (TypeScript) ───────────────────────────────────────────

WEB = ROOT / "web" / "src"
T_CALL = re.compile(r"\b(?:t|n_)\(\s*'((?:[^'\\]|\\.)*)'")
ENTRY = re.compile(r"^\s*'((?:[^'\\]|\\.)*)'\s*:\s*'(?:[^'\\]|\\.)*',?\s*$", re.M)


def _ts_code(text: str) -> str:
    """The code without its comments (// to the end of a line, /* */), strings kept."""
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return "\n".join(re.sub(r"(^|\s)//.*$", "", ln) for ln in text.splitlines())


def _web_sources() -> list[Path]:
    return [p for p in sorted(WEB.rglob("*.ts")) if "i18n" not in p.relative_to(WEB).parts[:1]]


def _web_catalog() -> dict[str, str]:
    out = {}
    for p in (WEB / "i18n" / "en").glob("*.ts"):
        for m in ENTRY.finditer(p.read_text()):
            out[m.group(1)] = p.name
    return out


def test_every_text_of_the_pages_has_its_english():
    have = _web_catalog()
    missing = sorted({m.group(1) for p in _web_sources() for m in T_CALL.finditer(_ts_code(p.read_text()))} - set(have))
    assert not missing, f"{len(missing)} texts with no English (web/src/i18n/en/): {missing[:20]}"


def test_no_korean_is_left_outside_t_in_the_pages():
    left = []
    for p in _web_sources():
        for n, line in enumerate(_ts_code(p.read_text()).splitlines(), 1):
            if EXEMPT in p.read_text().splitlines()[n - 1]:
                continue
            if HANGUL.search(T_CALL.sub("", line)):
                left.append(f"{p.relative_to(ROOT)}:{n}: {line.strip()[:100]}")
    assert not left, f"{len(left)} lines of Korean outside t():\n" + "\n".join(left[:40])


# ── the server pages and messages (Python, templates) ────────────────────

# the kernel's rule packages are rules (their Korean words are what rules match in a model's writing), not pages
SERVER = [*sorted((ROOT / "src" / "portal").glob("*.py")),
          *[p for p in sorted((ROOT / "src" / "refhandbook").rglob("*.py")) if "packages" not in p.parts]]
TEMPLATES = sorted((ROOT / "src" / "portal" / "templates").glob("*.html"))
JINJA_T = re.compile(r"""\b(?:t|N_)\(\s*(['"])((?:(?!\1).)*)\1""")


def _py_texts(path: Path) -> tuple[set[str], list[str]]:
    """The texts given to t() in a module, and the Korean strings it has elsewhere (not docstrings)."""
    src = path.read_text()
    lines = src.splitlines()
    toks = [x for x in tokenize.generate_tokens(io.StringIO(src).readline)
            if x.type not in (tokenize.COMMENT, tokenize.NL)]
    given, loose = set(), []
    for i, tok in enumerate(toks):
        is_str = tok.type == tokenize.STRING
        is_f = tok.type == getattr(tokenize, "FSTRING_MIDDLE", -1)
        if not (is_str or is_f) or not HANGUL.search(tok.string) or EXEMPT in lines[tok.start[0] - 1]:
            continue
        prev = [x for x in toks[max(0, i - 2):i]]
        if is_str and len(prev) == 2 and prev[0].string in ("t", "N_") and prev[1].string == "(":
            given.add(eval(tok.string))  # noqa: S307 — a literal of our own source
            continue
        before = toks[i - 1].type if i else tokenize.NEWLINE
        if is_str and before in (tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT, tokenize.ENCODING):
            continue  # a docstring: for the reader of the code
        loose.append(f"{path.relative_to(ROOT)}:{tok.start[0]}: {lines[tok.start[0] - 1].strip()[:100]}")
    return given, loose


def test_every_server_text_has_its_english():
    texts = set()
    for p in SERVER:
        if "locale" in p.parts:
            continue
        texts |= _py_texts(p)[0]
    for p in TEMPLATES:
        texts |= {m.group(2) for m in JINJA_T.finditer(p.read_text())}
    missing = sorted(texts - set(EN))
    assert not missing, f"{len(missing)} texts with no English (portal/locale/en.py): {missing[:20]}"


def test_no_korean_is_left_outside_t_on_the_server():
    left = []
    for p in SERVER:
        if "locale" not in p.parts:
            left += _py_texts(p)[1]
    for p in TEMPLATES:
        for n, line in enumerate(p.read_text().splitlines(), 1):
            if EXEMPT not in line and HANGUL.search(JINJA_T.sub("", re.sub(r"\{#.*?#\}", "", line))):
                left.append(f"{p.relative_to(ROOT)}:{n}: {line.strip()[:100]}")
    assert not left, f"{len(left)} lines of Korean outside t():\n" + "\n".join(left[:40])


def test_every_translation_keeps_the_values_of_its_text():
    """A {value} the Korean names, the translation names too (else format() fails or drops it)."""
    names = re.compile(r"\{(\w+)\}")
    bad = [k for k, v in EN.items() if set(names.findall(k)) != set(names.findall(v))]
    assert not bad, bad[:20]


@pytest.mark.parametrize("cookie,accept,want", [
    (None, None, "ko"), ("en", "ko-KR", "en"), ("auto", "en-US,en;q=0.9,ko;q=0.8", "en"),
    (None, "fr-FR,ko;q=0.7,en;q=0.5", "ko"), ("xx", "de", "ko")])
def test_a_request_speaks_the_persons_language(cookie, accept, want):
    assert i18n.pick(cookie, accept) == want


def test_the_server_pages_speak_it(monkeypatch):
    token = i18n.use("en")
    try:
        monkeypatch.setitem(EN, "테스트 {n}개", "{n} tests")
        assert i18n.t("테스트 {n}개", n=3) == "3 tests" and i18n.t("없는 문장") == "없는 문장"
    finally:
        i18n._current.reset(token)
    assert i18n.t("테스트 {n}개", n=3) == "테스트 3개"
