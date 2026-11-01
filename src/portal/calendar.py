"""Calendars: one for each person and one for each of their projects, with iCalendar events, behind
the site sign-in (docs/calendar.md).

    GET    /calendar/api/v1/calendars                the calendars this person may see (made on first sight)
    POST   /calendar/api/v1/calendars                another one of theirs, or of a project of theirs
    PATCH  /calendar/api/v1/calendars/<id>           name, color
    DELETE /calendar/api/v1/calendars/<id>           not the main one of a person or a project
    GET    /calendar/api/v1/events?from&to[&cal=a,b] the occurrences in [from, to): repeats expanded
    POST   /calendar/api/v1/events                   {cal, summary, start, end, allday, rrule, ...}
    GET/PATCH/DELETE /calendar/api/v1/events/<id>
    GET    /calendar/api/v1/freebusy?group=cn&from&to  the members' busy spans, without their titles
    GET/POST/DELETE /calendar/api/v1/feeds[/<token>]   subscription addresses, read-only
    GET    /calendar/feed/<token>.ics                 the feed itself (a public route: the token is the key)

nginx mints the token for the audience `calendar`; what a person may see is theirs and their projects'
(portal/membership.py, NSS, on every request). Time is kept as UTC instants (2026-11-02T09:00:00Z) and
all-day events as dates (2026-11-02, the end exclusive), which is what the ICS feed says as it is.
Repeats are an RRULE subset expanded here: FREQ=DAILY|WEEKLY|MONTHLY|YEARLY, INTERVAL, COUNT, UNTIL,
BYDAY (weekly), plus EXDATE (the instances taken out; they still count toward COUNT, as the standard
says). A write must say `Content-Type: application/json` (as portal/apps.py: a cross-site form cannot).
"""

from __future__ import annotations

import json
import os
import re
import secrets
import sqlite3
import threading
import time
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

from . import membership, tokens
from .config import Settings
from .i18n import N_, t
from .security import SecurityHeadersMiddleware

AUDIENCE = "calendar"
PREFIX = "/calendar/api/v1"
FEED = "/calendar/feed"
NAME = re.compile(r"^[a-z][a-z0-9-]{0,31}$")
COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
INSTANT = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2})?Z$")
FREQS = ("DAILY", "WEEKLY", "MONTHLY", "YEARLY")
DAYS = ("MO", "TU", "WE", "TH", "FR", "SA", "SU")
MAX_OCCURRENCES = 1000  # of one event in one query: a bound, not a feature
MAX_SPAN_DAYS = 400  # of one events query
MAIN_NAME = N_("내 캘린더")  # a person's main calendar, named in their language when first seen

SCHEMA = """
CREATE TABLE IF NOT EXISTS calendars (
    id      TEXT PRIMARY KEY,
    owner   TEXT NOT NULL,              -- a uid (kind user) or a project's cn (kind group)
    kind    TEXT NOT NULL,              -- user | group
    name    TEXT NOT NULL,
    color   TEXT NOT NULL DEFAULT '',
    main    INTEGER NOT NULL DEFAULT 0, -- the one made for the owner on first sight: cannot be deleted
    created REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS calendars_owner ON calendars(owner, kind);
CREATE TABLE IF NOT EXISTS events (
    id          TEXT PRIMARY KEY,
    cal         TEXT NOT NULL REFERENCES calendars(id) ON DELETE CASCADE,
    summary     TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    location    TEXT NOT NULL DEFAULT '',
    start       TEXT NOT NULL,          -- 2026-11-02T09:00:00Z, or 2026-11-02 when allday
    end         TEXT NOT NULL,          -- exclusive
    allday      INTEGER NOT NULL DEFAULT 0,
    rrule       TEXT NOT NULL DEFAULT '',
    exdates     TEXT NOT NULL DEFAULT '[]',
    status      TEXT NOT NULL DEFAULT 'CONFIRMED',
    created     REAL NOT NULL,
    created_by  TEXT NOT NULL,
    updated     REAL NOT NULL,
    updated_by  TEXT NOT NULL,
    seq         INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS events_cal ON events(cal, start);
CREATE TABLE IF NOT EXISTS feeds (
    token   TEXT PRIMARY KEY,
    uid     TEXT NOT NULL,
    cals    TEXT NOT NULL,              -- JSON list of calendar ids, [] = all the person may see
    name    TEXT NOT NULL DEFAULT '',
    created REAL NOT NULL
);
"""


class CalendarError(ValueError):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


# ── time ──────────────────────────────────────────────────────────────────


def parse_when(text: str, allday: bool) -> datetime:
    """A stored or given time as a UTC datetime (a date at midnight when allday)."""
    if allday:
        if not DATE.match(text):
            raise CalendarError(400, t("종일 일정의 날짜는 YYYY-MM-DD 꼴입니다."))
        try:
            d = date.fromisoformat(text)
        except ValueError as e:
            raise CalendarError(400, t("종일 일정의 날짜는 YYYY-MM-DD 꼴입니다.")) from e
        return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
    if not INSTANT.match(text):
        raise CalendarError(400, t("시각은 UTC 로 YYYY-MM-DDTHH:MM:SSZ 꼴입니다."))
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError as e:
        raise CalendarError(400, t("시각은 UTC 로 YYYY-MM-DDTHH:MM:SSZ 꼴입니다.")) from e


def parse_bound(text: str) -> datetime:
    """A query bound: a date or an instant."""
    return parse_when(text, allday=bool(DATE.match(text)))


def fmt(dt: datetime, allday: bool) -> str:
    return dt.date().isoformat() if allday else dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def ics_time(dt: datetime, allday: bool) -> str:
    return dt.strftime("%Y%m%d") if allday else dt.strftime("%Y%m%dT%H%M%SZ")


# ── repeats ───────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Rule:
    freq: str
    interval: int = 1
    count: int | None = None
    until: datetime | None = None
    byday: tuple[int, ...] = ()  # weekday numbers (Monday 0), weekly only

    def text(self) -> str:
        parts = [f"FREQ={self.freq}"]
        if self.interval != 1:
            parts.append(f"INTERVAL={self.interval}")
        if self.byday:
            parts.append("BYDAY=" + ",".join(DAYS[d] for d in self.byday))
        if self.count is not None:
            parts.append(f"COUNT={self.count}")
        if self.until is not None:
            parts.append("UNTIL=" + self.until.strftime("%Y%m%dT%H%M%SZ"))
        return ";".join(parts)


def parse_rule(text: str) -> Rule | None:
    """The RRULE subset this service expands; CalendarError on anything else."""
    text = (text or "").strip()
    if not text:
        return None
    fields: dict[str, str] = {}
    for part in text.split(";"):
        k, _, v = part.partition("=")
        k = k.strip().upper()
        if not k or not v or k in fields:
            raise CalendarError(400, t("반복 규칙을 읽을 수 없습니다: {rule}", rule=text))
        fields[k] = v.strip().upper()
    freq = fields.pop("FREQ", "")
    if freq not in FREQS:
        raise CalendarError(400, t("반복은 DAILY·WEEKLY·MONTHLY·YEARLY 중 하나입니다."))
    try:
        interval = int(fields.pop("INTERVAL", "1"))
        count = int(fields.pop("COUNT")) if "COUNT" in fields else None
    except ValueError as e:
        raise CalendarError(400, t("반복 규칙을 읽을 수 없습니다: {rule}", rule=text)) from e
    if interval < 1 or interval > 366 or (count is not None and not 1 <= count <= MAX_OCCURRENCES):
        raise CalendarError(400, t("반복 규칙을 읽을 수 없습니다: {rule}", rule=text))
    until = None
    if "UNTIL" in fields:
        u = fields.pop("UNTIL")
        try:
            until = (datetime.strptime(u, "%Y%m%dT%H%M%SZ") if "T" in u else datetime.strptime(u, "%Y%m%d")).replace(tzinfo=timezone.utc)
        except ValueError as e:
            raise CalendarError(400, t("반복 규칙을 읽을 수 없습니다: {rule}", rule=text)) from e
    byday: tuple[int, ...] = ()
    if "BYDAY" in fields:
        if freq != "WEEKLY":
            raise CalendarError(400, t("BYDAY 는 매주 반복에서만 씁니다."))
        try:
            byday = tuple(sorted({DAYS.index(d) for d in fields.pop("BYDAY").split(",")}))
        except ValueError as e:
            raise CalendarError(400, t("반복 규칙을 읽을 수 없습니다: {rule}", rule=text)) from e
    if fields:
        raise CalendarError(400, t("반복 규칙에서 모르는 부분: {part}", part=", ".join(sorted(fields))))
    if count is not None and until is not None:
        raise CalendarError(400, t("COUNT 와 UNTIL 은 함께 쓰지 않습니다."))
    return Rule(freq, interval, count, until, byday)


def _add_months(d: datetime, months: int) -> datetime | None:
    y, m = divmod(d.month - 1 + months, 12)
    try:
        return d.replace(year=d.year + y, month=m + 1)
    except ValueError:
        return None  # no such day that month (the 31st, Feb 29): the standard skips it


def occurrences(start: datetime, rule: Rule | None) -> Iterator[datetime]:
    """The starts of an event's instances, in order, from its first; finite under COUNT/UNTIL, else
    the caller stops. Weekly BYDAY: the named days of every INTERVAL-th week from the week of `start`
    (weeks start on Monday), none before `start`."""
    if rule is None:
        yield start
        return
    n = 0

    def ok(dt: datetime) -> bool:
        return rule.until is None or dt <= rule.until

    if rule.freq == "WEEKLY" and rule.byday:
        week = start - timedelta(days=start.weekday())
        w = 0
        while True:
            for d in rule.byday:
                dt = week + timedelta(days=w * 7 * rule.interval + d)
                if dt < start:
                    continue
                if not ok(dt) or (rule.count is not None and n >= rule.count):
                    return
                n += 1
                yield dt
            w += 1
            if w > 100000:
                return
        return
    k = 0
    while True:
        if rule.freq == "DAILY":
            dt: datetime | None = start + timedelta(days=k * rule.interval)
        elif rule.freq == "WEEKLY":
            dt = start + timedelta(days=7 * k * rule.interval)
        elif rule.freq == "MONTHLY":
            dt = _add_months(start, k * rule.interval)
        else:
            dt = _add_months(start, 12 * k * rule.interval)
        k += 1
        if k > 100000:
            return
        if dt is None:
            continue
        if not ok(dt):
            return
        if rule.count is not None and n >= rule.count:
            return
        n += 1  # only generated instances count: a month without the day is not one
        yield dt


# ── the store ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Calendar:
    id: str
    owner: str
    kind: str
    name: str
    color: str
    main: bool
    created: float

    def json(self) -> dict:
        return {"id": self.id, "owner": self.owner, "kind": self.kind, "name": self.name, "color": self.color,
                "main": self.main, "created": self.created}


@dataclass(frozen=True)
class Event:
    id: str
    cal: str
    summary: str
    description: str
    location: str
    start: str
    end: str
    allday: bool
    rrule: str
    exdates: tuple[str, ...]
    status: str
    created: float
    created_by: str
    updated: float
    updated_by: str
    seq: int

    def json(self) -> dict:
        return {"id": self.id, "cal": self.cal, "summary": self.summary, "description": self.description,
                "location": self.location, "start": self.start, "end": self.end, "allday": self.allday,
                "rrule": self.rrule, "exdates": list(self.exdates), "status": self.status, "created": self.created,
                "created_by": self.created_by, "updated": self.updated, "updated_by": self.updated_by, "seq": self.seq}


class Store:
    def __init__(self, path: str):
        if path != ":memory:":
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self._lock = threading.Lock()
        self.db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self.db.execute("PRAGMA foreign_keys = ON")
        self.db.executescript(SCHEMA)
        if path != ":memory:":
            os.chmod(path, 0o600)

    # calendars
    def _cal(self, row: tuple) -> Calendar:
        return Calendar(row[0], row[1], row[2], row[3], row[4], bool(row[5]), row[6])

    def main_calendar(self, owner: str, kind: str, name: str = "") -> Calendar:
        """The owner's main calendar, made on first sight (named `name`, else after the owner)."""
        with self._lock:
            row = self.db.execute("SELECT * FROM calendars WHERE owner=? AND kind=? AND main=1", (owner, kind)).fetchone()
            if row:
                return self._cal(row)
            cid = f"{kind[0]}-{uuid.uuid4().hex[:12]}"
            name = name or owner
            self.db.execute("INSERT INTO calendars VALUES (?,?,?,?,?,1,?)", (cid, owner, kind, name, "", time.time()))
            return self._cal(self.db.execute("SELECT * FROM calendars WHERE id=?", (cid,)).fetchone())

    def calendars_of(self, owner: str, kind: str) -> list[Calendar]:
        with self._lock:
            rows = self.db.execute("SELECT * FROM calendars WHERE owner=? AND kind=? ORDER BY main DESC, created", (owner, kind)).fetchall()
        return [self._cal(r) for r in rows]

    def calendar(self, cid: str) -> Calendar | None:
        with self._lock:
            row = self.db.execute("SELECT * FROM calendars WHERE id=?", (cid,)).fetchone()
        return self._cal(row) if row else None

    def add_calendar(self, owner: str, kind: str, name: str, color: str) -> Calendar:
        cid = f"{kind[0]}-{uuid.uuid4().hex[:12]}"
        with self._lock:
            self.db.execute("INSERT INTO calendars VALUES (?,?,?,?,?,0,?)", (cid, owner, kind, name, color, time.time()))
            return self._cal(self.db.execute("SELECT * FROM calendars WHERE id=?", (cid,)).fetchone())

    def update_calendar(self, cid: str, name: str | None, color: str | None) -> Calendar:
        with self._lock:
            if name is not None:
                self.db.execute("UPDATE calendars SET name=? WHERE id=?", (name, cid))
            if color is not None:
                self.db.execute("UPDATE calendars SET color=? WHERE id=?", (color, cid))
            return self._cal(self.db.execute("SELECT * FROM calendars WHERE id=?", (cid,)).fetchone())

    def delete_calendar(self, cid: str) -> None:
        with self._lock:
            self.db.execute("DELETE FROM calendars WHERE id=?", (cid,))

    # events
    def _event(self, row: tuple) -> Event:
        return Event(row[0], row[1], row[2], row[3], row[4], row[5], row[6], bool(row[7]), row[8],
                     tuple(json.loads(row[9])), row[10], row[11], row[12], row[13], row[14], row[15])

    def event(self, eid: str) -> Event | None:
        with self._lock:
            row = self.db.execute("SELECT * FROM events WHERE id=?", (eid,)).fetchone()
        return self._event(row) if row else None

    def events_of(self, cals: list[str]) -> list[Event]:
        if not cals:
            return []
        q = ",".join("?" * len(cals))
        with self._lock:
            rows = self.db.execute(f"SELECT * FROM events WHERE cal IN ({q}) ORDER BY start", cals).fetchall()
        return [self._event(r) for r in rows]

    def add_event(self, by: str, **v) -> Event:  # noqa: ANN003
        eid = uuid.uuid4().hex
        now = time.time()
        with self._lock:
            self.db.execute("INSERT INTO events VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0)",
                            (eid, v["cal"], v["summary"], v["description"], v["location"], v["start"], v["end"],
                             int(v["allday"]), v["rrule"], json.dumps(v["exdates"]), "CONFIRMED", now, by, now, by))
            return self._event(self.db.execute("SELECT * FROM events WHERE id=?", (eid,)).fetchone())

    def update_event(self, eid: str, by: str, **v) -> Event:  # noqa: ANN003
        with self._lock:
            self.db.execute("UPDATE events SET cal=?, summary=?, description=?, location=?, start=?, end=?, allday=?, rrule=?,"
                            " exdates=?, updated=?, updated_by=?, seq=seq+1 WHERE id=?",
                            (v["cal"], v["summary"], v["description"], v["location"], v["start"], v["end"], int(v["allday"]),
                             v["rrule"], json.dumps(v["exdates"]), time.time(), by, eid))
            return self._event(self.db.execute("SELECT * FROM events WHERE id=?", (eid,)).fetchone())

    def delete_event(self, eid: str) -> None:
        with self._lock:
            self.db.execute("DELETE FROM events WHERE id=?", (eid,))

    # feeds
    def feeds_of(self, uid: str) -> list[dict]:
        with self._lock:
            rows = self.db.execute("SELECT token, cals, name, created FROM feeds WHERE uid=? ORDER BY created", (uid,)).fetchall()
        return [{"token": r[0], "cals": json.loads(r[1]), "name": r[2], "created": r[3]} for r in rows]

    def add_feed(self, uid: str, cals: list[str], name: str) -> str:
        token = secrets.token_urlsafe(24)
        with self._lock:
            self.db.execute("INSERT INTO feeds VALUES (?,?,?,?,?)", (token, uid, json.dumps(cals), name, time.time()))
        return token

    def feed(self, token: str) -> dict | None:
        with self._lock:
            row = self.db.execute("SELECT token, uid, cals, name FROM feeds WHERE token=?", (token,)).fetchone()
        return {"token": row[0], "uid": row[1], "cals": json.loads(row[2]), "name": row[3]} if row else None

    def delete_feed(self, uid: str, token: str) -> bool:
        with self._lock:
            n = self.db.execute("DELETE FROM feeds WHERE uid=? AND token=?", (uid, token)).rowcount
        return n > 0


# ── expansion ─────────────────────────────────────────────────────────────


def expand(e: Event, lo: datetime, hi: datetime) -> list[dict]:
    """The occurrences of `e` that overlap [lo, hi), as the page draws them."""
    start = parse_when(e.start, e.allday)
    end = parse_when(e.end, e.allday)
    length = end - start
    rule = parse_rule(e.rrule) if e.rrule else None
    out = []
    n = 0
    for s in occurrences(start, rule):
        n += 1
        if s >= hi or n > MAX_OCCURRENCES:
            break
        if s + length <= lo:
            continue
        if fmt(s, e.allday) in e.exdates:
            continue
        out.append({**e.json(), "start": fmt(s, e.allday), "end": fmt(s + length, e.allday),
                    "first": e.start, "recurring": rule is not None})
    return out


def ics(calendars: list[Calendar], events: list[Event], name: str) -> str:
    """The calendars as an iCalendar feed: the events as kept (RRULE and EXDATE included)."""
    def esc(s: str) -> str:
        return s.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")

    def fold(line: str) -> str:  # RFC 5545 §3.1: lines of at most 75 octets, continued with a space
        out, b = [], line.encode()
        while len(b) > 75:
            cut = 75
            while cut > 0 and (b[cut] & 0xC0) == 0x80:  # never inside a multibyte character
                cut -= 1
            out.append(b[:cut].decode())
            b = b" " + b[cut:]
        out.append(b.decode())
        return "\r\n".join(out)

    names = {c.id: c.name for c in calendars}
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//m00nny//calendar//KO", "CALSCALE:GREGORIAN",
             f"X-WR-CALNAME:{esc(name)}"]
    for e in events:
        s, en = parse_when(e.start, e.allday), parse_when(e.end, e.allday)
        kind = ";VALUE=DATE" if e.allday else ""
        lines += ["BEGIN:VEVENT", f"UID:{e.id}@m00nny", f"DTSTAMP:{ics_time(datetime.fromtimestamp(e.updated, timezone.utc), False)}",
                  f"DTSTART{kind}:{ics_time(s, e.allday)}", f"DTEND{kind}:{ics_time(en, e.allday)}",
                  f"SUMMARY:{esc(e.summary)}", f"SEQUENCE:{e.seq}", f"STATUS:{e.status}"]
        if e.description:
            lines.append(f"DESCRIPTION:{esc(e.description)}")
        if e.location:
            lines.append(f"LOCATION:{esc(e.location)}")
        if names.get(e.cal):
            lines.append(f"CATEGORIES:{esc(names[e.cal])}")
        if e.rrule:
            lines.append(f"RRULE:{parse_rule(e.rrule).text()}")  # type: ignore[union-attr]
        for x in e.exdates:
            lines.append(f"EXDATE{kind}:{ics_time(parse_when(x, e.allday), e.allday)}")
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    return "\r\n".join(fold(ln) for ln in lines) + "\r\n"


# ── the service ───────────────────────────────────────────────────────────


def create_app(settings: Settings | None = None, store: Store | None = None, public_key=None,  # noqa: ANN001
               projects_of: Callable[[str], set[str]] | None = None,
               members_of: Callable[[str], list[str]] | None = None) -> FastAPI:
    s = settings or Settings()
    public_key = public_key or tokens.load_public_key(s.sso_public_key_file)
    store = store or Store(s.calendar_db)
    projects_of = projects_of or (lambda uid: membership.project_groups_of(uid, s.project_gid_min, s.project_gid_max))
    members_of = members_of or membership.members_of

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(SecurityHeadersMiddleware)
    from . import i18n

    app.add_middleware(i18n.Language)

    def err(status: int, message: str) -> JSONResponse:
        return JSONResponse({"error": message}, status_code=status)

    @app.exception_handler(CalendarError)
    async def calendar_error(request: Request, e: CalendarError):  # noqa: ANN202
        return err(e.status, str(e))

    def who(request: Request) -> str:
        token = request.headers.get("x-auth-token", "")
        try:
            return tokens.verify(public_key, token, s.sso_issuer, AUDIENCE) if token else ""
        except tokens.TokenError:
            return ""

    def gate(request: Request) -> str:
        uid = who(request)
        if not uid:
            raise CalendarError(401, t("먼저 로그인하세요."))
        return uid

    def visible(uid: str) -> list[Calendar]:
        """The calendars this person may see: theirs, and each of their projects' (made on first sight)."""
        store.main_calendar(uid, "user", t(MAIN_NAME))
        out = store.calendars_of(uid, "user")
        for g in sorted(projects_of(uid)):
            store.main_calendar(g, "group")
            out += store.calendars_of(g, "group")
        return out

    def mine(uid: str, cid: str) -> Calendar:
        c = store.calendar(cid)
        if not c or c.id not in {x.id for x in visible(uid)}:
            raise CalendarError(404, t("그런 캘린더가 없습니다."))
        return c

    async def body_of(request: Request) -> dict:
        if request.headers.get("content-type", "").split(";")[0].strip() != "application/json":
            raise CalendarError(415, "send application/json")
        try:
            data = json.loads(await request.body())
        except ValueError as e:
            raise CalendarError(400, "the body is not JSON") from e
        if not isinstance(data, dict):
            raise CalendarError(400, "the body is not a JSON object")
        return data

    def text_field(data: dict, name: str, limit: int, required: bool = False, default: str = "") -> str:
        v = data.get(name, default)
        if v is None:
            v = ""
        if not isinstance(v, str):
            raise CalendarError(400, t("{name} 은(는) 글입니다.", name=name))
        v = v.strip()
        if required and not v:
            raise CalendarError(400, t("{name} 을(를) 적으세요.", name=name))
        if len(v) > limit:
            raise CalendarError(400, t("{name} 은(는) {n}자까지입니다.", name=name, n=limit))
        return v

    def event_values(uid: str, data: dict, current: Event | None = None) -> dict:
        """A new or changed event's fields, checked; the calendar must be one the person may see."""
        base = current.json() if current else {}
        merged = {**base, **data}
        cal = mine(uid, str(merged.get("cal", "")))
        allday = bool(merged.get("allday", False))
        start_s = text_field(merged, "start", 32, required=True)
        end_s = text_field(merged, "end", 32)
        start = parse_when(start_s, allday)
        end = parse_when(end_s, allday) if end_s else start + (timedelta(days=1) if allday else timedelta(hours=1))
        if allday and end <= start:
            end = start + timedelta(days=1)
        if end <= start:
            raise CalendarError(400, t("끝은 시작 뒤여야 합니다."))
        rrule = text_field(merged, "rrule", 200)
        rule = parse_rule(rrule)
        exdates = merged.get("exdates") or []
        if not isinstance(exdates, list) or any(not isinstance(x, str) for x in exdates):
            raise CalendarError(400, t("exdates 는 날짜 목록입니다."))
        for x in exdates:
            parse_when(x, allday)
        return {"cal": cal.id, "summary": text_field(merged, "summary", 200, required=True),
                "description": text_field(merged, "description", 4000), "location": text_field(merged, "location", 200),
                "start": fmt(start, allday), "end": fmt(end, allday), "allday": allday,
                "rrule": rule.text() if rule else "", "exdates": sorted(set(exdates))}

    def span(request: Request) -> tuple[datetime, datetime]:
        lo = request.query_params.get("from", "")
        hi = request.query_params.get("to", "")
        if not lo or not hi:
            raise CalendarError(400, t("from 과 to 를 주세요."))
        a, b = parse_bound(lo), parse_bound(hi)
        if b <= a or b - a > timedelta(days=MAX_SPAN_DAYS):
            raise CalendarError(400, t("구간은 {n}일까지입니다.", n=MAX_SPAN_DAYS))
        return a, b

    # ── calendars
    @app.get(f"{PREFIX}/calendars")
    async def list_calendars(request: Request):
        uid = gate(request)
        return {"calendars": [c.json() for c in visible(uid)], "projects": sorted(projects_of(uid))}

    @app.post(f"{PREFIX}/calendars")
    async def add_calendar(request: Request):
        uid = gate(request)
        data = await body_of(request)
        name = text_field(data, "name", 60, required=True)
        color = text_field(data, "color", 7)
        if color and not COLOR.match(color):
            raise CalendarError(400, t("색은 #rrggbb 꼴입니다."))
        group = text_field(data, "group", 32)
        if group:
            if group not in projects_of(uid):
                raise CalendarError(404, t("그런 프로젝트가 없습니다."))
            c = store.add_calendar(group, "group", name, color)
        else:
            c = store.add_calendar(uid, "user", name, color)
        return JSONResponse(c.json(), status_code=201)

    @app.patch(f"{PREFIX}/calendars/{{cid}}")
    async def update_calendar(request: Request, cid: str):
        uid = gate(request)
        mine(uid, cid)
        data = await body_of(request)
        name = text_field(data, "name", 60, required=True) if "name" in data else None
        color = text_field(data, "color", 7) if "color" in data else None
        if color and not COLOR.match(color):
            raise CalendarError(400, t("색은 #rrggbb 꼴입니다."))
        return store.update_calendar(cid, name, color).json()

    @app.delete(f"{PREFIX}/calendars/{{cid}}")
    async def delete_calendar(request: Request, cid: str):
        uid = gate(request)
        c = mine(uid, cid)
        if c.main:
            raise CalendarError(409, t("기본 캘린더는 지울 수 없습니다."))
        store.delete_calendar(cid)
        return Response(status_code=204)

    # ── events
    @app.get(f"{PREFIX}/events")
    async def list_events(request: Request):
        uid = gate(request)
        lo, hi = span(request)
        cals = visible(uid)
        want = [x for x in request.query_params.get("cal", "").split(",") if x]
        ids = [c.id for c in cals if not want or c.id in want]
        out = []
        for e in store.events_of(ids):
            out += expand(e, lo, hi)
        out.sort(key=lambda o: (o["start"], o["summary"]))
        return {"events": out}

    @app.post(f"{PREFIX}/events")
    async def add_event(request: Request):
        uid = gate(request)
        data = await body_of(request)
        return JSONResponse(store.add_event(uid, **event_values(uid, data)).json(), status_code=201)

    def owned_event(uid: str, eid: str) -> Event:
        e = store.event(eid)
        if not e or e.cal not in {c.id for c in visible(uid)}:
            raise CalendarError(404, t("그런 일정이 없습니다."))
        return e

    @app.get(f"{PREFIX}/events/{{eid}}")
    async def get_event(request: Request, eid: str):
        return owned_event(gate(request), eid).json()

    @app.patch(f"{PREFIX}/events/{{eid}}")
    async def update_event(request: Request, eid: str):
        uid = gate(request)
        e = owned_event(uid, eid)
        data = await body_of(request)
        return store.update_event(eid, uid, **event_values(uid, data, e)).json()

    @app.delete(f"{PREFIX}/events/{{eid}}")
    async def delete_event(request: Request, eid: str):
        uid = gate(request)
        owned_event(uid, eid)
        store.delete_event(eid)
        return Response(status_code=204)

    # ── free/busy of a project's members
    @app.get(f"{PREFIX}/freebusy")
    async def freebusy(request: Request):
        uid = gate(request)
        group = request.query_params.get("group", "")
        if group not in projects_of(uid):
            raise CalendarError(404, t("그런 프로젝트가 없습니다."))
        lo, hi = span(request)
        busy: dict[str, list[list[str]]] = {}
        for member in sorted(members_of(group)):
            cals = [c.id for c in store.calendars_of(member, "user")]
            spans = []
            for e in store.events_of(cals):
                spans += [[o["start"], o["end"]] for o in expand(e, lo, hi)]
            busy[member] = sorted(spans)
        return {"group": group, "busy": busy}

    # ── feeds
    def feed_url(request: Request, token: str) -> str:
        return f"{request.url.scheme}://{request.headers.get('host', request.url.netloc)}{FEED}/{token}.ics"

    @app.get(f"{PREFIX}/feeds")
    async def list_feeds(request: Request):
        uid = gate(request)
        return {"feeds": [{**f, "url": feed_url(request, f["token"])} for f in store.feeds_of(uid)]}

    @app.post(f"{PREFIX}/feeds")
    async def add_feed(request: Request):
        uid = gate(request)
        data = await body_of(request)
        name = text_field(data, "name", 60)
        cals = data.get("cals") or []
        if not isinstance(cals, list) or any(not isinstance(x, str) for x in cals):
            raise CalendarError(400, t("cals 는 캘린더 id 목록입니다."))
        for cid in cals:
            mine(uid, cid)
        if len(store.feeds_of(uid)) >= 20:
            raise CalendarError(409, t("구독 주소는 20개까지입니다. 몇 개를 먼저 거두세요."))
        token = store.add_feed(uid, cals, name)
        return JSONResponse({"token": token, "cals": cals, "name": name, "url": feed_url(request, token)}, status_code=201)

    @app.delete(f"{PREFIX}/feeds/{{token}}")
    async def delete_feed(request: Request, token: str):
        uid = gate(request)
        if not store.delete_feed(uid, token):
            raise CalendarError(404, t("그런 구독 주소가 없습니다."))
        return Response(status_code=204)

    @app.get(f"{FEED}/{{token}}.ics")
    async def feed(token: str):
        """The feed: public by route, the token being the key; what it shows is what its owner may see
        now (a lost membership stops a project's events)."""
        f = store.feed(token)
        if not f:
            return Response("not found", status_code=404, media_type="text/plain")
        cals = visible(f["uid"])
        if f["cals"]:
            cals = [c for c in cals if c.id in f["cals"]]
        text = ics(cals, store.events_of([c.id for c in cals]), f["name"] or (cals[0].name if len(cals) == 1 else "calendar"))
        return Response(text, media_type="text/calendar; charset=utf-8",
                        headers={"Cache-Control": "private, max-age=300", "Content-Disposition": "inline; filename=calendar.ics"})

    @app.get("/calendar/healthz")
    async def healthz():
        return Response("ok", media_type="text/plain")

    return app
