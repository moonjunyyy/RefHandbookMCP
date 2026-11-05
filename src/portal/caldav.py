"""CalDAV for the calendars (docs/calendar.md, docs/apps-vault-calendar.md §8.3): the subset of RFC 4791
(with RFC 4918 WebDAV and RFC 5545 iCalendar) that a phone's or a desktop's calendar app needs to read
and write a person's calendars — mounted on the calendar service (portal/calendar.py) under
/calendar/dav/, behind HTTP Basic with a *device password* the person makes on the calendar page.

    /calendar/dav/                      PROPFIND: current-user-principal → /calendar/dav/<uid>/ · GET: a collection
    /calendar/dav/<uid>/                the principal and the calendar home (depth 1: the calendars) · GET: a collection
    /calendar/dav/<uid>/<cid>/          a calendar collection (getctag, sync-token; depth 1: the events)
    /calendar/dav/<uid>/<cid>/<id>.ics  one event: GET · PUT (If-None-Match: * | If-Match) · DELETE
    REPORT on a calendar: calendar-query (time-range) · calendar-multiget · sync-collection
    /.well-known/caldav                 nginx: 301 → /calendar/dav/ (deploy/site.toml)

A plain GET of the root or of the caller's home answers as a collection does (200, where the calendars are):
a client may look with GET before it asks with PROPFIND — the macOS account setup does, and gives up on a
404 (11-04, the site's nginx log: GET /calendar/dav/ 401 → 404, nothing after).

The resource name a client chooses becomes the event's id (so a later GET finds it), and the VEVENT's
UID is kept as it came (`ical_uid`). A calendar's `version` grows with every change under it: it is the
ctag and the sync-token, and each event carries the version it was last written at (sync-collection
answers the changes since a token; deleted ones from the tombstones). What the model cannot hold is
refused with a reason (403): a repeat the service's RRULE subset does not cover, a VEVENT that changes
one instance of a repeat (RECURRENCE-ID). Times with a TZID are converted to UTC (zoneinfo); floating
times are read as UTC; VALUE=DATE is an all-day event (the end exclusive, as iCalendar has it).
"""

from __future__ import annotations

import base64
import re
from datetime import datetime, timedelta, timezone
from xml.etree import ElementTree as ET
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import FastAPI, Request
from fastapi.responses import Response

from .i18n import t

DAV = "DAV:"
CAL = "urn:ietf:params:xml:ns:caldav"
CS = "http://calendarserver.org/ns/"
APPLE = "http://apple.com/ns/ical/"
NS = {"D": DAV, "C": CAL, "CS": CS, "A": APPLE}
PREFIX = "/calendar/dav"
RESOURCE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._@-]{0,127}$")
DURATION = re.compile(r"^([+-])?P(?:(\d+)W)?(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?$")


class DavError(ValueError):
    def __init__(self, status: int, message: str = ""):
        super().__init__(message)
        self.status = status


# ── iCalendar, read ───────────────────────────────────────────────────────


def unfold(text: str) -> list[str]:
    out: list[str] = []
    for ln in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if ln[:1] in (" ", "\t") and out:
            out[-1] += ln[1:]
        elif ln:
            out.append(ln)
    return out


def unescape(s: str) -> str:
    out, i = [], 0
    while i < len(s):
        c = s[i]
        if c == "\\" and i + 1 < len(s):
            n = s[i + 1]
            out.append("\n" if n in "nN" else n)
            i += 2
        else:
            out.append(c)
            i += 1
    return "".join(out)


def prop_line(line: str) -> tuple[str, dict[str, str], str]:
    """NAME;PARAM=VALUE;PARAM="a:b":value → (NAME, {PARAM: VALUE}, value)."""
    i, quoted = 0, False
    while i < len(line):
        c = line[i]
        if c == '"':
            quoted = not quoted
        elif c == ":" and not quoted:
            break
        i += 1
    head, value = line[:i], line[i + 1:]
    parts = head.split(";")
    params = {}
    for p in parts[1:]:
        k, _, v = p.partition("=")
        params[k.upper()] = v.strip('"')
    return parts[0].upper(), params, value


def read_time(value: str, params: dict[str, str]) -> tuple[datetime, bool]:
    """A DTSTART/DTEND/EXDATE value as a UTC datetime, and whether it is a date (all-day)."""
    v = value.strip()
    if params.get("VALUE") == "DATE" or (len(v) == 8 and v.isdigit()):
        try:
            d = datetime.strptime(v, "%Y%m%d")
        except ValueError as e:
            raise DavError(403, t("날짜를 읽을 수 없습니다: {v}", v=v)) from e
        return d.replace(tzinfo=timezone.utc), True
    utc = v.endswith("Z")
    try:
        d = datetime.strptime(v.rstrip("Z"), "%Y%m%dT%H%M%S")
    except ValueError as e:
        raise DavError(403, t("시각을 읽을 수 없습니다: {v}", v=v)) from e
    if utc:
        return d.replace(tzinfo=timezone.utc), False
    tzid = params.get("TZID")
    if tzid:
        try:
            zone = ZoneInfo(tzid)
        except (ZoneInfoNotFoundError, ValueError) as e:
            raise DavError(403, t("모르는 시간대입니다: {tz}", tz=tzid)) from e
        return d.replace(tzinfo=zone).astimezone(timezone.utc), False
    return d.replace(tzinfo=timezone.utc), False  # floating: read as UTC


def read_duration(v: str) -> timedelta:
    m = DURATION.match(v.strip())
    if not m:
        raise DavError(403, t("기간을 읽을 수 없습니다: {v}", v=v))
    sign = -1 if m.group(1) == "-" else 1
    w, d, h, mi, s = (int(x or 0) for x in m.groups()[1:])
    return sign * timedelta(weeks=w, days=d, hours=h, minutes=mi, seconds=s)


def read_vevent(text: str) -> dict:
    """The one VEVENT of an iCalendar object, as the service's event fields (start/end UTC or dates,
    allday, rrule text, exdates) plus `uid` and `seq`. Refuses what the model cannot hold."""
    lines = unfold(text)
    events: list[list[str]] = []
    depth: list[str] = []
    for ln in lines:
        name, _, value = prop_line(ln)
        if name == "BEGIN":
            depth.append(value.strip().upper())
            if depth[-1] == "VEVENT":
                events.append([])
            continue
        if name == "END":
            if depth:
                depth.pop()
            continue
        if depth and depth[-1] == "VEVENT" and events:
            events[-1].append(ln)
    if not events:
        raise DavError(403, t("VEVENT 가 없습니다."))
    masters = [e for e in events if not any(prop_line(x)[0] == "RECURRENCE-ID" for x in e)]
    if len(events) > len(masters):
        raise DavError(403, t("반복 일정의 한 회만 바꾼 것(RECURRENCE-ID)은 아직 받지 않습니다. 계열 전체를 고치거나 그 회를 빼세요."))
    if len(masters) != 1:
        raise DavError(403, t("한 자원에는 VEVENT 하나입니다."))
    out: dict = {"summary": "", "description": "", "location": "", "rrule": "", "exdates": [], "uid": "", "seq": 0, "status": "CONFIRMED"}
    start = end = None
    allday = False
    duration = None
    exdates: list[tuple[datetime, bool]] = []
    for ln in masters[0]:
        name, params, value = prop_line(ln)
        if name == "UID":
            out["uid"] = value.strip()[:255]
        elif name == "SUMMARY":
            out["summary"] = unescape(value).strip()
        elif name == "DESCRIPTION":
            out["description"] = unescape(value)
        elif name == "LOCATION":
            out["location"] = unescape(value).strip()
        elif name == "DTSTART":
            start, allday = read_time(value, params)
        elif name == "DTEND":
            end, _ = read_time(value, params)
        elif name == "DURATION":
            duration = read_duration(value)
        elif name == "RRULE":
            out["rrule"] = value.strip()
        elif name == "EXDATE":
            for v in value.split(","):
                if v.strip():
                    exdates.append(read_time(v, params))
        elif name == "SEQUENCE":
            try:
                out["seq"] = int(value.strip())
            except ValueError:
                pass
        elif name == "STATUS":
            out["status"] = value.strip().upper() or "CONFIRMED"
    if start is None:
        raise DavError(403, t("DTSTART 가 없습니다."))
    if end is None:
        end = start + (duration if duration is not None else (timedelta(days=1) if allday else timedelta(hours=1)))
    if end <= start:
        end = start + (timedelta(days=1) if allday else timedelta(hours=1))
    from .calendar import fmt

    out.update({"start": fmt(start, allday), "end": fmt(end, allday), "allday": allday,
                "exdates": sorted({fmt(x, allday) for x, _ in exdates})})
    return out


# ── XML, written and read ─────────────────────────────────────────────────


def esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")  # text content: quotes stay (an ETag is quoted)


def href(path: str) -> str:
    return f"<D:href>{esc(path)}</D:href>"


def multistatus(responses: list[str]) -> Response:
    body = ('<?xml version="1.0" encoding="utf-8"?>\n'
            f'<D:multistatus xmlns:D="{DAV}" xmlns:C="{CAL}" xmlns:CS="{CS}" xmlns:A="{APPLE}">' + "".join(responses) + "</D:multistatus>")
    return Response(body, status_code=207, media_type="application/xml; charset=utf-8")


def response(path: str, found: dict[str, str], missing: list[str], status: str = "") -> str:
    """One <D:response>: the found props (name → inner xml) at 200, the missing names at 404; or a
    status-only response (sync-collection's deleted members)."""
    if status:
        return f"<D:response>{href(path)}<D:status>{status}</D:status></D:response>"
    parts = [href(path)]
    if found:
        parts.append("<D:propstat><D:prop>" + "".join(f"<{k}>{v}</{k.split(' ')[0]}>" if v else f"<{k}/>" for k, v in found.items())
                      + "</D:prop><D:status>HTTP/1.1 200 OK</D:status></D:propstat>")
    if missing:
        parts.append("<D:propstat><D:prop>" + "".join(f"<{k}/>" for k in missing) + "</D:prop><D:status>HTTP/1.1 404 Not Found</D:status></D:propstat>")
    return "<D:response>" + "".join(parts) + "</D:response>"


def qname(el: ET.Element) -> str:
    """{ns}name → prefix:name with our prefixes (unknown ns → the name with its namespace in braces)."""
    if el.tag.startswith("{"):
        ns, _, name = el.tag[1:].partition("}")
        for p, u in NS.items():
            if u == ns:
                return f"{p}:{name}"
        return el.tag
    return el.tag


def requested_props(body: bytes) -> list[str] | None:
    """The props a PROPFIND/REPORT asks for (prefix:name), or None for allprop / no body."""
    if not body.strip():
        return None
    try:
        root = ET.fromstring(body)
    except ET.ParseError as e:
        raise DavError(400, "the body is not XML") from e
    prop = root.find("D:prop", NS)
    if prop is None:
        return None
    return [qname(c) for c in prop]


# ── the service ───────────────────────────────────────────────────────────


def mount(app: FastAPI, store, visible, projects_of) -> None:  # noqa: ANN001
    """The DAV routes on the calendar service's app. `visible(uid)` lists the calendars a person may
    see; `store` is the calendar Store (devices, calendars, events, tombstones)."""
    from . import calendar as cal

    def unauthorized() -> Response:
        return Response("sign in with a device password", status_code=401, media_type="text/plain",
                        headers={"WWW-Authenticate": 'Basic realm="calendar", charset="UTF-8"'})

    def who(request: Request) -> str | None:
        auth = request.headers.get("authorization", "")
        if not auth.lower().startswith("basic "):
            return None
        try:
            raw = base64.b64decode(auth[6:].strip(), validate=True).decode()
        except (ValueError, UnicodeDecodeError):
            return None
        uid, _, password = raw.partition(":")
        uid = uid.strip().lower()
        if not uid or not password:
            return None
        return uid if store.device_login(uid, password) else None

    def base(request: Request) -> str:
        return f"{request.url.scheme}://{request.headers.get('host', request.url.netloc)}"

    def calendars_of(uid: str) -> dict:
        return {c.id: c for c in visible(uid)}

    def collection(uid: str) -> Response:
        """What a plain GET of the root or of the home shows: the calendars and where they are."""
        lines = [t("{uid} 의 캘린더 (CalDAV)", uid=uid)] + [f"{PREFIX}/{uid}/{c.id}/  {c.name}" for c in visible(uid)]
        return Response("\n".join(lines) + "\n", media_type="text/plain; charset=utf-8",
                        headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "no-store"})

    def principal_props(uid: str, want: list[str] | None) -> tuple[dict, list]:
        all_props = {
            "D:resourcetype": "<D:collection/><D:principal/>",
            "D:displayname": esc(uid),
            "D:current-user-principal": href(f"{PREFIX}/{uid}/"),
            "D:principal-URL": href(f"{PREFIX}/{uid}/"),
            "C:calendar-home-set": href(f"{PREFIX}/{uid}/"),
            "C:calendar-user-address-set": href(f"{PREFIX}/{uid}/"),
            "D:owner": href(f"{PREFIX}/{uid}/"),
            "D:supported-report-set": "",
            "D:current-user-privilege-set": "<D:privilege><D:read/></D:privilege><D:privilege><D:write/></D:privilege>",
        }
        return pick(all_props, want)

    def calendar_props(uid: str, c, want: list[str] | None) -> tuple[dict, list]:  # noqa: ANN001
        token = f"{PREFIX}/{uid}/{c.id}/sync/{c.version}"
        all_props = {
            "D:resourcetype": "<D:collection/><C:calendar/>",
            "D:displayname": esc(c.name),
            "C:calendar-description": esc(c.name),
            "D:owner": href(f"{PREFIX}/{uid}/"),
            "D:current-user-principal": href(f"{PREFIX}/{uid}/"),
            "C:supported-calendar-component-set": '<C:comp name="VEVENT"/>',
            "C:supported-calendar-data": '<C:calendar-data content-type="text/calendar" version="2.0"/>',
            "CS:getctag": esc(str(c.version)),
            "D:sync-token": esc(token),
            "D:supported-report-set": ("<D:supported-report><D:report><C:calendar-query/></D:report></D:supported-report>"
                                       "<D:supported-report><D:report><C:calendar-multiget/></D:report></D:supported-report>"
                                       "<D:supported-report><D:report><D:sync-collection/></D:report></D:supported-report>"),
            "D:current-user-privilege-set": "<D:privilege><D:read/></D:privilege><D:privilege><D:write/></D:privilege>",
            "A:calendar-color": esc(c.color or ""),
            "A:calendar-order": esc(str(0 if c.main else 1)),
        }
        return pick(all_props, want)

    def event_props(e, want: list[str] | None, data: bool = False, domain: str = "") -> tuple[dict, list]:  # noqa: ANN001
        all_props = {
            "D:getetag": esc(f'"{e.seq}"'),
            "D:getcontenttype": "text/calendar; charset=utf-8; component=VEVENT",
            "D:resourcetype": "",
        }
        if data:
            all_props["C:calendar-data"] = esc(cal.ics([], [e], e.summary, domain))
        return pick(all_props, want)

    def pick(all_props: dict[str, str], want: list[str] | None) -> tuple[dict, list]:
        if want is None:
            return {k: v for k, v in all_props.items() if k != "C:calendar-data"}, []
        found = {k: all_props[k] for k in want if k in all_props}
        return found, [k for k in want if k not in all_props and ":" in k and not k.startswith("{")]

    def depth(request: Request) -> int:
        d = request.headers.get("depth", "0").strip().lower()
        return 0 if d == "0" else 1

    def parse_path(path: str) -> tuple[str, str, str]:
        """/<uid>/[<cid>/[<name>.ics]] → (uid, cid, resource) with '' where absent."""
        parts = [p for p in path.strip("/").split("/") if p]
        uid = parts[0] if parts else ""
        cid = parts[1] if len(parts) > 1 else ""
        res = parts[2] if len(parts) > 2 else ""
        if len(parts) > 3 or (res and not res.endswith(".ics")):
            raise DavError(404)
        return uid, cid, res[:-4] if res else ""

    async def gate(request: Request) -> str:
        uid = who(request)
        if not uid:
            raise DavError(401)
        return uid

    def own(uid: str, path_uid: str) -> None:
        if path_uid != uid:
            raise DavError(404)

    def wants_data(body: bytes) -> bool:
        return b"calendar-data" in body

    @app.exception_handler(DavError)
    async def dav_error(request: Request, e: DavError):  # noqa: ANN202
        if e.status == 401:
            return unauthorized()
        return Response(str(e) or {403: "forbidden", 404: "not found", 412: "precondition failed", 400: "bad request"}.get(e.status, ""),
                        status_code=e.status, media_type="text/plain; charset=utf-8")

    @app.api_route(f"{PREFIX}/{{path:path}}", methods=["OPTIONS"])
    @app.api_route(PREFIX, methods=["OPTIONS"])
    async def options(request: Request, path: str = ""):
        return Response(status_code=200, headers={"DAV": "1, 3, calendar-access", "Allow": "OPTIONS, PROPFIND, REPORT, GET, PUT, DELETE"})

    @app.api_route(f"{PREFIX}/{{path:path}}", methods=["PROPFIND"])
    @app.api_route(PREFIX, methods=["PROPFIND"])
    @app.api_route(f"{PREFIX}/", methods=["PROPFIND"])
    async def propfind(request: Request, path: str = ""):
        uid = await gate(request)
        want = requested_props(await request.body())
        d = depth(request)
        puid, cid, res = parse_path(path)
        if not puid:  # the root: where the principal is
            found, missing = pick({"D:current-user-principal": href(f"{PREFIX}/{uid}/"), "D:resourcetype": "<D:collection/>",
                                   "D:displayname": "calendar"}, want)
            return multistatus([response(f"{PREFIX}/", found, missing)])
        own(uid, puid)
        cals = calendars_of(uid)
        if not cid:  # the principal = the home
            out = [response(f"{PREFIX}/{uid}/", *principal_props(uid, want))]
            if d == 1:
                for c in cals.values():
                    out.append(response(f"{PREFIX}/{uid}/{c.id}/", *calendar_props(uid, c, want)))
            return multistatus(out)
        c = cals.get(cid)
        if not c:
            raise DavError(404)
        if res:
            e = store.event(res)
            if not e or e.cal != cid:
                raise DavError(404)
            return multistatus([response(f"{PREFIX}/{uid}/{cid}/{res}.ics", *event_props(e, want))])
        out = [response(f"{PREFIX}/{uid}/{cid}/", *calendar_props(uid, c, want))]
        if d == 1:
            for e in store.events_of([cid]):
                out.append(response(f"{PREFIX}/{uid}/{cid}/{e.id}.ics", *event_props(e, want)))
        return multistatus(out)

    @app.api_route(f"{PREFIX}/{{path:path}}", methods=["REPORT"])
    async def report(request: Request, path: str):
        uid = await gate(request)
        puid, cid, res = parse_path(path)
        own(uid, puid)
        c = calendars_of(uid).get(cid)
        if not c or res:
            raise DavError(404)
        body = await request.body()
        try:
            root = ET.fromstring(body) if body.strip() else None
        except ET.ParseError as e:
            raise DavError(400, "the body is not XML") from e
        if root is None:
            raise DavError(400, "a REPORT needs a body")
        want = requested_props(body)
        kind = qname(root)
        domain = request.headers.get("host", "calendar").split(":")[0]
        if kind == "C:calendar-multiget":
            out = []
            for h in root.findall("D:href", NS):
                name = (h.text or "").strip().rsplit("/", 1)[-1]
                eid = name[:-4] if name.endswith(".ics") else ""
                e = store.event(eid) if eid else None
                if not e or e.cal != cid:
                    out.append(response(h.text or "", {}, [], "HTTP/1.1 404 Not Found"))
                else:
                    out.append(response(f"{PREFIX}/{uid}/{cid}/{e.id}.ics", *event_props(e, want, wants_data(body), domain)))
            return multistatus(out)
        if kind == "C:calendar-query":
            lo = hi = None
            tr = root.find(".//C:time-range", NS)
            if tr is not None:
                lo = read_time(tr.get("start"), {})[0] if tr.get("start") else None
                hi = read_time(tr.get("end"), {})[0] if tr.get("end") else None
            out = []
            for e in store.events_of([cid]):
                if lo is not None or hi is not None:
                    a = lo or datetime(1970, 1, 1, tzinfo=timezone.utc)
                    b = hi or datetime(2100, 1, 1, tzinfo=timezone.utc)
                    if not cal.expand(e, a, b):
                        continue
                out.append(response(f"{PREFIX}/{uid}/{cid}/{e.id}.ics", *event_props(e, want, wants_data(body), domain)))
            return multistatus(out)
        if kind == "D:sync-collection":
            token_el = root.find("D:sync-token", NS)
            token = (token_el.text or "").strip() if token_el is not None else ""
            since = 0
            if token:
                m = re.search(r"/sync/(\d+)$", token)
                if not m:
                    raise DavError(403, "the sync-token is not one of this calendar's")
                since = int(m.group(1))
            out = []
            for e in store.events_of([cid]):
                if e.ver > since:
                    out.append(response(f"{PREFIX}/{uid}/{cid}/{e.id}.ics", *event_props(e, want, wants_data(body), domain)))
            for eid in store.tombstones(cid, since):
                out.append(response(f"{PREFIX}/{uid}/{cid}/{eid}.ics", {}, [], "HTTP/1.1 404 Not Found"))
            out.append(f"<D:sync-token>{esc(f'{PREFIX}/{uid}/{cid}/sync/{store.calendar(cid).version}')}</D:sync-token>")
            return multistatus(out)
        raise DavError(403, f"unsupported report {kind}")

    @app.api_route(f"{PREFIX}/{{path:path}}", methods=["GET", "HEAD"])
    async def get(request: Request, path: str):
        uid = await gate(request)
        puid, cid, res = parse_path(path)
        if puid:
            own(uid, puid)
        if not cid:  # the root, or the caller's home: collections, answered as one (a client may look before it asks)
            return collection(uid)
        if cid not in calendars_of(uid):
            raise DavError(404)
        domain = request.headers.get("host", "calendar").split(":")[0]
        if not res:  # the whole calendar, as a feed (a convenience: a client may GET a collection)
            c = store.calendar(cid)
            return Response(cal.ics([c], store.events_of([cid]), c.name, domain), media_type="text/calendar; charset=utf-8")
        e = store.event(res)
        if not e or e.cal != cid:
            raise DavError(404)
        return Response(cal.ics([], [e], e.summary, domain), media_type="text/calendar; charset=utf-8", headers={"ETag": f'"{e.seq}"'})

    @app.api_route(f"{PREFIX}/{{path:path}}", methods=["PUT"])
    async def put(request: Request, path: str):
        uid = await gate(request)
        puid, cid, res = parse_path(path)
        own(uid, puid)
        if not cid or cid not in calendars_of(uid):
            raise DavError(404)
        if not res or not RESOURCE.match(res):
            raise DavError(403, t("자원 이름은 글자·숫자·._@- 로 128자까지입니다."))
        text = (await request.body()).decode("utf-8", "replace")
        v = read_vevent(text)
        if v["rrule"]:
            try:
                rule = cal.parse_rule(v["rrule"])
            except cal.CalendarError as e:
                raise DavError(403, t("이 반복은 아직 받지 않습니다: {why}", why=str(e))) from e
            v["rrule"] = rule.text() if rule else ""
        if not v["summary"]:
            v["summary"] = t("(제목 없음)")
        current = store.event(res)
        if current and current.cal != cid:
            raise DavError(404)
        if_match = request.headers.get("if-match", "").strip()
        if request.headers.get("if-none-match", "").strip() == "*" and current:
            raise DavError(412)
        if if_match and if_match != "*" and (not current or if_match.strip('"') != str(current.seq)):
            raise DavError(412)
        fields = {"cal": cid, "summary": v["summary"][:200], "description": v["description"][:4000], "location": v["location"][:200],
                  "start": v["start"], "end": v["end"], "allday": v["allday"], "rrule": v["rrule"], "exdates": v["exdates"]}
        if current:
            e = store.update_event(res, uid, **fields)
            store.set_ical(res, v["uid"] or current.ical_uid)
            return Response(status_code=204, headers={"ETag": f'"{e.seq}"'})
        e = store.add_event(uid, eid=res, **fields)
        store.set_ical(res, v["uid"])
        return Response(status_code=201, headers={"ETag": f'"{e.seq}"'})

    @app.api_route(f"{PREFIX}/{{path:path}}", methods=["DELETE"])
    async def delete(request: Request, path: str):
        uid = await gate(request)
        puid, cid, res = parse_path(path)
        own(uid, puid)
        if not cid or cid not in calendars_of(uid):
            raise DavError(404)
        if not res:
            raise DavError(403, t("캘린더는 캘린더 페이지에서 지웁니다."))
        e = store.event(res)
        if not e or e.cal != cid:
            raise DavError(404)
        store.delete_event(res)
        return Response(status_code=204)

    @app.api_route(f"{PREFIX}/{{path:path}}", methods=["MKCALENDAR", "MKCOL", "MOVE", "COPY", "PROPPATCH", "POST"])
    async def refused(request: Request, path: str):
        await gate(request)
        if request.method == "PROPPATCH":
            return Response(status_code=403, content="properties are set on the calendar page", media_type="text/plain")
        return Response(status_code=403, content=t("캘린더는 캘린더 페이지에서 만들고 지웁니다."), media_type="text/plain; charset=utf-8")
