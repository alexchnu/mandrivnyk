from datetime import datetime

import pytest

from planner import hours as h


def test_24_7():
    week = h.parse("24/7")
    assert all(week[d] == [(0, 1440)] for d in range(7))


def test_ranges_and_off():
    week = h.parse("Mo-Fr 09:00-18:00; Sa 10:00-16:00; Su off")
    assert week[0] == [(540, 1080)] and week[5] == [(600, 960)] and week[6] == []


def test_multiple_spans_and_lists():
    week = h.parse("Tu,Th 10:00-13:00,14:00-18:00")
    assert week[1] == [(600, 780), (840, 1080)] and week[0] == [] and week[3] == week[1]


def test_no_day_means_every_day():
    assert h.parse("10:00-20:00")[6] == [(600, 1200)]


def test_later_rule_overrides():
    week = h.parse("Mo-Su 10:00-18:00; Mo off")
    assert week[0] == [] and week[1] == [(600, 1080)]


def test_overnight_span():
    week = h.parse("Fr-Sa 22:00-04:00")
    assert week[4] == [(1320, 1680)]
    assert h.intervals_for_day(week, 5) == [(0, 240), (1320, 1680)]
    assert h.is_open(week, datetime(2026, 11, 21, 2, 0)) is True  # Saturday 02:00
    assert h.is_open(week, datetime(2026, 11, 20, 12, 0)) is False


def test_wrapping_day_range():
    assert h.parse("Sa-Mo 08:00-12:00")[0] == [(480, 720)]


def test_public_holidays_ignored():
    week = h.parse("Mo-Fr 09:00-17:00; PH off")
    assert week[2] == [(540, 1020)]


@pytest.mark.parametrize(
    "value", [None, "", "sunrise-sunset", "Apr-Oct: Mo-Su 10:00-18:00", "by appointment", "Mo-Fr 9-17"]
)
def test_unknown_values(value):
    assert h.parse(value) is None
    assert h.is_open(h.parse(value), datetime(2026, 11, 16, 12, 0)) is None
