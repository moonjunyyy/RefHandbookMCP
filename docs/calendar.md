# The calendar: one for each person and each of their projects (src/portal/calendar.py)

A calendar is a thing of a group (docs/projects.md): a person has their own, and every project of
theirs has one, and the site shows them together — one month grid, the person's events and their
projects' on it, each calendar a chip above the grid. Phones take it as an iCalendar subscription.
The service is `<name>-calendar` (its own user, its own state; `facts.ROLES` gives it port 8120),
behind the site sign-in, and the pages app draws it (`/calendar`, `web/src/pages/calendar.ts`) and
its widgets (`web/widgets/calendar.ts`: today — with the to-dos due by today under the events —, the
next seven days, and the to-do list itself: a line written with Enter, checked off in place, its due
day and the rest on its menu). The page shows time at its levels (`?v=year|week|day|list&d=…`; the
month has no `v`): the year (twelve months, each day at the level of its events), the month (a column
of weeks that scrolls on — the title and `?m=` follow the month in view; the weeks are read 52 at a
time, under the bound of one query), the week and the day (seven columns from Monday, or one, over an
all-day row and 24 hours, overlapping events side by side, a line at the present time), and the list
(the days ahead that have events, 30 at a time). The title goes up one level and a day goes down to its
day (the picked day's title in the month, a day's head in the week); `g` goes to a date; on the hours a sideways swipe or wheel moves one range. In the head, what is pressed (‹ ›, today, the views, the scale) comes before the title, so nothing pressed moves when the title's length changes. The grid takes the room down to the window's lower edge and is fitted again when the window changes: the month shows six weeks of it and the hours the whole day, with nothing to scroll; `−` and `+` (in the head, and as keys) show more or fewer weeks (8, 6, 5, 4) or hours (24, 16, 12, 8, 6), the choice is kept in the browser, and neither grid draws a scrollbar. An empty
slot pressed opens a small card there (the frame's `peek`): a title and Enter write an hour's event at
that time, and 자세히 takes the title and the slot to the dialog. An event pressed shows its card — what,
when, which calendar, its place and notes — with 편집 (the dialog), 지우기 and its menu. An
event is moved by dragging it onto another day or hour (`PATCH /events/<id>` with the new `start` and
`end`, the length kept) — a repeating one is not dragged, its series is changed in the dialog. Every
object has its menu where it is (right-click, ⋯, Shift+F10): an event — open, duplicate, move or copy
to another calendar, delete; a day — a new event (timed or all-day), the week or the month it is in; a
calendar's chip — hide, only this one, rename and recolour, its own subscription address, delete (the
name typed; the main one stays); the chips' ⋯ — a new calendar (the person's or a project's), show
all, the phone subscription. Sharing is by project: an event moved or copied onto a project's calendar
is seen by its members; a subscription address carries a calendar to a phone. The day panel also
lists the to-dos due that day, and a line written there is due that day.

## What a person sees

Their calendars, and the calendars of every project they are a member of — decided on every request
from the system's groups (`portal/membership.py`: NSS, the gid range of projects
`PORTAL_PROJECT_GID_MIN`–`MAX`), never from a copy. A calendar a person has never been shown is made
when they first look (`main = 1`: the one of an owner that cannot be deleted; a person's is named
in their language on that first sight, `내 캘린더` / `My calendar`). More calendars of theirs, or
of a project of theirs, are added with `POST /calendars`.

Nobody else's calendar is reachable, and a project's events are the project's: any member may
write, change and remove them. A project's `freebusy` shows its members' busy spans without their
titles (`GET /freebusy?group=<cn>&from&to`), which is what a meeting needs.

## Time

The service keeps **UTC instants** (`2026-11-02T09:00:00Z`) and **all-day events as dates**
(`2026-11-02`, the end exclusive: a one-day event ends the next day), and gives them back as they
are; the browser shows them in its own zone (`fromServer()` in the page), and the ICS feed says
them as `DTSTART:20261102T090000Z` or `DTSTART;VALUE=DATE:20261102`. There is no zone in the
record, so a person in Seoul and one in Berlin see the same instant, each in their time, and an
all-day event stays on its day for both.

Repeats are an RRULE subset expanded by the service (`occurrences()`), not by every client:
`FREQ=DAILY|WEEKLY|MONTHLY|YEARLY`, `INTERVAL`, `COUNT`, `UNTIL`, `BYDAY` for weekly rules;
`EXDATE` takes instances out, and they still count toward `COUNT`, as RFC 5545 says. A monthly rule
on the 31st skips the months without one. One query expands at most 1000 occurrences of one event
and spans at most 400 days (`MAX_OCCURRENCES`, `MAX_SPAN_DAYS`): bounds, not features.

## The API (`/calendar/api/v1`)

| | |
|---|---|
| `GET /calendars` | `{calendars: [...], projects: [cn, ...]}` — theirs and their projects', made on first sight |
| `POST /calendars` `{name, color[, group]}` | another of theirs, or of a project of theirs when `group` names it |
| `PATCH /calendars/<id>` `{name, color}` · `DELETE /calendars/<id>` | not the main one (`409`) |
| `GET /events?from=&to=[&cal=a,b]` | the occurrences in `[from, to)`, repeats expanded: each with `start`, `end`, `first` (the series' start) and `recurring` |
| `POST /events` `{cal, summary, start, end, allday, rrule, exdates, location, description}` | → 201 and the event |
| `GET` · `PATCH` · `DELETE /events/<id>` | the series; a change raises `seq` (`SEQUENCE` in the feed) |
| `GET /freebusy?group=<cn>&from&to` | `{group, busy: {uid: [[start, end], ...]}}` |
| `GET` · `POST /feeds` `{cals, name}` · `DELETE /feeds/<token>` | subscription addresses; `cals = []` is everything the person may see |
| `GET /calendar/feed/<token>.ics` | the feed itself — a public route: the token is the key, read-only, revoked by deleting it |
| `GET /tasks` | the person's to-do list: open ones first in their order (`rank`), then the done ones, latest first |
| `POST /tasks` `{text, due?}` | → 201; `due` a date or absent; at most 200 |
| `PATCH /tasks/<id>` `{text?, done?, due?, rank?}` · `DELETE /tasks/<id>` | a change; taking one out |
| `POST /tasks/clear-done` | takes out the done ones → `{removed}` |
| `GET` · `POST /devices` `{name}` · `DELETE /devices/<id>` | device passwords for CalDAV: `POST` answers the password once (`password`, `username`, `url`); the list never does |

A write must say `Content-Type: application/json` (as the apps' store: a cross-site form cannot).
Errors are `{error}` with the status (`400` a bad value, `404` not theirs, `415` not JSON).

## CalDAV (`/calendar/dav/`)

A phone's or a desktop's calendar app reads and writes the calendars over CalDAV (RFC 4791, the subset
`portal/caldav.py` implements): HTTP Basic with the username and a *device password* made on the
calendar page (칩 줄 ⋯ → 기기 연결), one per device, shown once and kept as a hash. Discovery:
`/.well-known/caldav` → `/calendar/dav/`; a plain `GET` of the root or of the home answers as a
collection (200, the calendars and where they are: the macOS account setup looks with `GET` before it asks
with `PROPFIND`, and stops at a 404); `PROPFIND /calendar/dav/` names the principal
`/calendar/dav/<uid>/`, which is also the calendar home (depth 1: the calendars the person may see —
their own and their projects'); a calendar `/calendar/dav/<uid>/<cid>/` carries `getctag` and a
`sync-token` (its `version`, grown by every change under it); an event is `<id>.ics` with `getetag`
`"<seq>"`, `GET` · `PUT` (`If-None-Match: *` makes, `If-Match` changes; a stale tag is 412) · `DELETE`.
`REPORT`: `calendar-query` (a time range, repeats expanded), `calendar-multiget`, `sync-collection`
(the changes since a token, deletions as 404 members from the tombstones). The resource name a client
chooses becomes the event's id and its `UID` is kept (`ical_uid`); what the model does not hold is
refused with a reason — a repeat outside the RRULE subset, a change to one instance of a repeat
(`RECURRENCE-ID`), a calendar made over DAV (`MKCALENDAR`: calendars are made on the page). Times with a
`TZID` become UTC, floating times are read as UTC, `VALUE=DATE` is an all-day event.

## The feed

A feed is a random token in the person's record (`feeds`), listing which calendars it covers; the
address `/calendar/feed/<token>.ics` is public in nginx (`[[app.route]] auth = "public"`), because a
phone's calendar app cannot sign in to the site. The response is one `VCALENDAR` with the covered
calendars' events as `VEVENT`s, repeats as the `RRULE`/`EXDATE` they were written as (a phone expands
them itself), lines folded at 75 octets. The page makes one on the first "폰에 구독" and shows it
with a copy; "거두기" deletes it, and the address stops working.

## Storage, units, settings

SQLite under the service's state directory, `PORTAL_CALENDAR_DB` (`/var/lib/<name>-calendar/calendar.db`):
`calendars` (id, owner, kind, name, color, main), `events` (id, cal, summary, description, location,
start, end, allday, rrule, exdates, status, created/updated and by whom, seq), `feeds` (token, uid,
cals, name). Deleting a calendar deletes its events (`ON DELETE CASCADE`).

`deploy/templates/calendar.service` (with the socket every listening role gets, `listen.socket`):
`uvicorn portal.calendar:create_app --factory --fd 3`, as every service (docs/site.md, "updates without downtime"); the unit has no keytab and no secret —
it checks the SSO's token for the audience `calendar` with the public key. The site file declares the
app (`[[app]] id = "calendar"`, `audience = "calendar"`, routes `/calendar/api/` with `signin = false`
and `/calendar/feed/` public, pages `/calendar`, widgets `today` 2x1 and `upcoming`), and
`tests/portal/test_calendar.py` covers the rules, the span, the feed and who sees what.

## Not here (on purpose)

Invitations and attendees (`ATTENDEE`, replies), CalDAV, a two-way sync with a phone, time zones
in the record (an instant is enough), alarms, and agents' schedules beside the events
(docs/projects.md names them for later). A project's calendar is its members' alone; there is no
public or read-only sharing beyond the feed.
