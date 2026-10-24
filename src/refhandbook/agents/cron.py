"""Cron expressions (the five standard fields), for scheduled runs. Standard library only.

    minute hour day-of-month month day-of-week
    *  a,b  a-b  */n  a-b/n      day-of-week 0–7 (0 and 7 are Sunday), names (mon, jan) accepted

As cron does: when both day-of-month and day-of-week are restricted, a day matching either fires.
Times are the server's local time.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

FIELDS = (("minute", 0, 59), ("hour", 0, 23), ("day", 1, 31), ("month", 1, 12), ("weekday", 0, 7))
NAMES = {"month": ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"],
         "weekday": ["sun", "mon", "tue", "wed", "thu", "fri", "sat"]}
SHORTHANDS = {"@hourly": "0 * * * *", "@daily": "0 0 * * *", "@weekly": "0 0 * * 0", "@monthly": "0 0 1 * *"}


class CronError(ValueError):
    pass


def _value(text: str, name: str, lo: int) -> int:
    t = text.lower()
    if name in NAMES and t in NAMES[name]:
        return NAMES[name].index(t) + (1 if name == "month" else 0)
    if not t.isdigit():
        raise CronError(f"{name}: {text!r} is not a number")
    return int(t)


def _field(text: str, name: str, lo: int, hi: int) -> frozenset[int]:
    out: set[int] = set()
    for part in text.split(","):
        rng, _, step = part.partition("/")
        n = 1
        if step:
            if not step.isdigit() or int(step) < 1:
                raise CronError(f"{name}: step {step!r}")
            n = int(step)
        if rng == "*":
            a, b = lo, hi
        elif "-" in rng:
            x, _, y = rng.partition("-")
            a, b = _value(x, name, lo), _value(y, name, lo)
        else:
            a = _value(rng, name, lo)
            b = hi if step else a
        if not (lo <= a <= hi and lo <= b <= hi) or a > b:
            raise CronError(f"{name}: {part!r} is outside {lo}–{hi}")
        out.update(range(a, b + 1, n))
    if name == "weekday" and 7 in out:
        out = (out - {7}) | {0}
    return frozenset(out)


@dataclass(frozen=True)
class Cron:
    text: str
    minute: frozenset[int]
    hour: frozenset[int]
    day: frozenset[int]
    month: frozenset[int]
    weekday: frozenset[int]
    day_any: bool
    weekday_any: bool

    def _day_ok(self, d: dt.date) -> bool:
        if d.month not in self.month:
            return False
        dom, dow = d.day in self.day, (d.isoweekday() % 7) in self.weekday
        if self.day_any or self.weekday_any:
            return dom and dow
        return dom or dow

    def next_after(self, t: dt.datetime) -> dt.datetime:
        """The first time strictly after `t` (to the minute) the expression fires."""
        t = t.replace(second=0, microsecond=0) + dt.timedelta(minutes=1)
        for _ in range(366 * 5):  # every day of five years: enough for any valid expression (Feb 29)
            if self._day_ok(t.date()):
                for h in sorted(x for x in self.hour if x >= t.hour):
                    for m in sorted(x for x in self.minute if h > t.hour or x >= t.minute):
                        return t.replace(hour=h, minute=m)
            t = (t + dt.timedelta(days=1)).replace(hour=0, minute=0)
        raise CronError(f"{self.text!r} never fires")


def parse(text: str) -> Cron:
    expr = SHORTHANDS.get(text.strip().lower(), text.strip())
    parts = expr.split()
    if len(parts) != 5:
        raise CronError("five fields: minute hour day-of-month month day-of-week (e.g. 0 9 * * mon-fri)")
    sets = [_field(p, name, lo, hi) for p, (name, lo, hi) in zip(parts, FIELDS)]
    c = Cron(text.strip(), *sets, day_any=parts[2] == "*", weekday_any=parts[4] == "*")
    c.next_after(dt.datetime(2000, 1, 1))  # one that never fires (31 2 *) is refused now
    return c
