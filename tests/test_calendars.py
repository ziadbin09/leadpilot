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


class _Exec:
    def __init__(self, result):
        self.result = result

    def execute(self):
        return self.result


class FakeService:
    """Stands in for the Google Calendar API client; no network."""

    def __init__(self, busy=(), errors=None):
        self.busy, self.errors = list(busy), errors
        self.queries, self.inserted = [], []

    def freebusy(self):
        return self

    def events(self):
        return self

    def query(self, body):
        self.queries.append(body)
        cal = {"busy": self.busy}
        if self.errors:
            cal["errors"] = self.errors
        return _Exec({"calendars": {body["items"][0]["id"]: cal}})

    def insert(self, calendarId, body):
        self.inserted.append((calendarId, body))
        return _Exec({"id": "evt"})


def google(service, calendar_id="owner@gmail.com"):
    cal = GoogleCalendar("creds.json", calendar_id=calendar_id, now=lambda: NOW)
    cal._service = lambda: service
    return cal


def test_google_books_offered_slot_on_configured_calendar():
    svc = FakeService()
    cal = google(svc)
    slot = cal.free_slots(1)[0]
    assert slot == "2026-11-25T10:00:00+00:00"
    cal.book(slot, "Sara", "sara@example.com")
    assert svc.inserted[0][0] == "owner@gmail.com"
    assert svc.queries[0]["items"] == [{"id": "owner@gmail.com"}]


@pytest.mark.parametrize("slot", [
    "2026-11-20T10:00:00+00:00",  # past
    "2026-11-28T10:00:00+00:00",  # Saturday
    "2026-11-25T03:00:00+00:00",  # off-grid hour
    "2026-11-24T14:00:00+00:00",  # today (slots start tomorrow)
])
def test_google_rejects_slots_outside_the_grid(slot):
    svc = FakeService()
    with pytest.raises(ValueError):
        google(svc).book(slot, "Sara", "sara@example.com")
    assert svc.inserted == []


def test_google_busy_slot_raises_taken():
    svc = FakeService(busy=[{"start": "2026-11-25T10:00:00Z", "end": "2026-11-25T11:00:00Z"}])
    cal = google(svc)
    assert "2026-11-25T10:00:00+00:00" not in cal.free_slots(3)
    with pytest.raises(SlotTakenError):
        cal.book("2026-11-25T10:00:00+00:00", "Sara", "sara@example.com")
    assert svc.inserted == []


def test_google_freebusy_errors_are_not_treated_as_free():
    svc = FakeService(errors=[{"domain": "global", "reason": "notFound"}])
    cal = google(svc)
    with pytest.raises(RuntimeError):
        cal.free_slots(3)
    with pytest.raises(RuntimeError):
        cal.book("2026-11-25T10:00:00+00:00", "Sara", "sara@example.com")
    assert svc.inserted == []


def test_get_calendar_passes_calendar_id():
    s = Settings("u", None, "m", "creds.json", google_calendar_id="owner@gmail.com")
    assert get_calendar(s)._calendar_id == "owner@gmail.com"
