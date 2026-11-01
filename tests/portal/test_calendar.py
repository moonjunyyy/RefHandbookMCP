"""The calendars (portal/calendar.py): one per person and per project, events with repeats, the feed."""
import pytest
from .conftest import SITE
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

from portal import tokens
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
