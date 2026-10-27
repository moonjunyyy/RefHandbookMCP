"""The languages of the site's server pages and messages (the pages app has its own, web/src/lib/i18n.ts).

Korean is the source: a message is written in Korean and is its own key; a catalog per other language
(portal/locale/<lang>.py, LANG = {korean: translation}) says it there, falling back to the Korean. A
message with values names them as {name} and passes them to t(): t("{uid}님", uid=uid). A table built
at import marks its texts N_("…") and translates them where it shows them: t(NAMES[x]).

Which language a request is in: the site-wide `lang` cookie (the person's setting, which the pages
write: web/src/lib/prefs.ts), else the browser's Accept-Language, else Korean. `Language` (ASGI
middleware) decides it once per request and keeps it in a context variable, so every t() under that
request (handlers, templates, the thread pool) speaks it without passing it along.
"""

from __future__ import annotations

import contextvars
import importlib
from functools import cache
from typing import Any

LANGS: tuple[str, ...] = ("ko", "en")
DEFAULT = "ko"
NAMES = {"ko": "한국어", "en": "English"}  # i18n: data (each language in its own words)

_current: contextvars.ContextVar[str] = contextvars.ContextVar("lang", default=DEFAULT)


@cache
def catalog(lang: str) -> dict[str, str]:
    if lang == DEFAULT or lang not in LANGS:
        return {}
    return importlib.import_module(f"portal.locale.{lang}").LANG


def pick(cookie: str | None, accept: str | None) -> str:
    """The language for a request: the person's setting (cookie), else the browser's best one we have."""
    if cookie in LANGS:
        return cookie
    best, weight = DEFAULT, -1.0
    for part in (accept or "").split(","):
        tag, _, q = part.strip().partition(";")
        code = tag.strip().lower().split("-")[0]
        try:
            w = float(q.split("=", 1)[1]) if q.strip().startswith("q=") else 1.0
        except ValueError:
            w = 0.0
        if code in LANGS and w > weight:
            best, weight = code, w
    return best


def current() -> str:
    return _current.get()


def use(lang: str) -> contextvars.Token:
    return _current.set(lang if lang in LANGS else DEFAULT)


def t(text: str, /, **values: Any) -> str:
    """`text` (Korean) in the request's language, with its {values} filled in."""
    out = catalog(current()).get(text, text)
    return out.format(**values) if values else out


def N_(text: str) -> str:  # noqa: N802 — gettext's name for it
    """A text kept as it is now (a table built at import, before any request), translated where it is
    shown: t(TABLE[x]). Marked, so the catalog test finds it."""
    return text


def _cookie(header: str, name: str) -> str | None:
    for part in header.split(";"):
        k, _, v = part.strip().partition("=")
        if k == name:
            return v
    return None


class Language:
    """ASGI middleware: the request's language, for every t() under it."""

    def __init__(self, app: Any):
        self.app = app

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
        token = use(pick(_cookie(headers.get("cookie", ""), "lang"), headers.get("accept-language")))
        try:
            await self.app(scope, receive, send)
        finally:
            _current.reset(token)
