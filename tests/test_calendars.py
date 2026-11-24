from datetime import datetime, timezone

import pytest

from app.calendars import FakeCalendar, GoogleCalendar, SlotTakenError, get_calendar
from app.config import Settings

# Tuesday 2026-11-24 12:00 UTC
NOW = datetime(2026, 11, 24, 12, 0, tzinfo=timezone.utc)


def make() -> FakeCalendar:
    return FakeCalendar(now=lambda: NOW)


def test_slots_are_future_weekdays_utc():
    slots = make().free_slots(3)
    assert slots == [
        "2026-11-25T10:00:00+00:00",
        "2026-11-25T14:00:00+00:00",
        "2026-11-25T16:00:00+00:00",
    ]


def test_slots_skip_weekends():
    friday = datetime(2026, 11, 27, 9, 0, tzinfo=timezone.utc)
    slots = FakeCalendar(now=lambda: friday).free_slots(4)
    assert slots[0] == "2026-11-30T10:00:00+00:00"  # Monday
    for s in slots:
        d = datetime.fromisoformat(s)
        assert d.weekday() < 5 and d.utcoffset().total_seconds() == 0


def test_booked_slot_disappears():
    cal = make()
    first = cal.free_slots(1)[0]
    msg = cal.book(first, "Sara", "sara@example.com")
    assert "Sara" in msg and first in msg
    assert first not in cal.free_slots(3)
    assert len(cal.free_slots(3)) == 3


def test_double_book_raises():
    cal = make()
    slot = cal.free_slots(1)[0]
    cal.book(slot, "Sara", "sara@example.com")
    with pytest.raises(SlotTakenError):
        cal.book(slot.replace("+00:00", "Z"), "Bo", "bo@example.com")


def test_book_unknown_slot_raises():
    cal = make()
    with pytest.raises(ValueError):
        cal.book("2026-11-25T11:00:00+00:00", "Sara", "sara@example.com")
    with pytest.raises(ValueError):
        cal.book("2026-11-25T10:00:00", "Sara", "sara@example.com")  # naive
    with pytest.raises(ValueError):
        cal.book("not a date", "Sara", "sara@example.com")


def test_get_calendar_defaults_to_fake():
    s = Settings("u", None, "m", None)
    assert isinstance(get_calendar(s), FakeCalendar)


def test_get_calendar_uses_google_when_configured():
    s = Settings("u", None, "m", "creds.json")
    assert isinstance(get_calendar(s), GoogleCalendar)  # lazy: no import/credentials yet
