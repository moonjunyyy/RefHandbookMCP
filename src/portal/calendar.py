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
    GET    /calendar/api/v1/tasks                    this person's to-do list: open ones first, by rank
    POST   /calendar/api/v1/tasks                    {text, due?}  (due a date, or absent)
    PATCH  /calendar/api/v1/tasks/<id>               text, done, due, rank
    DELETE /calendar/api/v1/tasks/<id>
    POST   /calendar/api/v1/tasks/clear-done         takes out the ones that are done
    GET    /calendar/api/v1/devices                  the device passwords (name, when made and last used — never the password)
    POST   /calendar/api/v1/devices {name}           a new one: the password is in the answer, once
    DELETE /calendar/api/v1/devices/<id>
    /calendar/dav/…                                  CalDAV (portal/caldav.py), HTTP Basic with uid and a device password

nginx mints the token for the audience `calendar`; what a person may see is theirs and their projects'
(portal/membership.py, NSS, on every request). Time is kept as UTC instants (2026-11-02T09:00:00Z) and
all-day events as dates (2026-11-02, the end exclusive), which is what the ICS feed says as it is.
Repeats are an RRULE subset expanded here: FREQ=DAILY|WEEKLY|MONTHLY|YEARLY, INTERVAL, COUNT, UNTIL,
BYDAY (weekly), plus EXDATE (the instances taken out; they still count toward COUNT, as the standard
says). A write must say `Content-Type: application/json` (as portal/apps.py: a cross-site form cannot).
The to-do list (docs/apps-vault-calendar.md §7.3) is the person's own: short lines with a done mark and
a due date, kept here because the main page's `tasks` widget and the day panel show them next to the
events of the day; it is not an event and does not go into the feeds.
"""

from __future__ import annotations

import hashlib
import hmac
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

from . import caldav, membership, tokens
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
CREATE TABLE IF NOT EXISTS tasks (
    id      TEXT PRIMARY KEY,
    uid     TEXT NOT NULL,
    text    TEXT NOT NULL,
    done    INTEGER NOT NULL DEFAULT 0,
    due     TEXT NOT NULL DEFAULT '',   -- 2026-11-02, or '' when it has no day
    rank    REAL NOT NULL,              -- the order the person keeps: lower first; a new one goes last
    created REAL NOT NULL,
    updated REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS tasks_uid ON tasks(uid, done, rank);
CREATE TABLE IF NOT EXISTS tombstones (
    cal     TEXT NOT NULL,              -- an event deleted from this calendar, at this version (sync-collection)
    id      TEXT NOT NULL,
    version INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS tombstones_cal ON tombstones(cal, version);
CREATE TABLE IF NOT EXISTS devices (
    id        TEXT PRIMARY KEY,
    uid       TEXT NOT NULL,
    name      TEXT NOT NULL,
    secret    TEXT NOT NULL,            -- sha256 of the password; the password itself is shown once and kept nowhere
    created   REAL NOT NULL,
    last_used REAL NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS devices_uid ON devices(uid);
"""
# columns added after the first release (CREATE TABLE IF NOT EXISTS does not add them): table → (column, DDL)
MIGRATIONS = (("calendars", "version", "INTEGER NOT NULL DEFAULT 0"),   # grows with every change under it: the ctag / sync-token
              ("events", "ver", "INTEGER NOT NULL DEFAULT 0"),            # the calendar's version at the last write
              ("events", "ical_uid", "TEXT NOT NULL DEFAULT ''"))         # the UID a CalDAV client gave, kept as it came
MAX_TASKS = 200  # open or done, of one person
MAX_DEVICES = 20  # of one person


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
    version: int = 0

    def json(self) -> dict:
        return {"id": self.id, "owner": self.owner, "kind": self.kind, "name": self.name, "color": self.color,
                "main": self.main, "created": self.created, "version": self.version}


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
    ver: int = 0
    ical_uid: str = ""

    def json(self) -> dict:
        return {"id": self.id, "cal": self.cal, "summary": self.summary, "description": self.description,
                "location": self.location, "start": self.start, "end": self.end, "allday": self.allday,
                "rrule": self.rrule, "exdates": list(self.exdates), "status": self.status, "created": self.created,
                "created_by": self.created_by, "updated": self.updated, "updated_by": self.updated_by, "seq": self.seq}


@dataclass
class Task:
    id: str
    uid: str
    text: str
    done: bool
    due: str
    rank: float
    created: float
    updated: float

    def json(self) -> dict:
        return {"id": self.id, "text": self.text, "done": self.done, "due": self.due, "rank": self.rank,
                "created": self.created, "updated": self.updated}


class Store:
    def __init__(self, path: str):
        if path != ":memory:":
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self._lock = threading.Lock()
        self.db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self.db.execute("PRAGMA foreign_keys = ON")
        self.db.executescript(SCHEMA)
        for table, column, ddl in MIGRATIONS:
            if column not in {r[1] for r in self.db.execute(f"PRAGMA table_info({table})")}:
                self.db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")
        if path != ":memory:":
            os.chmod(path, 0o600)

    # calendars
    def _cal(self, row: tuple) -> Calendar:
        return Calendar(row[0], row[1], row[2], row[3], row[4], bool(row[5]), row[6], row[7])

    def _bump(self, cid: str) -> int:
        """A change under the calendar: its version grows (the ctag and the sync-token). Under the lock."""
        self.db.execute("UPDATE calendars SET version=version+1 WHERE id=?", (cid,))
        return self.db.execute("SELECT version FROM calendars WHERE id=?", (cid,)).fetchone()[0]

    def main_calendar(self, owner: str, kind: str, name: str = "") -> Calendar:
        """The owner's main calendar, made on first sight (named `name`, else after the owner)."""
        with self._lock:
            row = self.db.execute("SELECT * FROM calendars WHERE owner=? AND kind=? AND main=1", (owner, kind)).fetchone()
            if row:
                return self._cal(row)
            cid = f"{kind[0]}-{uuid.uuid4().hex[:12]}"
            name = name or owner
            self.db.execute("INSERT INTO calendars VALUES (?,?,?,?,?,1,?,0)", (cid, owner, kind, name, "", time.time()))
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
            self.db.execute("INSERT INTO calendars VALUES (?,?,?,?,?,0,?,0)", (cid, owner, kind, name, color, time.time()))
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
                     tuple(json.loads(row[9])), row[10], row[11], row[12], row[13], row[14], row[15], row[16], row[17])

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

    def add_event(self, by: str, eid: str = "", **v) -> Event:  # noqa: ANN003
        eid = eid or uuid.uuid4().hex
        now = time.time()
        with self._lock:
            ver = self._bump(v["cal"])
            self.db.execute("INSERT INTO events VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0,?,'')",
                            (eid, v["cal"], v["summary"], v["description"], v["location"], v["start"], v["end"],
                             int(v["allday"]), v["rrule"], json.dumps(v["exdates"]), "CONFIRMED", now, by, now, by, ver))
            return self._event(self.db.execute("SELECT * FROM events WHERE id=?", (eid,)).fetchone())

    def update_event(self, eid: str, by: str, **v) -> Event:  # noqa: ANN003
        with self._lock:
            was = self.db.execute("SELECT cal FROM events WHERE id=?", (eid,)).fetchone()
            ver = self._bump(v["cal"])
            if was and was[0] != v["cal"]:  # moved to another calendar: gone from the old one's point of view
                old_ver = self._bump(was[0])
                self.db.execute("INSERT INTO tombstones VALUES (?,?,?)", (was[0], eid, old_ver))
            self.db.execute("UPDATE events SET cal=?, summary=?, description=?, location=?, start=?, end=?, allday=?, rrule=?,"
                            " exdates=?, updated=?, updated_by=?, seq=seq+1, ver=? WHERE id=?",
                            (v["cal"], v["summary"], v["description"], v["location"], v["start"], v["end"], int(v["allday"]),
                             v["rrule"], json.dumps(v["exdates"]), time.time(), by, ver, eid))
            return self._event(self.db.execute("SELECT * FROM events WHERE id=?", (eid,)).fetchone())

    def set_ical(self, eid: str, ical_uid: str) -> None:
        with self._lock:
            self.db.execute("UPDATE events SET ical_uid=? WHERE id=?", (ical_uid[:255], eid))

    def delete_event(self, eid: str) -> None:
        with self._lock:
            row = self.db.execute("SELECT cal FROM events WHERE id=?", (eid,)).fetchone()
            if not row:
                return
            ver = self._bump(row[0])
            self.db.execute("DELETE FROM events WHERE id=?", (eid,))
            self.db.execute("INSERT INTO tombstones VALUES (?,?,?)", (row[0], eid, ver))

    def tombstones(self, cid: str, since: int) -> list[str]:
        """The ids deleted from the calendar after version `since`."""
        with self._lock:
            rows = self.db.execute("SELECT id FROM tombstones WHERE cal=? AND version>? ORDER BY version", (cid, since)).fetchall()
        return [r[0] for r in rows]

    # devices: a password per device for CalDAV (shown once; kept as a hash)
    def devices_of(self, uid: str) -> list[dict]:
        with self._lock:
            rows = self.db.execute("SELECT id, name, created, last_used FROM devices WHERE uid=? ORDER BY created", (uid,)).fetchall()
        return [{"id": r[0], "name": r[1], "created": r[2], "last_used": r[3]} for r in rows]

    def add_device(self, uid: str, name: str) -> tuple[dict, str]:
        did = uuid.uuid4().hex[:10]
        password = secrets.token_urlsafe(18)
        now = time.time()
        with self._lock:
            self.db.execute("INSERT INTO devices VALUES (?,?,?,?,?,0)", (did, uid, name, hashlib.sha256(password.encode()).hexdigest(), now))
        return {"id": did, "name": name, "created": now, "last_used": 0}, password

    def delete_device(self, uid: str, did: str) -> bool:
        with self._lock:
            return self.db.execute("DELETE FROM devices WHERE uid=? AND id=?", (uid, did)).rowcount > 0

    def device_login(self, uid: str, password: str) -> bool:
        """Whether the password is one of the person's devices' (constant-time compare per device)."""
        digest = hashlib.sha256(password.encode()).hexdigest()
        with self._lock:
            rows = self.db.execute("SELECT id, secret FROM devices WHERE uid=?", (uid,)).fetchall()
            hit = [r[0] for r in rows if hmac.compare_digest(r[1], digest)]
            if hit:
                self.db.execute("UPDATE devices SET last_used=? WHERE id=?", (time.time(), hit[0]))
        return bool(hit)

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

    # tasks
    def _task(self, row: tuple) -> Task:
        return Task(row[0], row[1], row[2], bool(row[3]), row[4], row[5], row[6], row[7])

    def tasks_of(self, uid: str) -> list[Task]:
        """Open ones first in the person's order, then the done ones, the latest done first."""
        with self._lock:
            rows = self.db.execute("SELECT * FROM tasks WHERE uid=? ORDER BY done, CASE WHEN done THEN -updated ELSE rank END",
                                   (uid,)).fetchall()
        return [self._task(r) for r in rows]

    def task(self, uid: str, tid: str) -> Task | None:
        with self._lock:
            row = self.db.execute("SELECT * FROM tasks WHERE uid=? AND id=?", (uid, tid)).fetchone()
        return self._task(row) if row else None

    def add_task(self, uid: str, text: str, due: str) -> Task:
        tid = uuid.uuid4().hex[:12]
        now = time.time()
        with self._lock:
            last = self.db.execute("SELECT MAX(rank) FROM tasks WHERE uid=?", (uid,)).fetchone()[0]
            rank = (last or 0.0) + 1.0
            self.db.execute("INSERT INTO tasks VALUES (?,?,?,0,?,?,?,?)", (tid, uid, text, due, rank, now, now))
            return self._task(self.db.execute("SELECT * FROM tasks WHERE id=?", (tid,)).fetchone())

    def update_task(self, uid: str, tid: str, **v) -> Task:  # noqa: ANN003
        sets = ", ".join(f"{k}=?" for k in v)
        with self._lock:
            self.db.execute(f"UPDATE tasks SET {sets}, updated=? WHERE uid=? AND id=?", (*v.values(), time.time(), uid, tid))
            return self._task(self.db.execute("SELECT * FROM tasks WHERE id=?", (tid,)).fetchone())

    def delete_task(self, uid: str, tid: str) -> bool:
        with self._lock:
            return self.db.execute("DELETE FROM tasks WHERE uid=? AND id=?", (uid, tid)).rowcount > 0

    def clear_done_tasks(self, uid: str) -> int:
        with self._lock:
            return self.db.execute("DELETE FROM tasks WHERE uid=? AND done=1", (uid,)).rowcount


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


def ics(calendars: list[Calendar], events: list[Event], name: str, domain: str = "calendar") -> str:
    """The calendars as an iCalendar feed: the events as kept (RRULE and EXDATE included). A UID a
    CalDAV client gave is kept as it came; the service's own are <id>@<domain>."""
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
        lines += ["BEGIN:VEVENT", f"UID:{esc(e.ical_uid) if e.ical_uid else f'{e.id}@{domain}'}",
                  f"DTSTAMP:{ics_time(datetime.fromtimestamp(e.updated, timezone.utc), False)}",
                  f"LAST-MODIFIED:{ics_time(datetime.fromtimestamp(e.updated, timezone.utc), False)}",
                  f"CREATED:{ics_time(datetime.fromtimestamp(e.created, timezone.utc), False)}",
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
    async def feed(request: Request, token: str):
        """The feed: public by route, the token being the key; what it shows is what its owner may see
        now (a lost membership stops a project's events)."""
        f = store.feed(token)
        if not f:
            return Response("not found", status_code=404, media_type="text/plain")
        cals = visible(f["uid"])
        if f["cals"]:
            cals = [c for c in cals if c.id in f["cals"]]
        text = ics(cals, store.events_of([c.id for c in cals]), f["name"] or (cals[0].name if len(cals) == 1 else "calendar"),
                   request.headers.get("host", "calendar").split(":")[0])
        return Response(text, media_type="text/calendar; charset=utf-8",
                        headers={"Cache-Control": "private, max-age=300", "Content-Disposition": "inline; filename=calendar.ics"})

    # ── tasks (the person's own to-do list)
    def task_values(data: dict, current: Task | None) -> dict:
        v: dict = {}
        if "text" in data or current is None:
            v["text"] = text_field(data, "text", 200, required=True)
        if "due" in data:
            due = text_field(data, "due", 10)
            if due and not DATE.match(due):
                raise CalendarError(400, t("due 는 날짜(2026-11-02)입니다."))
            v["due"] = due
        if "done" in data:
            if not isinstance(data["done"], bool):
                raise CalendarError(400, t("done 은 참/거짓입니다."))
            v["done"] = int(data["done"])
        if "rank" in data:
            if not isinstance(data["rank"], (int, float)) or isinstance(data["rank"], bool):
                raise CalendarError(400, t("rank 는 수입니다."))
            v["rank"] = float(data["rank"])
        return v

    def owned_task(uid: str, tid: str) -> Task:
        x = store.task(uid, tid)
        if not x:
            raise CalendarError(404, t("그런 할 일이 없습니다."))
        return x

    @app.get(f"{PREFIX}/tasks")
    async def list_tasks(request: Request):
        uid = gate(request)
        return {"tasks": [x.json() for x in store.tasks_of(uid)]}

    @app.post(f"{PREFIX}/tasks")
    async def add_task(request: Request):
        uid = gate(request)
        data = await body_of(request)
        v = task_values(data, None)
        if len(store.tasks_of(uid)) >= MAX_TASKS:
            raise CalendarError(409, t("할 일은 {n}개까지입니다. 끝난 것을 먼저 치우세요.", n=MAX_TASKS))
        return JSONResponse(store.add_task(uid, v["text"], v.get("due", "")).json(), status_code=201)

    @app.post(f"{PREFIX}/tasks/clear-done")
    async def clear_done(request: Request):
        uid = gate(request)
        return {"removed": store.clear_done_tasks(uid)}

    @app.patch(f"{PREFIX}/tasks/{{tid}}")
    async def update_task(request: Request, tid: str):
        uid = gate(request)
        current = owned_task(uid, tid)
        v = task_values(await body_of(request), current)
        if not v:
            return current.json()
        return store.update_task(uid, tid, **v).json()

    @app.delete(f"{PREFIX}/tasks/{{tid}}")
    async def delete_task(request: Request, tid: str):
        uid = gate(request)
        owned_task(uid, tid)
        store.delete_task(uid, tid)
        return Response(status_code=204)

    # ── devices: a password per device for CalDAV (docs/calendar.md)
    @app.get(f"{PREFIX}/devices")
    async def list_devices(request: Request):
        uid = gate(request)
        return {"devices": store.devices_of(uid), "url": f"{request.url.scheme}://{request.headers.get('host', request.url.netloc)}{caldav.PREFIX}/",
                "username": uid}

    @app.post(f"{PREFIX}/devices")
    async def add_device(request: Request):
        uid = gate(request)
        data = await body_of(request)
        name = text_field(data, "name", 60, required=True)
        if len(store.devices_of(uid)) >= MAX_DEVICES:
            raise CalendarError(409, t("기기 비밀번호는 {n}개까지입니다. 안 쓰는 것을 먼저 거두세요.", n=MAX_DEVICES))
        d, password = store.add_device(uid, name)
        return JSONResponse({**d, "password": password, "username": uid,
                             "url": f"{request.url.scheme}://{request.headers.get('host', request.url.netloc)}{caldav.PREFIX}/"}, status_code=201)

    @app.delete(f"{PREFIX}/devices/{{did}}")
    async def delete_device(request: Request, did: str):
        uid = gate(request)
        if not store.delete_device(uid, did):
            raise CalendarError(404, t("그런 기기가 없습니다."))
        return Response(status_code=204)

    caldav.mount(app, store, visible, projects_of)

    @app.get("/calendar/healthz")
    async def healthz():
        return Response("ok", media_type="text/plain")

    return app
