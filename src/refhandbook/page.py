"""The handbook's HTML pages (the consent page at /login, the approval page at /agents): the site's
look, from the site's own stylesheet, and one set of security headers."""
from __future__ import annotations

from html import escape

from starlette.responses import HTMLResponse


def stylesheet(login_url: str) -> str:
    """The site's stylesheet, which the sign-in serves beside its pages (portal.sso: /auth/login,
    /auth/static/style.css): the same origin, so these pages need no styles of their own."""
    return login_url.rsplit("/", 1)[0] + "/static/style.css"


def page(title: str, body: str, *, login_url: str, status: int = 200, form_action: str = "'self'",
         referrer: str = "same-origin") -> HTMLResponse:
    """A page with `body` in the site's frame. `form_action` widens CSP form-action (the consent page's
    POST ends in a redirect to the client, which form-action also governs).

    Referrer-Policy same-origin, never no-referrer: under no-referrer a browser sends `Origin: null` on
    the page's own form POSTs (Fetch, "append a request Origin header"), and every POST here is
    refused unless its Origin is the site's. same-origin still sends nothing to other sites."""
    doc = ("<!doctype html><html lang=ko><head><meta charset=utf-8>"
           "<meta name=viewport content='width=device-width,initial-scale=1'>"
           f"<title>{escape(title)}</title><link rel=stylesheet href='{escape(stylesheet(login_url))}'></head>"
           f"<body><header><a class=brand href='/'>{escape(title)}</a></header><main>{body}</main></body></html>")
    return HTMLResponse(doc, status_code=status, headers={
        "Cache-Control": "no-store", "X-Frame-Options": "DENY", "Referrer-Policy": referrer,
        "Content-Security-Policy": f"default-src 'none'; style-src 'self'; form-action {form_action}; "
                                   "frame-ancestors 'none'; base-uri 'none'"})
