"""Parser for the common subset of the OSM ``opening_hours`` syntax.

Supported: ``24/7``; weekday lists and ranges (``Mo-Fr``, ``Sa,Su``); several time
spans per rule (``10:00-13:00,14:00-18:00``); spans over midnight; ``off`` /
``closed``; rules separated by ``;`` where later rules override earlier ones for
the days they mention. Unsupported constructs (month ranges, sunrise/sunset,
week numbers, comments) make the whole value *unknown* (``None``) rather than
silently wrong; public-holiday rules (``PH``) are ignored.
"""

from __future__ import annotations

import re
from datetime import datetime

Interval = tuple[int, int]  # minutes from midnight, end may exceed 1440 for spans over midnight
Week = dict[int, list[Interval]]  # weekday 0 (Monday) .. 6 -> opening intervals

_DAYS = {"mo": 0, "tu": 1, "we": 2, "th": 3, "fr": 4, "sa": 5, "su": 6}
_SPAN = re.compile(r"^(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})$")
_DAY = r"(?:Mo|Tu|We|Th|Fr|Sa|Su|PH|SH)"
_DAY_SPEC = re.compile(rf"^((?:{_DAY}(?:\s*-\s*{_DAY})?\s*,?\s*)+)(.*)$", re.IGNORECASE)
_OPEN_END = re.compile(r"^(\d{1,2}):(\d{2})\+$")


def _parse_days(text: str) -> list[int] | None:
    days: list[int] = []
    for part in text.split(","):
        part = part.strip().lower()
        if part in ("ph", "sh"):
            continue
        if "-" in part:
            a, _, b = part.partition("-")
            if a.strip() not in _DAYS or b.strip() not in _DAYS:
                return None
            i, j = _DAYS[a.strip()], _DAYS[b.strip()]
            days.extend(range(i, j + 1) if i <= j else [*range(i, 7), *range(0, j + 1)])
        elif part in _DAYS:
            days.append(_DAYS[part])
        else:
            return None
    return days


def _parse_spans(text: str) -> list[Interval] | None:
    spans: list[Interval] = []
    for part in text.split(","):
        part = part.strip()
        m = _SPAN.match(part)
        if m:
            start = int(m[1]) * 60 + int(m[2])
            end = int(m[3]) * 60 + int(m[4])
            if int(m[1]) > 24 or int(m[3]) > 48 or int(m[2]) > 59 or int(m[4]) > 59:
                return None
            if end <= start:
                end += 1440
            spans.append((start, end))
            continue
        m = _OPEN_END.match(part)
        if m:
            spans.append((int(m[1]) * 60 + int(m[2]), 1440))
            continue
        return None
    return spans


def parse(value: str | None) -> Week | None:
    """Return weekly opening intervals or ``None`` when the value is unknown."""
    if not value:
        return None
    value = value.strip()
    if value.lower() == "24/7":
        return {d: [(0, 1440)] for d in range(7)}
    week: Week = {d: [] for d in range(7)}
    touched = False
    for rule in value.split(";"):
        rule = rule.strip()
        if not rule:
            continue
        low = rule.lower()
        if low.startswith(("ph", "sh")):
            continue
        tokens = rule.split(None, 1)
        first = tokens[0].lower().rstrip(",")
        has_days = first[:2] in _DAYS
        if has_days:
            # day spec may contain spaces after commas: "Mo, We 10:00-12:00"
            m = _DAY_SPEC.match(rule)
            if not m:
                return None
            days = _parse_days(m[1].strip().rstrip(","))
            rest = m[2].strip()
        else:
            days, rest = list(range(7)), rule
        if days is None:
            return None
        if rest.lower() in ("off", "closed"):
            for d in days:
                week[d] = []
            touched = True
            continue
        if not rest:
            return None
        spans = [(0, 1440)] if rest.lower() == "24/7" else _parse_spans(rest)
        if spans is None:
            return None
        for d in days:
            week[d] = list(spans)
        touched = True
    return week if touched else None


def intervals_for_day(week: Week | None, weekday: int) -> list[Interval] | None:
    """Opening intervals relevant for ``weekday`` including the tail of the previous night."""
    if week is None:
        return None
    spans = list(week.get(weekday, []))
    for start, end in week.get((weekday - 1) % 7, []):
        if end > 1440:
            spans.append((0, end - 1440))
    return sorted(spans)


def is_open(week: Week | None, moment: datetime) -> bool | None:
    spans = intervals_for_day(week, moment.weekday())
    if spans is None:
        return None
    minute = moment.hour * 60 + moment.minute
    return any(a <= minute < b for a, b in spans)
