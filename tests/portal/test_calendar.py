"""The calendars (portal/calendar.py): one per person and per project, events with repeats, the feed."""
import pytest
from .conftest import SITE
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

from portal import tokens
import base64

from portal import caldav
from portal.calendar import CalendarError, Rule, Store, create_app, expand, occurrences, parse_rule, parse_when
from portal.config import Settings

ISS = "https://www.m00nny.kr"
JSON = {"Content-Type": "application/json"}
PROJECTS = {"alice": {"lab"}, "bob": {"lab"}, "carol": set()}
MEMBERS = {"lab": ["alice", "bob"]}


@pytest.fixture
def key():
    return Ed25519PrivateKey.generate()


@pytest.fixture
def client(tmp_path, key):
    s = Settings(session_secret="x" * 40, audit_log=str(tmp_path / "a.log"), sso_issuer=ISS, site_file=str(SITE))
    return TestClient(create_app(s, Store(":memory:"), key.public_key(),
                                 projects_of=lambda uid: PROJECTS.get(uid, set()), members_of=lambda g: MEMBERS.get(g, [])))


def as_user(key, uid="alice", aud="calendar"):
    return {"X-Auth-Token": tokens.issue(key, ISS, aud, uid)}


def post(client, h, path, body, method="post"):
    return getattr(client, method)(f"/calendar/api/v1/{path}", headers={**h, **JSON}, json=body)


# ── repeats, on their own ──────────────────────────────────────────────────


def test_the_rrule_subset_parses_and_prints():
    r = parse_rule("FREQ=WEEKLY;INTERVAL=2;BYDAY=WE,MO;COUNT=5")
    assert r == Rule("WEEKLY", 2, 5, None, (0, 2)) and r.text() == "FREQ=WEEKLY;INTERVAL=2;BYDAY=MO,WE;COUNT=5"
    assert parse_rule("freq=daily;until=20261231T000000Z").text() == "FREQ=DAILY;UNTIL=20261231T000000Z"
    assert parse_rule("") is None
    for bad in ("FREQ=HOURLY", "FREQ=DAILY;BYDAY=MO", "FREQ=DAILY;COUNT=2;UNTIL=20261231", "FREQ=DAILY;BYMONTH=1",
                "FREQ=DAILY;INTERVAL=0", "DAILY"):
        with pytest.raises(CalendarError):
            parse_rule(bad)


def test_occurrences_follow_the_standard():
    s = parse_when("2026-11-02T09:00:00Z", False)  # a Monday
    take = lambda rule, n=10: [x.strftime("%m-%d") for _, x in zip(range(n), occurrences(s, parse_rule(rule)))]  # noqa: E731
    assert take("FREQ=DAILY;COUNT=3") == ["11-02", "11-03", "11-04"]
    assert take("FREQ=DAILY;INTERVAL=7;UNTIL=20261117T090000Z") == ["11-02", "11-09", "11-16"]
    assert take("FREQ=WEEKLY;BYDAY=MO,WE;COUNT=4") == ["11-02", "11-04", "11-09", "11-11"]
    assert take("FREQ=WEEKLY;INTERVAL=2;BYDAY=FR;COUNT=2") == ["11-06", "11-20"]  # the week of the start, then every other
    assert take("FREQ=MONTHLY;COUNT=3") == ["11-02", "12-02", "01-02"]
    jan31 = parse_when("2026-01-31", True)
    assert [x.strftime("%m-%d") for _, x in zip(range(3), occurrences(jan31, parse_rule("FREQ=MONTHLY")))] == ["01-31", "03-31", "05-31"]  # no 31st: skipped
    assert take("FREQ=YEARLY;COUNT=2") == ["11-02", "11-02"]
    assert take("") == ["11-02"]


def test_expansion_keeps_to_the_span_and_the_exdates():
    from portal.calendar import Event

    e = Event("e1", "c", "standup", "", "", "2026-11-02T09:00:00Z", "2026-11-02T09:30:00Z", False,
              "FREQ=DAILY;COUNT=5", ("2026-11-04T09:00:00Z",), "CONFIRMED", 0, "a", 0, "a", 0)
    got = expand(e, parse_when("2026-11-03", True), parse_when("2026-11-06", True))
    assert [o["start"] for o in got] == ["2026-11-03T09:00:00Z", "2026-11-05T09:00:00Z"]  # the 4th is taken out; the 6th is outside
    assert all(o["recurring"] and o["first"] == "2026-11-02T09:00:00Z" and o["end"].endswith("09:30:00Z") for o in got)
    allday = Event("e2", "c", "trip", "", "", "2026-11-05", "2026-11-08", True, "", (), "CONFIRMED", 0, "a", 0, "a", 0)
    assert [o["start"] for o in expand(allday, parse_when("2026-11-07", True), parse_when("2026-11-30", True))] == ["2026-11-05"]
    assert expand(allday, parse_when("2026-11-08", True), parse_when("2026-11-30", True)) == []  # the end is exclusive


# ── the service ────────────────────────────────────────────────────────────


def test_a_person_sees_their_own_and_their_projects_calendars(client, key):
    alice, bob, carol = as_user(key), as_user(key, "bob"), as_user(key, "carol")
    assert client.get("/calendar/api/v1/calendars").status_code == 401
    assert client.get("/calendar/api/v1/calendars", headers=as_user(key, aud="vault")).status_code == 401
    cals = client.get("/calendar/api/v1/calendars", headers=alice).json()
    assert [(c["kind"], c["owner"], c["main"]) for c in cals["calendars"]] == [("user", "alice", True), ("group", "lab", True)]
    assert cals["projects"] == ["lab"]
    lab = next(c for c in cals["calendars"] if c["kind"] == "group")
    assert lab["name"] == "lab"
    # bob, in the lab too, sees the same lab calendar; carol, in no project, does not
    assert lab["id"] in [c["id"] for c in client.get("/calendar/api/v1/calendars", headers=bob).json()["calendars"]]
    assert [c["kind"] for c in client.get("/calendar/api/v1/calendars", headers=carol).json()["calendars"]] == ["user"]
    assert client.patch(f"/calendar/api/v1/calendars/{lab['id']}", headers={**carol, **JSON}, json={"name": "x"}).status_code == 404
    # more calendars: one of alice's, one of the lab's; the main ones stay
    r = post(client, alice, "calendars", {"name": "운동", "color": "#33aa55"})
    assert r.status_code == 201 and r.json()["kind"] == "user" and not r.json()["main"]
    assert post(client, alice, "calendars", {"name": "회의", "group": "lab"}).json()["owner"] == "lab"
    assert post(client, carol, "calendars", {"name": "회의", "group": "lab"}).status_code == 404
    assert post(client, alice, "calendars", {"name": "x", "color": "red"}).status_code == 400
    assert client.delete(f"/calendar/api/v1/calendars/{lab['id']}", headers=alice).status_code == 409  # a main one
    assert client.delete(f"/calendar/api/v1/calendars/{r.json()['id']}", headers=alice).status_code == 204


def test_events_are_kept_queried_and_expanded(client, key):
    alice, bob, carol = as_user(key), as_user(key, "bob"), as_user(key, "carol")
    cals = client.get("/calendar/api/v1/calendars", headers=alice).json()["calendars"]
    mine, lab = cals[0]["id"], cals[1]["id"]
    r = post(client, alice, "events", {"cal": mine, "summary": "치과", "start": "2026-11-03T05:00:00Z", "end": "2026-11-03T06:00:00Z"})
    assert r.status_code == 201
    dentist = r.json()
    assert dentist["created_by"] == "alice" and dentist["seq"] == 0
    standup = post(client, bob, "events", {"cal": lab, "summary": "standup", "start": "2026-11-02T00:30:00Z",
                                           "end": "2026-11-02T00:45:00Z", "rrule": "FREQ=WEEKLY;BYDAY=MO,WE,FR"}).json()
    trip = post(client, alice, "events", {"cal": mine, "summary": "출장", "start": "2026-11-05", "end": "2026-11-05", "allday": True}).json()
    assert trip["end"] == "2026-11-06"  # a day long
    got = client.get("/calendar/api/v1/events?from=2026-11-02&to=2026-11-09", headers=alice).json()["events"]
    assert [(o["summary"], o["start"]) for o in got] == [
        ("standup", "2026-11-02T00:30:00Z"), ("치과", "2026-11-03T05:00:00Z"), ("standup", "2026-11-04T00:30:00Z"),
        ("출장", "2026-11-05"), ("standup", "2026-11-06T00:30:00Z")]
    only_lab = client.get(f"/calendar/api/v1/events?from=2026-11-02&to=2026-11-09&cal={lab}", headers=alice).json()["events"]
    assert {o["summary"] for o in only_lab} == {"standup"}
    # bob sees the lab's but not alice's own; carol sees neither
    assert {o["summary"] for o in client.get("/calendar/api/v1/events?from=2026-11-02&to=2026-11-09", headers=bob).json()["events"]} == {"standup"}
    assert client.get("/calendar/api/v1/events?from=2026-11-02&to=2026-11-09", headers=carol).json()["events"] == []
    assert client.get(f"/calendar/api/v1/events/{dentist['id']}", headers=bob).status_code == 404
    # a change bumps the sequence; one instance of the repeat is taken out
    r = client.patch(f"/calendar/api/v1/events/{standup['id']}", headers={**alice, **JSON}, json={"exdates": ["2026-11-04T00:30:00Z"]})
    assert r.status_code == 200 and r.json()["seq"] == 1 and r.json()["updated_by"] == "alice"
    got = client.get("/calendar/api/v1/events?from=2026-11-02&to=2026-11-09", headers=alice).json()["events"]
    assert [o["start"] for o in got if o["summary"] == "standup"] == ["2026-11-02T00:30:00Z", "2026-11-06T00:30:00Z"]
    # what is refused
    assert post(client, alice, "events", {"cal": mine, "summary": "", "start": "2026-11-03T05:00:00Z"}).status_code == 400
    assert post(client, alice, "events", {"cal": mine, "summary": "x", "start": "2026-11-03T05:00", "end": "2026-11-03T06:00"}).status_code == 400
    assert post(client, alice, "events", {"cal": mine, "summary": "x", "start": "2026-11-03T06:00:00Z", "end": "2026-11-03T05:00:00Z"}).status_code == 400
    assert post(client, alice, "events", {"cal": mine, "summary": "x", "start": "2026-11-03T05:00:00Z", "rrule": "FREQ=HOURLY"}).status_code == 400
    assert post(client, carol, "events", {"cal": lab, "summary": "x", "start": "2026-11-03T05:00:00Z"}).status_code == 404
    assert client.post("/calendar/api/v1/events", headers={**alice, "Content-Type": "text/plain"}, content="{}").status_code == 415
    assert client.get("/calendar/api/v1/events?from=2026-11-02&to=2028-11-02", headers=alice).status_code == 400  # too long a span
    assert client.delete(f"/calendar/api/v1/events/{dentist['id']}", headers=alice).status_code == 204
    assert client.get(f"/calendar/api/v1/events/{dentist['id']}", headers=alice).status_code == 404


def test_free_busy_shows_the_members_spans_without_titles(client, key):
    alice, bob, carol = as_user(key), as_user(key, "bob"), as_user(key, "carol")
    mine = client.get("/calendar/api/v1/calendars", headers=alice).json()["calendars"][0]["id"]
    post(client, alice, "events", {"cal": mine, "summary": "비밀", "start": "2026-11-03T05:00:00Z", "end": "2026-11-03T06:00:00Z"})
    client.get("/calendar/api/v1/calendars", headers=bob)  # bob's own calendar exists once seen
    r = client.get("/calendar/api/v1/freebusy?group=lab&from=2026-11-02&to=2026-11-09", headers=bob).json()
    assert r == {"group": "lab", "busy": {"alice": [["2026-11-03T05:00:00Z", "2026-11-03T06:00:00Z"]], "bob": []}}
    assert "비밀" not in str(r)
    assert client.get("/calendar/api/v1/freebusy?group=lab&from=2026-11-02&to=2026-11-09", headers=carol).status_code == 404


def test_a_feed_is_a_public_ics_of_what_its_owner_may_see(client, key):
    alice, carol = as_user(key), as_user(key, "carol")
    cals = client.get("/calendar/api/v1/calendars", headers=alice).json()["calendars"]
    mine, lab = cals[0]["id"], cals[1]["id"]
    post(client, alice, "events", {"cal": mine, "summary": "치과; 10:00, 2층", "start": "2026-11-03T05:00:00Z", "end": "2026-11-03T06:00:00Z",
                                   "description": "줄\n둘"})
    post(client, alice, "events", {"cal": lab, "summary": "standup", "start": "2026-11-02T00:30:00Z", "end": "2026-11-02T00:45:00Z",
                                   "rrule": "FREQ=WEEKLY;BYDAY=MO", "exdates": ["2026-11-09T00:30:00Z"]})
    post(client, alice, "events", {"cal": mine, "summary": "출장", "start": "2026-11-05", "allday": True})
    r = post(client, alice, "feeds", {"name": "폰"})
    assert r.status_code == 201
    token, url = r.json()["token"], r.json()["url"]
    assert url.endswith(f"/calendar/feed/{token}.ics") and url.startswith("http")
    assert [f["token"] for f in client.get("/calendar/api/v1/feeds", headers=alice).json()["feeds"]] == [token]
    assert client.get("/calendar/api/v1/feeds", headers=carol).json()["feeds"] == []
    ics = client.get(f"/calendar/feed/{token}.ics")  # no token header: the address is the key
    assert ics.status_code == 200 and ics.headers["content-type"].startswith("text/calendar")
    text = ics.text
    assert text.startswith("BEGIN:VCALENDAR\r\n") and text.endswith("END:VCALENDAR\r\n") and text.count("BEGIN:VEVENT") == 3
    assert "SUMMARY:치과\\; 10:00\\, 2층" in text and "DESCRIPTION:줄\\n둘" in text
    assert "DTSTART:20261103T050000Z" in text and "DTEND:20261103T060000Z" in text
    assert "DTSTART;VALUE=DATE:20261105" in text and "DTEND;VALUE=DATE:20261106" in text
    assert "RRULE:FREQ=WEEKLY;BYDAY=MO" in text and "EXDATE:20261109T003000Z" in text and "X-WR-CALNAME:폰" in text
    assert all(len(line.encode()) <= 75 for line in text.split("\r\n"))
    # one calendar only
    r = post(client, alice, "feeds", {"cals": [lab]})
    only = client.get(f"/calendar/feed/{r.json()['token']}.ics").text
    assert only.count("BEGIN:VEVENT") == 1 and "standup" in only and "X-WR-CALNAME:lab" in only
    assert post(client, carol, "feeds", {"cals": [lab]}).status_code == 404  # not hers to subscribe to
    assert client.delete(f"/calendar/api/v1/feeds/{token}", headers=carol).status_code == 404
    assert client.delete(f"/calendar/api/v1/feeds/{token}", headers=alice).status_code == 204
    assert client.get(f"/calendar/feed/{token}.ics").status_code == 404
    assert client.get("/calendar/feed/nope.ics").status_code == 404


# ── the to-do list (docs/apps-vault-calendar.md §7.3) ─────────────────────


def test_the_to_do_list_is_the_persons_own_in_their_order(client, key):
    h = as_user(key)
    assert client.get("/calendar/api/v1/tasks", headers=h).json() == {"tasks": []}
    a = post(client, h, "tasks", {"text": "  논문 초록 고치기 "})
    assert a.status_code == 201 and a.json()["text"] == "논문 초록 고치기" and a.json()["done"] is False and a.json()["due"] == ""
    b = post(client, h, "tasks", {"text": "세미나 신청", "due": "2026-11-05"}).json()
    assert b["due"] == "2026-11-05" and b["rank"] > a.json()["rank"]
    # a new one goes last; the list is open ones first in rank order
    assert [x["text"] for x in client.get("/calendar/api/v1/tasks", headers=h).json()["tasks"]] == ["논문 초록 고치기", "세미나 신청"]
    # moving: a rank between
    assert post(client, h, f"tasks/{b['id']}", {"rank": 0.5}, "patch").json()["rank"] == 0.5
    assert [x["text"] for x in client.get("/calendar/api/v1/tasks", headers=h).json()["tasks"]] == ["세미나 신청", "논문 초록 고치기"]
    # done ones go below the open ones; clearing takes them out
    done = post(client, h, f"tasks/{b['id']}", {"done": True}, "patch").json()
    assert done["done"] is True
    assert [x["text"] for x in client.get("/calendar/api/v1/tasks", headers=h).json()["tasks"]] == ["논문 초록 고치기", "세미나 신청"]
    assert post(client, h, f"tasks/{a.json()['id']}", {"text": "초록 고치기", "due": ""}, "patch").json()["text"] == "초록 고치기"
    assert post(client, h, "tasks/clear-done", {}).json() == {"removed": 1}
    assert [x["text"] for x in client.get("/calendar/api/v1/tasks", headers=h).json()["tasks"]] == ["초록 고치기"]
    # another person sees none of it, and cannot touch it
    other = as_user(key, "bob")
    assert client.get("/calendar/api/v1/tasks", headers=other).json() == {"tasks": []}
    assert post(client, other, f"tasks/{a.json()['id']}", {"done": True}, "patch").status_code == 404
    assert client.delete(f"/calendar/api/v1/tasks/{a.json()['id']}", headers=other).status_code == 404
    assert client.delete(f"/calendar/api/v1/tasks/{a.json()['id']}", headers=h).status_code == 204
    assert client.get("/calendar/api/v1/tasks", headers=h).json() == {"tasks": []}
    # what is refused, in the person's language
    assert post(client, h, "tasks", {"text": ""}).status_code == 400
    assert post(client, h, "tasks", {"text": "x" * 201}).status_code == 400
    r = post(client, h, "tasks", {"text": "x", "due": "tomorrow"})
    assert r.status_code == 400 and "날짜" in r.json()["error"]
    assert post(client, h, "tasks", {"text": "x", "due": "2026-11-05"}).status_code == 201
    assert client.get("/calendar/api/v1/tasks").status_code == 401


# ── CalDAV (portal/caldav.py; docs/apps-vault-calendar.md §8.3) ───────────


VEVENT = """BEGIN:VCALENDAR\r
VERSION:2.0\r
PRODID:-//test//EN\r
BEGIN:VTIMEZONE\r
TZID:Asia/Seoul\r
END:VTIMEZONE\r
BEGIN:VEVENT\r
UID:abc-123@phone\r
DTSTAMP:20261103T000000Z\r
DTSTART;TZID=Asia/Seoul:20261105T090000\r
DTEND;TZID=Asia/Seoul:20261105T103000\r
SUMMARY:Lab meeting\\, weekly\r
DESCRIPTION:line one\\nline two\r
LOCATION:Room 3\r
RRULE:FREQ=WEEKLY;BYDAY=TH;COUNT=4\r
EXDATE;TZID=Asia/Seoul:20261112T090000\r
BEGIN:VALARM\r
TRIGGER:-PT10M\r
END:VALARM\r
END:VEVENT\r
END:VCALENDAR\r
"""


def basic(uid, password):
    return {"Authorization": "Basic " + base64.b64encode(f"{uid}:{password}".encode()).decode()}


def dav(client, method, path, h, body="", **headers):
    return client.request(method, path, headers={**h, "Content-Type": "application/xml", **headers}, content=body)


def test_the_icalendar_reader_takes_what_the_model_holds():
    v = caldav.read_vevent(VEVENT)
    assert v["uid"] == "abc-123@phone" and v["summary"] == "Lab meeting, weekly" and v["description"] == "line one\nline two"
    assert v["start"] == "2026-11-05T00:00:00Z" and v["end"] == "2026-11-05T01:30:00Z" and v["allday"] is False  # Seoul → UTC
    assert v["rrule"] == "FREQ=WEEKLY;BYDAY=TH;COUNT=4" and v["exdates"] == ["2026-11-12T00:00:00Z"] and v["location"] == "Room 3"
    allday = caldav.read_vevent("BEGIN:VCALENDAR\nBEGIN:VEVENT\nUID:d\nDTSTART;VALUE=DATE:20261201\nSUMMARY:Day\nEND:VEVENT\nEND:VCALENDAR\n")
    assert allday["allday"] and allday["start"] == "2026-12-01" and allday["end"] == "2026-12-02"  # the end defaults to the next day
    dur = caldav.read_vevent("BEGIN:VEVENT\nUID:e\nDTSTART:20261201T100000Z\nDURATION:PT2H\nSUMMARY:x\nEND:VEVENT\n")
    assert dur["end"] == "2026-12-01T12:00:00Z"
    with pytest.raises(caldav.DavError, match="RECURRENCE-ID"):
        caldav.read_vevent(VEVENT.replace("END:VCALENDAR", "BEGIN:VEVENT\r\nUID:abc-123@phone\r\nRECURRENCE-ID:20261119T000000Z\r\nDTSTART:20261119T010000Z\r\nEND:VEVENT\r\nEND:VCALENDAR"))
    with pytest.raises(caldav.DavError, match="DTSTART"):
        caldav.read_vevent("BEGIN:VEVENT\nUID:f\nSUMMARY:x\nEND:VEVENT\n")
    with pytest.raises(caldav.DavError, match="시간대"):
        caldav.read_vevent("BEGIN:VEVENT\nUID:g\nDTSTART;TZID=Mars/Olympus:20261201T100000\nEND:VEVENT\n")


def test_devices_and_the_caldav_round_trip(client, key):
    h = as_user(key)
    # a device password: shown once, never listed, revocable; the DAV address and the username come with it
    assert client.get("/calendar/api/v1/devices", headers=h).json()["devices"] == []
    made = post(client, h, "devices", {"name": "폰"})
    assert made.status_code == 201 and made.json()["name"] == "폰" and len(made.json()["password"]) >= 20
    assert made.json()["url"].endswith("/calendar/dav/") and made.json()["username"] == "alice"
    password = made.json()["password"]
    listed = client.get("/calendar/api/v1/devices", headers=h).json()["devices"]
    assert [d["name"] for d in listed] == ["폰"] and "password" not in listed[0] and "secret" not in listed[0]
    # Basic: none → 401 with the challenge; a wrong one → 401; the right one → the principal
    r = client.request("PROPFIND", "/calendar/dav/")
    assert r.status_code == 401 and r.headers["www-authenticate"].startswith("Basic")
    assert client.request("PROPFIND", "/calendar/dav/", headers=basic("alice", "nope")).status_code == 401
    assert client.request("PROPFIND", "/calendar/dav/", headers=basic("bob", password)).status_code == 401  # not bob's
    b = basic("alice", password)
    r = client.request("OPTIONS", "/calendar/dav/", headers=b)
    assert "calendar-access" in r.headers["dav"] and "REPORT" in r.headers["allow"]
    r = dav(client, "PROPFIND", "/calendar/dav/", b, '<D:propfind xmlns:D="DAV:"><D:prop><D:current-user-principal/></D:prop></D:propfind>', Depth="0")
    assert r.status_code == 207 and "<D:href>/calendar/dav/alice/</D:href>" in r.text
    r = dav(client, "PROPFIND", "/calendar/dav/alice/", b, '<D:propfind xmlns:D="DAV:" xmlns:C="urn:ietf:params:xml:ns:caldav"><D:prop><C:calendar-home-set/><D:nope/></D:prop></D:propfind>', Depth="0")
    assert "<C:calendar-home-set><D:href>/calendar/dav/alice/</D:href></C:calendar-home-set>" in r.text and "<D:nope/>" in r.text and "404 Not Found" in r.text
    # the home, depth 1: alice's own calendar and the lab's
    r = dav(client, "PROPFIND", "/calendar/dav/alice/", b, "", Depth="1")
    cals = client.get("/calendar/api/v1/calendars", headers=h).json()["calendars"]
    mine = next(c for c in cals if c["kind"] == "user")["id"]
    lab = next(c for c in cals if c["kind"] == "group")["id"]
    assert f"/calendar/dav/alice/{mine}/" in r.text and f"/calendar/dav/alice/{lab}/" in r.text
    assert "<C:calendar/>" in r.text and "<CS:getctag>0</CS:getctag>" in r.text and 'name="VEVENT"' in r.text
    # a plain GET of the root or of the home answers as a collection (the macOS account setup looks with GET first, and
    # stops at a 404); someone else's home and a path that is no calendar stay 404, and the challenge stays
    for p in ("/calendar/dav/", "/calendar/dav/alice/", "/calendar/dav/alice"):
        r = client.get(p, headers=b)
        assert r.status_code == 200 and r.headers["content-type"].startswith("text/plain"), (p, r.status_code)
        assert f"/calendar/dav/alice/{mine}/" in r.text and f"/calendar/dav/alice/{lab}/" in r.text
    assert client.head("/calendar/dav/", headers=b).status_code == 200
    assert client.get("/calendar/dav/").status_code == 401
    assert client.get("/calendar/dav/bob/", headers=b).status_code == 404
    assert client.get("/calendar/dav/alice/calendars", headers=b).status_code == 404
    # PUT a new event from a phone: the resource name becomes the id, the UID is kept, Seoul becomes UTC
    r = client.request("PUT", f"/calendar/dav/alice/{mine}/abc-123.ics", headers={**b, "Content-Type": "text/calendar", "If-None-Match": "*"}, content=VEVENT)
    assert r.status_code == 201 and r.headers["etag"] == '"0"'
    e = client.get("/calendar/api/v1/events/abc-123", headers=h).json()
    assert e["summary"] == "Lab meeting, weekly" and e["start"] == "2026-11-05T00:00:00Z" and e["rrule"] == "FREQ=WEEKLY;BYDAY=TH;COUNT=4"
    assert client.request("PUT", f"/calendar/dav/alice/{mine}/abc-123.ics", headers={**b, "If-None-Match": "*"}, content=VEVENT).status_code == 412  # it exists now
    r = client.request("GET", f"/calendar/dav/alice/{mine}/abc-123.ics", headers=b)
    assert r.status_code == 200 and "UID:abc-123@phone" in r.text and "SUMMARY:Lab meeting\\, weekly" in r.text and r.headers["etag"] == '"0"'
    # the calendar changed: ctag 1; depth 1 lists the event with its etag
    r = dav(client, "PROPFIND", f"/calendar/dav/alice/{mine}/", b, "", Depth="1")
    assert "<CS:getctag>1</CS:getctag>" in r.text and f"/calendar/dav/alice/{mine}/abc-123.ics" in r.text and '<D:getetag>"0"</D:getetag>' in r.text
    # PUT a change with the right etag → 204 and a new etag; a stale etag → 412
    changed = VEVENT.replace("SUMMARY:Lab meeting\\, weekly", "SUMMARY:Lab meeting (moved)")
    r = client.request("PUT", f"/calendar/dav/alice/{mine}/abc-123.ics", headers={**b, "If-Match": '"0"'}, content=changed)
    assert r.status_code == 204 and r.headers["etag"] == '"1"'
    assert client.request("PUT", f"/calendar/dav/alice/{mine}/abc-123.ics", headers={**b, "If-Match": '"0"'}, content=changed).status_code == 412
    # an event made on the page shows up for the phone too, with its own UID
    web = post(client, h, "events", {"cal": mine, "summary": "From the page", "start": "2026-11-20T09:00:00Z", "end": "2026-11-20T10:00:00Z"}).json()
    r = client.request("GET", f"/calendar/dav/alice/{mine}/{web['id']}.ics", headers=b)
    assert f"UID:{web['id']}@testserver" in r.text
    # REPORT calendar-query with a time range: only what overlaps; multiget: only what was asked, with the data
    q = ('<C:calendar-query xmlns:D="DAV:" xmlns:C="urn:ietf:params:xml:ns:caldav"><D:prop><D:getetag/><C:calendar-data/></D:prop>'
         '<C:filter><C:comp-filter name="VCALENDAR"><C:comp-filter name="VEVENT"><C:time-range start="20261120T000000Z" end="20261121T000000Z"/></C:comp-filter></C:comp-filter></C:filter></C:calendar-query>')
    r = dav(client, "REPORT", f"/calendar/dav/alice/{mine}/", b, q, Depth="1")
    assert r.status_code == 207 and f"{web['id']}.ics" in r.text and "abc-123.ics" not in r.text and "BEGIN:VEVENT" in r.text
    m = ('<C:calendar-multiget xmlns:D="DAV:" xmlns:C="urn:ietf:params:xml:ns:caldav"><D:prop><D:getetag/><C:calendar-data/></D:prop>'
         f'<D:href>/calendar/dav/alice/{mine}/abc-123.ics</D:href><D:href>/calendar/dav/alice/{mine}/nope.ics</D:href></C:calendar-multiget>')
    r = dav(client, "REPORT", f"/calendar/dav/alice/{mine}/", b, m)
    assert "abc-123.ics" in r.text and "SUMMARY:Lab meeting (moved)" in r.text and "nope.ics" in r.text and "404 Not Found" in r.text and f"{web['id']}.ics" not in r.text
    # sync-collection: everything from an empty token; then only what changed; a deletion as a 404 member
    sc = '<D:sync-collection xmlns:D="DAV:"><D:sync-token>{}</D:sync-token><D:sync-level>1</D:sync-level><D:prop><D:getetag/></D:prop></D:sync-collection>'
    r = dav(client, "REPORT", f"/calendar/dav/alice/{mine}/", b, sc.format(""))
    assert "abc-123.ics" in r.text and f"{web['id']}.ics" in r.text
    token = r.text.split("<D:sync-token>")[-1].split("</D:sync-token>")[0]
    assert token.endswith("/sync/3")
    assert client.request("DELETE", f"/calendar/dav/alice/{mine}/{web['id']}.ics", headers=b).status_code == 204
    r = dav(client, "REPORT", f"/calendar/dav/alice/{mine}/", b, sc.format(token))
    assert f"{web['id']}.ics" in r.text and "404 Not Found" in r.text and "abc-123.ics" not in r.text
    assert client.get(f"/calendar/api/v1/events/{web['id']}", headers=h).status_code == 404
    # what is refused: a calendar made over DAV, a repeat the subset lacks, someone else's path, a bad name
    assert client.request("MKCALENDAR", "/calendar/dav/alice/new/", headers=b).status_code == 403
    r = client.request("PUT", f"/calendar/dav/alice/{mine}/hourly.ics", headers=b, content=VEVENT.replace("FREQ=WEEKLY;BYDAY=TH;COUNT=4", "FREQ=HOURLY"))
    assert r.status_code == 403 and "반복" in r.text
    assert client.request("PROPFIND", f"/calendar/dav/bob/{mine}/", headers=b).status_code == 404
    assert client.request("PUT", f"/calendar/dav/alice/{mine}/bad name.ics", headers=b, content=VEVENT).status_code == 403
    # the device revoked: the phone is out
    did = listed[0]["id"]
    assert client.delete(f"/calendar/api/v1/devices/{did}", headers=h).status_code == 204
    assert client.request("PROPFIND", "/calendar/dav/", headers=b).status_code == 401
